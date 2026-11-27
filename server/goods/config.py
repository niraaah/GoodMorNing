import json
import os
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.getenv('GOODMORNING_DATA', str(ROOT / 'data')))
MODEL_REVISION = 'f9972ac22e696a105c482202646979e33e4b5a1e'
USER_AGENT = 'GoodMorNing-Collector/1.0 (+https://github.com/niraaah/GoodMorNing)'
PRODUCT_HOSTS = ('naver.com', 'coupang.com', 'coupa.ng', 'pokemonstore.co.kr', 'daewonshop.com')

def egress_proxy():
    # Runtime isolation must fail closed, not silently use a direct host connection.
    value=os.getenv('GOODMORNING_EGRESS_PROXY','')
    if value!='http://172.30.74.2:8080':
        raise RuntimeError('Isolated egress gateway is required. Run scripts/start-search.ps1.')
    return value
GUIDANCE = ('찾는 굿즈가 없다면 아직 검색 목록에 없거나 사진에서 특징이 잘 보이지 않았을 수 있어요. '
            '더 정확하게 찾고 스티커를 만들 수 있도록 밝은 곳에서 굿즈가 화면에 크게 나오게 선명하게 찍어 주세요. '
            '상품명·캐릭터명을 함께 입력하거나 상품 링크를 직접 연결할 수도 있어요.')

def settings():
    path = DATA / 'search.local.json'
    result = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    for key in ('COUPANG_ACCESS_KEY', 'COUPANG_SECRET_KEY', 'COUPANG_SUB_ID', 'EMBEDDING_DEVICE'):
        if os.getenv(key): result[key] = os.environ[key]
    return result

def product_url(value):
    if not isinstance(value, str) or len(value) > 2048: raise ValueError('상품 링크를 확인해 주세요.')
    url = urlsplit(value.strip())
    host = (url.hostname or '').lower()
    if url.scheme != 'https' or url.username or url.password or url.port not in (None,443):
        raise ValueError('HTTPS 상품 링크를 입력해 주세요.')
    if not any(host == domain or host.endswith('.'+domain) for domain in PRODUCT_HOSTS):
        raise ValueError('네이버·쿠팡·포켓몬스토어·대원샵의 상품 링크를 입력해 주세요.')
    return value.strip()
