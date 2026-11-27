"""Persistent public product candidates; private photos never enter this catalog."""
from datetime import datetime, timezone
import hashlib
import time
import unicodedata
import uuid
from urllib.parse import urlsplit
import numpy as np
from ..db import Jsonb, connection, initialize as initialize_database
from .config import DATA, product_url

VERSION = '20261126_goods_catalog_v1'
POSTGRES_VERSION = '20261127_postgresql_v1'


def utc_now():
    return datetime.now(timezone.utc)


def initialize():
    DATA.mkdir(parents=True, exist_ok=True)
    initialize_database()


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', str(value)).casefold().split())


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def query_key(query):
    return digest(normalized(query))


def cached_sources(query, config_hash):
    with connection() as con:
        row = con.execute('SELECT * FROM catalog_query_cache WHERE query_hash=%s AND config_hash=%s',
                          (query_key(query), config_hash)).fetchone()
    return row['sources'] if row and (utc_now() - row['checked_at']).total_seconds() < 900 else None


def record_collection(query, config_hash, products, sources, started_at):
    """Persist only public listing fields, never request headers/config/user images."""
    observed = utc_now()
    started_at = datetime.fromtimestamp(started_at, timezone.utc)
    key = query_key(query)
    by_source = {}
    for product in products:
        by_source.setdefault(product['source'], []).append(product)
    with connection() as con:
        for state in sources:
            source = state['source']
            job = uuid.uuid4().hex
            rows = by_source.pop(source, [])
            con.execute('INSERT INTO catalog_collect_jobs VALUES(%s,%s,%s,%s,%s,%s,%s)',
                        (job, source, key, state['state'], len(rows), started_at, observed))
            for product in rows:
                url = product_url(product['url'])
                parts = urlsplit(url)
                origin = f'https://{parts.hostname}'
                mall = digest(source + '|' + origin)
                method = 'api' if source == '쿠팡' else 'crawl'
                con.execute('INSERT INTO catalog_malls VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                            (mall, source, origin, method, observed))
                external = str(product.get('id') or url)
                ident = 'offer-' + digest(mall + '|' + external)[:32]
                price = product.get('price')
                price = price if type(price) is int and price >= 0 else None
                previous = con.execute('SELECT price,shipping_fee,availability FROM catalog_offers WHERE id=%s', (ident,)).fetchone()
                title = str(product['title'])[:300]
                con.execute('''INSERT INTO catalog_offers
                    (id,mall_id,external_id,title,title_search,url,image_url,price,affiliate,observed_at,created_at)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,title_search=excluded.title_search,url=excluded.url,
                    image_url=excluded.image_url,price=excluded.price,affiliate=excluded.affiliate,
                    observed_at=excluded.observed_at''',
                    (ident,mall,external,title,normalized(title),url,product.get('image_url'),price,
                     bool(product.get('affiliate')),observed,observed))
                if previous is None or previous['price'] != price:
                    con.execute('INSERT INTO catalog_offer_history(offer_id,price,shipping_fee,availability,observed_at) VALUES(%s,%s,%s,%s,%s)',
                                (ident,price,previous['shipping_fee'] if previous else None,
                                 previous['availability'] if previous else 'unknown',observed))
                payload = {k: product.get(k) for k in ('id','title','source','url','image_url','price','affiliate')}
                con.execute('INSERT INTO catalog_raw_listings(job_id,offer_id,payload,collected_at) VALUES(%s,%s,%s,%s)',
                            (job,ident,Jsonb(payload),observed))
                con.execute('INSERT INTO catalog_query_offers VALUES(%s,%s,%s) ON CONFLICT(query_hash,offer_id) DO UPDATE SET seen_at=excluded.seen_at',
                            (key,ident,observed))
        con.execute('INSERT INTO catalog_query_cache VALUES(%s,%s,%s,%s) ON CONFLICT(query_hash,config_hash) DO UPDATE SET checked_at=excluded.checked_at,sources=excluded.sources',
                    (key,config_hash,observed,Jsonb(sources)))


def candidates(query, limit=32):
    # Previously found results survive a source outage. A bounded pool keeps CPU work predictable.
    words = normalized(query).split()[:8]
    escaped = [word.replace('\\','\\\\').replace('%','\\%').replace('_','\\_') for word in words]
    conditions = ' OR '.join("o.title_search LIKE %s ESCAPE '\\'" for _ in words) or 'false'
    with connection() as con:
        rows = con.execute(f'''SELECT o.*, m.name AS source FROM catalog_offers o
            JOIN catalog_malls m ON m.id=o.mall_id
            LEFT JOIN catalog_query_offers q ON q.offer_id=o.id AND q.query_hash=%s
            WHERE q.offer_id IS NOT NULL OR {conditions}
            ORDER BY (q.offer_id IS NOT NULL) DESC,o.observed_at DESC LIMIT %s''',
            [query_key(query), *['%'+word+'%' for word in escaped], limit]).fetchall()
    return [{'id':r['id'],'offer_id':r['id'],'variant_id':r['variant_id'],'title':r['title'],
             'url':r['url'],'source':r['source'],'image_url':r['image_url'],'price':r['price'],
             'affiliate':bool(r['affiliate']),'observed_at':int(r['observed_at'].timestamp()),
             'stale':(utc_now()-r['observed_at']).total_seconds()>86400} for r in rows]


def image_record(offer_id):
    with connection() as con:
        row=con.execute('SELECT * FROM catalog_images WHERE offer_id=%s',(offer_id,)).fetchone()
    # Callers compare the age in UTC seconds, as with the former SQLite REAL column.
    return {**row,'observed_at':row['observed_at'].timestamp()} if row else None


def record_image(offer_id, source_url, path, sha, width, height):
    with connection() as con:
        con.execute('''INSERT INTO catalog_images VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(offer_id) DO UPDATE SET
          source_url=excluded.source_url,local_path=excluded.local_path,sha256=excluded.sha256,
          width=excluded.width,height=excluded.height,observed_at=excluded.observed_at''',
          (offer_id,source_url,path,sha,width,height,utc_now()))


def vector(offer_id, kind, revision, content_hash):
    with connection() as con:
        row=con.execute('SELECT dimensions,vector FROM catalog_embeddings WHERE offer_id=%s AND kind=%s AND revision=%s AND content_hash=%s',
                        (offer_id,kind,revision,content_hash)).fetchone()
    # The search server reads float32-le bytes, as it did from the SQLite blob.
    return (row['dimensions'],row['vector'].to_numpy().astype('<f4').tobytes()) if row else None


def record_vector(offer_id, kind, revision, content_hash, dimensions, value):
    with connection() as con:
        con.execute('''INSERT INTO catalog_embeddings(offer_id,kind,model,revision,content_hash,dimensions,vector,created_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(offer_id,kind,revision) DO UPDATE SET
          content_hash=excluded.content_hash,dimensions=excluded.dimensions,vector=excluded.vector,created_at=excluded.created_at''',
          (offer_id,kind,'google/embeddinggemma-2',revision,content_hash,dimensions,np.frombuffer(value,dtype='<f4'),utc_now()))


def link_asset(con, asset_id, owner, goods):
    if not goods or not goods.get('confirmed_by_user'): return
    # A personal choice never verifies or merges the shared product catalog.
    offer_id = goods.get('offer_id')
    offer=con.execute('SELECT id,variant_id FROM catalog_offers WHERE id=%s',(offer_id,)).fetchone() if offer_id else None
    method=goods.get('match_method')
    if method not in ('manual','user_selected_recommendation'): return
    snapshot={k:goods[k] for k in ('title','url','source','affiliate','price','observed_at','match_method','confirmed_at') if k in goods}
    con.execute('''INSERT INTO asset_product_links VALUES(%s,%s,%s,%s,%s,%s,to_timestamp(%s)) ON CONFLICT DO NOTHING''',
                (asset_id,owner,offer['id'] if offer else None,offer['variant_id'] if offer else None,
                 method,Jsonb(snapshot),goods.get('confirmed_at') or time.time()))


def backfill_links(con):
    for row in con.execute('''SELECT a.id,a.metadata,COALESCE(o.owner,'private') AS owner FROM assets a
      LEFT JOIN ownership o ON o.kind='asset' AND o.ident=a.id
      LEFT JOIN asset_product_links l ON l.asset_id=a.id WHERE l.asset_id IS NULL''').fetchall():
        link_asset(con,row['id'],row['owner'],row['metadata'].get('goods'))
