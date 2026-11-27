"""Isolated security checks: no provider requests, browser or production data."""
from contextlib import contextmanager
import secrets
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from server import social_auth as auth
from server.access import guest_token, guest_owner
from server import db, account_policy
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


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    monkeypatch.setenv('GOODMORNING_ADMIN_DATABASE_URL', db.admin_url())
    monkeypatch.setattr(db, 'data_dir', lambda: tmp_path)
    auth._registrations.clear()
    yield
    auth._registrations.clear()


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


def test_promoted_guest_is_revoked_and_logout_revokes_session(con, client, monkeypatch):
    testclient, key = client
    visitor = guest_token(key)
    owner = guest_owner(Request({'type':'http','headers':[(b'authorization',('Bearer '+visitor).encode())]}),key)
    session, _ = auth.complete_identity(con, 'google', 'user', 'Name', owner)
    request = Request({'type':'http', 'headers':[(b'authorization', ('Bearer '+visitor).encode())]})
    assert auth.identify(request, key, True) == (None, None)
    assert testclient.get('/auth/me', headers={'Authorization':'Bearer '+session}).json()['kind'] == 'member'
    registry=auth.nearby.Registry()
    monkeypatch.setattr(auth.nearby,'registry',registry)
    registry.start(owner,auth.digest(session))
    assert registry.entries
    assert testclient.post('/auth/logout', headers={'Authorization':'Bearer '+session}).status_code == 200
    assert not registry.entries
    assert auth.member_session(con, session) is None


@pytest.mark.parametrize('provider', ['google', 'kakao', 'naver'])
def test_oauth_state_origin_provider_verifier_expiry_and_replay(con, client, monkeypatch, provider):
    testclient, _ = client
    assert testclient.post('/auth/google/start', json=dict(terms=True,privacy=True,age14=True,policy_version=account_policy.VERSION), headers={'Origin':'https://evil.example'}).status_code == 400
    started = testclient.post(f'/auth/{provider}/start', json=dict(terms=True,privacy=True,age14=True,policy_version=account_policy.VERSION)).json()
    body = dict(state=started['state'], verifier=started['verifier'], code='isolated-test-code')
    calls = []
    class FakeClient:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, data):
            calls.append(url)
            assert url == auth.PROVIDERS[provider][1]
            if provider == 'naver': assert data['state'] == body['state']
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'access_token':'isolated-provider-token'})
        def get(self, url, headers):
            profile = {'sub':'isolated-subject', 'name':'Test'} if provider == 'google' else {'id':12345,'kakao_account':{'profile':{'nickname':'Test'}}}
            if provider == 'naver': profile = {'resultcode':'00','response':{'id':'isolated-subject'}}
            assert url == auth.PROVIDERS[provider][2]
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
    assert result.status_code == 200 and len(result.json()['signup_token']) == 43
    assert not con.execute('SELECT 1 FROM account_profiles').fetchone()
    assert result.headers['cache-control'] == 'no-store'
    assert testclient.post(f'/auth/{provider}/complete', json=body).status_code == 400
    assert len(calls) == 1
    expired = testclient.post(f'/auth/{provider}/start', json=dict(terms=True,privacy=True,age14=True,policy_version=account_policy.VERSION)).json()
    con.execute("UPDATE oauth_attempts SET expires_at=now()-interval '1 second'")
    assert testclient.post(f'/auth/{provider}/complete', json={**body,'state':expired['state'],'verifier':expired['verifier']}).status_code == 400
    assert len(calls) == 1


def test_failed_exchange_consumes_state(client, monkeypatch):
    testclient, _ = client
    start = testclient.post('/auth/google/start', json=dict(terms=True,privacy=True,age14=True,policy_version=account_policy.VERSION)).json()
    def failure(**kwargs): raise auth.httpx.ConnectError('isolated failure')
    monkeypatch.setattr(auth.httpx, 'Client', failure)
    body = {k:start[k] for k in ('state','verifier')} | {'code':'isolated-code'}
    assert testclient.post('/auth/google/complete', json=body).status_code == 502
    assert testclient.post('/auth/google/complete', json=body).status_code == 400


@pytest.mark.parametrize('credential', ['bearer', 'cookie'])
@pytest.mark.parametrize('host,external,cf_ray,allowed', [
    ('127.0.0.1', False, False, True),
    ('127.0.0.1', True, False, False),
    ('127.0.0.1', False, True, False),
    ('public.example', False, False, False),
])
def test_owner_capability_is_local_only(credential, host, external, cf_ray, allowed):
    from server.access import COOKIE, session
    key = secrets.token_urlsafe(32)
    headers = [(b'host', host.encode())]
    if credential == 'bearer': headers.append((b'authorization', ('Bearer '+key).encode()))
    else: headers.append((b'cookie', (COOKIE+'='+session(key)).encode()))
    if cf_ray: headers.append((b'cf-ray', b'synthetic'))
    request = Request({'type':'http', 'headers':headers, 'scheme':'http',
                       'server':(host,8787), 'path':'/'})
    assert auth.identify(request,key,external) == (('private',None) if allowed else (None,None))


@pytest.mark.parametrize('profile', [
    {'resultcode':'00','response':{'id':'naver-minimal'}},
    {'resultcode':'00','response':{'id':'naver-full','email':'synthetic@example.invalid','name':'Do not import','nickname':'Ignore','profile_image':'https://example.invalid/photo.png'}},
    {'resultcode':'024','response':{'id':'untrusted'}},
    {'resultcode':'00','response':{}},
    {'resultcode':'00','response':{'id':True}},
    {'resultcode':'00','response':{'id':' '}},
    {'resultcode':'00','response':[]},
])
def test_naver_profile_contract_and_minimal_collection(con,client,monkeypatch,profile):
    testclient,_=client
    public=testclient.get('/auth/providers').json()['naver']
    assert set(public)=={'enabled','callback_url'}
    started=testclient.post('/auth/naver/start',json=dict(terms=True,privacy=True,age14=True,policy_version=account_policy.VERSION)).json()
    from urllib.parse import urlsplit,parse_qs
    query=parse_qs(urlsplit(started['authorize_url']).query)
    assert query['state']==[started['state']] and 'client_secret' not in query and 'scope' not in query
    class FakeClient:
        def __init__(self,**kwargs): assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,data):
            assert data['state']==started['state'] and data['grant_type']=='authorization_code'
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'access_token':'synthetic-provider-only'})
        def get(self,url,headers):
            assert url=='https://openapi.naver.com/v1/nid/me'
            assert headers['Authorization']=='Bearer synthetic-provider-only'
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:profile)
    monkeypatch.setattr(auth.httpx,'Client',FakeClient)
    body={k:started[k] for k in ('state','verifier')}|{'code':'synthetic-code'}
    response=testclient.post('/auth/naver/complete',json=body)
    valid=profile.get('response',{}).get('id') in ('naver-minimal','naver-full') if isinstance(profile.get('response'),dict) else False
    assert response.status_code==(200 if valid else 502)
    assert 'synthetic-provider-only' not in response.text
    assert testclient.post('/auth/naver/complete',json=body).status_code==400
    if valid:
        assert not con.execute('select 1 from account_profiles').fetchone()
        registered=testclient.post('/auth/register',json={'signup_token':response.json()['signup_token'],'nickname':'내 수집방',**CONSENT})
        assert registered.status_code==200
        member=auth.member_session(con,registered.json()['token'])
        assert member['display_name']=='내 수집방' and member['profile_ready'] and not member['has_avatar']
        assert con.execute("select subject from auth_identities where provider='naver'").fetchone()['subject']==profile['response']['id']
    else:assert not con.execute("select 1 from auth_identities where provider='naver'").fetchone()


def test_naver_identity_is_separate_from_other_providers(con):
    sessions=[auth.complete_identity(con,p,'same-subject','Ignored',None)[0] for p in ('google','kakao','naver')]
    assert len({auth.member_session(con,t)['user_id'] for t in sessions})==3


def test_naver_login_settings_do_not_use_shopping_credentials(tmp_path,monkeypatch):
    import json
    monkeypatch.setattr(auth,'data_dir',lambda:tmp_path)
    for key in ('NAVER_LOGIN_CLIENT_ID','NAVER_LOGIN_CLIENT_SECRET','NAVER_LOGIN_CALLBACK_URL'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('NAVER_CLIENT_ID','synthetic-shopping-id')
    monkeypatch.setenv('NAVER_CLIENT_SECRET','synthetic-shopping-secret')
    assert not auth.configured(auth.settings('naver'))
    (tmp_path/'auth.local.json').write_text(json.dumps({'NAVER_LOGIN_CLIENT_ID':'synthetic-login-id','NAVER_LOGIN_CLIENT_SECRET':'synthetic-login-secret'}))
    config=auth.settings('naver')
    assert config['client_id']=='synthetic-login-id' and config['client_secret']=='synthetic-login-secret'
    assert config['callback_url']=='https://niraaah.github.io/GoodMorNing/auth/naver.html'


@pytest.mark.parametrize('status',[200,400,401,503])
def test_naver_withdrawal_revokes_token_without_url_credentials(monkeypatch,status):
    from server import accounts
    monkeypatch.setattr(auth,'settings',lambda p:{'client_id':'synthetic-client','client_secret':'synthetic-secret'})
    def post(url,**kwargs):
        assert url=='https://nid.naver.com/oauth2.0/revoke' and '?' not in url
        assert kwargs['data']=={'client_id':'synthetic-client','client_secret':'synthetic-secret','token':'synthetic-access','token_type_hint':'access_token'}
        assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        return SimpleNamespace(status_code=status)
    monkeypatch.setattr(accounts.httpx,'post',post)
    accounts.remember_provider('synthetic-naver-session','naver','synthetic-access')
    assert accounts.revoke_provider('synthetic-naver-session') is (status==200)
    assert accounts.revoke_provider('synthetic-naver-session') is False


CONSENT=dict(terms=True,privacy=True,age14=True,policy_version=account_policy.VERSION)

def make_signup(subject='signup-test', candidate=None):
    return auth.pending_registration(auth.settings('google'),subject,'synthetic-only-token',candidate,'https://app.example')['signup_token']

@pytest.mark.parametrize('provider',['google','kakao','naver'])
def test_existing_login_needs_no_signup_consent(con,client,monkeypatch,provider):
    testclient,_=client
    auth.complete_identity(con,provider,'returning-user','ignored',None)
    con.execute("UPDATE account_profiles SET display_name='기존 닉네임',profile_ready=true,terms_version=%s,privacy_version=%s,agreed_at=now()-interval '1 day'",(account_policy.VERSION,account_policy.VERSION))
    before=dict(con.execute('select display_name,agreed_at,terms_version,privacy_version from account_profiles').fetchone())
    started=testclient.post(f'/auth/{provider}/start',json={})
    assert started.status_code==200
    state=started.json()
    class Provider:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'access_token':'synthetic-only'})
        def get(self,*args,**kwargs):return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'sub':'returning-user','id':'returning-user','resultcode':'00','response':{'id':'returning-user'}})
    monkeypatch.setattr(auth.httpx,'Client',Provider)
    result=testclient.post(f'/auth/{provider}/complete',json={k:state[k] for k in ('state','verifier')}|{'code':'synthetic'})
    assert result.status_code==200 and result.json()['token'].startswith('member.')
    assert 'signup_token' not in result.json()
    assert dict(con.execute('select display_name,agreed_at,terms_version,privacy_version from account_profiles').fetchone())==before
    assert not auth._registrations

@pytest.mark.parametrize('invalid',[{}, {**CONSENT,'privacy':False}, {**CONSENT,'age14':False}, {**CONSENT,'terms':False}, {**CONSENT,'policy_version':'old'}])
def test_signup_requires_consent_before_persisting_or_promoting(con,client,invalid):
    http,_=client;ticket=make_signup(candidate='guest-untouched')
    result=http.post('/auth/register',json={'signup_token':ticket,'nickname':'새 닉네임','keep_guest':True,**invalid})
    assert result.status_code==422
    assert not con.execute('select 1 from auth_identities').fetchone()
    assert not con.execute('select 1 from account_profiles').fetchone()
    assert not con.execute('select 1 from account_sessions').fetchone()
    assert auth.guest_available(con,'guest-untouched')

@pytest.mark.parametrize('keep',[False,True])
def test_signup_promotion_is_explicit_and_ticket_single_use(con,client,keep):
    http,_=client;ticket=make_signup(candidate='guest-chosen')
    expires=auth._registrations[auth.digest(ticket)]['expires']
    body={'signup_token':ticket,'nickname':'나의 닉네임','keep_guest':keep,**CONSENT}
    result=http.post('/auth/register',json=body)
    assert result.status_code==200 and result.json()['guest_promoted'] is keep
    assert auth.accounts._provider_tokens[auth.digest(result.json()['token'])][0] <= expires
    user=auth.member_session(con,result.json()['token'])
    assert user['profile_ready'] and user['display_name']=='나의 닉네임'
    assert (user['owner']=='guest-chosen') is keep
    assert http.post('/auth/register',json=body).status_code==400

def test_signup_cancel_expiry_origin_and_config_binding(con,client,monkeypatch):
    http,_=client;ticket=make_signup()
    body={'signup_token':ticket,'nickname':'새 계정',**CONSENT}
    assert http.post('/auth/register',json=body,headers={'Origin':'https://evil.example'}).status_code==400
    http.post('/auth/register/cancel',json={'signup_token':ticket},headers={'Origin':'https://evil.example'})
    assert auth.digest(ticket) in auth._registrations
    assert http.post('/auth/register/cancel',json={'signup_token':ticket}).status_code==200
    assert http.post('/auth/register',json=body).status_code==400
    ticket=make_signup();auth._registrations[auth.digest(ticket)]['expires']=0
    assert http.post('/auth/register',json={**body,'signup_token':ticket}).status_code==400
    assert not auth._registrations
    ticket=make_signup();config=auth.settings('google');config['client_secret']='changed-synthetic'
    monkeypatch.setattr(auth,'settings',lambda p:config)
    assert http.post('/auth/register',json={**body,'signup_token':ticket}).status_code==400
    assert not con.execute('select 1 from account_profiles').fetchone()

def test_parallel_signup_tickets_cannot_overwrite_existing_profile(con,client):
    http,_=client;first=make_signup();second=make_signup()
    one=http.post('/auth/register',json={'signup_token':first,'nickname':'첫번째 별명',**CONSENT})
    assert one.status_code==200
    before=dict(con.execute('select display_name,agreed_at from account_profiles').fetchone())
    two=http.post('/auth/register',json={'signup_token':second,'nickname':'덮어쓰기 시도',**CONSENT})
    assert two.status_code==200
    assert dict(con.execute('select display_name,agreed_at from account_profiles').fetchone())==before
    assert auth.member_session(con,one.json()['token'])['user_id']==auth.member_session(con,two.json()['token'])['user_id']
