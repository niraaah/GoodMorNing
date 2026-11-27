"""Versioned notices, kept readable without signing in."""
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import JSONResponse

VERSION='2026-11-27-v2'
OPERATOR='Team GoodGeeks'
CONTACT='goodgeeks.info@gmail.com'
ROOT=Path(__file__).resolve().parents[1]


def accepted(value):
    if not (value.terms and value.privacy and value.age14 and value.policy_version==VERSION):
        raise HTTPException(422,'현재 약관·개인정보 안내와 만 14세 이상 여부를 확인해 주세요.')


def notice():
    return {'version':VERSION,'operator':OPERATOR,'contact':CONTACT,
            'terms':(ROOT/'docs/TERMS.md').read_text(encoding='utf-8'),
            'privacy':(ROOT/'docs/PRIVACY.md').read_text(encoding='utf-8')}


def register(app):
    @app.get('/auth/legal')
    def legal():
        return JSONResponse(notice(),headers={'Cache-Control':'no-store'})
