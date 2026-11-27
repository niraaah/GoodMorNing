"""Bounded Scrapy + headless Playwright collection in a separate reactor process.
Selectors/settings reference bloodmoon3929/goodmorning@988904c collector.
No sign-in, challenge solving, stealth, or retrying blocked pages.
"""
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.robotparser import RobotFileParser
import httpx
import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy_playwright.page import PageMethod
from .config import USER_AGENT, product_url, egress_proxy

def allowed(site, url):
    try:
        response = httpx.get(site['origin']+'/robots.txt',timeout=10,follow_redirects=False,trust_env=False,headers={'User-Agent':USER_AGENT},proxy=egress_proxy())
        if response.status_code != 200: return False
        robots=RobotFileParser(); robots.parse(response.text.splitlines())
        return robots.can_fetch(USER_AGENT,url)
    except httpx.HTTPError: return False

async def restrict_browser(route, request):
    # The browser only visits known shop resources; no local network navigation.
    host=(urlsplit(request.url).hostname or '').lower()
    domains=('pokemonstore.co.kr','daewonshop.com','shopby.co.kr','nhncommerce.com','cdn-nhncommerce.com',
             'shopby-api.com','naver.net','pstatic.net','googleapis.com','gstatic.com','jsdelivr.net')
    parsed=urlsplit(request.url)
    if request.url.startswith('data:') or (parsed.scheme=='https' and not parsed.username and not parsed.password and parsed.port in (None,443) and any(host==d or host.endswith('.'+d) for d in domains)):
        await route.continue_()
    else: await route.abort()

async def prepare_page(page, request):
    await page.route('**/*',restrict_browser)

class GoodsSpider(scrapy.Spider):
    name='goods'
    def __init__(self, sites, query, output, **kwargs):
        super().__init__(**kwargs); self.sites=sites; self.query=query; self.output=output
        self.products=[]; self.states=[]
    async def start(self):
        for site in self.sites:
            url=site['search'].format(query=quote(self.query))
            if not allowed(site,url):
                self.states.append({'source':site['source'],'state':'blocked','message':'이 판매처는 현재 자동 수집을 허용하지 않아요.'}); continue
            yield scrapy.Request(url,callback=self.parse,errback=self.failed,meta={'site':site,'proxy':egress_proxy(),
                'playwright':site.get('js',False),'playwright_page_init_callback':prepare_page,
                'playwright_page_methods':[PageMethod('wait_for_timeout',1800)],'handle_httpstatus_all':True})
    def parse(self,response):
        site=response.meta['site']
        if response.status != 200:
            self.states.append({'source':site['source'],'state':'blocked','message':'판매처가 요청을 받지 않아 이번 검색에서 제외했어요.'}); return
        count=0
        for node in response.css(site['item'])[:12]:
            title=' '.join(node.css(site['title']).getall()).strip()
            link=node.css(site['link']).get()
            if not title or not link: continue
            try: link=product_url(response.urljoin(link))
            except ValueError: continue
            img=node.css(site['image']).get()
            price=re.sub(r'[^0-9]','',''.join(node.css(site['price']).getall()))
            self.products.append({'id':hashlib.sha256(link.encode()).hexdigest()[:24], 'source':site['source'],
                'title':title[:300],'url':link,'image_url':response.urljoin(img) if img else None,
                'price':int(price) if price else None,'affiliate':False})
            count+=1
        self.states.append({'source':site['source'],'state':'ok' if count else 'empty',
            'message':f'상품 {count}개를 확인했어요.' if count else '검색 결과가 없거나 판매처 화면을 읽지 못했어요.'})
    def failed(self,failure):
        self.states.append({'source':failure.request.meta['site']['source'],'state':'unavailable','message':'판매처에 연결하지 못했어요.'})
    def closed(self,reason):
        Path(self.output).write_text(json.dumps({'products':self.products,'sources':self.states},ensure_ascii=False),encoding='utf-8')

def main():
    query, output=sys.argv[1:3]
    sites=json.loads((Path(__file__).parent/'sites.json').read_text(encoding='utf-8'))
    process=CrawlerProcess(settings={'USER_AGENT':USER_AGENT,'ROBOTSTXT_OBEY':True,'DOWNLOAD_DELAY':3,
        'CONCURRENT_REQUESTS_PER_DOMAIN':1,'CONCURRENT_REQUESTS':2,'RETRY_ENABLED':False,
        'DOWNLOAD_TIMEOUT':25,'DOWNLOAD_MAXSIZE':8*1024*1024,'CLOSESPIDER_TIMEOUT':80,'COOKIES_ENABLED':False,
        'LOG_LEVEL':'ERROR','REDIRECT_ENABLED':False,'PLAYWRIGHT_BROWSER_TYPE':'chromium',
        'PLAYWRIGHT_LAUNCH_OPTIONS':{'headless':True,'chromium_sandbox':True,'proxy':{'server':egress_proxy()}},'PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT':25000,
        'DOWNLOAD_HANDLERS':{'http':'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler','https':'scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler'},
        'TWISTED_REACTOR':'twisted.internet.asyncioreactor.AsyncioSelectorReactor'})
    process.crawl(GoodsSpider,sites=sites,query=query,output=output); process.start()

if __name__=='__main__': main()
