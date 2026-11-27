import importlib
import io
import json
import os
import struct
import time
import uuid

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from psycopg.conninfo import conninfo_to_dict, make_conninfo

# A PostgreSQL server with pgvector: GOODMORNING_TEST_DATABASE_URL, or the local Docker
# container from scripts/setup-postgres.ps1. Each test gets its own temporary database.
def admin_url():
    if os.getenv('GOODMORNING_TEST_DATABASE_URL'):
        return os.environ['GOODMORNING_TEST_DATABASE_URL']
    from server import db
    try:
        return db.url()
    except RuntimeError:
        return ''


ADMIN_URL = admin_url()


@pytest.fixture
def client(tmp_path, monkeypatch):
    if not ADMIN_URL:
        pytest.skip('PostgreSQL is not set up; run scripts/setup-postgres.ps1 or set GOODMORNING_TEST_DATABASE_URL.')
    name = 'goodmorning_test_' + uuid.uuid4().hex[:12]
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE {name}')
    url = make_conninfo(**{**conninfo_to_dict(ADMIN_URL), 'dbname': name})
    monkeypatch.setenv('GOODMORNING_DATA',str(tmp_path))
    monkeypatch.setenv('GOODMORNING_DATABASE_URL', url)
    from server import db
    from server import app as module
    db.close()
    module = importlib.reload(module)
    try:
        with TestClient(module.app) as client:
            yield client, tmp_path, url
    finally:
        db.close()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE {name} WITH (FORCE)')


def photo():
    image=Image.new('RGBA',(200,240),(0,0,0,0))
    draw=ImageDraw.Draw(image);draw.ellipse((35,35,165,205),fill=(230,155,95,255));draw.ellipse((70,90,82,106),fill='black')
    out=io.BytesIO();image.save(out,'PNG');return out.getvalue()


def test_photo_to_gaussian_glb_and_saved_diary(client):
    c,data,url=client
    job=c.post('/api/stickers',data={'name':'test sticker'},files={'photo':('rabbit.png',photo(),'image/png')})
    assert job.status_code==202,job.text
    ident=job.json()['id']
    for _ in range(100):
        state=c.get('/api/jobs/'+ident).json()
        if state['state'] in ('completed','failed'):break
        time.sleep(.05)
    assert state['state']=='completed',state
    glb=c.get(f'/files/{ident}/sticker.glb').content
    assert struct.unpack('<4sII',glb[:12])==(b'glTF',2,len(glb))
    length=struct.unpack('<I',glb[12:16])[0]
    manifest=json.loads(glb[20:20+length])
    assert manifest['materials'][0]['extensions']['KHR_materials_clearcoat']['clearcoatFactor']==1
    assert c.get(f'/files/{ident}/sticker.ply').content.startswith(b'ply\n')
    assert c.get(f'/files/{ident}/process.jpg').content.startswith(b'\xff\xd8')
    metadata=c.get(f'/files/{ident}/sticker.json').json()
    # The test data folder has no depth model, so the silhouette relief is used and recorded.
    assert metadata['depth']=='silhouette-distance' and '3_depth' not in metadata['process']['stages']
    assert metadata['gaussians']['count']>100
    assert metadata['max_height_mm']>0
    diary={'id':'persistent','title':'나의 기록','note':'hello','date':'2026-11-26','paper':'#fff9eb','placements':[
        {'id':'placed','asset_id':ident,'x':.4,'y':.6,'size':.25,'rotation':12}]}
    assert c.put('/api/diaries/persistent',json=diary).status_code==200
    assert next(d for d in c.get('/api/diaries').json() if d['id']=='persistent')==diary
    # A separate PostgreSQL connection verifies persistence outside the request context.
    with psycopg.connect(url) as db:
        assert db.execute("select body from diaries where id='persistent'").fetchone()[0]==diary
        assert db.execute("select jsonb_typeof(metadata) from assets where id=%s",(ident,)).fetchone()[0]=='object'


def test_reject_invalid_upload_and_geometry(client):
    c,_,_=client
    assert c.post('/api/stickers',data={'name':'bad'},files={'photo':('fake.png',b'not an image','image/png')}).status_code==400
    assert c.post('/api/stickers',data={'name':'bad','box':'[0,0,0,0]'},files={'photo':('a.png',photo(),'image/png')}).status_code==422
    assert c.get('/files/anything/source.png').status_code==404
    assert c.get('/api/unknown').status_code==404


def test_origin_and_unknown_asset_rejected(client):
    c,_,_=client
    assert c.post('/api/stickers',headers={'Origin':'https://unrelated.invalid'},data={'name':'bad'},files={'photo':('a.png',photo(),'image/png')}).status_code==403
    diary={'id':'bad','title':'bad','date':'2026-11-26','placements':[{'id':'x','asset_id':'missing','x':.5,'y':.5,'size':.2,'rotation':0}]}
    assert c.put('/api/diaries/bad',json=diary).status_code==422


def test_remote_access_key_required(client):
    c,data,_=client
    remote={'Host':'preview.trycloudflare.com','cf-ray':'test'}
    assert c.get('/api/assets',headers=remote).status_code==401
    assert c.post('/auth/login',headers=remote,json={'key':'wrong'}).status_code==403
    key=(data/'access.key').read_text()
    assert c.post('/auth/login',headers=remote,json={'key':key}).status_code==200
    assert c.get('/api/assets',headers=remote).status_code==200


def test_notebook_trash_and_restore(client):
    c,_,_=client
    attachment=c.post('/api/notebook/files',files={'attachment':('photo.png',photo(),'image/png')}).json()
    page={'items':[{'id':'s1','file':{'__gmAsset':'pochita','part':'model'}}],'diaryLayout':[{'file':attachment,'caption':'메모'}]}
    assert c.put('/api/notebook/pages/page:2',json=page).status_code==200
    assert c.get('/api/notebook/pages/page:2').json()==page
    assert c.get('/api/notebook/pages').json()==['page:2']
    assert c.put('/api/notebook/pages/page:3',json={**page,'diaryLayout':[{'file':{'__gmFile':'0'*64}}]}).status_code==404
    assert c.post('/api/assets/pochita/trash',json={'name':'포치타'}).status_code==403
    made=c.post('/api/photos',data={'name':'나의 사진'},files={'photo':('a.png',photo(),'image/png')}).json()
    assert c.post(f"/api/assets/{made['id']}/trash",json={'name':'틀린 이름'}).status_code==422
    assert c.post(f"/api/assets/{made['id']}/trash",json={'name':'나의 사진'}).status_code==200
    assert made['id'] not in [a['id'] for a in c.get('/api/assets').json()]
    assert [a['id'] for a in c.get('/api/trash').json()]==[made['id']]
    assert c.post(f"/api/trash/{made['id']}/restore").status_code==200
    assert made['id'] in [a['id'] for a in c.get('/api/assets').json()]


def test_catalog_offers_vectors_and_links(client):
    _,_,url=client
    from server.goods import catalog
    started=time.time()
    product={'id':'p1','title':'포치타 인형 키링','source':'포켓몬스토어','url':'https://www.pokemonstore.co.kr/goods/1',
             'image_url':'https://www.pokemonstore.co.kr/1.jpg','price':12000,'affiliate':False}
    catalog.record_collection('포치타 키링','cfg',[product],[{'source':'포켓몬스토어','state':'ok'}],started)
    assert catalog.cached_sources('포치타 키링','cfg')==[{'source':'포켓몬스토어','state':'ok'}]
    found=catalog.candidates('포치타')
    assert [f['title'] for f in found]==['포치타 인형 키링'] and found[0]['stale'] is False
    assert abs(found[0]['observed_at']-started)<60
    offer=found[0]['offer_id']
    vector=np.arange(1,769,dtype='<f4')/768
    catalog.record_vector(offer,'text','rev',catalog.digest('t'),768,vector.tobytes())
    dimensions,raw=catalog.vector(offer,'text','rev',catalog.digest('t'))
    assert dimensions==768 and np.array_equal(np.frombuffer(raw,dtype='<f4'),vector)
    catalog.record_image(offer,product['image_url'],'a.jpg','0'*64,10,10)
    assert time.time()-catalog.image_record(offer)['observed_at']<60
    goods={'title':'포치타 인형 키링','url':product['url'],'offer_id':offer,'confirmed_by_user':True,
           'match_method':'user_selected_recommendation','confirmed_at':int(time.time())}
    with psycopg.connect(url) as db:
        db.execute("INSERT INTO assets VALUES('linked','키링','sticker','sam2-gaussian',now(),'{}')")
        db.commit()
    from server.db import connection
    with connection() as con:
        catalog.link_asset(con,'linked','private',goods)
    with psycopg.connect(url) as db:
        row=db.execute("select l.offer_id, l.snapshot->>'title', vector_dims(e.vector) from asset_product_links l join catalog_embeddings e on e.offer_id=l.offer_id where l.asset_id='linked'").fetchone()
    assert row==(offer,'포치타 인형 키링',768)


def test_admin_viewer_is_owner_only_and_read_only(client):
    c,data,_=client
    query=lambda sql,**kw: c.post('/api/admin/query',json={'sql':sql},**kw)
    answer=query("SELECT name, kind FROM assets WHERE id='pochita'")
    assert answer.status_code==200 and answer.json()['columns']==['name','kind'] and answer.json()['rows']==[['포치타','sticker']]
    assert c.get('/api/admin/summary').json()['pgvector']
    # Visitors connect with a guest token from the Pages app; they never see the shared tables.
    remote={'Host':'preview.trycloudflare.com','cf-ray':'test'}
    key=(data/'access.key').read_text()
    from server.access import guest_token
    guest={**remote,'Authorization':'Bearer '+guest_token(key)}
    assert query('SELECT 1',headers=guest).status_code==403
    assert c.get('/api/admin/summary',headers=guest).status_code==403
    assert query('SELECT 1',headers=remote).status_code==401
    assert query('SELECT 1',headers={**remote,'Authorization':'Bearer '+key}).status_code==200
    for sql,message in [("DELETE FROM assets",'조회만'),("UPDATE assets SET name='x'",'조회만'),
                        ("SELECT 1; DELETE FROM assets",'한 문장'),("COMMIT; DELETE FROM assets",'한 문장'),
                        ("SELECT pg_read_file('/etc/hostname')",'조회 전용'),("SET ROLE goodmorning",''),
                        ("SELECT pg_sleep(6)",'5초')]:
        response=query(sql)
        assert response.status_code==400 and message in response.json()['detail'], (sql,response.text)
    assert query("SELECT count(*) AS n FROM assets").json()['rows'][0][0]>=3
