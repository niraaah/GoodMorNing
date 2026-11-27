"""Synthetic profiles and erasure in disposable DBs; no live accounts/provider calls."""
import base64
import hashlib
import io
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import FastAPI, Request, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from server import accounts, account_policy, db, social_auth as auth, access
from server.diary_store import store_page
from server.test_diary_store import con
from server.test_db_security import secured

CONSENT=dict(terms=True,privacy=True,age14=True,policy_version=account_policy.VERSION)


@pytest.fixture(autouse=True)
def isolated_files(tmp_path,monkeypatch):
    monkeypatch.setenv('GOODMORNING_ADMIN_DATABASE_URL', db.admin_url())
    monkeypatch.setattr(db,'data_dir',lambda:tmp_path)
    accounts._provider_tokens.clear()
    yield tmp_path
    accounts._provider_tokens.clear()


@pytest.fixture
def client(secured,monkeypatch):
    admin,urls=secured
    monkeypatch.setenv('GOODMORNING_API_DATABASE_URL',urls['api'])
    db.close();db.initialize()
    monkeypatch.setattr(accounts,'revoke_provider',lambda session:False)
    app=FastAPI();app.state.access_key='synthetic-only'
    @app.middleware('http')
    async def identity(request:Request,call_next):
        request.state.owner,request.state.member=auth.identify(request,app.state.access_key,True)
        if not request.state.owner:
            return accounts.response({'detail':'unauthorized'},401)
        async with accounts.owner_lock(request.state.owner):
            with db.owner_scope(request.state.owner):return await call_next(request)
    accounts.register(app);auth.register(app);account_policy.register(app)
    with TestClient(app) as http:
        yield http,admin


def member(admin,subject='one',ready=True,owner=None):
    token,_=auth.complete_identity(admin,'google',subject,'ignored social name',owner)
    row=auth.member_session(admin,token)
    if ready:
        admin.execute('UPDATE account_profiles SET display_name=%s,profile_ready=true,terms_version=%s,privacy_version=%s WHERE user_id=%s',
                      ('수집가'+subject,account_policy.VERSION,account_policy.VERSION,row['user_id']))
    admin.commit()
    return token,dict(row)


def headers(token):return {'Authorization':'Bearer '+token}


def test_profile_requires_versioned_consent_and_keeps_chosen_name(client):
    http,admin=client;token,row=member(admin,ready=False)
    assert http.get('/auth/me',headers=headers(token)).json()['profile_ready'] is False
    for invalid in ({},{**CONSENT,'age14':False},{**CONSENT,'policy_version':'old'},{**CONSENT,'terms':'true'}):
        assert http.post('/auth/profile',headers=headers(token),json={'nickname':'내 닉네임',**invalid}).status_code==422
    response=http.post('/auth/profile',headers=headers(token),json={'nickname':'내 닉네임',**CONSENT})
    assert response.status_code==200
    other,_=auth.complete_identity(admin,'google','one','provider overwrite',None);admin.commit()
    me=http.get('/auth/me',headers=headers(other)).json()
    assert me['profile_ready'] and me['name']=='내 닉네임' and not me['has_avatar']
    assert http.post('/auth/profile',headers=headers(other),json={'nickname':'바꾼 별명'}).status_code==200


def test_avatar_is_private_reencoded_and_removable(client):
    http,admin=client;token,row=member(admin);second,_=member(admin,'two')
    image=Image.new('RGB',(40,60),'blue');exif=Image.Exif();exif[270]='private metadata'
    output=io.BytesIO();image.save(output,'JPEG',exif=exif)
    value={'nickname':'사진 수집가','photo':base64.b64encode(output.getvalue()).decode()}
    assert http.post('/auth/profile',headers=headers(token),json=value).status_code==200
    response=http.get('/auth/avatar',headers=headers(token))
    assert response.status_code==200 and response.headers['cache-control']=='no-store'
    with Image.open(io.BytesIO(response.content)) as normalized:
        assert normalized.size==(256,256) and not normalized.getexif()
    assert http.get('/auth/avatar',headers=headers(second)).status_code==404
    assert http.get('/auth/avatar').status_code==401
    assert http.post('/auth/profile',headers=headers(token),json={'nickname':'사진 수집가','remove_photo':True}).status_code==200
    assert http.get('/auth/avatar',headers=headers(token)).status_code==404


@pytest.mark.parametrize('name',['a','<script>alert</script>','😀😀','   ','x'*21])
def test_bad_nickname_rejected(name):
    with pytest.raises(HTTPException):accounts.nickname(name)


@pytest.mark.parametrize('raw',[b'<svg/>',b'not an image',b'GIF89a'])
def test_non_image_rejected(raw):
    with pytest.raises(HTTPException):accounts.avatar(base64.b64encode(raw).decode())


def test_oversized_and_extra_profile_input_rejected(client):
    http,admin=client;token,_=member(admin)
    assert http.post('/auth/profile',headers=headers(token),json={'nickname':'좋은 이름','owner':'private'}).status_code==422
    assert http.post('/auth/profile',headers=headers(token),content=b' '*(2_900_001)).status_code==413


def populate(admin,row,root):
    owner=row['owner'];asset=uuid4().hex;failed=uuid4().hex;file=hashlib.sha256(owner.encode()).hexdigest()
    for ident,kind in ((asset,'asset'),(failed,'job')):
        admin.execute('INSERT INTO ownership VALUES(%s,%s,%s)',(kind,ident,owner))
        path=root/'assets'/ident;path.mkdir(parents=True);(path/'source.png').write_bytes(b'synthetic')
    admin.execute("INSERT INTO assets VALUES(%s,'test','sticker','synthetic',now(),'{}')",(asset,))
    admin.execute("INSERT INTO jobs VALUES(%s,'failed','failed',0,'',NULL,now())",(failed,))
    admin.execute("INSERT INTO notebook_files VALUES(%s,%s,'test.png','image/png')",(file,owner))
    directory=root/'notebook-files';directory.mkdir(exist_ok=True);(directory/file).write_bytes(b'synthetic')
    store_page(admin,owner,'page:1',{'items':[{'id':asset}], 'diaryLayout':[]},datetime.now(timezone.utc))
    admin.execute('INSERT INTO asset_trash VALUES(%s,%s,now())',(owner,asset))
    admin.execute("INSERT INTO goods_searches VALUES(%s,%s,'completed','{}',now())",(uuid4().hex,owner))
    admin.commit()
    return asset,failed,file


def test_withdraw_deletes_owned_content_all_sessions_and_old_guest_only(client,isolated_files):
    http,admin=client
    guest=access.guest_token('synthetic-only')
    request=Request({'type':'http','headers':[(b'authorization',('Bearer '+guest).encode())]})
    owner=access.guest_owner(request,'synthetic-only')
    token,row=member(admin,owner=owner);old,_=auth.complete_identity(admin,'google','one','ignored',None);admin.commit()
    other,otherrow=member(admin,'two')
    removed=populate(admin,row,isolated_files);kept=populate(admin,otherrow,isolated_files)
    data={'confirmation':'수집가one','acknowledged':True}
    assert http.post('/auth/delete',headers=headers(token),json={**data,'confirmation':'wrong'}).status_code==422
    result=http.post('/auth/delete',headers=headers(token),json=data)
    assert result.status_code==200 and result.json()['deleted']
    assert http.get('/auth/me',headers=headers(token)).status_code==401
    assert http.get('/auth/me',headers=headers(old)).status_code==401
    assert http.get('/auth/me',headers=headers(guest)).status_code==401
    assert http.get('/auth/me',headers=headers(other)).status_code==200
    for table in ('account_profiles','auth_identities','app_users','app_owner_bindings','notebook_pages','assets','jobs','notebook_files','goods_searches'):
        assert admin.execute(f'SELECT count(*) AS n FROM {table}').fetchone()['n']==1
    assert not (isolated_files/'assets'/removed[0]).exists()
    assert not (isolated_files/'assets'/removed[1]).exists()
    assert not (isolated_files/'notebook-files'/removed[2]).exists()
    assert (isolated_files/'assets'/kept[0]).exists()
    record=(accounts.ledger_root()/(str(row['user_id'])+'.json')).read_text()
    assert '수집가' not in record and 'google' not in record and owner not in record


def test_old_session_and_busy_job_prevent_erasure(client):
    http,admin=client;token,row=member(admin)
    body={'confirmation':'수집가one','acknowledged':True}
    admin.execute("UPDATE account_sessions SET created_at=now()-interval '11 minutes'");admin.commit()
    assert http.post('/auth/delete',headers=headers(token),json=body).status_code==409
    admin.execute('UPDATE account_sessions SET created_at=now()')
    ident=uuid4().hex;admin.execute("INSERT INTO ownership VALUES('job',%s,%s)",(ident,row['owner']))
    admin.execute("INSERT INTO jobs VALUES(%s,'test','running',0,'',NULL,now())",(ident,));admin.commit()
    assert http.post('/auth/delete',headers=headers(token),json=body).status_code==409
    assert not list(accounts.ledger_root().glob('*.json'))


def test_erasure_failure_blocks_login_and_retries(client,monkeypatch,isolated_files):
    http,admin=client;token,row=member(admin);populate(admin,row,isolated_files)
    original=accounts.remove_owned_file
    def fail(*args):raise OSError('synthetic file failure')
    monkeypatch.setattr(accounts,'remove_owned_file',fail)
    result=http.post('/auth/delete',headers=headers(token),json={'confirmation':'수집가one','acknowledged':True})
    assert result.status_code==202 and result.json()['pending']
    assert http.get('/auth/me',headers=headers(token)).status_code==401
    with pytest.raises(HTTPException):auth.complete_identity(admin,'google','one','ignored',None)
    admin.rollback()
    monkeypatch.setattr(accounts,'remove_owned_file',original)
    accounts.maintenance()
    assert admin.execute('SELECT count(*) AS n FROM account_profiles').fetchone()['n']==0


def test_ledger_blocks_restored_profile_and_does_not_expire_ordinary_members(client,isolated_files):
    http,admin=client;token,row=member(admin,ready=False)
    admin.execute("UPDATE account_profiles SET created_at=now()-interval '40 days'");admin.commit()
    accounts.maintenance()
    assert http.get('/auth/me',headers=headers(token)).status_code==200
    accounts.record_erasure(row['user_id'],row['owner'])
    # This is also the state after restoring a pre-withdrawal database backup.
    assert http.get('/auth/me',headers=headers(token)).status_code==401
    accounts.initialize()
    assert admin.execute('SELECT count(*) AS n FROM account_profiles').fetchone()['n']==0


def test_expired_managed_backups_only_are_removed(client,isolated_files):
    folder=isolated_files/'backups';folder.mkdir()
    old=folder/'old.dump';old.write_bytes(b'synthetic');os.utime(old,(time.time()-8*86400,)*2)
    recent=folder/'recent.dump';recent.write_bytes(b'synthetic')
    outside=isolated_files/'legacy.sqlite3';outside.write_bytes(b'synthetic');os.utime(outside,(time.time()-8*86400,)*2)
    accounts.maintenance()
    assert not old.exists() and recent.exists() and outside.exists()


def test_file_identifiers_cannot_escape_owned_buckets(isolated_files):
    with pytest.raises(RuntimeError):accounts.remove_owned_file('assets','../secret',True)
    with pytest.raises(RuntimeError):accounts.erase_member(uuid4(),'private')


def test_guest_tokens_expire_without_changing_owner(monkeypatch):
    start=1800000000;monkeypatch.setattr(access.time,'time',lambda:start)
    token=access.guest_token('synthetic-only')
    request=Request({'type':'http','headers':[(b'authorization',('Bearer '+token).encode())]})
    assert access.guest_owner(request,'synthetic-only').startswith('guest-')
    monkeypatch.setattr(access.time,'time',lambda:start+30*86400)
    assert access.guest_owner(request,'synthetic-only') is None
