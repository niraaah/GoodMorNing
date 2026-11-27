"""Account bindings and a transactional, rebuildable projection of diary JSON.

Stable slots preserve current photo indexes and permit repeated sticker assets.
The JSON remains canonical until a future API transition; no legacy data is deleted.
"""
import hashlib
import json
import math
from uuid import NAMESPACE_URL, uuid5

from .db import Jsonb

VERSION = '20261127_account_diary_structure_v1'


def ident(kind, value):
    return uuid5(NAMESPACE_URL, f'goodmorning:{kind}:{value}')


def document(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(body):
    return hashlib.sha256(document(body).encode()).hexdigest()


def ensure_user(con, owner):
    existing = con.execute('SELECT user_id FROM app_owner_bindings WHERE owner=%s', (owner,)).fetchone()
    if existing:
        return existing['user_id']
    user = ident('user', owner)
    kind = 'local' if owner == 'private' else 'guest' if owner.startswith('guest-') else 'legacy'
    con.execute('INSERT INTO app_users(id,kind) VALUES(%s,%s) ON CONFLICT DO NOTHING', (user, kind))
    con.execute('INSERT INTO app_owner_bindings(owner,user_id) VALUES(%s,%s) ON CONFLICT DO NOTHING', (owner, user))
    return con.execute('SELECT user_id FROM app_owner_bindings WHERE owner=%s', (owner,)).fetchone()['user_id']


def finite(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def placements(body):
    photos = body.get('diaryLayout', [])
    items = body.get('items', [])
    photos = photos if isinstance(photos, list) else []
    items = items if isinstance(items, list) else []
    def order(index):
        photo = photos[index]
        rank = finite(photo.get('layerOrder')) if isinstance(photo, dict) else None
        return (index if rank is None else rank, index)
    ranks = {slot: rank for rank, slot in enumerate(sorted(range(len(photos)), key=order))}
    for kind, values in [('photo', photos), ('sticker', items)]:
        for slot, value in enumerate(values):
            data = value if isinstance(value, dict) else {}
            yield kind, slot, ranks[slot] if kind == 'photo' else slot, data, value


def sync_page(con, owner, key, body, updated):
    user = ensure_user(con, owner)
    notebook = ident('notebook', f'{user}:default')
    con.execute('INSERT INTO user_notebooks(id,user_id) VALUES(%s,%s) ON CONFLICT DO NOTHING', (notebook, user))
    page = ident('page', f'{owner}:{key}')
    paper = body.get('paperStyle', {})
    con.execute('''INSERT INTO diary_pages(id,notebook_id,legacy_owner,page_key,paper_style,source_hash,updated_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(legacy_owner,page_key) DO UPDATE SET
        notebook_id=excluded.notebook_id,paper_style=excluded.paper_style,
        source_hash=excluded.source_hash,updated_at=excluded.updated_at''',
        (page, notebook, owner, key, Jsonb(paper if isinstance(paper, dict) else {}), fingerprint(body), updated))
    keep = []
    for kind, slot, rank, data, original in placements(body):
        item_id = ident('placement', f'{page}:{kind}:{slot}')
        keep.append(item_id)
        file = data.get('file') if isinstance(data.get('file'), dict) else {}
        asset = file.get('__gmAsset') or data.get('backendAssetId') or (data.get('sourceId') if kind == 'sticker' else None)
        asset = asset if isinstance(asset, str) and con.execute('SELECT 1 FROM assets WHERE id=%s', (asset,)).fetchone() else None
        attachment = file.get('__gmFile')
        attachment = attachment if isinstance(attachment, str) and con.execute(
            'SELECT 1 FROM notebook_files WHERE id=%s AND owner=%s', (attachment, owner)).fetchone() else None
        con.execute('''INSERT INTO diary_page_items(id,page_id,kind,slot,stack_order,asset_id,file_id,
            x_percent,y_percent,size_percent,rotation,caption,removed,properties)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(id) DO UPDATE SET stack_order=excluded.stack_order,asset_id=excluded.asset_id,
            file_id=excluded.file_id,x_percent=excluded.x_percent,y_percent=excluded.y_percent,
            size_percent=excluded.size_percent,rotation=excluded.rotation,caption=excluded.caption,
            removed=excluded.removed,properties=excluded.properties''',
            (item_id, page, kind, slot, rank, asset, attachment,
             finite(data.get('x')), finite(data.get('y')), finite(data.get('size')), finite(data.get('rotation')),
             data.get('caption') if isinstance(data.get('caption'), str) else None,
             bool(data.get('removed')), Jsonb(original)))
    con.execute('DELETE FROM diary_page_items WHERE page_id=%s AND NOT(id=ANY(%s::uuid[]))', (page, keep))
    return page


def store_page(con, owner, key, body, updated):
    # Serialize the canonical JSON and projection together, including concurrent saves.
    con.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (f'notebook:{owner}:{key}',))
    con.execute('''INSERT INTO notebook_pages VALUES(%s,%s,%s,%s)
        ON CONFLICT(owner,page_key) DO UPDATE SET body=excluded.body,updated=excluded.updated''',
        (owner, key, Jsonb(body, dumps=document), updated))
    sync_page(con, owner, key, body, updated)


def backfill(con):
    owners = con.execute('''SELECT owner FROM ownership UNION SELECT owner FROM notebook_pages
        UNION SELECT owner FROM notebook_files UNION SELECT owner FROM asset_trash
        UNION SELECT owner FROM goods_searches UNION SELECT 'private' AS owner''').fetchall()
    for row in owners:
        ensure_user(con, row['owner'])
    pages = con.execute('SELECT owner,page_key,body,updated FROM notebook_pages ORDER BY owner,page_key').fetchall()
    for row in pages:
        sync_page(con, row['owner'], row['page_key'], row['body'], row['updated'])
    con.execute('INSERT INTO schema_migrations(version,applied_at) VALUES(%s,now()) ON CONFLICT DO NOTHING', (VERSION,))
    return {'owners': len(owners), 'pages': len(pages)}
