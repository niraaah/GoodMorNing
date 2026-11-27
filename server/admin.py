"""Read-only database viewer for the PC owner (/admin page, /api/admin/*).

The tables hold every visitor's data, so only the owner (access key, or a local
request on this PC) may use it. Queries run as a SELECT-only login role, inside a
READ ONLY transaction that is always rolled back, one statement at a time, with a
statement timeout and a row limit.
"""
from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

import psycopg
from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from .db import reader_connection
from .access import requires_access
from psycopg.rows import dict_row

ROW_LIMIT = 300


class Query(BaseModel):
    sql: str = Field(min_length=1, max_length=20000)


def owner_only(request: Request):
    origin = request.headers.get('origin')
    if request.state.owner != 'private' or requires_access(request) or (origin and origin != str(request.base_url).rstrip('/')):
        raise HTTPException(403, 'DB 조회는 이 PC의 로컬 관리자 화면에서만 열 수 있어요.')


def cell(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f'(bytea {len(value)}B)'
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (dict, list)):
        return value
    return str(value)


def register(app):
    @app.get('/api/admin/summary')
    def summary(request: Request):
        owner_only(request)
        with reader_connection(row_factory=dict_row) as con:
            con.execute('SET TRANSACTION READ ONLY')
            con.execute("SET LOCAL statement_timeout='5s'")
            tables = con.execute("""SELECT table_name AS name FROM information_schema.tables
                WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name""").fetchall()
            for table in tables:
                table['rows'] = con.execute(f'SELECT count(*) AS n FROM "{table["name"]}"').fetchone()['n']
            info = con.execute("""SELECT current_setting('server_version') AS version,
                (SELECT extversion FROM pg_extension WHERE extname='vector') AS pgvector,
                pg_database_size(current_database()) AS bytes, current_database() AS database""").fetchone()
        return {**info, 'tables': tables}

    @app.post('/api/admin/query')
    def query(body: Query, request: Request):
        owner_only(request)
        source = body.sql.strip().rstrip(';').strip()
        if not source:
            raise HTTPException(422, 'SQL을 입력해 주세요.')
        try:
            with reader_connection() as con:
                con.execute('SET TRANSACTION READ ONLY')
                con.execute("SET LOCAL statement_timeout = '5s'")
                # A prepared statement accepts exactly one command.
                cursor = con.execute(source, prepare=True)
                columns = [column.name for column in cursor.description or []]
                rows = cursor.fetchmany(ROW_LIMIT + 1) if cursor.description else []
                con.rollback()
        except psycopg.errors.ReadOnlySqlTransaction:
            raise HTTPException(400, '조회만 할 수 있어요. 이 화면에서는 DB를 바꿀 수 없어요.')
        except psycopg.errors.QueryCanceled:
            raise HTTPException(400, '5초 안에 끝나지 않아 멈췄어요. 조건이나 LIMIT을 넣어 주세요.')
        except psycopg.errors.InsufficientPrivilege:
            raise HTTPException(400, '조회 전용 계정으로는 실행할 수 없는 문장이에요.')
        except psycopg.Error as error:
            message = str(error).strip().splitlines()[0] if str(error).strip() else '실행하지 못했어요.'
            if 'multiple commands' in message:
                message = '한 번에 한 문장만 실행할 수 있어요.'
            raise HTTPException(400, message)
        return {'columns': columns, 'rows': [[cell(v) for v in row] for row in rows[:ROW_LIMIT]],
                'more': len(rows) > ROW_LIMIT, 'limit': ROW_LIMIT}
