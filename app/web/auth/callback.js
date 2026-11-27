/* Static OAuth return page: same-tab proof stays in sessionStorage.
   Provider credentials and provider tokens are handled only by the local API. */
(async () => {
  const query=new URLSearchParams(location.search);
  history.replaceState(null,'',location.pathname);
  const status=document.getElementById('status');
  const home=new URL('../',location.href);
  document.getElementById('home').href=home.href;
  try {
    const pending=JSON.parse(sessionStorage.getItem('goodmorning-oauth')||'null');
    const provider=location.pathname.split('/').pop().replace('.html','');
    if(!['google','kakao','naver'].includes(provider) || !pending || pending.provider!==provider ||
       !Number.isFinite(pending.expires) || pending.expires<Date.now() || pending.state!==query.get('state')) {
      throw Error('로그인 요청이 만료되었어요. 앱으로 돌아가 다시 시작해 주세요.');
    }
    if(query.has('error') || !query.get('code')) throw Error('로그인을 완료하지 않았어요. 앱에서 다시 시작할 수 있어요.');
    const server=new URL(pending.server);
    if(server.protocol!=='https:' || server.origin!==pending.server) throw Error('서버 연결을 확인해 주세요.');
    const response=await fetch(server.origin+'/auth/'+provider+'/complete', {
      method:'POST', credentials:'omit', cache:'no-store', referrerPolicy:'no-referrer',
      headers:{'Content-Type':'application/json'}, signal:AbortSignal.timeout(45000),
      body:JSON.stringify({state:pending.state,verifier:pending.verifier,code:query.get('code')}),
    });
    const result=await response.json();
    if(!response.ok) throw Error(typeof result.detail==='string'?result.detail:'로그인을 완료하지 못했어요. 다시 시도해 주세요.');
    if(result.signup_token) {
      if(!/^[A-Za-z0-9_-]{43}$/.test(result.signup_token) || result.expires_in!==600) throw Error('가입 응답을 확인하지 못했어요.');
      sessionStorage.setItem('goodmorning-signup', JSON.stringify({token:result.signup_token, server:server.origin, expires:Date.now()+600000}));
      sessionStorage.removeItem('goodmorning-oauth');
      location.replace(home.href);
      return;
    }
    if(!/^member\.[A-Za-z0-9_-]{43}$/.test(result.token)) throw Error('로그인 응답을 확인하지 못했어요.');
    sessionStorage.setItem('goodmorning-token',result.token);
    if(result.guest_promoted && localStorage.getItem('goodmorning-visitor-token')===pending.guestToken) {
      localStorage.removeItem('goodmorning-visitor-token');
    }
    sessionStorage.removeItem('goodmorning-oauth');
    location.replace(home.href);
  } catch(error) {
    sessionStorage.removeItem('goodmorning-oauth');
    status.textContent=error.name==='TimeoutError'?'연결 시간이 길어지고 있어요. 앱에서 다시 로그인해 주세요.':error.message;
  }
})();
