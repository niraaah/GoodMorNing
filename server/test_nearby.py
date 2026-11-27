"""Synthetic coordinates and isolated memory only; no GPS or live member data."""
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from server import nearby


@pytest.fixture
def service(monkeypatch):
    now=[1000.0]
    registry=nearby.Registry(lambda:now[0])
    monkeypatch.setattr(nearby,'registry',registry)
    app=FastAPI()
    @app.middleware('http')
    async def identity(request,call_next):
        # Stub only after the real authentication boundary: no production bypass.
        session=request.headers.get('x-test-session')
        owner=request.headers.get('x-test-owner','a')
        request.state.member={'owner':owner,'token_hash':session} if session else None
        return await call_next(request)
    nearby.attach(app)
    return TestClient(app),registry,now


def headers(owner='a',session=None):
    return {'x-test-session':session or owner,'x-test-owner':owner}


def start(client,owner='a',session=None):
    response=client.post('/api/nearby/start',json={'consent':True},headers=headers(owner,session))
    assert response.status_code==200
    return response.json()['lease']


def update(client,lease,owner='a',session=None,latitude=0.0004,longitude=0.0004):
    return client.post('/api/nearby/update',json={'lease':lease,'latitude':latitude,'longitude':longitude,'accuracy':30.0},headers=headers(owner,session))


@pytest.mark.parametrize('path',['start','update','stop'])
def test_guests_and_owner_key_do_not_get_proximity(service,path):
    client,_,_=service
    assert client.post('/api/nearby/'+path,json={}).status_code==403


def test_explicit_consent_and_bounded_body(service):
    client,registry,_=service
    for payload in ({'consent':False},{'consent':'yes'},{'consent':True,'owner':'other'}):
        assert client.post('/api/nearby/start',json=payload,headers=headers()).status_code in (400,422)
    assert client.post('/api/nearby/start',content=b'x'*1025,headers=headers()).status_code==413
    assert not registry.entries


def test_mutual_opt_in_only_boolean_no_identity_or_location(service):
    client,registry,now=service
    a=start(client);b=start(client,'b')
    assert update(client,a).json()['nearby'] is False  # b has not supplied location
    result=update(client,b,'b',latitude=0.004).json()
    assert result['nearby'] is True and result['notify'] is True
    assert set(result)=={'nearby','notify','remaining_seconds'}
    assert registry.entries['a'].position==(0.0,0.0)
    now[0]+=30
    result=update(client,a)
    assert result.json()['notify'] is True
    assert result.headers['cache-control']=='no-store'
    assert 'latitude' not in result.text and 'session' not in result.text


def test_far_user_is_not_nearby(service):
    client,_,_=service
    a=start(client);b=start(client,'b')
    update(client,a)
    assert update(client,b,'b',latitude=1.0).json()['nearby'] is False


@pytest.mark.parametrize('field,value',[('latitude',91),('longitude',181),('accuracy',251),('accuracy',-1),('latitude','0'),('latitude',True)])
def test_invalid_location_never_echoes_inputs(service,field,value):
    client,registry,_=service
    lease=start(client)
    payload={'lease':lease,'latitude':0.0,'longitude':0.0,'accuracy':10.0,field:value}
    result=client.post('/api/nearby/update',json=payload,headers=headers())
    assert result.status_code==422 and set(result.json())=={'detail'}
    assert registry.entries['a'].position is None


def test_non_finite_location_rejected(service):
    client,registry,_=service;lease=start(client)
    result=client.post('/api/nearby/update',content=json.dumps({'lease':lease,'latitude':float('nan'),'longitude':0.0,'accuracy':10.0}),headers=headers())
    assert result.status_code==422 and 'NaN' not in result.text
    assert registry.entries['a'].position is None


def test_lease_is_bound_to_member_and_session(service):
    client,registry,_=service;a=start(client)
    assert update(client,a,'b').status_code==409
    assert update(client,a,session='different-session').status_code==409
    client.post('/api/nearby/stop',json={'lease':a},headers=headers('b'))
    assert 'a' in registry.entries
    client.post('/api/nearby/stop',json={'lease':a},headers=headers())
    assert 'a' not in registry.entries
    assert update(client,a).status_code==409


def test_stale_and_absolute_expiry_even_with_heartbeats(service):
    client,registry,now=service;a=start(client);update(client,a)
    now[0]+=90
    assert update(client,a).status_code==409
    assert not registry.entries
    a=start(client)
    for _ in range(29):
        now[0]+=30;assert update(client,a).status_code==200
    now[0]+=30
    assert update(client,a).status_code==409


def test_rate_limit_and_cooldown_survive_restart_of_sharing(service):
    client,registry,now=service;a=start(client);b=start(client,'b')
    update(client,a);assert update(client,b,'b').json()['notify'] is True
    assert update(client,b,'b').status_code==429
    assert client.post('/api/nearby/start',json={'consent':True},headers=headers('b')).status_code==429
    now[0]+=30
    client.post('/api/nearby/stop',json={'lease':b},headers=headers('b'))
    b=start(client,'b')
    assert update(client,b,'b').json()['notify'] is False
    for _ in range(20):
        now[0]+=30;update(client,a);result=update(client,b,'b')
    assert registry.alerts['b']>=1600


def test_old_tab_stop_does_not_delete_new_share_and_logout_removes(service):
    client,registry,now=service;a=start(client)
    now[0]+=11;new=start(client)
    client.post('/api/nearby/stop',json={'lease':a},headers=headers())
    assert registry.entries['a'].lease==new
    registry.logout('a');assert not registry.entries


def test_capacity_is_bounded_and_expired_memory_is_removed(service,monkeypatch):
    client,registry,now=service;monkeypatch.setattr(nearby,'CAPACITY',2)
    start(client);start(client,'b')
    assert client.post('/api/nearby/start',json={'consent':True},headers=headers('c')).status_code==503
    now[0]+=901;registry.purge()
    assert not registry.entries and not registry.starts and not registry.alerts
    assert start(client,'c')


def test_same_owner_never_detects_itself(service):
    client,_,_=service;a=start(client)
    assert update(client,a).json()['nearby'] is False


def test_antimeridian_distance_is_correct():
    assert nearby.distance((0,179.999),(0,-179.999))<300
