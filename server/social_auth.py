"""Google/Kakao/Naver authorization-code login with browser-bound, single-use state.

Provider secrets/tokens never reach the frontend. Application bearer sessions
are random, stored as hashes, expire and can be revoked independently.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ConfigDict

from . import nearby, accounts, account_policy
from .access import authorized, guest_owner, requires_access
from .db import connection, data_dir
from .diary_store import ensure_user

PROVIDERS = {
    'naver': ('https://nid.naver.com/oauth2.0/authorize', 'https://nid.naver.com/oauth2.0/token', 'https://openapi.naver.com/v1/nid/me', ''),
    'google': ('https://accounts.google.com/o/oauth2/v2/auth', 'https://oauth2.googleapis.com/token', 'https://openidconnect.googleapis.com/v1/userinfo', 'openid'),
    'kakao': ('https://kauth.kakao.com/oauth/authorize', 'https://kauth.kakao.com/oauth/token', 'https://kapi.kakao.com/v2/user/me', ''),
}
PUBLIC_PATHS = {'/auth/providers','/auth/legal','/auth/register','/auth/register/cancel'} | {f'/auth/{p}/{action}' for p in PROVIDERS for action in ('start', 'complete')}


# Unregistered identities remain ephemeral until explicit signup consent.
_registrations = {}
_registration_lock = threading.RLock()

def cleanup_registrations():
    with _registration_lock:
        for key, value in list(_registrations.items()):
            if value['expires'] <= time.monotonic(): _registrations.pop(key, None)

def pending_registration(config, subject, token, candidate, origin):
    with _registration_lock:
        cleanup_registrations()
        if len(_registrations) >= 2048:
            raise HTTPException(503, '가입 요청이 많아요. 잠시 후 다시 시도해 주세요.')
        ticket = secrets.token_urlsafe(32)
        _registrations[digest(ticket)] = dict(provider=config['provider'], subject=subject,
            access_token=token, candidate=candidate, origin=origin,
            config_hash=digest(json.dumps(config, sort_keys=True)), expires=time.monotonic()+600)
        return {'signup_token':ticket, 'expires_in':600}

class Registration(accounts.Profile):
    signup_token: str = Field(min_length=43, max_length=43, pattern=r'^[A-Za-z0-9_-]+$')
    keep_guest: bool = False

class CancelRegistration(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    signup_token: str = Field(min_length=43,max_length=43,pattern=r'^[A-Za-z0-9_-]+$')


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def settings(provider):
    if provider not in PROVIDERS:
        raise HTTPException(404, '지원하지 않는 로그인 방식이에요.')
    prefix = 'NAVER_LOGIN' if provider == 'naver' else provider.upper()
    path = data_dir()/'auth.local.json'
    try:
        values = json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else {}
        result = {key: str(os.getenv(prefix+'_'+key.upper()) or values.get(prefix+'_'+key.upper(), ''))
                  for key in ('client_id', 'client_secret', 'callback_url')}
    except (ValueError, AttributeError):
        raise HTTPException(503, '로그인 연결 설정을 확인하고 있어요.')
    result['provider'] = provider
    result['callback_url'] = result['callback_url'] or f'https://niraaah.github.io/GoodMorNing/auth/{provider}.html'
    callback = urlsplit(result['callback_url'])
    if not callback.netloc or callback.scheme != 'https' or callback.username or callback.password or callback.query or callback.fragment:
        raise HTTPException(503, '로그인 연결 설정을 확인하고 있어요.')
    return result


def configured(config):
    return bool(config['client_id'] and config['client_secret'])


def guest_available(con, owner):
    return not con.execute('SELECT 1 FROM account_profiles WHERE owner=%s', (owner,)).fetchone() and not con.execute('SELECT 1 FROM retired_guest_owners WHERE owner_hash=%s AND expires_at>now()',(digest(owner),)).fetchone()


def member_session(con, token):
    if not re.fullmatch(r'member\.[A-Za-z0-9_-]{43}', token):
        return None
    row = con.execute('''SELECT p.user_id,p.owner,p.display_name,p.profile_ready,p.terms_version,p.privacy_version,(p.avatar IS NOT NULL) AS has_avatar,s.token_hash FROM account_sessions s
        JOIN account_profiles p ON p.user_id=s.user_id WHERE s.token_hash=%s AND s.revoked_at IS NULL
        AND NOT p.deleting AND s.expires_at>now() AND s.last_seen>now()-interval '24 hours' ''', (digest(token),)).fetchone()
    if row and (accounts.ledger_root()/(str(row['user_id'])+'.json')).exists():return None
    if row:
        con.execute("UPDATE account_sessions SET last_seen=now() WHERE token_hash=%s AND last_seen<now()-interval '5 minutes'", (row['token_hash'],))
    return row


def identify(request, key, external_frontend):
    bearer = request.headers.get('authorization', '')
    # Owner capabilities are local administration only, never public app sessions.
    if authorized(request, key):
        return ('private', None) if not (requires_access(request) or external_frontend) else (None, None)
    if bearer:
        token = bearer.removeprefix('Bearer ')
        if token.startswith('member.'):
            with connection() as con:
                member = member_session(con, token)
            return (member['owner'], member) if member else (None, None)
        owner = guest_owner(request, key)
        if owner:
            with connection() as con:
                if guest_available(con, owner):
                    return owner, None
        # An invalid explicit token must never fall back to local administrator access.
        return None, None
    return ('private', None) if not (requires_access(request) or external_frontend) else (None, None)


def issue_session(con, user):
    token = 'member.' + secrets.token_urlsafe(32)
    con.execute("DELETE FROM account_sessions WHERE expires_at<now() OR revoked_at<now()-interval '1 day'")
    con.execute("INSERT INTO account_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,now()+interval '7 days')", (digest(token), user))
    return token


def complete_identity(con, provider, subject, name, candidate):
    # Serializes concurrent first logins for the same provider subject.
    con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (provider+':'+subject,))
    existing = con.execute('SELECT user_id FROM auth_identities WHERE provider=%s AND subject=%s', (provider, subject)).fetchone()
    promoted = False
    if existing:
        user = existing['user_id']
        if con.execute('SELECT 1 FROM account_profiles WHERE user_id=%s AND deleting',(user,)).fetchone() or (accounts.ledger_root()/(str(user)+'.json')).exists():
            raise HTTPException(409,'탈퇴 자료를 정리 중이에요. 잠시 후 다시 시도해 주세요.')
    else:
        if candidate and candidate.startswith('guest-'):
            user = ensure_user(con, candidate)
            con.execute('SELECT id FROM app_users WHERE id=%s FOR UPDATE', (user,))
            promoted = guest_available(con, candidate)
        if not promoted:
            candidate = 'member-' + uuid4().hex
            user = ensure_user(con, candidate)
        con.execute("UPDATE app_users SET kind='member' WHERE id=%s", (user,))
        con.execute('INSERT INTO account_profiles(user_id,owner,display_name) VALUES(%s,%s,%s)', (user, candidate, '새 수집가'))
        con.execute('INSERT INTO auth_identities(provider,subject,user_id) VALUES(%s,%s,%s)', (provider, subject, user))
    return issue_session(con, user), promoted


class Begin(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    keep_guest: bool = False
    # Legacy clients may send these; login never records them as signup consent.
    terms:bool=False
    privacy:bool=False
    age14:bool=False
    policy_version:str=''


class Finish(BaseModel):
    state: str = Field(min_length=32, max_length=128)
    verifier: str = Field(min_length=32, max_length=128)
    code: str = Field(min_length=1, max_length=2048)


def response(value):
    return JSONResponse(value, headers={'Cache-Control': 'no-store', 'Pragma': 'no-cache'})


def register(app):
    @app.get('/auth/providers')
    def providers():
        return response({p: {'enabled': configured(settings(p)), 'callback_url': settings(p)['callback_url']} for p in PROVIDERS})

    @app.get('/auth/me')
    def me(request: Request):
        member = request.state.member
        if member:

            with connection() as con:
                provider=con.execute('SELECT provider FROM auth_identities WHERE user_id=%s LIMIT 1',(member['user_id'],)).fetchone()['provider']
            return response({'kind':'member','name':member['display_name'],'profile_ready':member['profile_ready'] and member['terms_version']==account_policy.VERSION and member['privacy_version']==account_policy.VERSION,
                'has_avatar':member['has_avatar'],'provider':provider,'profile_created':member['profile_ready']})
        return response({'kind': 'local' if request.state.owner == 'private' else 'guest'})

    @app.post('/auth/{provider}/start')
    def start(provider: str, body: Begin, request: Request):
        config = settings(provider)
        if not configured(config):
            raise HTTPException(503, '소셜 로그인 연결을 준비 중이에요. 잠시 후 다시 이용해 주세요.')
        callback = urlsplit(config['callback_url'])
        origin = request.headers.get('origin', '')
        if origin != f'{callback.scheme}://{callback.netloc}':
            raise HTTPException(400, '공개 웹 주소에서 소셜 로그인을 이용해 주세요.')
        client = request.headers.get('cf-connecting-ip') if request.headers.get('cf-ray') else request.client.host
        client_hash = hmac.new(app.state.access_key.encode(), (client or 'unknown').encode(), hashlib.sha256).hexdigest()
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        owner = request.state.owner
        candidate = owner if owner and owner.startswith('guest-') and not request.state.member else None
        with connection() as con:
            con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('oauth-start:'+client_hash,))
            con.execute('DELETE FROM oauth_attempts WHERE expires_at<now()')
            if con.execute('SELECT count(*) AS n FROM oauth_attempts WHERE client_hash=%s', (client_hash,)).fetchone()['n'] >= 30:
                raise HTTPException(429, '로그인 요청이 많아요. 10분 뒤 다시 시도해 주세요.')
            con.execute('''INSERT INTO oauth_attempts(state_hash,verifier_hash,client_hash,config_hash,origin,guest_owner,expires_at,policy_version)
                VALUES(%s,%s,%s,%s,%s,%s,now()+interval '10 minutes',%s)''',
                (digest(state), digest(verifier), client_hash, digest(json.dumps(config,sort_keys=True)), origin, candidate, account_policy.VERSION))
        query = urlencode({'response_type': 'code', 'client_id': config['client_id'],
                           'redirect_uri': config['callback_url'], 'state': state, 'scope': PROVIDERS[provider][3]})
        if not PROVIDERS[provider][3]:
            query=urlencode({'response_type':'code','client_id':config['client_id'],'redirect_uri':config['callback_url'],'state':state})
        return response({'authorize_url': PROVIDERS[provider][0]+'?'+query, 'state': state, 'verifier': verifier})

    @app.post('/auth/{provider}/complete')
    def finish(provider: str, body: Finish, request: Request):
        config = settings(provider)
        if not configured(config):
            raise HTTPException(503, '소셜 로그인 연결을 준비 중이에요.')
        with connection() as con:
            attempt = con.execute('''UPDATE oauth_attempts SET consumed_at=now() WHERE state_hash=%s
                AND verifier_hash=%s AND origin=%s AND config_hash=%s AND consumed_at IS NULL AND expires_at>now()
                RETURNING guest_owner,policy_version''', (digest(body.state), digest(body.verifier), request.headers.get('origin',''),
                digest(json.dumps(config,sort_keys=True)))).fetchone()
        if not attempt:
            raise HTTPException(400, '로그인 요청이 만료되었어요. 앱에서 다시 시작해 주세요.')
        try:
            with httpx.Client(timeout=15, trust_env=False, follow_redirects=False) as client:
                tokens = client.post(PROVIDERS[provider][1], data={
                    'grant_type': 'authorization_code', 'client_id': config['client_id'],
                    'client_secret': config['client_secret'], 'code': body.code,
                    'redirect_uri': config['callback_url'],
                    **({'state': body.state} if provider == 'naver' else {})})
                tokens.raise_for_status()
                token_data = tokens.json()
                if token_data.get('error'):
                    raise ValueError()
                token = token_data.get('access_token')
                if not isinstance(token, str) or not token:
                    raise ValueError()
                profile = client.get(PROVIDERS[provider][2], headers={'Authorization': 'Bearer '+token})
                profile.raise_for_status()
                data = profile.json()
                if provider == 'naver':
                    if data.get('resultcode') != '00' or not isinstance(data.get('response'), dict):
                        raise ValueError()
                    subject = data['response'].get('id')
                else:
                    subject = data.get('sub') if provider == 'google' else data.get('id')
                if not isinstance(subject, (str, int)) or isinstance(subject, bool) or not 1 <= len(str(subject)) <= 200:
                    raise ValueError()
                subject = str(subject)
                if not subject.strip() or subject != subject.strip():
                    raise ValueError()
                name='새 수집가'  # Do not import social names, email or profile photos.
        except (httpx.HTTPError, ValueError, TypeError, AttributeError):
            raise HTTPException(502, '소셜 로그인을 확인하지 못했어요. 앱에서 다시 시도해 주세요.')
        with connection() as con:
            existing = con.execute('SELECT 1 FROM auth_identities WHERE provider=%s AND subject=%s', (provider, subject)).fetchone()
            if existing:
                session, promoted = complete_identity(con, provider, subject, name, None)
        if not existing:
            return response(pending_registration(config, subject, token, attempt['guest_owner'], request.headers.get('origin','')))
        accounts.remember_provider(digest(session),provider,token)
        return response({'token': session, 'guest_promoted': promoted})

    @app.post('/auth/register')
    async def signup(request: Request):
        value = await accounts.payload(request, Registration, 2_900_000)
        with _registration_lock:
            cleanup_registrations()
            pending = _registrations.get(digest(value.signup_token))
            if not pending or pending['origin'] != request.headers.get('origin',''):
                raise HTTPException(400, '가입 요청이 만료되었어요. 다시 로그인해 주세요.')
        account_policy.accepted(value)
        name = accounts.nickname(value.nickname)
        if value.photo and value.remove_photo: raise HTTPException(422, '사진 변경 방법을 하나만 선택해 주세요.')
        image = accounts.avatar(value.photo) if value.photo else None
        with _registration_lock:
            cleanup_registrations()
            item = _registrations.get(digest(value.signup_token))
            if not item or item['origin'] != request.headers.get('origin',''):
                raise HTTPException(400, '가입 요청이 만료되었어요. 다시 로그인해 주세요.')
            config = settings(item['provider'])
            if item['config_hash'] != digest(json.dumps(config,sort_keys=True)):
                raise HTTPException(400, '로그인 설정이 변경되었어요. 다시 로그인해 주세요.')
            with connection() as con:
                session, promoted = complete_identity(con, item['provider'], item['subject'], name,
                    item['candidate'] if value.keep_guest else None)
                user = member_session(con, session)
                # A parallel signup may already have completed this identity.
                # Never overwrite an existing profile or its consent history.
                con.execute("""UPDATE account_profiles SET display_name=%s,avatar=%s,profile_ready=true,
                    terms_version=%s,privacy_version=%s,agreed_at=now()
                    WHERE user_id=%s AND NOT profile_ready AND NOT deleting""",
                    (name,image,account_policy.VERSION,account_policy.VERSION,user['user_id']))
            _registrations.pop(digest(value.signup_token),None)
            accounts.remember_provider(digest(session),item['provider'],item['access_token'],expires=item['expires'])
        return response({'token':session,'guest_promoted':promoted})

    @app.post('/auth/register/cancel')
    async def cancel_signup(request: Request):
        value = await accounts.payload(request, CancelRegistration, 1024)
        with _registration_lock:
            cleanup_registrations()
            item = _registrations.get(digest(value.signup_token))
            if item and item['origin'] == request.headers.get('origin',''):
                _registrations.pop(digest(value.signup_token),None)
        return response({'cancelled':True})

    @app.post('/auth/logout')
    def logout(request: Request):
        if request.state.member:
            with connection() as con:
                con.execute('UPDATE account_sessions SET revoked_at=now() WHERE token_hash=%s', (request.state.member['token_hash'],))
            nearby.registry.logout(request.state.member['token_hash'])
            accounts.discard_provider(request.state.member['token_hash'])
        return response({'ok': True})
