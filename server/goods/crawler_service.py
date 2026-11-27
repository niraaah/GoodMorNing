"""Query-only crawler boundary: no member photos, DB or owner credentials."""
import asyncio
import hmac
import json
import os
import signal
from pathlib import Path
import sys
import tempfile
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
gate=asyncio.Lock()


class Query(BaseModel):
    model_config=ConfigDict(extra='forbid')
    query:str=Field(min_length=1,max_length=80)


def authorize(request):
    expected=Path(os.environ['GOODMORNING_CRAWLER_KEY_FILE']).read_text(encoding='utf-8').strip()
    value=request.headers.get('authorization','').removeprefix('Bearer ')
    if not expected or not hmac.compare_digest(value.encode(),expected.encode()):
        raise HTTPException(401,'Unauthorized')


@app.get('/health')
def health(request:Request):
    authorize(request)
    return {'status':'ok','isolated':True}


@app.post('/collect')
async def collect(request:Request):
    authorize(request)
    chunks=bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks)>4096:
            raise HTTPException(413,'Query too large')
    try:
        query=Query.model_validate_json(chunks).query.strip()
        if not query:raise ValueError()
    except (ValidationError,ValueError):
        raise HTTPException(422,'Invalid query')
    if gate.locked():raise HTTPException(429,'Crawler busy')
    async with gate:
        with tempfile.TemporaryDirectory(prefix='goods-') as folder:
            output=Path(folder)/'catalog.json'
            process=await asyncio.create_subprocess_exec(sys.executable,'-m','server.goods.crawl',query,str(output),
                stdout=asyncio.subprocess.DEVNULL,stderr=asyncio.subprocess.DEVNULL,start_new_session=True)
            try:
                await asyncio.wait_for(process.wait(),100)
                if process.returncode or not output.is_file() or output.stat().st_size>256*1024:
                    raise ValueError()
                result=json.loads(output.read_text(encoding='utf-8'))
                if not isinstance(result.get('products'),list) or not isinstance(result.get('sources'),list):
                    raise ValueError()
                return {'products':result['products'][:24],'sources':result['sources'][:4]}
            except (ValueError,OSError,TimeoutError):
                raise HTTPException(502,'Collection unavailable')
            finally:
                # Kill the whole Linux process group, including browser children.
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                await process.wait()
