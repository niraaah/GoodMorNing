"""Local containment checks only: no user photo, product collection or DB mutation."""
import json
import subprocess
import sys
from search_sandbox import docker, healthy


def probe(name, code):
    result=subprocess.run([docker(),'exec','-i','goodmorning-'+name,'python','-'],
        input=code,text=True,capture_output=True,timeout=55)
    # Suppress raw exception/headers/environment output, which could contain keys.
    if result.returncode:
        raise RuntimeError(name+' containment probe failed; inspect locally without credentials.')
    print(name+': containment checks passed')


FILES='''
import os, socket
from pathlib import Path
assert os.getuid()!=0
status=Path('/proc/self/status').read_text()
assert int(next(x.split()[1] for x in status.splitlines() if x.startswith('CapEff:')),16)==0
assert 'NoNewPrivs:\\t1' in status
for path in ('/data/access.key','/data/postgres.key','/data/postgres-api.key','/data/auth.local.json','/var/run/docker.sock'):
    assert not Path(path).exists()
try:Path('/app/forbidden-write').write_text('probe')
except OSError:pass
else:raise AssertionError('Writable root')
def blocked(host,port):
    try:
        with socket.create_connection((host,port),timeout=1):pass
    except OSError:return
    raise AssertionError('Unexpected network access')
for host,port in (('172.30.74.1',8787),('172.30.74.1',55432),('1.1.1.1',443),('169.254.169.254',80)):
    blocked(host,port)
'''


def main():
    if not healthy():raise RuntimeError('Isolated search is not ready.')
    for name in ('search','crawler','gateway'):
        info=json.loads(subprocess.check_output([docker(),'inspect','goodmorning-'+name],text=True))[0]
        assert info['HostConfig']['ReadonlyRootfs'] is True
        assert info['HostConfig']['CapDrop']==['ALL'] and not info['HostConfig']['CapAdd']
        assert not info['HostConfig']['Privileged']
        assert all(m['Destination']!='/var/run/docker.sock' for m in info['Mounts'])
    probe('crawler',FILES+'''
blocked('172.30.74.10',5432)
assert not Path('/data/postgres-search.key').exists()
import httpx
for destination in ('https://localhost/','https://example.com/','https://169.254.169.254/'):
    try:httpx.get(destination,proxy='http://172.30.74.2:8080',trust_env=False,timeout=3)
    except httpx.ProxyError:pass
    else:raise AssertionError('Gateway accepted forbidden destination')
''')
    probe('search',FILES+'''
import httpx
with socket.create_connection(('172.30.74.10',5432),timeout=3):pass
key=Path('/run/secrets/crawler-service.key').read_text().strip()
response=httpx.get('http://172.30.74.4:8790/health',headers={'Authorization':'Bearer '+key},trust_env=False)
assert response.status_code==200 and response.json()['isolated'] is True
assert httpx.get('http://172.30.74.4:8790/health',trust_env=False).status_code==401
from server import db
db.select_service('search')
db.initialize()
''')
    probe('crawler','''
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,chromium_sandbox=True,
        proxy={'server':'http://172.30.74.2:8080'})
    page=browser.new_page()
    page.goto('about:blank')
    assert page.url=='about:blank'
    browser.close()
''')
    print('All local isolation checks passed. No photo inference or real shopping crawl was performed.')


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Containment verification failed: '+type(error).__name__+'. No private values were printed.')
        sys.exit(1)
