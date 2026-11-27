"""Persist the original prototype's pages and binary attachments per owner."""
import hashlib
import io
import json
import re
import struct
from fastapi import Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from .diary_store import ensure_user, store_page

def initialize(con, data):
    # Tables are created from server/schema.sql.
    (data / 'notebook-files').mkdir(exist_ok=True)


def register(app, data, connection, accessible, normalized_image, now):
    def valid_key(key):
        if not re.fullmatch(r'(story:chiikawa|page:[1-9][0-9]{0,3})', key):
            raise HTTPException(422, '다이어리 페이지 주소를 확인해 주세요.')

    @app.get('/api/notebook/pages')
    def pages(request: Request):
        with connection() as con:
            return [row['page_key'] for row in con.execute(
                'SELECT page_key FROM notebook_pages WHERE owner=%s', (request.state.owner,))]

    @app.get('/api/notebook/pages/{key}')
    def read_page(key: str, request: Request):
        valid_key(key)
        with connection() as con:
            row = con.execute('SELECT body FROM notebook_pages WHERE owner=%s AND page_key=%s',
                              (request.state.owner, key)).fetchone()
        return row['body'] if row else None

    @app.put('/api/notebook/pages/{key}')
    async def save_page(key: str, request: Request):
        valid_key(key)
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 512 * 1024:
                raise HTTPException(413, '페이지 내용이 너무 커요. 사진은 별도 첨부로 저장해 주세요.')
        try:
            body = json.loads(chunks)
        except (ValueError, UnicodeDecodeError):
            raise HTTPException(422, '페이지 형식을 확인해 주세요.')
        if not isinstance(body, dict) or not isinstance(body.get('items'), list) or len(body['items']) > 60:
            raise HTTPException(422, '페이지에는 에셋을 60개까지 저장할 수 있어요.')
        if not isinstance(body.get('diaryLayout'), list) or len(body['diaryLayout']) > 100:
            raise HTTPException(422, '사진 배치를 확인해 주세요.')
        with connection() as con:
            def validate(value, depth=0):
                if depth > 20:
                    raise HTTPException(422, '페이지 구조가 너무 복잡해요.')
                if isinstance(value, dict):
                    if '__gmFile' in value:
                        row = con.execute('SELECT id FROM notebook_files WHERE id=%s AND owner=%s',
                                          (str(value['__gmFile']), request.state.owner)).fetchone()
                        if not row:
                            raise HTTPException(404, '첨부 사진을 찾지 못했어요.')
                    if '__gmAsset' in value:
                        ident = str(value['__gmAsset'])
                        row = con.execute('SELECT id FROM assets WHERE id=%s', (ident,)).fetchone()
                        if not row or not accessible(con, 'asset', ident, request.state.owner):
                            raise HTTPException(404, '스티커를 찾지 못했어요.')
                        if value.get('part') not in ('model', 'thumbnail'):
                            raise HTTPException(422, '에셋 파일 종류를 확인해 주세요.')
                    for child in value.values():
                        validate(child, depth + 1)
                elif isinstance(value, list):
                    for child in value:
                        validate(child, depth + 1)
            validate(body)
            store_page(con, request.state.owner, key, body, now())
        return {'saved': True}

    @app.post('/api/notebook/files', status_code=201)
    async def upload_file(request: Request, attachment: UploadFile = File()):
        content = await attachment.read(16 * 1024 * 1024 + 1)
        await attachment.close()
        if len(content) > 16 * 1024 * 1024:
            raise HTTPException(413, '사진 또는 GLB 파일은 16MB 이하로 올려 주세요.')
        if content.startswith(b'glTF'):
            if len(content) < 20 or struct.unpack_from('<II', content, 4) != (2, len(content)):
                raise HTTPException(422, '올바른 GLB 파일이 아니에요.')
            mime, name = 'model/gltf-binary', 'sticker.glb'
        else:
            try:
                image = normalized_image(content)
                output = io.BytesIO()
                image.save(output, format='PNG')
                content = output.getvalue()
            except ValueError as error:
                raise HTTPException(422, str(error))
            mime, name = 'image/png', 'photo.png'
        ident = hashlib.sha256(request.state.owner.encode() + b'\0' + content).hexdigest()
        (data / 'notebook-files' / ident).write_bytes(content)
        with connection() as con:
            ensure_user(con, request.state.owner)
            con.execute('INSERT INTO notebook_files VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                        (ident, request.state.owner, name, mime))
        return {'__gmFile': ident, 'name': name, 'type': mime}

    @app.get('/api/notebook/files/{ident}')
    def get_file(ident: str, request: Request):
        if not re.fullmatch(r'[a-f0-9]{64}', ident):
            raise HTTPException(404)
        with connection() as con:
            row = con.execute('SELECT * FROM notebook_files WHERE id=%s AND owner=%s',
                              (ident, request.state.owner)).fetchone()
        if not row:
            raise HTTPException(404)
        return FileResponse(data / 'notebook-files' / ident, media_type=row['mime'])
