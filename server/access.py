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
    return HTMLResponse('''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>굿모닝에 들어가기</title>
<style>body{margin:0;background:#eef7fc;color:#294653;font:16px sans-serif;display:grid;place-items:center;min-height:100vh}main{width:min(380px,80vw);background:white;padding:32px;border-radius:24px;border:1px solid #d5e5ed}h1{font-size:30px}p{font-size:14px;line-height:1.8;color:#6d8795}input,button{box-sizing:border-box;width:100%;padding:14px;border-radius:12px;border:1px solid #d5e5ed;margin-top:12px}button{background:#294653;color:white;cursor:pointer}#error{color:#ad5151}</style>
<main><p>MY LITTLE COLLECTION</p><h1>굿모닝 ☀</h1><p>나의 작은 수집방에 오신 걸 환영해요.<br>전달받은 접속 링크로 열거나 접근 키를 입력해 주세요.</p><form id="form"><input id="key" type="password" autocomplete="off" aria-label="접근 키" placeholder="접근 키"><button>내 수집방 열기</button></form><p id="error"></p></main>
<script>const form=document.querySelector('#form'),key=document.querySelector('#key'),error=document.querySelector('#error');async function login(value){error.textContent='연결하고 있어요…';try{const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({key:value})});if(!r.ok)throw Error('접근 키를 다시 확인해 주세요.');location.replace('/');}catch(e){error.textContent=e.message;}}form.onsubmit=e=>{e.preventDefault();login(key.value);};if(location.hash.length>1){const token=decodeURIComponent(location.hash.slice(1));history.replaceState(null,'','/connect');login(token);}</script></html>''',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
