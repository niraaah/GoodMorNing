"""Build/start/stop the isolated local search stack. Never print credential contents."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent.parent
COMPOSE=ROOT/'containers/search/compose.json'
NETWORK='goodmorning-sandbox'
SUBNET='172.30.74.0/24'


def docker():
    executable=shutil.which('docker')
    if executable:return executable
    for folder in (Path(os.environ.get('LOCALAPPDATA',''))/'Programs/DockerDesktop',Path(os.environ.get('ProgramFiles',''))/'Docker/Docker'):
        candidate=folder/'resources/bin/docker.exe'
        if candidate.is_file():return str(candidate)
    raise RuntimeError('Docker Desktop is required.')


def run(*args,capture=False):
    result=subprocess.run([docker(),*args],check=True,stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None,text=True)
    return result.stdout.strip() if capture else None


def compose(*args):
    env={**os.environ,'GOODMORNING_ROOT':ROOT.as_posix()}
    subprocess.run([docker(),'compose','-f',str(COMPOSE),*args],check=True,env=env)


def prepare():
    data=ROOT/'data'
    for name in ('postgres-search.key','search-service.key','models/embeddinggemma-2/model.safetensors'):
        if not (data/name).is_file():raise RuntimeError('Search DB keys and model must be prepared first.')
    folder=data/'search-sandbox';folder.mkdir(exist_ok=True)
    key=folder/'crawler-service.key'
    if not key.exists():key.write_text(secrets.token_urlsafe(32),encoding='utf-8')
    source=data/'search.local.json'
    config=json.loads(source.read_text(encoding='utf-8-sig')) if source.is_file() else {}
    selected={key:os.getenv(key) or config.get(key,'') for key in ('COUPANG_ACCESS_KEY','COUPANG_SECRET_KEY','COUPANG_SUB_ID')}
    selected.update({'EMBEDDING_DEVICE':'cpu','official_shops':config.get('official_shops',True) is True})
    (folder/'search.local.json').write_text(json.dumps(selected,ensure_ascii=False),encoding='utf-8')
    (data/'catalog-images').mkdir(exist_ok=True)


def network():
    names=run('network','ls','--format','{{.Name}}',capture=True).splitlines()
    if NETWORK not in names:
        run('network','create','--internal','--subnet',SUBNET,'--label','goodmorning.managed=search-sandbox',NETWORK,capture=True)
    info=json.loads(run('network','inspect',NETWORK,capture=True))[0]
    if not info['Internal'] or info.get('Labels',{}).get('goodmorning.managed')!='search-sandbox' or info['IPAM']['Config'][0]['Subnet']!=SUBNET:
        raise RuntimeError('Existing network does not match the managed isolation network.')
    postgres=json.loads(run('inspect','goodmorning-postgres',capture=True))[0]
    attached=postgres['NetworkSettings']['Networks'].get(NETWORK)
    if attached is None:
        run('network','connect','--ip','172.30.74.10',NETWORK,'goodmorning-postgres')
    elif attached['IPAddress']!='172.30.74.10':
        raise RuntimeError('Database network address mismatch.')


def healthy():
    key=(ROOT/'data/search-service.key').read_text(encoding='utf-8').strip()
    request=urllib.request.Request('http://127.0.0.1:8788/health',headers={'Authorization':'Bearer '+key})
    try:
        with urllib.request.urlopen(request,timeout=3) as response:
            return json.load(response).get('isolated') is True
    except Exception:return False


def deployment_fingerprint():
    digest=hashlib.sha256()
    for name in ('compose.json','chromium-seccomp.json'):
        digest.update((COMPOSE.parent/name).read_bytes())
    for name in ('search','crawler','gateway','network-guard'):
        ident=run('image','inspect','--format','{{.Id}}','goodmorning-'+name+':local',capture=True)
        digest.update(ident.encode())
    return digest.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['build','start','stop'])
    args=parser.parse_args()
    if args.action=='stop':
        compose('stop','--timeout','15')
        return
    prepare()
    if args.action=='build':
        compose('build')
        return
    network()
    fingerprint=deployment_fingerprint()
    marker=ROOT/'data/search-sandbox/runtime-fingerprint'
    if healthy() and marker.is_file() and marker.read_text()==fingerprint:
        print('Isolated search is already running; local search settings synchronized.')
        return
    compose('up','-d','--no-build','--force-recreate')
    for _ in range(45):
        if healthy():
            marker.write_text(fingerprint)
            print('Isolated search API ready on 127.0.0.1:8788; model warmup continues separately.')
            return
        time.sleep(1)
    raise RuntimeError('Isolated search did not become ready; inspect local service status.')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Search isolation action failed ('+type(error).__name__+'). No credential values were printed.')
        raise SystemExit(1)
