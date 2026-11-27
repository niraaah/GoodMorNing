"""Fail closed on private files or known local credentials in Git/build output.
Only paths and rule names are printed, never secret values or matching lines.
Run alongside Gitleaks, which detects credentials not present on this PC.
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, unquote, urlsplit

ROOT = Path(__file__).resolve().parent.parent

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def sensitive_path(path):
    parts=Path(path.replace('\\','/')).parts
    name=parts[-1].lower() if parts else ''
    if parts and parts[0].lower() in ('data','logs','.venv','.venv-search','.aws','.ssh'):
        return True
    if name in ('access-link.txt','pages-link.txt'): return True
    if name.startswith('.env') and name not in ('.env.example','.env.sample'): return True
    return name.endswith(('.key','.pem','.p12','.pfx','.sqlite','.sqlite3','.db','.local.json'))

def known_secrets():
    values=set()
    def add(value):
        if isinstance(value,str) and len(value.strip())>=12: values.add(value.strip())
    for path in (ROOT/'data').rglob('*.key'):
        if path.exists():add(path.read_text(encoding='utf-8').strip())
    keyfile=ROOT/'data/access.key'
    if keyfile.exists():
        key=keyfile.read_text(encoding='utf-8').strip();add(key)
        add(hmac.new(key.encode(),b'goodmorning-browser-session-v1',hashlib.sha256).hexdigest())
    for settings in (ROOT/'data/search.local.json',ROOT/'data/search-sandbox/search.local.json'):
        if not settings.exists():continue
        body=json.loads(settings.read_text(encoding='utf-8-sig'))
        for name in ('COUPANG_ACCESS_KEY','COUPANG_SECRET_KEY','NAVER_CLIENT_ID','NAVER_CLIENT_SECRET','HF_TOKEN'):
            add(body.get(name))
    for name,value in os.environ.items():
        if re.search(r'(?:API_KEY|ACCESS_KEY|SECRET_KEY|SECRET|TOKEN|CLIENT_ID)$',name): add(value)
    auth=ROOT/'data/auth.local.json'
    if auth.exists():
        body=json.loads(auth.read_text(encoding='utf-8-sig'))
        for name in ('GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','KAKAO_CLIENT_ID','KAKAO_CLIENT_SECRET'):
            add(body.get(name))
    for filename in ('access-link.txt','pages-link.txt'):
        path=ROOT/'logs'/filename
        if not path.exists(): continue
        for line in path.read_text(encoding='utf-8').splitlines():
            fragment=urlsplit(line.strip()).fragment
            if '=' in fragment:
                for name,items in parse_qs(fragment).items():
                    if name.lower() in ('key','token','secret'):
                        for item in items:add(item)
            else:add(unquote(fragment))
    raw={value.encode() for value in values}
    # Catch simple accidental encoding as well as literal credentials.
    return raw | {base64.b64encode(value) for value in raw}

def objects(history):
    if not history:
        entries=[]
        for line in git('ls-files','--stage','-z').split(b'\0'):
            if not line:continue
            head,path=line.split(b'\t',1);mode,ident,stage=head.split()
            if mode==b'160000':continue  # Submodules are scanned separately in CI.
            entries.append((ident.decode(),path.decode('utf-8')))
        return entries
    lines=git('rev-list','--objects','--all').decode('utf-8').splitlines()
    names={line.split(' ',1)[0]:line.split(' ',1)[1] if ' ' in line else 'commit metadata' for line in lines}
    raw=subprocess.check_output(['git','cat-file','--batch-check=%(objectname) %(objecttype)'],
        input=('\n'.join(names)+'\n').encode(),cwd=ROOT).decode().splitlines()
    return [(ident,names[ident]) for ident,kind in (line.split() for line in raw) if kind in ('blob','commit')]

def scan(history=False,artifact=None):
    secrets=known_secrets();findings=set();count=0
    def check(path,content):
        nonlocal count
        count+=1
        if sensitive_path(path):findings.add((path,'private file must not be tracked/published'))
        if any(value in content for value in secrets):findings.add((path,'known local credential detected [REDACTED]'))
    if artifact:
        folder=Path(artifact).resolve()
        if not folder.is_dir():raise RuntimeError('Artifact directory not found.')
        for file in folder.rglob('*'):
            if file.is_file():check(file.relative_to(folder).as_posix(),file.read_bytes())
    else:
        process=subprocess.Popen(['git','cat-file','--batch'],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE)
        try:
            for ident,path in objects(history):
                process.stdin.write((ident+'\n').encode());process.stdin.flush()
                header=process.stdout.readline().split()
                if len(header)!=3:raise RuntimeError('Could not read Git object.')
                content=process.stdout.read(int(header[2]));process.stdout.read(1)
                check(path,content)
        finally:
            process.stdin.close();process.wait()
    for path,reason in sorted(findings):print(f'BLOCKED: {path}: {reason}')
    print(f'Checked {count} objects/files; {len(findings)} findings. Secret values were not printed.')
    return 1 if findings else 0

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--history',action='store_true')
    parser.add_argument('--artifact')
    args=parser.parse_args()
    try:raise SystemExit(scan(args.history,args.artifact))
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError):
        print('Secret check could not complete. Commit/deployment remains blocked; inspect local configuration without printing credentials.')
        raise SystemExit(2)
