"""PostgreSQL access shared by the API server and the goods search server.

PostgreSQL 17 + pgvector runs in Docker on this PC (scripts/setup-postgres.ps1).
Connection settings come from GOODMORNING_DATABASE_URL, or from the generated
password in data/postgres.key with the local container defaults. The password
is never printed or committed.
"""
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from psycopg import connect, sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

ROOT = Path(__file__).resolve().parent.parent
# Application tables first: the catalog's asset links reference assets.
SCHEMAS = (Path(__file__).with_name('schema.sql'), Path(__file__).parent / 'goods' / 'catalog.sql',
           Path(__file__).with_name('diary_schema.sql'))
READER = 'goodmorning_reader'
_pool = None
_lock = threading.Lock()

__all__ = ['Jsonb', 'connection', 'initialize', 'close', 'url', 'reader_url']


def data_dir():
    return Path(os.getenv('GOODMORNING_DATA', str(ROOT / 'data'))).resolve()


def url():
    explicit = os.getenv('GOODMORNING_DATABASE_URL', '').strip()
    if explicit:
        return explicit
    key = data_dir() / 'postgres.key'
    if not key.is_file():
        raise RuntimeError('PostgreSQL 접속 정보가 없습니다. scripts/setup-postgres.ps1을 먼저 실행해 주세요.')
    return make_conninfo(host='127.0.0.1', port=os.getenv('GOODMORNING_DATABASE_PORT', '55432'),
                         dbname='goodmorning', user='goodmorning',
                         password=key.read_text(encoding='utf-8').strip())


def reader_url():
    """Login role for the /admin viewer: SELECT only, not a superuser."""
    settings = conninfo_to_dict(url())
    return make_conninfo(**{**settings, 'user': READER})


def initialize():
    """Create the vector extension, every table and the read-only role. Safe to repeat."""
    with connect(url(), autocommit=True) as con:
        con.execute('CREATE EXTENSION IF NOT EXISTS vector')
        password = conninfo_to_dict(url()).get('password') or ''
        if not con.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', (READER,)).fetchone():
            con.execute(sql.SQL('CREATE ROLE {} LOGIN').format(sql.Identifier(READER)))
        # Same local password as the owner account; the role can only read tables.
        con.execute(sql.SQL('ALTER ROLE {} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}')
                    .format(sql.Identifier(READER), sql.Literal(password)))
    with connection() as con:
        # SQL is packaged source; no runtime or user text is interpolated.
        for schema in SCHEMAS:
            con.execute(schema.read_text(encoding='utf-8'))
        con.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(
            sql.Identifier(con.info.dbname), sql.Identifier(READER)))
        con.execute(sql.SQL('GRANT USAGE ON SCHEMA public TO {0}; GRANT SELECT ON ALL TABLES IN SCHEMA public TO {0}')
                    .format(sql.Identifier(READER)))


def _configure(con):
    register_vector(con)
    con.commit()  # the pool requires an idle connection after setup


def _pool_for_process():
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(url(), min_size=1, max_size=10, open=True, configure=_configure,
                                   kwargs={'row_factory': dict_row}, name='goodmorning')
        return _pool


@contextmanager
def connection():
    """One transaction: committed when the block ends, rolled back on an exception."""
    with _pool_for_process().connection() as con:
        yield con


def close():
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None
