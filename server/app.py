import hmac
import json
import logging
import os
import queue
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ConfigDict
from PIL import Image

from .gpu import Segmenter
from .depth import DepthEstimator
from .stickers import generate, normalized_image
from . import notebook, asset_trash, admin
from .db import Jsonb, connection
from .goods import api as goods_api
from .goods import catalog
from .access import COOKIE, load_key, session, requires_access, authorized, connect_page, guest_token, guest_owner

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv('GOODMORNING_DATA', str(ROOT / 'data'))).resolve()
ENGINE = ROOT / 'sticker-engine'
tasks = queue.Queue(maxsize=4)
segmenter = Segmenter(DATA / 'models' / 'sam2')
depth_estimator = DepthEstimator(DATA / 'models' / 'yolo-depth', segmenter.device_id)
log = logging.getLogger('goodmorning')
SAMPLES = {'pochita', '2026_11_24_08_15', '2026_11_24_08_16'}


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize():
    (DATA / 'assets').mkdir(parents=True, exist_ok=True)
    (DATA / 'models').mkdir(exist_ok=True)
    app.state.access_key = load_key(DATA)
    # Creates every table (server/schema.sql, server/goods/catalog.sql) in PostgreSQL.
    catalog.initialize()
    with connection() as con:
        notebook.initialize(con, DATA)
        asset_trash.initialize(con)
        goods_api.initialize(con)
        con.execute("UPDATE jobs SET state='failed', message='서버가 재시작되어 중단됐어요. 사진을 다시 올려 주세요.' WHERE state IN ('queued','running')")
        for ident, title in [('pochita', '포치타'), ('2026_11_24_08_15', '디무'), ('2026_11_24_08_16', '토끼 인형')]:
            src = ENGINE / 'assets' / ident
            if not (src / 'sticker.glb').exists():
                continue
            dest = DATA / 'assets' / ident
            dest.mkdir(exist_ok=True)
            for filename in ('sticker.glb', 'sticker.png', 'sticker.json'):
                if not (dest / filename).exists() and (src / filename).exists():
                    shutil.copy2(src / filename, dest / filename)
            con.execute('INSERT INTO assets VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                        (ident, title, 'sticker', 'sam3d-sample', now(), Jsonb({'sample': True})))
        if con.execute('SELECT count(*) AS n FROM diaries').fetchone()['n'] == 0:
            diary = {'id': 'my-first-diary', 'title': '좋아하는 것들로 가득', 'note': '작고 귀여운 순간들을 차곡차곡 모아요.',
                     'date': datetime.now().strftime('%Y-%m-%d'), 'paper': '#fff9eb', 'placements': [
                         {'id': 'starter-1', 'asset_id': 'pochita', 'x': .28, 'y': .40, 'size': .32, 'rotation': -12},
                         {'id': 'starter-2', 'asset_id': '2026_11_24_08_16', 'x': .70, 'y': .64, 'size': .29, 'rotation': 11}]}
            con.execute('INSERT INTO diaries VALUES(%s,%s,%s)', (diary['id'], Jsonb(diary), now()))
        catalog.backfill_links(con)


def accessible(con, kind, ident, owner):
    if kind == 'asset' and ident in SAMPLES:
        return True
    row = con.execute('SELECT owner FROM ownership WHERE kind=%s AND ident=%s', (kind, ident)).fetchone()
    return (row['owner'] if row else 'private') == owner


def assign(con, kind, ident, owner):
    con.execute('INSERT INTO ownership VALUES(%s,%s,%s)', (kind, ident, owner))


def asset_dict(row):
    result = dict(row)  # metadata is JSONB, already a dict
    result['thumbnail'] = f"/files/{result['id']}/sticker.png"
    result['model'] = f"/files/{result['id']}/sticker.glb" if result['kind'] == 'sticker' else None
    return result


def update_job(ident, state, progress, message, asset=None):
    with connection() as con:
        con.execute('UPDATE jobs SET state=%s, progress=%s, message=%s, asset_id=%s WHERE id=%s',
                    (state, progress, message, asset, ident))


def worker():
    while True:
        task = tasks.get()
        if task is None:
            tasks.task_done()
            return
        ident, options = task
        path = DATA / 'assets' / ident
        try:
            def progress(number, message):
                update_job(ident, 'running', number, message)
            info = generate(path / 'source.png', path, segmenter, options, progress, depth_estimator)
            if options.get('goods'): info['goods'] = options['goods']
            with connection() as con:
                con.execute('INSERT INTO assets VALUES(%s,%s,%s,%s,%s,%s)',
                            (ident, options['name'], 'sticker', options['engine'], now(), Jsonb(info)))
                assign(con, 'asset', ident, options.get('owner', 'private'))
                catalog.link_asset(con,ident,options.get('owner','private'),options.get('goods'))
            update_job(ident, 'completed', 100, '에셋함에 저장했어요!', ident)
        except Exception as error:
            log.exception('Sticker generation failed for %s', ident)
            message = str(error) if isinstance(error, (ValueError, RuntimeError)) else '변환 중 오류가 발생했어요. 다른 사진으로 다시 시도해 주세요.'
            update_job(ident, 'failed', 0, message)
        finally:
            tasks.task_done()


@asynccontextmanager
async def lifespan(app):
    initialize()
    thread = threading.Thread(target=worker, daemon=True, name='sticker-worker')
    thread.start()
    yield
    try:
        tasks.put_nowait(None)
    except queue.Full:
        pass


app = FastAPI(title='굿모닝 · local studio', lifespan=lifespan)
ALLOWED_ORIGINS = [origin.strip() for origin in os.getenv('GOODMORNING_FRONTEND_ORIGINS', 'https://niraaah.github.io').split(',') if origin.strip()]


@app.middleware('http')
async def same_origin(request: Request, call_next):
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin:
        parsed = urlsplit(origin)
        if origin not in ALLOWED_ORIGINS and (parsed.scheme not in ('http', 'https') or parsed.netloc != request.headers.get('host')):
            return JSONResponse({'detail': '다른 사이트에서 보낸 요청은 허용되지 않습니다.'}, 403)
    external_frontend = origin in ALLOWED_ORIGINS and urlsplit(origin).netloc != request.headers.get('host')
    private = authorized(request, app.state.access_key) or not (requires_access(request) or external_frontend)
    visitor = guest_owner(request, app.state.access_key)
    request.state.owner = 'private' if private else visitor
    if request.url.path not in ('/connect','/auth/login','/auth/guest') and not private and not visitor:
        if request.url.path.startswith(('/api/','/files/')):
            return JSONResponse({'detail':'접속 링크로 먼저 로그인해 주세요.'},401)
        return RedirectResponse('/connect',status_code=303)
    response=await call_next(request)
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='SAMEORIGIN'
    return response


app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                   allow_credentials=False, allow_methods=['GET', 'POST', 'PUT', 'OPTIONS'],
                   allow_headers=['Authorization', 'Content-Type'], max_age=600)


@app.get('/connect',include_in_schema=False)
def connect():
    return connect_page()


@app.post('/auth/login',include_in_schema=False)
async def login(request: Request):
    try:
        if int(request.headers.get('content-length','0'))>1024:
            raise ValueError()
        body=await request.json()
        value=body.get('key','')
        if not isinstance(value,str) or not hmac.compare_digest(value,app.state.access_key):
            raise ValueError()
    except (ValueError,AttributeError):
        raise HTTPException(403,'접근 키가 올바르지 않습니다.')
    response=JSONResponse({'ok':True})
    response.set_cookie(COOKIE,session(app.state.access_key),httponly=True,samesite='strict',
                        secure=request.url.scheme=='https' or request.headers.get('x-forwarded-proto')=='https',max_age=604800)
    return response


@app.post('/auth/guest', include_in_schema=False)
def automatic_session(request: Request):
    # A public browser gets only its own collection, never the private owner's key/data.
    if request.headers.get('origin') not in ALLOWED_ORIGINS:
        raise HTTPException(403, '앱에서 연결해 주세요.')
    return JSONResponse({'token': guest_token(app.state.access_key)}, headers={'Cache-Control': 'no-store'})


@app.get('/api/health')
def health():
    gpu = segmenter.status()
    return {'status': 'ok', 'storage': 'local', 'gpu': gpu, 'engine': 'sam2-gaussian',
            'photo_ready': gpu['model_ready'], 'depth_ready': depth_estimator.ready(), 'queue_size': tasks.qsize(),
            'pipeline': 'SAM 2.1 → YOLO26n depth → single-photo Gaussian relief → glossy GLB'}


@app.get('/api/assets')
def assets(request: Request, include_deleted: bool = False):
    with connection() as con:
        return [asset_dict(row) for row in con.execute('SELECT * FROM assets ORDER BY created DESC') if accessible(con, 'asset', row['id'], request.state.owner) and (include_deleted or not asset_trash.hidden(con,request.state.owner,row['id']))]


async def uploaded_image(photo):
    content = await photo.read(16 * 1024 * 1024 + 1)
    await photo.close()
    if len(content) > 16 * 1024 * 1024:
        raise HTTPException(413, '사진은 16MB 이하로 올려 주세요.')
    try:
        return normalized_image(content)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.post('/api/stickers', status_code=202)
async def create_sticker(request: Request, photo: UploadFile = File(), name: str = Form(min_length=1, max_length=60),
                         engine: Literal['sam2-gaussian'] = Form('sam2-gaussian'),
                         background: Literal['auto', 'keep'] = Form('auto'), box: str = Form('[0.05,0.05,0.95,0.95]'),
                         goods_search_id: str = Form('',max_length=64), goods_candidate_id: str = Form('',max_length=100),
                         goods_manual_url: str = Form('',max_length=2048), goods_manual_title: str = Form('',max_length=300)):
    if not name.strip():
        raise HTTPException(422, '스티커 이름을 입력해 주세요.')
    try:
        bounds = json.loads(box)
        if len(bounds) != 4 or not all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in bounds) or bounds[2]-bounds[0] < .02 or bounds[3]-bounds[1] < .02:
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(422, '굿즈를 감싸는 사각형을 선택해 주세요.')
    if tasks.full():
        raise HTTPException(429, '만드는 중인 스티커가 많아요. 잠시 후 다시 시도해 주세요.')
    image = await uploaded_image(photo)
    with connection() as con:
        goods = goods_api.selection(con,request.state.owner,goods_search_id,goods_candidate_id,goods_manual_url,goods_manual_title)
    ident = uuid.uuid4().hex
    dest = DATA / 'assets' / ident
    dest.mkdir()
    image.save(dest / 'source.png')
    with connection() as con:
        con.execute('INSERT INTO jobs VALUES(%s,%s,%s,%s,%s,%s,%s)', (ident, name.strip(), 'queued', 0, '차례를 기다리고 있어요', None, now()))
        assign(con, 'job', ident, request.state.owner)
    try:
        tasks.put_nowait((ident, {'name': name.strip(), 'engine': engine, 'background': background, 'box': bounds, 'owner': request.state.owner, 'goods':goods}))
    except queue.Full:
        update_job(ident, 'failed', 0, '대기열이 가득 찼어요. 다시 시도해 주세요.')
        raise HTTPException(429, '대기열이 가득 찼어요.')
    return {'id': ident, 'state': 'queued'}


@app.post('/api/photos', status_code=201)
async def add_photo(request: Request, photo: UploadFile = File(), name: str = Form('나의 사진', max_length=60)):
    image = await uploaded_image(photo)
    ident = uuid.uuid4().hex
    dest = DATA / 'assets' / ident
    dest.mkdir()
    image.save(dest / 'sticker.png')
    with connection() as con:
        con.execute('INSERT INTO assets VALUES(%s,%s,%s,%s,%s,%s)', (ident, name, 'photo', 'photo', now(), Jsonb({})))
        assign(con, 'asset', ident, request.state.owner)
        return asset_dict(con.execute('SELECT * FROM assets WHERE id=%s', (ident,)).fetchone())


@app.get('/api/jobs')
def jobs(request: Request):
    with connection() as con:
        return [dict(row) for row in con.execute('SELECT * FROM jobs ORDER BY created DESC') if accessible(con, 'job', row['id'], request.state.owner)][:30]


@app.get('/api/jobs/{ident}')
def job(ident: str, request: Request):
    with connection() as con:
        if not accessible(con, 'job', ident, request.state.owner):
            raise HTTPException(404, '작업을 찾지 못했어요.')
        row = con.execute('SELECT * FROM jobs WHERE id=%s', (ident,)).fetchone()
    if row is None:
        raise HTTPException(404, '작업을 찾지 못했어요.')
    return dict(row)


class Placement(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=80)
    asset_id: str = Field(min_length=1, max_length=80)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    size: float = Field(ge=.06, le=.85)
    rotation: float = Field(ge=-180, le=180)


class Diary(BaseModel):
    id: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
    title: str = Field(min_length=1, max_length=60)
    note: str = Field(max_length=1000, default='')
    date: str = Field(pattern=r'^\d{4}-\d{2}-\d{2}$')
    paper: str = Field(pattern=r'^#[0-9a-fA-F]{6}$', default='#fff9eb')
    placements: list[Placement] = Field(max_length=60, default_factory=list)


@app.get('/api/diaries')
def diaries(request: Request):
    with connection() as con:
        result = [row['body'] for row in con.execute('SELECT id,body FROM diaries ORDER BY updated DESC') if accessible(con, 'diary', row['id'], request.state.owner)]
        if not result and request.state.owner != 'private':
            ident = request.state.owner + '-first'
            diary = {'id': ident, 'title': '나의 다이어리', 'date': datetime.now().strftime('%Y-%m-%d'), 'note': '', 'paper': '#fff9eb', 'placements': []}
            con.execute('INSERT INTO diaries VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', (ident, Jsonb(diary), now()))
            con.execute('INSERT INTO ownership VALUES(%s,%s,%s) ON CONFLICT DO NOTHING', ('diary', ident, request.state.owner))
            result = [diary]
        return result


@app.put('/api/diaries/{ident}')
def save_diary(ident: str, diary: Diary, request: Request):
    if ident != diary.id:
        raise HTTPException(400, '다이어리 ID가 일치하지 않아요.')
    ids = [p.id for p in diary.placements]
    if len(ids) != len(set(ids)):
        raise HTTPException(422, '스티커 배치 ID는 서로 달라야 합니다.')
    with connection() as con:
        # Serializes saves of one diary, as SQLite's BEGIN IMMEDIATE did.
        con.execute("SELECT pg_advisory_xact_lock(hashtext('diary:' || %s))", (ident,))
        exists = con.execute('SELECT id FROM diaries WHERE id=%s', (ident,)).fetchone()
        if exists and not accessible(con, 'diary', ident, request.state.owner):
            raise HTTPException(404, '다이어리를 찾지 못했어요.')
        known = {row['id'] for row in con.execute('SELECT id FROM assets') if accessible(con, 'asset', row['id'], request.state.owner)}
        if any(p.asset_id not in known for p in diary.placements):
            raise HTTPException(422, '저장되지 않은 에셋은 붙일 수 없어요.')
        con.execute('INSERT INTO diaries VALUES(%s,%s,%s) ON CONFLICT(id) DO UPDATE SET body=excluded.body,updated=excluded.updated',
                    (ident, Jsonb(diary.model_dump(mode='json')), now()))
        if not exists:
            assign(con, 'diary', ident, request.state.owner)
    return diary


@app.get('/files/{ident}/{filename}')
def file(ident: str, filename: str, request: Request):
    if filename not in ('sticker.glb', 'sticker.png', 'sticker.json', 'sticker.ply', 'sticker.splat', 'process.jpg') or not ident.replace('_', '').replace('-', '').isalnum():
        raise HTTPException(404)
    with connection() as con:
        if not accessible(con, 'asset', ident, request.state.owner):
            raise HTTPException(404)
    path = DATA / 'assets' / ident / filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type='model/gltf-binary' if filename.endswith('.glb') else None)


notebook.register(app, DATA, connection, accessible, normalized_image, now)
goods_api.register(app, connection, uploaded_image)
asset_trash.register(app, connection, accessible, asset_dict, now, SAMPLES)
admin.register(app)

app.mount('/scene', StaticFiles(directory=ROOT / 'server' / 'scene', html=True), name='scene')


@app.get('/{path:path}')
def frontend(path: str):
    root = (ROOT / 'app' / 'build' / 'web').resolve()
    if path.startswith(('api/', 'files/')):
        raise HTTPException(404)
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(404)
    if target.is_file():
        return FileResponse(target)
    # Static pages in their own folder (/admin/), served like GitHub Pages does.
    if path and target.is_dir() and (target / 'index.html').is_file():
        if not path.endswith('/'):
            return RedirectResponse(f'/{path}/', status_code=301)
        return FileResponse(target / 'index.html', headers={'Cache-Control': 'no-cache'})
    if not path or '.' not in Path(path).name:
        if (root / 'index.html').exists():
            return FileResponse(root / 'index.html', headers={'Cache-Control': 'no-cache'})
    raise HTTPException(404, 'Flutter 웹 앱을 먼저 빌드해 주세요.')
