"""Back up the local PostgreSQL container, rehearse/add the account/diary structure.

Stop both API servers first. Default rolls the whole migration back; --apply commits.
Existing table contents are fingerprinted before/after. No row contents are printed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from server.db import admin_connection as connection, data_dir, admin_url as url
from server.diary_store import backfill, document, fingerprint, placements

NEW_TABLES = {'app_users', 'app_owner_bindings', 'auth_identities', 'user_notebooks', 'diary_pages', 'diary_page_items'}


def stopped():
    for port in (8787, 8788):
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                raise RuntimeError('Stop both API servers before migrating.')
        except (ConnectionRefusedError, TimeoutError, OSError):
            pass


def backup():
    settings = conninfo_to_dict(url())
    if (settings.get('host'), settings.get('port'), settings.get('dbname')) != ('127.0.0.1', '55432', 'goodmorning'):
        raise RuntimeError('This backup command supports the default local Docker DB only; configure a verified backup for another DB.')
    docker = shutil.which('docker')
    if not docker:
        for base in (Path(os.environ.get('LOCALAPPDATA', ''))/'Programs/DockerDesktop',
                     Path(os.environ.get('ProgramFiles', ''))/'Docker/Docker'):
            candidate = base/'resources/bin/docker.exe'
            if candidate.is_file():
                docker = str(candidate)
                break
    if not docker:
        raise RuntimeError('Docker CLI was not found.')
    folder = data_dir()/'backups'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/('before-diary-structure-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.dump')
    with path.open('wb') as output:
        result = subprocess.run([docker, 'exec', 'goodmorning-postgres', 'pg_dump', '-U', 'goodmorning', '-d', 'goodmorning', '-Fc'],
                                stdout=output, stderr=subprocess.PIPE)
    if result.returncode or path.stat().st_size == 0:
        raise RuntimeError('Database backup failed; no migration was attempted.')
    with path.open('rb') as source:
        result = subprocess.run([docker, 'exec', '-i', 'goodmorning-postgres', 'pg_restore', '--list'],
                                stdin=source, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode or b'notebook_pages' not in result.stdout:
        raise RuntimeError('Backup archive validation failed.')
    return path


def fingerprints(con):
    tables = con.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'").fetchall()
    result = {}
    for entry in tables:
        name = entry['tablename']
        if name in NEW_TABLES or name == 'schema_migrations':
            continue
        rows = con.execute(sql.SQL('SELECT to_jsonb(t) AS row FROM {} t').format(sql.Identifier(name))).fetchall()
        hashes = sorted(fingerprint(row['row']) for row in rows)
        result[name] = (len(rows), hashlib.sha256(''.join(hashes).encode()).hexdigest())
    return result


def verify(con):
    rows = con.execute('SELECT owner,page_key,body FROM notebook_pages').fetchall()
    total = 0
    for row in rows:
        page = con.execute('''SELECT p.id,p.source_hash,p.paper_style,b.user_id,n.user_id AS notebook_user
            FROM diary_pages p JOIN app_owner_bindings b ON b.owner=p.legacy_owner
            JOIN user_notebooks n ON n.id=p.notebook_id WHERE p.legacy_owner=%s AND p.page_key=%s''',
            (row['owner'], row['page_key'])).fetchone()
        if not page or page['source_hash'] != fingerprint(row['body']) or page['user_id'] != page['notebook_user']:
            raise RuntimeError('Page content or owner verification failed.')
        expected = {(kind, slot): document(original) for kind, slot, rank, data, original in placements(row['body'])}
        actual = con.execute('SELECT kind,slot,properties FROM diary_page_items WHERE page_id=%s', (page['id'],)).fetchall()
        if {(item['kind'], item['slot']): document(item['properties']) for item in actual} != expected:
            raise RuntimeError('Placement content verification failed.')
        total += len(actual)
    return {'pages': len(rows), 'placements': total}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    stopped()
    with connection() as con:
        if con.execute("SELECT count(*) AS n FROM jobs WHERE state IN ('queued','running')").fetchone()['n']:
            raise RuntimeError('Sticker jobs are still active.')
        if con.execute("SELECT count(*) AS n FROM goods_searches WHERE state='running'").fetchone()['n']:
            raise RuntimeError('Search jobs are still active.')
    archive = backup()
    with connection() as con:
        con.execute("SELECT pg_advisory_xact_lock(hashtextextended('goodmorning:diary-migration',0))")
        before = fingerprints(con)
        con.execute((ROOT/'server/diary_schema.sql').read_text(encoding='utf-8'))
        backfill(con)
        first = verify(con)
        backfill(con)
        if verify(con) != first or fingerprints(con) != before:
            raise RuntimeError('Repeatability or existing-data preservation check failed.')
        if not args.apply:
            con.rollback()
    print(json.dumps({'applied': args.apply, 'backup': str(archive), 'existing_tables_unchanged': len(before), **first}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Driver errors can contain connection details or private row values.
        print('Migration failed ('+type(error).__name__+'); transaction rolled back. Inspect locally without printing private data.')
        raise SystemExit(1)
