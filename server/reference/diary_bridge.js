/* Storage adapter for the original prototype. Its layout and editing widgets
   remain upstream; authenticated pages/files live on the user's GPU server. */
(() => {
  let config, editorReady = false, processing = false, pendingAsset = null;
  let resolveConnection, rejectConnection;
  const connection = new Promise((resolve, reject) => { resolveConnection=resolve; rejectConnection=reject; });
  // Avoid an unhandled rejection on home/browse, where no server is needed.
  connection.catch(() => {});
  const binaryRefs = new WeakMap(), files = new Map(), added = new Set();
  const send = (type, data={}) => parent.postMessage({source:'goodmorning-reference',type,...data}, location.origin);
  let accountLabel='로그인', accountButton, nearbyButton, nearbyPeekButton, nearbyActive=false;
  function syncNearby() {
    for(const button of [nearbyButton,nearbyPeekButton]) {
      if(!button) continue;
      button.innerHTML='<span class="gm-material" data-icon="map" aria-hidden="true"></span><span class="gm-active-dot" aria-hidden="true"></span>';
      button.classList.toggle('is-active',nearbyActive);
      button.title=nearbyActive?'위치 공유 중 · 끄기/설정':'근처 수집가 알림';
      button.setAttribute('aria-label',button.title);
      button.setAttribute('aria-pressed',String(nearbyActive));
    }
  }
  document.addEventListener('DOMContentLoaded', () => {
    const topbar=document.querySelector('.topbar');
    if(!topbar) return;
    accountButton=document.createElement('button');
    accountButton.type='button';accountButton.textContent=accountLabel;
    accountButton.style.cssText='flex-shrink:0;border:0;background:transparent;color:#294653;padding:10px 8px;font:inherit;font-size:13px;cursor:pointer';
    accountButton.onclick=()=>{
      if(typeof draft!=='undefined' && draft) {
        send('error',{message:'편집 중인 다이어리를 저장하거나 취소한 뒤 로그인해 주세요.'});return;
      }
      send('account');
    };
    nearbyButton=document.createElement('button');
    nearbyButton.type='button'; nearbyButton.className='gm-icon-button gm-nearby-button';
    nearbyButton.style.cssText='flex-shrink:0;border:0;background:transparent;color:#294653;padding:10px 4px;min-width:44px;min-height:44px;font:inherit;font-size:12px;cursor:pointer';
    nearbyButton.onclick=()=>send('nearby');
    nearbyPeekButton=nearbyButton.cloneNode(false);
    nearbyPeekButton.id='gm-nearby-peek';
    nearbyPeekButton.onclick=()=>send('nearby');
    const nearbyStyle=document.createElement('style');
    nearbyStyle.textContent='#gm-nearby-peek{display:none}.peek-page #gm-nearby-peek{display:block;position:fixed;top:max(12px,env(safe-area-inset-top));right:12px;z-index:50;background:#eef7fc;border-radius:20px}';
    document.head.append(nearbyStyle);
    document.body.append(nearbyPeekButton);
    syncNearby();
    topbar.append(nearbyButton,accountButton);
    const separators=new Map();
    let headerFrame=null;
    function updateHeader() {
      headerFrame=null;
      let first=true;
      for(const button of topbar.querySelectorAll('button')) {
        let separator=separators.get(button);
        if(!separator) {
          separator=document.createElement('span');
          separator.className='gm-header-divider';separator.textContent='|';
          separator.setAttribute('aria-hidden','true');separator.hidden=true;
          button.before(separator);separators.set(button,separator);
        }
        const visible=button.getClientRects().length>0 && getComputedStyle(button).visibility!=='hidden';
        const hidden=!visible || first;
        if(separator.hidden!==hidden) separator.hidden=hidden;
        if(visible) first=false;
      }
    }
    function scheduleHeader() {
      if(headerFrame===null) headerFrame=requestAnimationFrame(updateHeader);
    }
    // Editing, fullscreen and sensor availability can each hide a different button.
    const headerObserver=new MutationObserver(scheduleHeader);
    headerObserver.observe(topbar,{subtree:true,attributes:true,attributeFilter:['hidden','class','style']});
    headerObserver.observe(document.body,{attributes:true,attributeFilter:['class']});
    const post=document.getElementById('post');
    if(post) headerObserver.observe(post,{attributes:true,attributeFilter:['class']});
    window.addEventListener('resize',scheduleHeader);
    window.addEventListener('pagehide',()=>{
      headerObserver.disconnect();cancelAnimationFrame(headerFrame);
      window.removeEventListener('resize',scheduleHeader);
    },{once:true});
    updateHeader();
  });
  document.addEventListener('click', event => {
    const link=event.target.closest('a');
    const revision=new URLSearchParams(location.search).get('_build');
    if(!link || !revision) return;
    const url=new URL(link.href,location.href);
    if(url.origin===location.origin && url.pathname===location.pathname) {
      url.searchParams.set('_build',revision);link.href=url.href;
    }
  },true);
  addEventListener('message', event => {
    if(event.source!==parent || event.origin!==location.origin || event.data?.source!=='goodmorning-app') return;
    const next=event.data;
    if(next.type!=='connection') return;
    accountLabel=next.accountLabel||'로그인';
    nearbyActive=next.nearbyActive===true;syncNearby();
    if(accountButton) accountButton.textContent=accountLabel;
    pendingAsset=next.pendingAsset || null;
    if(next.error) { rejectConnection(new Error('GPU 서버에 연결하지 못했어요. 연결 후 다이어리를 다시 열어 주세요.')); return; }
    if(!next.ready) return;
    const url=new URL(next.apiBase);
    if(url.protocol!=='https:' && !['localhost','127.0.0.1'].includes(url.hostname)) return;
    config={...next,apiBase:url.origin};
    resolveConnection(config);
    void processPending();
  });

  async function api(path, options={}) {
    const settings=await connection;
    const controller=new AbortController();
    const timer=setTimeout(()=>controller.abort(),60000);
    try {
      const response=await fetch(settings.apiBase+path, {
        ...options, headers:{...settings.headers,...options.headers},
        credentials:'same-origin', signal:controller.signal,
      });
      if(!response.ok) {
        const detail=await response.json().catch(()=>({}));
        throw new Error(typeof detail.detail==='string'?detail.detail:'서버에 저장하지 못했어요. 연결을 확인해 주세요.');
      }
      return response;
    } finally { clearTimeout(timer); }
  }

  async function resource(ref) {
    const key=JSON.stringify(ref);
    if(!files.has(key)) files.set(key,(async()=>{
      const path=ref.__gmAsset
        ? `/files/${encodeURIComponent(ref.__gmAsset)}/${ref.part==='model'?'sticker.glb':'sticker.png'}`
        : `/api/notebook/files/${encodeURIComponent(ref.__gmFile)}`;
      const response=await api(path);
      const blob=await response.blob();
      const file=new File([blob],ref.name||(ref.part==='model'?'sticker.glb':'photo.png'),{type:ref.type||blob.type});
      binaryRefs.set(file,ref);
      return file;
    })().catch(error=>{files.delete(key);throw error;}));
    return files.get(key);
  }

  async function encode(value) {
    if(value instanceof Blob) {
      if(binaryRefs.has(value)) return binaryRefs.get(value);
      const body=new FormData();body.append('attachment',value,value.name||'photo.png');
      const ref=await (await api('/api/notebook/files',{method:'POST',body})).json();
      binaryRefs.set(value,ref);
      return ref;
    }
    if(Array.isArray(value)) return Promise.all(value.map(encode));
    if(value && typeof value==='object') {
      const result={};
      for(const [key,child]of Object.entries(value)) if(child!==undefined) result[key]=await encode(child);
      return result;
    }
    return value;
  }

  async function decode(value) {
    if(!value || typeof value!=='object') return value;
    if(value.__gmFile || value.__gmAsset) return resource(value);
    if(Array.isArray(value)) return Promise.all(value.map(decode));
    const result={};
    for(const [key,child]of Object.entries(value)) result[key]=await decode(child);
    return result;
  }

  async function assetRows(includeDeleted=false) { return (await api('/api/assets'+(includeDeleted?'?include_deleted=true':''))).json(); }
  function assetRef(id,part) { return {__gmAsset:id,part}; }
  async function materialize(asset) {
    if(asset.file) return asset;
    const id=asset.backendAssetId || asset.id;
    return {...asset, file:await resource(assetRef(id,'model'))};
  }

  async function migrateLegacy() {
    const [rows,diaries]=await Promise.all([assetRows(true),api('/api/diaries').then(r=>r.json())]);
    const previous=diaries.find(d=>d.id===config.diaryId)||diaries[0];
    if(!previous?.placements?.length) return null;
    const layout=diaryPhotos.map(photo=>({...photo}));
    const items=[];
    for(const p of previous.placements) {
      const asset=rows.find(a=>a.id===p.asset_id); if(!asset) continue;
      if(asset.kind==='photo') {
        layout.push({file:await resource(assetRef(asset.id,'thumbnail')),x:p.x*100,y:p.y*100,size:p.size*100,rotation:p.rotation,tape:'kraft',caption:asset.name});
      } else {
        items.push({id:p.id,sourceId:asset.id,backendAssetId:asset.id,name:asset.name,finish:'sticker',
          file:await resource(assetRef(asset.id,'model')),preview:await resource(assetRef(asset.id,'thumbnail')),
          x:p.x*100,y:p.y*100,size:p.size*100,rotation:p.rotation,url:asset.metadata?.goods?.url||'',goods:asset.metadata?.goods});
      }
    }
    return {items,photo:null,diaryLayout:layout,diaryLayoutVersion};
  }

  async function processPending() {
    if(!config || !editorReady || processing || !pendingAsset || added.has(pendingAsset)) return;
    if(!demo || visitingDiary) return;
    const id=pendingAsset, requestedDraft=draft;processing=true;
    let editing, layout, token;
    try {
      const asset=(await assetRows()).find(a=>a.id===id);
      if(!asset) throw new Error('에셋을 찾지 못했어요.');
      if(draft!==requestedDraft || saving) { added.add(id);send('asset-added',{id});return; }
      if(!draft) elements.edit.click();
      if(!draft) throw new Error('다이어리 편집을 시작하지 못했어요.');
      editing=draft;layout=draftDiary;token=beginDiaryLoad();
      if(asset.kind==='photo') {
        const file=await resource(assetRef(id,'thumbnail'));
        if(draft!==editing || draftDiary!==layout || saving) return;
        const reusable=layout.findIndex((photo,index)=>index>=stories.length && photo.removed);
        if(reusable<0 && layout.length>=100) throw new Error('이 장의 사진이 가득 찼어요. 새 장에 추가해 주세요.');
        selectedDiaryPhoto=reusable>=0?reusable:layout.length;
        layout[selectedDiaryPhoto]={file,x:20,y:20,size:45,rotation:0,tape:'kraft',caption:''};
        renderDiary();syncDiaryControls();
        diaryObjectEditor?.selectPhoto(selectedDiaryPhoto);
      } else {
        if(draft.length>=maxItems) throw new Error(`한 페이지에는 에셋 ${maxItems}개까지 붙일 수 있어요. 새 장에 추가해 주세요.`);
        const ready=await materialize({id,name:asset.name,backendAssetId:id,finish:'sticker',url:asset.metadata?.goods?.url||'',goods:asset.metadata?.goods,preview:await resource(assetRef(id,'thumbnail'))});
        if(draft!==editing || saving) return;
        addItem(ready);
      }
      added.add(id);
      send('asset-added',{id});
      notice('에셋을 붙였어요. 위치를 정한 뒤 게시를 눌러 저장해 주세요.');
    } catch(error) { notice(error.message);send('error',{message:error.message}); }
    finally {
      if(token) endDiaryLoad(token);
      // A cancelled edit consumes this request without inserting into a new draft.
      if(editing && draft!==editing) { added.add(id);send('asset-added',{id}); }
      processing=false;
    }
  }

  window.goodmorningBridge={
    async readPost(key) {
      const body=await (await api('/api/notebook/pages/'+encodeURIComponent(key))).json();
      return body ? decode(body) : key==='story:chiikawa' ? migrateLegacy() : null;
    },
    async writePost(key,entry) {
      const body=JSON.stringify(await encode(entry));
      await api('/api/notebook/pages/'+encodeURIComponent(key),{method:'PUT',headers:{'Content-Type':'application/json'},body});
    },
    async pageKeys() { return (await api('/api/notebook/pages')).json(); },
    async stickers() {
      const rows=await assetRows();
      const samples=new Set(['pochita','2026_11_24_08_15','2026_11_24_08_16']);
      return Promise.all(rows.filter(a=>a.kind==='sticker'&&!samples.has(a.id)).map(async asset=>({
        id:asset.id,backendAssetId:asset.id,name:asset.name,finish:'sticker',url:asset.metadata?.goods?.url||'',goods:asset.metadata?.goods,
        preview:await resource(assetRef(asset.id,'thumbnail')),
      })));
    },
    materialize,
    markReady() { editorReady=true;void processPending(); },
  };
  send('ready');
})();
