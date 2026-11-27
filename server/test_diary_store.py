"""Database integrity checks, isolated from live data and browser/GPU behavior."""
import uuid
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from server import db
from server.diary_store import backfill, store_page


@pytest.fixture
def con():
    name = 'goodmorning_structure_test_' + uuid.uuid4().hex[:12]
    admin_url = db.admin_url()
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    try:
        target = make_conninfo(**{**conninfo_to_dict(admin_url), 'dbname': name})
        with psycopg.connect(target, row_factory=dict_row) as connection:
            connection.execute('CREATE EXTENSION vector')
            for path in db.SCHEMAS:
                connection.execute(path.read_text(encoding='utf-8'))
            connection.commit()
            yield connection
    finally:
        assert name.startswith('goodmorning_structure_test_')
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))


def body():
    return {'items': [{'id': 'same-asset', 'x': 20}, {'id': 'same-asset', 'x': 80}],
            'diaryLayout': [{'x': 20, 'caption': 'first', 'layerOrder': 8}, {'x': 30, 'caption': 'second', 'layerOrder': 2}],
            'paperStyle': {'color': 'sky', 'pattern': 'grid'}, 'extra': {'preserve': True}}


def test_owner_isolation_layer_order_and_independent_placements(con):
    value = body()
    for owner in ['private', 'guest-example']:
        store_page(con, owner, 'page:1', value, datetime.now(timezone.utc))
    pages = con.execute('SELECT id,paper_style,notebook_id FROM diary_pages').fetchall()
    assert len({p['notebook_id'] for p in pages}) == 2
    for page in pages:
        assert page['paper_style'] == value['paperStyle']
        items = con.execute('SELECT * FROM diary_page_items WHERE page_id=%s ORDER BY layer_group,stack_order', (page['id'],)).fetchall()
        assert [i['kind'] for i in items] == ['photo', 'photo', 'sticker', 'sticker']
        assert [i['caption'] for i in items[:2]] == ['second', 'first']
        assert len({i['id'] for i in items}) == 4
    assert con.execute('SELECT body FROM notebook_pages LIMIT 1').fetchone()['body'] == value


def test_repeat_backfill_preserves_ids_and_legacy_body(con):
    value = body()
    con.execute('INSERT INTO notebook_pages VALUES(%s,%s,%s,now())', ('private', 'page:1', db.Jsonb(value)))
    backfill(con)
    ids = con.execute('SELECT id FROM diary_page_items ORDER BY id').fetchall()
    backfill(con)
    assert ids == con.execute('SELECT id FROM diary_page_items ORDER BY id').fetchall()
    assert con.execute('SELECT body FROM notebook_pages').fetchone()['body'] == value
    assert con.execute('SELECT count(*) AS n FROM auth_identities').fetchone()['n'] == 0


def test_save_removes_stale_rows_and_rollback_keeps_both_views(con):
    original = body()
    store_page(con, 'private', 'page:1', original, datetime.now(timezone.utc))
    con.commit()
    changed = {'items': [], 'diaryLayout': []}
    with pytest.raises(RuntimeError):
        with con.transaction():
            store_page(con, 'private', 'page:1', changed, datetime.now(timezone.utc))
            raise RuntimeError('simulate failure before commit')
    assert con.execute('SELECT body FROM notebook_pages').fetchone()['body'] == original
    assert con.execute('SELECT count(*) AS n FROM diary_page_items').fetchone()['n'] == 4
    store_page(con, 'private', 'page:1', changed, datetime.now(timezone.utc))
    assert con.execute('SELECT count(*) AS n FROM diary_page_items').fetchone()['n'] == 0
