"""Offline additive migration. Restore-verify backup; preserve preexisting values."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from psycopg import sql
from server import db,db_security
from scripts import migrate_diary_structure as migration
from scripts.harden_database import restore_verify

ADDED={'account_profiles':['avatar','profile_ready','terms_version','privacy_version','agreed_at','deleting','deletion_requested_at'],
       'oauth_attempts':['policy_version']}


def fingerprints(con,tables):
    result={}
    for table in tables:
        result[table]=con.execute(sql.SQL("SELECT count(*) AS n,md5(COALESCE(string_agg(h,'' ORDER BY h),'')) AS h FROM (SELECT md5((to_jsonb(t)-%s::text[])::text) AS h FROM {} t) q").format(sql.Identifier(table)),(ADDED.get(table,[]),)).fetchone()
    return result


def main():
    migration.stopped();migration.NEW_TABLES=set()
    with db.admin_connection() as con:
        if con.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running') LIMIT 1").fetchone() or con.execute("SELECT 1 FROM goods_searches WHERE state='running' LIMIT 1").fetchone():
            raise RuntimeError('Active work must finish first')
        full=migration.fingerprints(con)
        tables=[row['tablename'] for row in con.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename<>'schema_migrations'")]
        before=fingerprints(con,tables)
    archive=migration.backup();restore_verify(archive,full)
    with db.admin_connection() as con:
        db_security.provision(con,db_security.credentials())
        if fingerprints(con,tables)!=before:raise RuntimeError('Existing values changed')
        for role in ('search','reader'):
            if con.execute("SELECT has_table_privilege(%s,'retired_guest_owners','SELECT') AS allowed",(db.ROLES[role],)).fetchone()['allowed']:
                raise RuntimeError('Private table permission mismatch')
    print('Account migration applied; backup restore verified; existing values preserved.')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Account migration failed: '+type(error).__name__+'. No private values printed.')
        raise SystemExit(1)
