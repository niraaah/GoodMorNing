"""Profile onboarding and durable, retryable account erasure with restricted DB roles."""
import asyncio
from contextlib import asynccontextmanager
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import time
import unicodedata
from uuid import UUID

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from PIL import Image, ImageOps
from . import db, nearby, account_policy

VERSION='20261127_profiles_erasure_v1'
_locks={}
# Provider tokens are only held briefly in RAM for optional connection revocation.
_provider_tokens={}


@asynccontextmanager
async def owner_lock(owner):
    entry=_locks.setdefault(owner,[asyncio.Lock(),0]);entry[1]+=1
    try:
        async with entry[0]:yield
    finally:
        entry[1]-=1
        if not entry[1]:_locks.pop(owner,None)


def remember_provider(session,provider,token,expires=None):
    now=time.monotonic()
    for key,value in list(_provider_tokens.items()):
        if value[0]<=now:_provider_tokens.pop(key,None)
    if len(_provider_tokens)<2048:_provider_tokens[session]=(min(now+600,expires) if expires is not None else now+600,provider,token)


def discard_provider(session):
    _provider_tokens.pop(session,None)


def revoke_provider(session):
    item=_provider_tokens.pop(session,None)
    if not item or item[0]<=time.monotonic():return False
    _,provider,token=item
    try:
        if provider=='kakao':
            result=httpx.post('https://kapi.kakao.com/v1/user/unlink',headers={'Authorization':'Bearer '+token},timeout=8,trust_env=False)
        elif provider=='naver':
            from .social_auth import settings, configured
            config=settings('naver')
            if not configured(config): return False
            result=httpx.post('https://nid.naver.com/oauth2.0/revoke',data={
                'client_id':config['client_id'],'client_secret':config['client_secret'],
                'token':token,'token_type_hint':'access_token'},timeout=8,trust_env=False,follow_redirects=False)
        elif provider=='google':
            result=httpx.post('https://oauth2.googleapis.com/revoke',data={'token':token},timeout=8,trust_env=False)
        else: return False
        return result.status_code==200
    except (httpx.HTTPError, HTTPException, ValueError):return False


class Profile(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    nickname:str=Field(min_length=2,max_length=40)
    photo:str|None=Field(default=None,max_length=2_800_000)
    remove_photo:bool=False
    terms:bool=False
    privacy:bool=False
    age14:bool=False
    policy_version:str=''


class Delete(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    confirmation:str=Field(max_length=40)
    acknowledged:bool


async def payload(request,model,limit):
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>limit:raise HTTPException(413,'사진은 2MB 이하로 선택해 주세요.')
    try:return model.model_validate_json(content)
    except ValidationError:raise HTTPException(422,'입력한 내용을 확인해 주세요.') from None


def nickname(value):
    value=unicodedata.normalize('NFKC',value).strip()
    if not 2<=len(value)<=20 or any(not (unicodedata.category(c)[0] in 'LN' or c in ' ._-') for c in value):
        raise HTTPException(422,'닉네임은 글자·숫자·공백·._-를 사용해 2~20자로 정해 주세요.')
    return value


def avatar(encoded):
    try:
        data=base64.b64decode(encoded,validate=True)
        if len(data)>2*1024*1024:raise ValueError()
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in ('JPEG','PNG','WEBP') or source.width*source.height>12_000_000 or getattr(source,'n_frames',1)!=1:
                raise ValueError()
            image=ImageOps.exif_transpose(source).convert('RGBA')
            image=ImageOps.fit(image,(256,256))
            clean=Image.new('RGB',(256,256),'white');clean.paste(image,mask=image.getchannel('A'))
            output=io.BytesIO();clean.save(output,'JPEG',quality=85)
            return output.getvalue()
    except (ValueError,OSError,Image.DecompressionBombError):
        raise HTTPException(422,'2MB 이하의 JPG·PNG·WebP 정지 사진을 선택해 주세요.') from None


def member(request):
    value=getattr(request.state,'member',None)
    if not value:raise HTTPException(403,'소셜 로그인 후 이용해 주세요.')
    return value


def response(value,status=200):
    return JSONResponse(value,status_code=status,headers={'Cache-Control':'no-store'})


def ledger_root():
    path=db.data_dir()/'privacy-erasure';path.mkdir(exist_ok=True)
    if path.is_symlink():raise RuntimeError('Invalid privacy directory')
    return path


def record_erasure(user,owner):
    # Outside DB backups so restoring an old DB cannot reactivate a withdrawn member.
    user=str(UUID(str(user)));path=ledger_root()/(user+'.json')
    if path.exists():return
    value={'user_id':user,'owner_hash':hashlib.sha256(owner.encode()).hexdigest(),'at':time.time()}
    temporary=path.with_suffix('.tmp')
    with temporary.open('w',encoding='utf-8') as output:
        json.dump(value,output);output.flush();os.fsync(output.fileno())
    temporary.replace(path)


def remove_owned_file(folder,ident,directory=False):
    # Fixed buckets and IDs only; never accept paths supplied by a user/JSON diary.
    if folder=='assets':valid=re.fullmatch(r'[a-f0-9]{32}',ident)
    else:valid=re.fullmatch(r'[a-f0-9]{64}',ident)
    if not valid:raise RuntimeError('Unexpected owned file identifier')
    bucket=db.data_dir()/folder
    if bucket.is_symlink():raise RuntimeError('Unsafe file bucket')
    base=bucket.resolve()
    if not base.is_relative_to(db.data_dir()):raise RuntimeError('Unsafe file bucket')
    target=base/ident
    if target.is_symlink() or not target.resolve().is_relative_to(base):raise RuntimeError('Unsafe owned path')
    if directory:
        if target.exists():shutil.rmtree(target)
    else:target.unlink(missing_ok=True)


def erase_member(user,owner):
    if owner == 'private':raise RuntimeError('Cannot erase administrator')
    with db.owner_scope(owner),db.connection() as con:
        profile=con.execute('SELECT deleting FROM account_profiles WHERE user_id=%s FOR UPDATE',(user,)).fetchone()
        if not profile or not profile['deleting']:return
        assets={r['ident'] for r in con.execute("SELECT ident FROM ownership WHERE owner=%s AND kind IN ('asset','job')",(owner,))}
        files=[r['id'] for r in con.execute('SELECT id FROM notebook_files WHERE owner=%s',(owner,))]
        for ident in assets:remove_owned_file('assets',ident,True)
        for ident in files:remove_owned_file('notebook-files',ident)
        # Keep ownership/bindings until dependent RLS policies have finished.
        con.execute('DELETE FROM notebook_pages WHERE owner=%s',(owner,))
        con.execute('DELETE FROM user_notebooks WHERE user_id=%s',(user,))
        con.execute('DELETE FROM notebook_files WHERE owner=%s',(owner,))
        con.execute('DELETE FROM asset_trash WHERE owner=%s',(owner,))
        con.execute('DELETE FROM asset_product_links WHERE owner=%s',(owner,))
        con.execute('DELETE FROM goods_searches WHERE owner=%s',(owner,))
        for table,kind in (('diaries','diary'),('jobs','job'),('assets','asset')):
            # table/kind are fixed program constants, never request values.
            con.execute(f'DELETE FROM {table} WHERE id IN (SELECT ident FROM ownership WHERE owner=%s AND kind=%s)',(owner,kind))
        con.execute('DELETE FROM ownership WHERE owner=%s',(owner,))
        con.execute('DELETE FROM oauth_attempts WHERE guest_owner=%s',(owner,))
        con.execute('DELETE FROM account_sessions WHERE user_id=%s',(user,))
        con.execute('DELETE FROM auth_identities WHERE user_id=%s',(user,))
        con.execute('DELETE FROM account_profiles WHERE user_id=%s',(user,))
        con.execute('DELETE FROM app_owner_bindings WHERE user_id=%s',(user,))
        con.execute('DELETE FROM app_users WHERE id=%s',(user,))


def maintenance():
    from .social_auth import cleanup_registrations
    cleanup_registrations()
    now=time.time()
    # Only this project's managed backup/legacy DB files; live PostgreSQL is untouched.
    backup=db.data_dir()/'backups'
    candidates=list(backup.glob('*.dump'))+list(backup.glob('*.sqlite*')) if backup.exists() else []
    for file in candidates:
        if file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(db.data_dir()) and now-file.stat().st_mtime>7*86400:
            file.unlink()
    with db.connection() as con:
        con.execute("DELETE FROM retired_guest_owners WHERE expires_at<now()")
        con.execute("DELETE FROM oauth_attempts WHERE expires_at<now()")
        con.execute("DELETE FROM account_sessions WHERE expires_at<now() OR revoked_at<now()-interval '1 day'")
    for file in ledger_root().glob('*.json'):
        record=json.loads(file.read_text(encoding='utf-8'));user=str(UUID(record['user_id']))
        with db.connection() as con:
            row=con.execute('SELECT owner FROM account_profiles WHERE user_id=%s',(user,)).fetchone()
            con.execute("INSERT INTO retired_guest_owners VALUES(%s,to_timestamp(%s)) ON CONFLICT(owner_hash) DO UPDATE SET expires_at=GREATEST(retired_guest_owners.expires_at,excluded.expires_at)",
                        (record['owner_hash'],record['at']+31*86400))
            if row:
                con.execute("UPDATE account_profiles SET deleting=true,avatar=NULL,display_name='탈퇴 처리 중',deletion_requested_at=COALESCE(deletion_requested_at,now()) WHERE user_id=%s",(user,))
                con.execute('DELETE FROM account_sessions WHERE user_id=%s',(user,))
        if row:
            try:erase_member(user,row['owner'])
            except (OSError,RuntimeError):continue  # Inaccessible until a later retry.
        if now-record['at']>31*86400:file.unlink()
    for key,value in list(_provider_tokens.items()):
        if value[0]<=time.monotonic():_provider_tokens.pop(key,None)


async def cleanup_loop():
    while True:
        await asyncio.sleep(60)
        try:await asyncio.to_thread(maintenance)
        except Exception:
            # No user details in operational error logs.
            import logging
            logging.getLogger('goodmorning').error('Account cleanup requires operator attention')


def initialize():
    with db.connection() as con:
        if not con.execute('SELECT 1 FROM schema_migrations WHERE version=%s',(VERSION,)).fetchone():
            raise RuntimeError('Account migration required')
    maintenance()


def register(app):
    @app.get('/auth/avatar')
    def photo(request:Request):
        user=member(request)
        with db.connection() as con:
            row=con.execute('SELECT avatar FROM account_profiles WHERE user_id=%s',(user['user_id'],)).fetchone()
        if not row or row['avatar'] is None:raise HTTPException(404)
        return Response(bytes(row['avatar']),media_type='image/jpeg',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})

    @app.post('/auth/profile')
    async def save(request:Request):
        user=member(request);value=await payload(request,Profile,2_900_000)
        name=nickname(value.nickname)
        if not user['profile_ready'] or user.get('terms_version')!=account_policy.VERSION or user.get('privacy_version')!=account_policy.VERSION:
            account_policy.accepted(value)
        if value.photo and value.remove_photo:raise HTTPException(422,'사진 변경 방법을 하나만 선택해 주세요.')
        image=avatar(value.photo) if value.photo else None
        with db.connection() as con:
            con.execute('''UPDATE account_profiles SET display_name=%s,profile_ready=true,
                avatar=CASE WHEN %s THEN %s ELSE avatar END,
                agreed_at=CASE WHEN terms_version IS DISTINCT FROM %s OR privacy_version IS DISTINCT FROM %s THEN now() ELSE COALESCE(agreed_at,now()) END,
                terms_version=%s,privacy_version=%s WHERE user_id=%s AND NOT deleting''',
                (name,bool(value.photo) or value.remove_photo,image,account_policy.VERSION,account_policy.VERSION,account_policy.VERSION,account_policy.VERSION,user['user_id']))
        return response({'saved':True})

    @app.post('/auth/delete')
    async def delete(request:Request):
        user=member(request);value=await payload(request,Delete,1024)
        expected=user['display_name'] if user['profile_ready'] else '회원탈퇴'
        if not value.acknowledged or value.confirmation!=expected:
            raise HTTPException(422,'삭제 안내를 확인하고 확인 문구를 정확히 입력해 주세요.')
        with db.connection() as con:
            recent=con.execute("SELECT 1 FROM account_sessions WHERE token_hash=%s AND created_at>now()-interval '10 minutes'",(user['token_hash'],)).fetchone()
            if not recent:raise HTTPException(409,'다시 소셜 로그인한 뒤 10분 안에 탈퇴를 진행해 주세요.')
            if con.execute("SELECT 1 FROM jobs WHERE state IN ('queued','running') LIMIT 1").fetchone() or con.execute("SELECT 1 FROM goods_searches WHERE owner=%s AND state='running' LIMIT 1",(user['owner'],)).fetchone():
                raise HTTPException(409,'진행 중인 스티커·검색 작업이 끝난 뒤 탈퇴해 주세요.')
        record_erasure(user['user_id'],user['owner'])
        with db.connection() as con:
            con.execute("UPDATE account_profiles SET deleting=true,avatar=NULL,display_name='탈퇴 처리 중',deletion_requested_at=now() WHERE user_id=%s",(user['user_id'],))
            for row in con.execute('SELECT token_hash FROM account_sessions WHERE user_id=%s',(user['user_id'],)):
                if row['token_hash']!=user['token_hash']:discard_provider(row['token_hash'])
            con.execute('DELETE FROM account_sessions WHERE user_id=%s',(user['user_id'],))
            con.execute("INSERT INTO retired_guest_owners VALUES(%s,now()+interval '31 days') ON CONFLICT(owner_hash) DO UPDATE SET expires_at=excluded.expires_at",(hashlib.sha256(user['owner'].encode()).hexdigest(),))
        nearby.registry.logout_owner(user['owner'])
        unlinked=await asyncio.to_thread(revoke_provider,user['token_hash'])
        complete=True
        try:await asyncio.to_thread(erase_member,user['user_id'],user['owner'])
        except Exception:complete=False
        return response({'deleted':complete,'pending':not complete,'provider_unlinked':unlinked,
            'message':'탈퇴했어요. 관리 백업은 최대 7일 뒤 삭제돼요.' if complete else '접속을 차단하고 삭제를 접수했어요. 남은 파일 삭제는 자동 재시도해요.'},200 if complete else 202)
