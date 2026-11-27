"""Opt-in, ephemeral radar. Only aggregate distance bands/directions leave this API.

Single API process only. Never persist presence to DB/logs or share it with AI.
"""
import asyncio
from dataclasses import dataclass
import math
import secrets
import threading
import time
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

TTL=90
DURATION=15*60
COOLDOWN=10*60
CAPACITY=2048


@dataclass
class Presence:
    session: str
    lease: str
    deadline: float
    seen: float
    position: tuple | None = None
    accuracy: float = 250
    last_update: float = -math.inf


def distance(a,b):
    lat1,lat2=map(math.radians,(a[0],b[0]))
    dlat=lat2-lat1;dlon=math.radians(b[1]-a[1])
    h=math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(h)))


def sector(a,b):
    """Clockwise eight-way compass: 0=N, 2=E, 4=S, 6=W. North is fixed."""
    lat1,lat2=map(math.radians,(a[0],b[0]))
    delta=math.radians(b[1]-a[1])
    bearing=math.degrees(math.atan2(math.sin(delta)*math.cos(lat2),
        math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(delta)))%360
    return int((bearing+22.5)//45)%8


def radar(position,accuracy,others):
    bins={}
    for other in others:
        if other.position is None:continue
        meters=distance(position,other.position)
        if meters>1000:continue
        band=0 if meters<=300 else 1 if meters<=600 else 2
        # Both fixes have measurement error; rounding adds further uncertainty.
        # Do not fabricate a bearing at close/coincident or low-confidence positions.
        direction=None if meters<=max(150,math.hypot(accuracy,other.accuracy)+140) else sector(position,other.position)
        key=(band,direction)
        bins[key]=bins.get(key,0)+1
    return [{'band':band,'direction':direction,'count':count}
            for (band,direction),count in sorted(bins.items(),key=lambda item:(item[0][0],-1 if item[0][1] is None else item[0][1]))]


class Registry:
    def __init__(self,clock=time.monotonic):
        self.clock=clock
        self.lock=threading.RLock()
        self.entries={}
        self.alerts={}
        self.starts={}

    def purge(self):
        with self.lock:
            now=self.clock()
            self.entries={k:v for k,v in self.entries.items() if now<v.deadline and now-v.seen<TTL}
            self.alerts={k:v for k,v in self.alerts.items() if now-v<COOLDOWN}
            self.starts={k:v for k,v in self.starts.items() if now-v<DURATION}

    def start(self,owner,session):
        with self.lock:
            self.purge();now=self.clock()
            if now-self.starts.get(owner,-math.inf)<10:
                raise HTTPException(429,'잠시 후 다시 켜 주세요.')
            if owner not in self.starts and len(self.starts)>=CAPACITY:
                raise HTTPException(503,'근처 알림이 잠시 붐비고 있어요. 나중에 다시 켜 주세요.')
            self.starts[owner]=now
            entry=Presence(session,secrets.token_urlsafe(24),now+DURATION,now)
            self.entries[owner]=entry
            return {'lease':entry.lease,'duration_seconds':DURATION,'ttl_seconds':TTL}

    def update(self,owner,session,body):
        with self.lock:
            self.purge();now=self.clock()
            entry=self.entries.get(owner)
            if not entry or entry.session!=session or not secrets.compare_digest(entry.lease,body.lease):
                raise HTTPException(409,'위치 공유가 끝났어요. 다시 켜 주세요.')
            if now-entry.last_update<20:
                raise HTTPException(429,'위치는 30초마다 확인해 주세요.')
            entry.position=(round(body.latitude,3),round(body.longitude,3))
            entry.accuracy=body.accuracy
            entry.seen=now;entry.last_update=now
            clusters=radar(entry.position,entry.accuracy,(value for other,value in self.entries.items() if other!=owner))
            nearby=bool(clusters)
            notify=nearby and now-self.alerts.get(owner,-math.inf)>=COOLDOWN
            if notify:self.alerts[owner]=now
            return {'nearby':nearby,'notify':notify,'remaining_seconds':max(0,int(entry.deadline-now)),
                    'clusters':clusters,'count':sum(group['count'] for group in clusters)}

    def stop(self,owner,session,lease):
        with self.lock:
            entry=self.entries.get(owner)
            if entry and entry.session==session and secrets.compare_digest(entry.lease,lease):
                del self.entries[owner]

    def logout(self,session):
        with self.lock:
            self.entries={k:v for k,v in self.entries.items() if v.session!=session}

    def logout_owner(self,owner):
        with self.lock:
            self.entries.pop(owner,None);self.alerts.pop(owner,None);self.starts.pop(owner,None)

    def clear(self):
        with self.lock:
            self.entries.clear();self.alerts.clear();self.starts.clear()


registry=Registry()


async def cleanup_loop():
    while True:
        await asyncio.sleep(15)
        registry.purge()


class Consent(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    consent:bool
    radar:bool=False


class Lease(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True,allow_inf_nan=False)
    lease:str=Field(pattern=r'^[A-Za-z0-9_-]{32}$')


class Location(Lease):
    latitude:float=Field(ge=-90,le=90)
    longitude:float=Field(ge=-180,le=180)
    accuracy:float=Field(ge=0,le=250)


def member(request):
    value=getattr(request.state,'member',None)
    if not value:
        raise HTTPException(403,'근처 알림은 구글·카카오 로그인 후 켤 수 있어요.')
    return value['owner'],value['token_hash']


async def body(request,model):
    content=bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content)>1024:raise HTTPException(413,'요청 크기를 확인해 주세요.')
    try:return model.model_validate_json(content)
    except ValidationError:
        # Never echo Pydantic input values (location) in validation responses.
        raise HTTPException(422,'위치를 확인하지 못했어요. 위치 정확도와 권한을 확인해 주세요.') from None


def response(value):
    return JSONResponse(value,headers={'Cache-Control':'no-store','Pragma':'no-cache'})


def attach(app):
    @app.post('/api/nearby/start')
    async def start(request:Request):
        owner,session=member(request)
        value=await body(request,Consent)
        if not value.consent:raise HTTPException(400,'위치 공유 동의가 필요해요.')
        if not value.radar:raise HTTPException(409,'화면을 새로고침하고 거리·방향 공유 안내를 확인해 주세요.')
        return response(registry.start(owner,session))

    @app.post('/api/nearby/update')
    async def update(request:Request):
        owner,session=member(request)
        value=await body(request,Location)
        return response(registry.update(owner,session,value))

    @app.post('/api/nearby/stop')
    async def stop(request:Request):
        owner,session=member(request)
        value=await body(request,Lease)
        registry.stop(owner,session,value.lease)
        return response({'stopped':True})
