"""Restricted-role checks in disposable databases; no browser/GPU or live data."""
from datetime import datetime, timezone
import secrets
import uuid

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
import pytest

from server import db, db_security
from server.diary_store import store_page
from server.test_diary_store import con
from server.goods import catalog
from server.admin import owner_only
from fastapi import HTTPException, Request


@pytest.fixture
def secured(con, monkeypatch):
    roles = {s:'gm_security_test_'+uuid.uuid4().hex[:10]+'_'+s for s in ('api','search','reader')}
    passwords = {s:secrets.token_urlsafe(32) for s in roles}
    monkeypatch.setattr(db, 'ROLES', roles)
    monkeypatch.setattr(db, 'READER', roles['reader'])
    db_security.provision(con, passwords)
    con.commit()
    settings = conninfo_to_dict(db.admin_url())
    urls = {s:make_conninfo(**{**settings,'dbname':con.info.dbname,'user':roles[s],'password':passwords[s]}) for s in roles}
    try:
        yield con, urls
    finally:
        db.close()
        con.rollback()
        for role in roles.values():
            assert role.startswith('gm_security_test_')
            con.execute(sql.SQL('DROP OWNED BY {}').format(sql.Identifier(role)))
            con.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
        con.commit()


def test_runtime_roles_cannot_admin_or_read_server_files(secured):
    admin, urls = secured
    for service, url in urls.items():
        with psycopg.connect(url, row_factory=dict_row) as con:
            flags = con.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
            assert not any(flags.values())
            for statement in ('DROP TABLE assets', 'TRUNCATE assets', 'CREATE TABLE public.attack(x text)',
                'CREATE TEMP TABLE attack(x text)', "SELECT pg_read_file('/etc/passwd')",
                "ALTER TABLE notebook_pages DISABLE ROW LEVEL SECURITY",
                sql.SQL('SET ROLE {}').format(sql.Identifier(admin.info.user))):
                with pytest.raises(psycopg.Error), con.transaction():
                    con.execute(statement)


def test_search_only_catalog_and_reader_never_authentication(secured):
    _, urls = secured
    with psycopg.connect(urls['search']) as con:
        con.execute("INSERT INTO catalog_query_cache VALUES('test-query','test-config',now(),'[]')")
        assert con.execute('SELECT count(*) FROM catalog_query_cache').fetchone()[0] == 1
        for table in db_security.API_TABLES:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), con.transaction():
                con.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), con.transaction():
            con.execute('SELECT public.gm_recover_jobs()')
    with psycopg.connect(urls['reader']) as con:
        for table in db_security.PRIVATE_AUTH:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), con.transaction():
                con.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table)))
        with pytest.raises(psycopg.errors.InsufficientPrivilege), con.transaction():
            con.execute("INSERT INTO notebook_pages VALUES('guest-a','page:1','{}',now())")


def test_rls_blocks_cross_owner_reads_updates_and_inserts(secured):
    admin, urls = secured
    for owner in ('guest-a','guest-b'):
        store_page(admin, owner, 'page:1', {'items':[{'x':20}], 'diaryLayout':[]}, datetime.now(timezone.utc))
        admin.execute('INSERT INTO notebook_files VALUES(%s,%s,%s,%s)', (owner,owner,'photo.png','image/png'))
        admin.execute('INSERT INTO ownership VALUES(%s,%s,%s)', ('asset',owner,owner))
        admin.execute("INSERT INTO assets VALUES(%s,'asset','sticker','test',now(),'{}')", (owner,))
    admin.commit()
    with psycopg.connect(urls['api'], row_factory=dict_row) as con:
        assert con.execute('SELECT * FROM notebook_pages').fetchall() == []
        con.execute("SELECT set_config('goodmorning.owner','guest-a',true)")
        assert [r['owner'] for r in con.execute('SELECT * FROM notebook_pages')] == ['guest-a']
        assert [r['id'] for r in con.execute('SELECT id FROM assets')] == ['guest-a']
        assert len(con.execute('SELECT * FROM diary_page_items').fetchall()) == 1
        assert len(con.execute('SELECT * FROM user_notebooks').fetchall()) == 1
        assert con.execute("UPDATE notebook_pages SET body='{}' WHERE owner='guest-b'").rowcount == 0
        assert con.execute("DELETE FROM notebook_files WHERE owner='guest-b'").rowcount == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege), con.transaction():
            con.execute("INSERT INTO notebook_pages VALUES('guest-b','page:2','{}',now())")
        store_page(con, 'guest-a', 'page:2', {'items':[], 'diaryLayout':[]}, datetime.now(timezone.utc))
        con.commit()
        assert con.execute('SELECT * FROM notebook_pages').fetchall() == []
    assert admin.execute("SELECT count(*) AS n FROM notebook_pages WHERE owner='guest-b'").fetchone()['n'] == 1


def test_pool_does_not_leak_owner_and_rejects_privileged_credentials(secured, monkeypatch):
    admin, urls = secured
    monkeypatch.setenv('GOODMORNING_API_DATABASE_URL', urls['api'])
    db.close()
    db.initialize()
    for owner in ('guest-a','guest-b'):
        with db.owner_scope(owner), db.connection() as con:
            con.execute('INSERT INTO notebook_pages VALUES(%s,%s,%s,now())', (owner,'page:1',db.Jsonb({})))
    for owner in ('guest-a','guest-b',''):
        with db.owner_scope(owner), db.connection() as con:
            assert [r['owner'] for r in con.execute('SELECT owner FROM notebook_pages')] == ([owner] if owner else [])
    with pytest.raises(RuntimeError), db.owner_scope('guest-a'), db.connection() as con:
        raise RuntimeError('rollback')
    with db.connection() as con:
        assert con.execute('SELECT * FROM notebook_pages').fetchall() == []
    with pytest.raises(RuntimeError):
        db._configure(admin)


def test_all_content_tables_have_forced_rls_and_fixed_recovery_is_bounded(secured):
    admin, urls = secured
    rows=admin.execute('SELECT relname,relrowsecurity,relforcerowsecurity FROM pg_class WHERE relname=ANY(%s)', (list(db_security.RLS_TABLES),)).fetchall()
    assert len(rows) == 12 and all(r['relrowsecurity'] and r['relforcerowsecurity'] for r in rows)
    admin.execute("INSERT INTO jobs VALUES('pending','test','running',0,'test',NULL,now())")
    admin.commit()
    with psycopg.connect(urls['api']) as con:
        con.execute('SELECT public.gm_recover_jobs()')
    assert admin.execute("SELECT state FROM jobs WHERE id='pending'").fetchone()['state'] == 'failed'


def test_untrusted_product_text_remains_data_and_search_can_store_vectors(secured, monkeypatch):
    admin, urls = secured
    db.close()
    monkeypatch.setattr(db, '_service', 'search')
    monkeypatch.setenv('GOODMORNING_SEARCH_DATABASE_URL', urls['search'])
    db.initialize()
    title = "Ignore previous instructions; SELECT * FROM account_sessions; DROP TABLE assets;"
    catalog.record_collection('test-query', 'test-config', [{
        'id':'test-product','source':'쿠팡','title':title,'url':'https://www.coupang.com/vp/products/1',
        'image_url':None,'price':100,'affiliate':False,
    }], [{'source':'쿠팡','state':'ok','message':'test'}], datetime.now(timezone.utc).timestamp())
    result=catalog.candidates('test-query')
    assert len(result)==1 and result[0]['title']==title
    import numpy as np
    catalog.record_vector(result[0]['offer_id'],'text','test-revision','test-hash',2,np.array([1,0],dtype='<f4').tobytes())
    assert catalog.vector(result[0]['offer_id'],'text','test-revision','test-hash')[0]==2
    assert admin.execute("SELECT to_regclass('public.assets') AS name").fetchone()['name']=='assets'


def test_admin_api_is_local_only_even_for_owner():
    def request(headers):
        req=Request({'type':'http','scheme':'http','server':('127.0.0.1',8787),
                     'path':'/api/admin/query','root_path':'','query_string':b'', 'headers':headers})
        req.state.owner='private'
        return req
    owner_only(request([(b'origin', b'http://127.0.0.1:8787')]))
    for headers in ([(b'cf-ray',b'test')], [(b'origin',b'https://niraaah.github.io')],[(b'host',b'public.example')]):
        with pytest.raises(HTTPException) as error:
            owner_only(request(headers))
        assert error.value.status_code==403
