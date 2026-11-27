"""Add social-login tables after a verified local DB backup; preserve every old row."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import migrate_diary_structure as migration
from server import db
from server.db_security import initialize


def main():
    migration.stopped()
    archive = migration.backup()
    # Unlike the earlier diary migration, include all existing account tables.
    migration.NEW_TABLES = set()
    with db.admin_connection() as con:
        before = migration.fingerprints(con)
        con.execute((ROOT/'server/auth_schema.sql').read_text(encoding='utf-8'))
        after = migration.fingerprints(con)
        if any(after.get(table) != value for table, value in before.items()):
            raise RuntimeError('Existing data changed; rolling back.')
    initialize()
    with db.admin_connection() as con:
        for table in ('account_sessions', 'oauth_attempts'):
            if con.execute('SELECT has_table_privilege(%s,%s,\'SELECT\') AS allowed', (db.READER, table)).fetchone()['allowed']:
                raise RuntimeError('Authentication table must not be readable by the viewer.')
    print(json.dumps({'backup':str(archive), 'existing_tables_unchanged':len(before), 'auth_tables_installed':True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print('Social-login migration failed ('+type(error).__name__+'). Inspect locally without printing private data.')
        raise SystemExit(1)
