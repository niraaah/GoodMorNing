"""Back up/restore-verify local data before installing least-privilege roles and RLS."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from server import db, db_security
from scripts import migrate_diary_structure as migration


def docker_cli():
    found = shutil.which('docker')
    if found:
        return found
    for base in (Path(os.environ.get('LOCALAPPDATA',''))/'Programs/DockerDesktop',
                 Path(os.environ.get('ProgramFiles',''))/'Docker/Docker'):
        candidate = base/'resources/bin/docker.exe'
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError('Docker CLI unavailable')


def restore_verify(archive, expected):
    name = 'goodmorning_restore_check_' + uuid4().hex[:12]
    settings = conninfo_to_dict(db.admin_url())
    with psycopg.connect(db.admin_url(), autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        with archive.open('rb') as source:
            result = subprocess.run([docker_cli(),'exec','-i','goodmorning-postgres','pg_restore',
                '--exit-on-error','--no-owner','--no-privileges','-U','goodmorning','-d',name],
                stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError('Backup restore failed')
        with psycopg.connect(make_conninfo(**{**settings,'dbname':name}),row_factory=dict_row) as con:
            if migration.fingerprints(con) != expected:
                raise RuntimeError('Restored rows differ')
    finally:
        assert name.startswith('goodmorning_restore_check_')
        with psycopg.connect(db.admin_url(), autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def main():
    migration.stopped()
    migration.NEW_TABLES = set()
    with db.admin_connection() as con:
        tables = con.execute("SELECT count(*) AS n FROM pg_tables WHERE schemaname='public'").fetchone()['n']
        before = migration.fingerprints(con)
        if tables:
            if con.execute("SELECT count(*) AS n FROM jobs WHERE state IN ('queued','running')").fetchone()['n']:
                raise RuntimeError('Active sticker jobs')
            if con.execute("SELECT count(*) AS n FROM goods_searches WHERE state='running'").fetchone()['n']:
                raise RuntimeError('Active search jobs')
            old_ownership = con.execute('SELECT kind,ident,owner FROM ownership ORDER BY kind,ident').fetchall()
        else:
            old_ownership = []
    archive = migration.backup() if tables else None
    if archive:
        restore_verify(archive, before)
    passwords = db_security.credentials()
    with db.admin_connection() as con:
        db_security.provision(con, passwords)
        after = migration.fingerprints(con)
        if any(after.get(table) != value for table,value in before.items() if table != 'ownership'):
            raise RuntimeError('Existing data changed; rolling back')
        new_ownership = con.execute('SELECT kind,ident,owner FROM ownership ORDER BY kind,ident').fetchall()
        if any(row not in new_ownership for row in old_ownership):
            raise RuntimeError('Existing ownership changed; rolling back')
    print(json.dumps({'backup':str(archive) if archive else None,'restore_verified':bool(archive),
        'existing_tables_checked':len(before),'original_ownership_preserved':True,
        'explicit_ownership_added':len(new_ownership)-len(old_ownership),
        'runtime_roles':list(db.ROLES.values()),'rls_tables':len(db_security.RLS_TABLES)}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Security migration failed ('+type(error).__name__+'). Inspect locally; no private details printed.')
        raise SystemExit(1)
