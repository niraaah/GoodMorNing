"""Copy the former SQLite database (data/goodmorning.sqlite3) into PostgreSQL.

Run after scripts/setup-postgres.ps1 and before starting the servers on PostgreSQL.
Stop both application servers first. The SQLite file is only read: a backup copy is
made in data/backups/ and the copy is migrated. Without --apply everything runs in
one transaction that is rolled back (rehearsal); with --apply it is committed.
Row contents are never printed, only table names, row counts and checks.
Files in data/assets/, data/notebook-files/ and data/catalog-images/ stay where they
are; the tables keep the same file references.
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server.db import Jsonb, admin_connection as connection, data_dir  # noqa: E402
from server.db_security import initialize, provision, credentials


def iso(value):
    return datetime.fromisoformat(value)


def seconds(value):
    return datetime.fromtimestamp(value, timezone.utc)


def document(value):
    return Jsonb(json.loads(value))


def flag(value):
    return bool(value)


def embedding(value):
    return np.frombuffer(value, dtype='<f4')


# Foreign-key order. Each entry lists the columns whose SQLite form changes.
TABLES = [
    ('ownership', {}),
    ('assets', {'created': iso, 'metadata': document}),
    ('jobs', {'created': iso}),
    ('diaries', {'body': document, 'updated': iso}),
    ('notebook_pages', {'body': document, 'updated': iso}),
    ('notebook_files', {}),
    ('asset_trash', {'deleted_at': iso}),
    ('goods_searches', {'body': document, 'created': seconds}),
    ('schema_migrations', {'applied_at': seconds}),
    ('catalog_products', {'created_at': seconds, 'updated_at': seconds}),
    ('catalog_variants', {'attrs': document, 'created_at': seconds}),
    ('catalog_malls', {'created_at': seconds}),
    ('catalog_offers', {'affiliate': flag, 'observed_at': seconds, 'created_at': seconds}),
    ('catalog_offer_history', {'observed_at': seconds}),
    ('catalog_collect_jobs', {'started_at': seconds, 'finished_at': seconds}),
    ('catalog_raw_listings', {'payload': document, 'collected_at': seconds}),
    ('catalog_query_cache', {'checked_at': seconds, 'sources': document}),
    ('catalog_query_offers', {'seen_at': seconds}),
    ('catalog_images', {'observed_at': seconds}),
    ('catalog_embeddings', {'vector': embedding, 'created_at': seconds}),
    ('asset_product_links', {'snapshot': document, 'confirmed_at': seconds}),
]
# The blob encoding column is implied by pgvector (float4).
DROPPED = {'catalog_embeddings': {'dtype'}}
IDENTITY = ('catalog_offer_history', 'catalog_raw_listings')


def backup(source):
    folder = source.parent / 'backups'
    folder.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    target = folder / f'before-postgres-{stamp}.sqlite3'
    src, dst = sqlite3.connect(source), sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def check_source(con):
    if con.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise RuntimeError('SQLite integrity check failed; stop migration.')
    tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'jobs' in tables and con.execute("SELECT count(*) FROM jobs WHERE state IN ('queued','running')").fetchone()[0]:
        raise RuntimeError('Active sticker jobs found; wait for them and stop the servers.')
    if 'goods_searches' in tables and con.execute("SELECT count(*) FROM goods_searches WHERE state='running'").fetchone()[0]:
        raise RuntimeError('Active goods searches found; wait for them and stop the servers.')
    if 'catalog_embeddings' in tables and con.execute("SELECT count(*) FROM catalog_embeddings WHERE dtype<>'float32-le'").fetchone()[0]:
        raise RuntimeError('Unexpected embedding encoding; stop migration.')
    unknown = tables - {name for name, _ in TABLES} - {'sqlite_sequence'}
    if unknown:
        raise RuntimeError('Unknown SQLite tables: ' + ', '.join(sorted(unknown)))
    return tables


def copy(source_con, target, table, convert):
    cursor = source_con.execute(f'SELECT * FROM "{table}"')
    columns = [d[0] for d in cursor.description if d[0] not in DROPPED.get(table, ())]
    names = ','.join(f'"{c}"' for c in columns)
    marks = ','.join(['%s'] * len(columns))
    count = 0
    with target.cursor() as out:
        for row in cursor:
            record = dict(zip([d[0] for d in cursor.description], row))
            values = [None if record[c] is None else convert.get(c, lambda v: v)(record[c]) for c in columns]
            conflict = ' ON CONFLICT(version) DO NOTHING' if table == 'schema_migrations' else ''
            out.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})'+conflict, values)
            count += 1
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--apply', action='store_true', help='commit the copy (default: rehearse and roll back)')
    parser.add_argument('--source', type=Path, default=data_dir() / 'goodmorning.sqlite3')
    args = parser.parse_args()
    if not args.source.is_file():
        raise SystemExit('SQLite database not found; nothing to migrate.')
    initialize()
    with connection() as target:
        filled = [t for t, _ in TABLES if t != 'schema_migrations' and target.execute(f'SELECT EXISTS (SELECT 1 FROM "{t}") AS x').fetchone()['x']]
    if filled:
        raise RuntimeError('PostgreSQL already has data in: ' + ', '.join(filled)
                           + '. Migrate into a new database (remove the goodmorning-pgdata volume) or skip.')
    copy_path = backup(args.source)
    source = sqlite3.connect(copy_path)
    report = {}
    try:
        tables = check_source(source)
        with connection() as target:
            for table, convert in TABLES:
                if table not in tables:
                    report[table] = 'absent in SQLite'
                    continue
                prior_versions = {r['version'] for r in target.execute('SELECT version FROM schema_migrations')} if table == 'schema_migrations' else set()
                copied = copy(source, target, table, convert)
                expected = source.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0]
                stored = target.execute(f'SELECT count(*) AS n FROM "{table}"').fetchone()['n']
                expected_stored = len(prior_versions | {r[0] for r in source.execute('SELECT version FROM schema_migrations')}) if table == 'schema_migrations' else expected
                if copied != expected or stored != expected_stored:
                    raise RuntimeError(f'Row count mismatch in {table}.')
                report[table] = stored
            for table in IDENTITY:
                target.execute(f"SELECT setval(pg_get_serial_sequence('{table}','id'), coalesce(max(id), 0) + 1, false) FROM \"{table}\"")
            if target.execute('SELECT count(*) AS n FROM catalog_embeddings WHERE vector_dims(vector) <> dimensions').fetchone()['n']:
                raise RuntimeError('Embedding dimensions do not match.')
            # Imported legacy rows can have implicit local ownership; make it explicit for RLS.
            provision(target, credentials())
            if not args.apply:
                target.rollback()
    finally:
        source.close()
    print(json.dumps({'applied': args.apply, 'backup': str(copy_path), 'rows': report}, ensure_ascii=False, indent=1))
    if not args.apply:
        print('Rehearsal only: nothing was written. Run again with --apply to copy the data.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Migration stopped ('+type(error).__name__+'). Inspect locally without printing credentials or row contents.')
