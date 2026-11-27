"""HMAC signing/response schema adapted from the user's initial collector.
Reference bloodmoon3929/goodmorning@988904c, backend/collector/api_clients/coupang.py.
Never log authorization headers or credentials.
"""
import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
import httpx
from .config import settings, product_url, egress_proxy

def search(query):
    config = settings()
    access, secret = config.get('COUPANG_ACCESS_KEY'), config.get('COUPANG_SECRET_KEY')
    if not access or not secret:
        return [], {'source':'쿠팡', 'state':'unconfigured', 'message':'쿠팡 상품 검색은 운영자의 API 연결을 기다리고 있어요.'}
    path = '/v2/providers/affiliate_open_api/apis/openapi/products/search'
    params = {'keyword':query, 'limit':10}
    if config.get('COUPANG_SUB_ID'): params['subId'] = config['COUPANG_SUB_ID']
    encoded = urlencode(params, quote_via=quote)
    date = datetime.now(timezone.utc).strftime('%y%m%dT%H%M%SZ')
    signature = hmac.new(secret.encode(), (date+'GET'+path+encoded).encode(), hashlib.sha256).hexdigest()
    auth = f'CEA algorithm=HmacSHA256, access-key={access}, signed-date={date}, signature={signature}'
    try:
        response = httpx.get('https://api-gateway.coupang.com'+path+'?'+encoded,
            headers={'Authorization':auth,'Content-Type':'application/json;charset=UTF-8'}, timeout=15, trust_env=False,proxy=egress_proxy())
        response.raise_for_status()
        body = response.json()
        if str(body.get('rCode','0')) != '0': raise ValueError('API rejected request')
        data = body.get('data') or {}
        rows = data.get('productData',[]) if isinstance(data,dict) else data
        products = []
        for row in rows[:10]:
            if not row.get('productId') or not row.get('productName'): continue
            link = product_url(row.get('productUrl') or f"https://www.coupang.com/vp/products/{row['productId']}")
            products.append({'id':'coupang-'+str(row['productId']), 'title':str(row['productName'])[:300],
                'source':'쿠팡','url':link,'image_url':row.get('productImage'),
                'price':row.get('productPrice'),'affiliate':bool(row.get('productUrl'))})
        return products, {'source':'쿠팡','state':'ok','message':f'상품 {len(products)}개를 확인했어요.'}
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return [], {'source':'쿠팡','state':'unavailable','message':'지금 쿠팡 상품 정보를 가져오지 못했어요. 잠시 후 다시 시도해 주세요.'}
