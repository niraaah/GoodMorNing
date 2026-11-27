"""Owner-scoped async photo search and explicit product-to-sticker association."""
import base64
import io
import json
import threading
import time
import uuid
import httpx
from fastapi import Request, UploadFile, File, Form, HTTPException
from ..db import Jsonb, owner_scope
from .config import DATA, GUIDANCE, product_url

DAY = "now() - interval '1 day'"

def initialize(con):
    pass  # Fixed startup recovery runs through gm_recover_jobs(), not broad SQL rights.

def selection(con,owner,search_id,candidate_id,manual_url,manual_title):
    if manual_url:
        try: url=product_url(manual_url)
        except ValueError as error: raise HTTPException(422,str(error))
        if search_id or candidate_id:raise HTTPException(422,'추천 상품과 직접 링크 중 하나를 선택해 주세요.')
        return {'title':manual_title.strip() or '직접 연결한 굿즈','url':url,'source':'직접 연결',
                'confirmed_by_user':True,'match_method':'manual','confirmed_at':int(time.time())}
    if not search_id and not candidate_id:return None
    row=con.execute(f"SELECT * FROM goods_searches WHERE id=%s AND owner=%s AND state='completed' AND created>={DAY}",(search_id,owner)).fetchone()
    if not row:raise HTTPException(422,'검색 결과가 만료됐어요. 다시 검색해 주세요.')
    item=next((p for p in row['body'].get('items',[]) if p['id']==candidate_id),None)
    if not item:raise HTTPException(422,'추천 목록에서 상품을 다시 선택해 주세요.')
    return {**{k:v for k,v in item.items() if k not in ('image_data','similarity')},
            'confirmed_by_user':True,'match_method':'user_selected_recommendation','confirmed_at':int(time.time())}

def register(app,connection,uploaded_image):
    gate=threading.BoundedSemaphore(2)
    def run(ident,photo,query,owner):
        try:
            key=(DATA/'search-service.key').read_text(encoding='utf-8').strip()
            response=httpx.post('http://127.0.0.1:8788/search',headers={'Authorization':'Bearer '+key},
                json={'photo':photo,'query':query},timeout=300,trust_env=False)
            if response.status_code!=200:
                message=response.json().get('detail','상품을 찾지 못했어요. 다시 시도해 주세요.')
                body={'message':message};state='failed'
            else:body=response.json();state='completed'
        except (httpx.HTTPError,ValueError,OSError):
            body={'message':'상품 검색 서버에 연결하지 못했어요. 잠시 후 다시 시도하거나 링크를 직접 연결해 주세요.'};state='failed'
        finally:gate.release()
        body['guidance']=GUIDANCE
        with owner_scope(owner), connection() as con:
            con.execute('UPDATE goods_searches SET state=%s,body=%s WHERE id=%s',(state,Jsonb(body),ident))

    @app.post('/api/goods/searches',status_code=202)
    async def begin(request:Request,photo:UploadFile=File(),query:str=Form(min_length=1,max_length=80),box:str=Form('[0,0,1,1]')):
        if not query.strip():raise HTTPException(422,'상품명이나 캐릭터명을 입력해 주세요.')
        try:
            bounds=json.loads(box)
            if len(bounds)!=4 or any(type(x) not in (int,float) or not 0<=x<=1 for x in bounds) or bounds[2]-bounds[0]<.02 or bounds[3]-bounds[1]<.02:raise ValueError()
        except (ValueError,TypeError):raise HTTPException(422,'사진에서 굿즈 영역을 선택해 주세요.')
        image=await uploaded_image(photo)
        w,h=image.size; image=image.crop((int(bounds[0]*w),int(bounds[1]*h),int(bounds[2]*w),int(bounds[3]*h))).convert('RGB');image.thumbnail((640,640))
        output=io.BytesIO();image.save(output,format='JPEG',quality=90)
        if not gate.acquire(blocking=False):raise HTTPException(429,'검색 중인 사진이 많아요. 잠시 후 다시 시도해 주세요.')
        ident=uuid.uuid4().hex
        try:
            with connection() as con:
                active=con.execute("SELECT id FROM goods_searches WHERE owner=%s AND state='running'",(request.state.owner,)).fetchone()
                if active:raise HTTPException(429,'이전에 올린 사진을 검색 중이에요. 결과를 기다려 주세요.')
                con.execute(f'DELETE FROM goods_searches WHERE created<{DAY}')
                con.execute('INSERT INTO goods_searches VALUES(%s,%s,%s,%s,now())',(ident,request.state.owner,'running',Jsonb({})))
            threading.Thread(target=run,args=(ident,base64.b64encode(output.getvalue()).decode(),query.strip(),request.state.owner),daemon=True).start()
        except Exception:gate.release();raise
        return {'id':ident,'state':'running'}

    @app.get('/api/goods/searches/{ident}')
    def result(ident:str,request:Request):
        with connection() as con:row=con.execute('SELECT * FROM goods_searches WHERE id=%s AND owner=%s',(ident,request.state.owner)).fetchone()
        if not row:raise HTTPException(404,'검색 결과를 찾지 못했어요.')
        return {'id':ident,'state':row['state'],**row['body']}
