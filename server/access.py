"""Capability link for the user's temporary remote preview."""
import hashlib
import hmac
import secrets
import re
import time
from pathlib import Path
from fastapi.responses import HTMLResponse

COOKIE = 'goodmorning_access'

def load_key(data: Path):
    path = data / 'access.key'
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32), encoding='utf-8')
    return path.read_text(encoding='utf-8').strip()

def session(key):
    return hmac.new(key.encode(), b'goodmorning-browser-session-v1', hashlib.sha256).hexdigest()

def requires_access(request):
    return bool(request.headers.get('cf-ray')) or request.url.hostname not in ('localhost','127.0.0.1','testserver','[::1]','::1')

def authorized(request, key):
    bearer = request.headers.get('authorization', '')
    if bearer.startswith('Bearer '):
        return hmac.compare_digest(bearer[7:].encode(), key.encode())
    return hmac.compare_digest(request.cookies.get(COOKIE,''), session(key))


def guest_token(key):
    ident = secrets.token_hex(16)
    issued=str(int(time.time()))
    signature = hmac.new(key.encode(), ('guest:' + issued + ':' + ident).encode(), hashlib.sha256).hexdigest()
    return f'guest.{issued}.{ident}.{signature}'


def guest_owner(request, key):
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    match = re.fullmatch(r'guest\.([0-9]{10})\.([a-f0-9]{32})\.([a-f0-9]{64})', token)
    if match:
        issued,ident,signature=match.groups()
        if not -60<=time.time()-int(issued)<30*86400:return None
        message='guest:'+issued+':'+ident
    else:
        match=re.fullmatch(r'guest\.([a-f0-9]{32})\.([a-f0-9]{64})',token)
        # Transition deadline for old non-expiring visitor links: 2026-12-27 UTC.
        if not match or time.time()>=1798329600:return None
        ident,signature=match.groups();message='guest:'+ident
    expected=hmac.new(key.encode(),message.encode(),hashlib.sha256).hexdigest()
    return 'guest-'+ident if hmac.compare_digest(signature,expected) else None


def connect_page():
    return HTMLResponse('''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>굿모닝</title>
<main><h1>굿모닝</h1><p>공개 앱에서 자동으로 연결돼요.</p><a href="https://niraaah.github.io/GoodMorNing/" rel="noreferrer">수집방 열기</a></main>
<script>if(location.hash)history.replaceState(null,'','/connect');</script></html>''', headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
