"""Containerized retrieval service; crawler and outbound network are separate boundaries."""
import base64
import hashlib
import hmac
import io
import json
import logging
import os
import threading
import time
from pathlib import Path
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit, urljoin
import httpx
import numpy as np
from PIL import Image
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field
from .config import ROOT, DATA, MODEL_REVISION, settings, egress_proxy
from .coupang import search as coupang_search
from . import catalog
from .. import db
db.select_service('search')

log=logging.getLogger('goods-search')
cache=DATA/'goods-cache'; cache.mkdir(parents=True,exist_ok=True)
model=None; model_error=None
model_lock=threading.Lock(); search_lock=threading.Lock()
image_cache=DATA/'catalog-images'; image_cache.mkdir(parents=True,exist_ok=True)

def load_model():
    global model, model_error
    with model_lock:
        if model is not None: return model
        try:
            import torch
            from sentence_transformers import SentenceTransformer
            path=DATA/'models/embeddinggemma-2'
            device=settings().get('EMBEDDING_DEVICE','cpu')
            torch.set_num_threads(min(6,torch.get_num_threads()))
            model=SentenceTransformer(str(path),device=device,local_files_only=True,
                config_kwargs={'audio_config':None},model_kwargs={'dtype':torch.float32})
            model_error=None
            return model
        except Exception:
            model_error='EmbeddingGemma 2 모델을 준비하지 못했어요.'
            log.exception('EmbeddingGemma initialization failed')
            raise

def warmup():
    try: load_model()
    except Exception: pass

@asynccontextmanager
async def lifespan(app):
    egress_proxy()
    catalog.initialize()
    threading.Thread(target=warmup,daemon=True).start()
    yield

app=FastAPI(lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

@app.middleware('http')
async def authorize(request:Request,call_next):
    expected=(DATA/'search-service.key').read_text(encoding='utf-8').strip()
    token=request.headers.get('authorization','').removeprefix('Bearer ')
    if not expected or not hmac.compare_digest(token.encode(),expected.encode()):
        from fastapi.responses import JSONResponse
        return JSONResponse({'detail':'Unauthorized'},status_code=401)
    return await call_next(request)

@app.get('/health')
def health():
    config=settings()
    return {'status':'ok','isolated':True,'model':'google/embeddinggemma-2','revision':MODEL_REVISION,
        'model_loaded':model is not None,'model_error':model_error,'device':config.get('EMBEDDING_DEVICE','cpu'),
        'coupang_configured':bool(config.get('COUPANG_ACCESS_KEY') and config.get('COUPANG_SECRET_KEY')),
        'naver':'api_retired_manual_links_only','official_shops':config.get('official_shops',True)}

class Search(BaseModel):
    query:str=Field(min_length=1,max_length=80)
    photo:str=Field(max_length=3_000_000)

def collect(query):
    config=settings()
    # Changing credentials/collection settings immediately invalidates cached configuration errors.
    fingerprint=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
    cached=catalog.cached_sources(query,fingerprint)
    if cached is not None: return catalog.candidates(query),cached
    started=time.time()
    products, state=coupang_search(query)
    states=[state,{'source':'네이버','state':'manual','message':'네이버 상품은 링크를 직접 입력해 연결할 수 있어요.'}]
    if config.get('official_shops',True):
        try:
            address=os.environ['GOODMORNING_CRAWLER_URL']
            if address!='http://172.30.74.4:8790':raise ValueError()
            key=Path(os.environ['GOODMORNING_CRAWLER_KEY_FILE']).read_text(encoding='utf-8').strip()
            with httpx.stream('POST',address+'/collect',json={'query':query},
                headers={'Authorization':'Bearer '+key},timeout=110,trust_env=False) as response:
                response.raise_for_status()
                content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>256*1024:raise ValueError()
            data=json.loads(content)
            if not isinstance(data['products'],list) or not isinstance(data['sources'],list):raise ValueError()
            products.extend(data['products'][:24]);states.extend(data['sources'][:4])
        except (httpx.HTTPError,OSError,ValueError,KeyError,TypeError):
            states.append({'source':'공식 굿즈몰','state':'unavailable','message':'공식몰에 연결하지 못했어요. 잠시 후 다시 검색해 주세요.'})
    unique=list({p['id']:p for p in products}.values())[:32]
    catalog.record_collection(query,fingerprint,unique,states,started)
    saved=catalog.candidates(query)
    if saved:
        states.append({'source':'저장된 상품 목록','state':'ok',
                       'message':'이전에 수집한 상품도 함께 비교해요. 최신 가격·옵션은 구매 페이지에서 확인해 주세요.'})
    return saved,states

def remote_image(url):
    if not url: return None
    domains=('coupangcdn.com','pstatic.net','pokemonstore.co.kr','daewonshop.com','cdn-nhncommerce.com','nhncommerce.com','shopby.co.kr')
    try:
        for _ in range(3):
            parsed=urlsplit(url);host=(parsed.hostname or '').lower()
            if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in (None,443): return None
            if not any(host==d or host.endswith('.'+d) for d in domains): return None
            with httpx.stream('GET',url,timeout=8,follow_redirects=False,trust_env=False,proxy=egress_proxy()) as response:
                if response.status_code in (301,302,303,307,308):
                    url=urljoin(url,response.headers.get('location',''));continue
                if response.status_code!=200 or not response.headers.get('content-type','').startswith('image/'): return None
                content=bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content)>5*1024*1024:return None
            image=Image.open(io.BytesIO(content))
            if image.width*image.height>24_000_000:return None
            image=image.convert('RGB');image.thumbnail((384,384))
            return image
    except (httpx.HTTPError,OSError,ValueError,Image.DecompressionBombError): pass
    return None

def product_image(product):
    """Only public listing thumbnails are persisted; input photos stay in memory."""
    record=catalog.image_record(product['offer_id'])
    saved=None
    if record and record['source_url']==product.get('image_url'):
        path=(image_cache/record['local_path']).resolve()
        if path.is_relative_to(image_cache.resolve()) and path.is_file():
            try:
                content=path.read_bytes()
                if hashlib.sha256(content).hexdigest()==record['sha256']:
                    with Image.open(io.BytesIO(content)) as image: saved=image.convert('RGB')
                    if time.time()-record['observed_at']<86400:return saved
            except (OSError,ValueError):pass
    image=remote_image(product.get('image_url'))
    if image is None:return saved
    output=io.BytesIO();image.save(output,format='JPEG',quality=80)
    content=output.getvalue();sha=hashlib.sha256(content).hexdigest()
    filename=sha+'.jpg';path=image_cache/filename
    # Content-addressed immutable files remain valid during concurrent reads.
    if not path.exists():
        with tempfile.NamedTemporaryFile(dir=image_cache,suffix='.tmp',delete=False) as output:
            output.write(content);temp=Path(output.name)
        try:temp.replace(path)
        finally:temp.unlink(missing_ok=True)
    catalog.record_image(product['offer_id'],product['image_url'],filename,sha,image.width,image.height)
    return image


def embedding(value, identity=None, offer_id=None, kind=None):
    content_hash=catalog.digest(identity) if identity else None
    cached=catalog.vector(offer_id,kind,MODEL_REVISION,content_hash) if offer_id else None
    if cached:
        dimensions,raw=cached
        result=np.frombuffer(raw,dtype='<f4')
        if result.size==dimensions and np.isfinite(result).all() and np.linalg.norm(result)>0:return result
    result=load_model().encode([value],normalize_embeddings=True,show_progress_bar=False,
        processing_kwargs={'image':{'max_soft_tokens':280}})[0].astype('float32')
    if result.ndim!=1 or not np.isfinite(result).all() or np.linalg.norm(result)==0:
        raise ValueError('Invalid embedding')
    if offer_id:
        catalog.record_vector(offer_id,kind,MODEL_REVISION,content_hash,len(result),result.astype('<f4').tobytes())
    return result

@app.post('/search')
def search(body:Search):
    if not search_lock.acquire(blocking=False): raise HTTPException(429,'검색 중이에요. 잠시 후 다시 시도해 주세요.')
    try:
        try:
            raw=base64.b64decode(body.photo,validate=True);photo=Image.open(io.BytesIO(raw))
            if photo.width*photo.height>4_000_000:raise ValueError()
            photo=photo.convert('RGB')
        except (ValueError,OSError):raise HTTPException(422,'사진을 읽지 못했어요.')
        products,sources=collect(body.query)
        if not products:return {'items':[],'sources':sources,'ranking':'no_candidates'}
        try: query_vector=embedding({'image':photo})
        except Exception:raise HTTPException(503,'사진 비교 모델을 준비 중이에요. 잠시 후 다시 시도하거나 상품 링크를 직접 연결해 주세요.')
        ranked=[]
        with ThreadPoolExecutor(max_workers=4) as downloads:
            images=list(downloads.map(product_image,products))
        for product,image in zip(products,images):
            item=dict(product)
            if image is not None:
                output=io.BytesIO();image.save(output,format='JPEG',quality=80);raw=output.getvalue()
                vector=embedding({'image':image},hashlib.sha256(raw).hexdigest(),item['offer_id'],'image')
                item['image_data']=base64.b64encode(raw).decode();item['basis']='image'
            else:
                vector=embedding(item['title'],'text:'+item['title'],item['offer_id'],'text');item['basis']='text';item['image_data']=None
            item['similarity']=float(np.dot(query_vector,vector))
            item['retrieved_at']=int(time.time());item.pop('image_url',None)
            ranked.append(item)
        ranked.sort(key=lambda x:x['similarity'],reverse=True)
        return {'items':ranked[:8],'sources':sources,'ranking':'embeddinggemma-2','device':str(load_model().device)}
    finally: search_lock.release()
