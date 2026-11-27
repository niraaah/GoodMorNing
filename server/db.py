"""Least-privilege runtime connections; schema changes run only from setup scripts."""
import os
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from psycopg import connect
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool
from pgvector.psycopg import register_vector

ROOT = Path(__file__).resolve().parent.parent
SCHEMAS = (Path(__file__).with_name('schema.sql'), Path(__file__).parent/'goods/catalog.sql',
           Path(__file__).with_name('diary_schema.sql'), Path(__file__).with_name('auth_schema.sql'))
ROLES = {'api':'goodmorning_api', 'search':'goodmorning_search', 'reader':'goodmorning_reader'}
READER = ROLES['reader']
SECURITY_VERSION = '20261127_least_privilege_rls_v1'
current_owner = ContextVar('goodmorning_owner', default='')
_service = 'api'
_pool = None
_lock = threading.Lock()


def data_dir():
    return Path(os.getenv('GOODMORNING_DATA', str(ROOT/'data'))).resolve()


def _local_url(role, keyfile):
    key = data_dir()/keyfile
    if not key.is_file():
        raise RuntimeError('DB 보안 설정이 필요합니다. scripts/setup-postgres.ps1을 실행해 주세요.')
    return make_conninfo(host=os.getenv('GOODMORNING_DATABASE_HOST','127.0.0.1'), port=os.getenv('GOODMORNING_DATABASE_PORT', '55432'),
                         dbname='goodmorning', user=role, password=key.read_text(encoding='utf-8').strip())


def admin_url():
    """Offline setup/migration only. Never used as a runtime fallback."""
    return (os.getenv('GOODMORNING_ADMIN_DATABASE_URL') or os.getenv('GOODMORNING_DATABASE_URL')
            or _local_url('goodmorning', 'postgres.key'))


def url(service=None):
    service = service or _service
    if service not in ROLES:
        raise ValueError('Unknown database service')
    return os.getenv('GOODMORNING_'+service.upper()+'_DATABASE_URL') or _local_url(ROLES[service], 'postgres-'+service+'.key')


def reader_url():
    return url('reader')


def select_service(service):
    global _service
    if service not in ('api','search') or _pool is not None:
        raise RuntimeError('Select a database service before opening its pool.')
    _service = service


def initialize():
    """Fail closed on privileged credentials/missing migration; never execute DDL."""
    with connect(url(), row_factory=dict_row) as con:
        _configure(con)
        if not con.execute('SELECT 1 FROM schema_migrations WHERE version=%s', (SECURITY_VERSION,)).fetchone():
            raise RuntimeError('DB 보안 마이그레이션을 먼저 적용해 주세요.')


def _configure(con):
    validate_role(con, _service)
    register_vector(con)
    con.commit()


def validate_role(con, service):
    with con.cursor(row_factory=dict_row) as cursor:
        role = cursor.execute('SELECT current_user AS name,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
    if role['name'] != ROLES[service] or any(role[k] for k in ('rolsuper','rolcreatedb','rolcreaterole','rolbypassrls')):
        raise RuntimeError('Privileged or mismatched runtime DB credentials are not allowed.')
    if con.execute("SELECT 1 FROM pg_class WHERE relnamespace='public'::regnamespace AND relowner=(SELECT oid FROM pg_roles WHERE rolname=current_user) LIMIT 1").fetchone():
        raise RuntimeError('Runtime role must not own database objects.')


@contextmanager
def reader_connection(**kwargs):
    with connect(reader_url(), connect_timeout=5, **kwargs) as con:
        validate_role(con, 'reader')
        con.rollback()
        yield con


def _pool_for_process():
    global _pool
    with _lock:
        if _pool is None:
            _pool = ConnectionPool(url(), min_size=1, max_size=10, open=True, configure=_configure,
                                   kwargs={'row_factory':dict_row}, name='goodmorning-'+_service)
        return _pool


@contextmanager
def owner_scope(owner):
    token = current_owner.set(owner or '')
    try:
        yield
    finally:
        current_owner.reset(token)


@contextmanager
def connection():
    with _pool_for_process().connection() as con:
        con.execute("SELECT set_config('goodmorning.owner',%s,true)", (current_owner.get(),))
        yield con


@contextmanager
def admin_connection():
    """Explicit maintenance connection; callers are scripts, not HTTP handlers."""
    with connect(admin_url(), row_factory=dict_row) as con:
        register_vector(con)
        yield con


def close():
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None
