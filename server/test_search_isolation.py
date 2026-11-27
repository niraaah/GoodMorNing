"""Boundary tests; no real photos, shopping requests or production DB writes."""
import asyncio
import importlib.util
import json
from pathlib import Path
import socket
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from server.goods import config, crawler_service

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('egress_gateway',ROOT/'containers/search/gateway.py')
gateway=importlib.util.module_from_spec(spec)
spec.loader.exec_module(gateway)


@pytest.mark.parametrize('target',['localhost:443','127.0.0.1:443','169.254.169.254:443',
    'pokemonstore.co.kr.attacker.test:443','attackerpokemonstore.co.kr:443',
    'pokemonstore.co.kr:80','user@pokemonstore.co.kr:443','[::1]:443'])
def test_denied_gateway_destination(target):
    with pytest.raises(ValueError):gateway.authority(target)


def test_allowed_gateway_destination():
    assert gateway.authority('API-GATEWAY.COUPANG.COM:443')=='api-gateway.coupang.com'
    assert gateway.authority('img.pokemonstore.co.kr:443')=='img.pokemonstore.co.kr'


@pytest.mark.parametrize('address',['127.0.0.1','10.1.2.3','172.30.74.10','192.168.1.1',
    '169.254.169.254','100.64.0.1','0.0.0.0','::1','2606:4700:4700::1111'])
def test_private_and_mixed_dns_rejected(address):
    records=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(a,443)) for a in ('1.1.1.1',address)]
    with pytest.raises(ValueError):gateway.public_addresses(records)


def test_upstream_pins_validated_ip():
    async def check():
        loop=asyncio.get_running_loop()
        records=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('1.1.1.1',443))]
        with patch.object(loop,'getaddrinfo',AsyncMock(return_value=records)) as dns, \
             patch.object(loop,'sock_connect',AsyncMock()) as connect, \
             patch.object(gateway.asyncio,'open_connection',AsyncMock(return_value=('r','w'))) as opened:
            assert await gateway.upstream('pokemonstore.co.kr')==('r','w')
            dns.assert_awaited_once()
            assert connect.await_args.args[1]==('1.1.1.1',443)
            assert set(opened.await_args.kwargs)=={'sock'}
            opened.await_args.kwargs['sock'].close()
    asyncio.run(check())


def test_missing_egress_config_fails_closed(monkeypatch):
    monkeypatch.delenv('GOODMORNING_EGRESS_PROXY',raising=False)
    with pytest.raises(RuntimeError):config.egress_proxy()
    monkeypatch.setenv('GOODMORNING_EGRESS_PROXY','http://localhost:8080')
    with pytest.raises(RuntimeError):config.egress_proxy()


def test_crawler_rejects_unauthorized_or_photo_payload(tmp_path,monkeypatch):
    key=tmp_path/'service.key';key.write_text('ephemeral-test-value')
    monkeypatch.setenv('GOODMORNING_CRAWLER_KEY_FILE',str(key))
    client=TestClient(crawler_service.app)
    assert client.get('/health').status_code==401
    headers={'Authorization':'Bearer ephemeral-test-value'}
    assert client.get('/health',headers=headers).json()['isolated'] is True
    for payload in ({'query':'x','photo':'private'},{'query':' '},{'query':'x'*81}):
        assert client.post('/collect',json=payload,headers=headers).status_code==422
    assert client.post('/collect',content=b'x'*4097,headers=headers).status_code==413
    key.write_text('')
    assert client.get('/health').status_code==401


def test_container_file_and_privilege_boundaries():
    compose=json.loads((ROOT/'containers/search/compose.json').read_text())
    services=compose['services']
    for name in ('search','crawler','gateway'):
        service=services[name]
        assert service['user'].split(':')[0]!='0'
        assert service['read_only'] is True and service['cap_drop']==['ALL']
        assert not service.get('cap_add') and not service.get('privileged')
        assert 'no-new-privileges:true' in service['security_opt']
        assert service['network_mode']=='service:guard-'+name
        assert not service.get('ports')
        assert all('docker.sock' not in m['source'] for m in service.get('volumes',[]))
    crawler_mounts=services['crawler']['volumes']
    assert len(crawler_mounts)==1 and crawler_mounts[0]['target']=='/run/secrets/crawler-service.key'
    assert crawler_mounts[0]['read_only'] is True
    search_mounts=services['search']['volumes']
    assert {m['target'] for m in search_mounts}=={
        '/data/models/embeddinggemma-2','/data/postgres-search.key','/data/search-service.key',
        '/data/search.local.json','/run/secrets/crawler-service.key','/data/catalog-images'}
    assert [m['target'] for m in search_mounts if not m['read_only']]==['/data/catalog-images']
    assert not services['gateway'].get('volumes')
    assert services['guard-search']['ports']==['127.0.0.1:8788:8788']
    assert set(services['guard-crawler']['networks'])=={'isolated'}
    assert set(services['guard-search']['networks'])=={'isolated','ingress'}
