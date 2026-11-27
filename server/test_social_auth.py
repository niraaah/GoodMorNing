"""Isolated security checks: no provider requests, browser or production data."""
from contextlib import contextmanager
import secrets
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from server import social_auth as auth
from server.access import guest_token
from server.test_diary_store import con  # isolated temporary database fixture


def test_identities_are_provider_scoped_and_never_merge_existing_accounts(con):
    first, promoted = auth.complete_identity(con, 'google', 'same-id', 'One', 'guest-one')
    assert promoted
    owner = auth.member_session(con, first)['owner']
    assert owner == 'guest-one' and not auth.guest_available(con, owner)
    again, promoted = auth.complete_identity(con, 'google', 'same-id', 'One', 'guest-two')
    assert not promoted and auth.member_session(con, again)['owner'] == owner
    second, promoted = auth.complete_identity(con, 'kakao', 'same-id', 'Two', 'guest-one')
    assert not promoted and auth.member_session(con, second)['owner'] != owner
    private, promoted = auth.complete_identity(con, 'google', 'other-id', 'Three', 'private')
    assert not promoted and auth.member_session(con, private)['owner'] != 'private'
    assert con.execute('SELECT count(*) AS n FROM account_profiles').fetchone()['n'] == 3
    assert first not in str(con.execute('SELECT * FROM account_sessions').fetchall())


@pytest.mark.parametrize('column', ['expires_at', 'last_seen', 'revoked_at'])
def test_sessions_expire_and_revoke(con, column):
    token, _ = auth.complete_identity(con, 'google', 'user', 'Name', None)
    assert auth.member_session(con, token)
    # Column is a fixed parametrized test literal, never user input.
    con.execute(f"UPDATE account_sessions SET {column}=now()-interval '2 days'")
    assert auth.member_session(con, token) is None


@pytest.fixture
def client(con, monkeypatch):
    @contextmanager
    def transaction():
        with con.transaction():
            yield con
    monkeypatch.setattr(auth, 'connection', transaction)
    configs = {provider: dict(provider=provider, client_id=secrets.token_urlsafe(20),
        client_secret=secrets.token_urlsafe(32), callback_url=f'https://app.example/auth/{provider}.html')
        for provider in auth.PROVIDERS}
    monkeypatch.setattr(auth, 'settings', lambda provider: configs[provider])
    app = FastAPI()
    app.state.access_key = secrets.token_urlsafe(32)
    @app.middleware('http')
    async def identity(request: Request, call_next):
        request.state.owner, request.state.member = auth.identify(request, app.state.access_key, True)
        return await call_next(request)
    auth.register(app)
    with TestClient(app, headers={'Origin': 'https://app.example'}) as testclient:
        yield testclient, app.state.access_key


def test_local_invalid_bearer_never_becomes_admin(client):
    testclient, key = client
    request = Request({'type':'http', 'headers':[(b'authorization', b'Bearer member.invalid')],
                       'scheme':'http', 'server':('localhost', 8787), 'path':'/'})
    assert auth.identify(request, key, False) == (None, None)


def test_promoted_guest_is_revoked_and_logout_revokes_session(con, client):
    testclient, key = client
    visitor = guest_token(key)
    owner = 'guest-' + visitor.split('.')[1]
    session, _ = auth.complete_identity(con, 'google', 'user', 'Name', owner)
    request = Request({'type':'http', 'headers':[(b'authorization', ('Bearer '+visitor).encode())]})
    assert auth.identify(request, key, True) == (None, None)
    assert testclient.get('/auth/me', headers={'Authorization':'Bearer '+session}).json()['kind'] == 'member'
    assert testclient.post('/auth/logout', headers={'Authorization':'Bearer '+session}).status_code == 200
    assert auth.member_session(con, session) is None


@pytest.mark.parametrize('provider', ['google', 'kakao'])
def test_oauth_state_origin_provider_verifier_expiry_and_replay(con, client, monkeypatch, provider):
    testclient, _ = client
    assert testclient.post('/auth/google/start', json={}, headers={'Origin':'https://evil.example'}).status_code == 400
    started = testclient.post(f'/auth/{provider}/start', json={}).json()
    body = dict(state=started['state'], verifier=started['verifier'], code='isolated-test-code')
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, data):
            calls.append(url)
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'access_token':'isolated-provider-token'})
        def get(self, url, headers):
            profile = {'sub':'isolated-subject', 'name':'Test'} if provider == 'google' else {'id':12345,'kakao_account':{'profile':{'nickname':'Test'}}}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: profile)
    # Only replace the backend provider client after the ASGI TestClient exists.
    monkeypatch.setattr(auth.httpx, 'Client', FakeClient)
    for route, payload, origin in [
        (provider, {**body, 'verifier':secrets.token_urlsafe(32)}, 'https://app.example'),
        ('kakao' if provider == 'google' else 'google', body, 'https://app.example'),
        (provider, body, 'https://evil.example'),
        (provider, {**body, 'state':secrets.token_urlsafe(32)}, 'https://app.example'),
    ]:
        assert testclient.post(f'/auth/{route}/complete', json=payload, headers={'Origin':origin}).status_code == 400
    assert not calls
    result = testclient.post(f'/auth/{provider}/complete', json=body)
    assert result.status_code == 200 and result.json()['token'].startswith('member.')
    assert result.headers['cache-control'] == 'no-store'
    assert testclient.post(f'/auth/{provider}/complete', json=body).status_code == 400
    assert len(calls) == 1
    expired = testclient.post(f'/auth/{provider}/start', json={}).json()
    con.execute("UPDATE oauth_attempts SET expires_at=now()-interval '1 second'")
    assert testclient.post(f'/auth/{provider}/complete', json={**body,'state':expired['state'],'verifier':expired['verifier']}).status_code == 400
    assert len(calls) == 1


def test_failed_exchange_consumes_state(client, monkeypatch):
    testclient, _ = client
    start = testclient.post('/auth/google/start', json={}).json()
    def failure(**kwargs): raise auth.httpx.ConnectError('isolated failure')
    monkeypatch.setattr(auth.httpx, 'Client', failure)
    body = {k:start[k] for k in ('state','verifier')} | {'code':'isolated-code'}
    assert testclient.post('/auth/google/complete', json=body).status_code == 502
    assert testclient.post('/auth/google/complete', json=body).status_code == 400
