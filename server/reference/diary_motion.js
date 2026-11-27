// Runs in the original diary's scope. Sensor motion changes light, never the book pose.
if (mountedBoard && demo) (() => {
  const board = elements.post;
  const gyro = document.getElementById('enable-tilt');
  const status = document.getElementById('tilt-status');
  const reading = document.getElementById('reading-mode');
  const manual = document.createElement('button');
  manual.type = 'button'; manual.className = 'button'; manual.textContent = '수동 기울이기';
  manual.hidden = true; manual.disabled = true;
  gyro.after(manual);
  const Orientation = window.DeviceOrientationEvent;
  const preferenceKey = 'goodmorning-motion-choice-v1';
  let preference = null;
  try {
    const saved = localStorage.getItem(preferenceKey);
    if (['on','off','later','denied'].includes(saved)) preference = saved;
  } catch {}
  function remember(value) {
    preference = value;
    try { localStorage.setItem(preferenceKey, value); } catch {}
  }
  // This is an app preference, never proof that the browser granted permission.
  const intro = document.createElement('section');
  intro.className = 'motion-permission-intro'; intro.hidden = true;
  intro.setAttribute('aria-labelledby', 'motion-permission-title');
  const title = document.createElement('h2'); title.id = 'motion-permission-title';
  title.textContent = '휴대폰을 기울여 스티커를 반짝이게 해 볼까요?';
  const description = document.createElement('p');
  description.textContent = '동작 센서로 스티커의 빛 반사를 움직여요. 센서 값은 화면 효과에만 사용하며 서버로 보내거나 저장하지 않아요. 지금 켜지 않아도 다이어리를 꾸밀 수 있어요.';
  const actions = document.createElement('div'); actions.className = 'motion-permission-actions';
  const allow = document.createElement('button'); allow.type = 'button'; allow.className = 'button primary';
  const switchMarkup='<span class="gm-material" data-icon="screen_rotation" aria-hidden="true"></span><span class="gm-motion-label">반짝임</span><span class="gm-switch-track" aria-hidden="true"><span class="gm-switch-thumb"></span></span>';
  for (const control of [gyro,allow]) {
    control.classList.add('gm-motion-control'); control.innerHTML=switchMarkup;
    control.setAttribute('role','switch'); control.setAttribute('aria-checked','false');
    control.removeAttribute('aria-pressed'); control.setAttribute('aria-describedby','tilt-status');
  }
  const later = document.createElement('button'); later.type = 'button'; later.className = 'button'; later.textContent = '나중에';
  actions.append(allow,later); intro.append(title,description,actions);
  document.getElementById('post-view').before(intro);
  let state = 'idle', enabled = false, origin = null, hasSensor = false;
  let requesting = false, attempt = 0;
  let targetX = 0, targetY = 0, lightX = 0, lightY = 0;
  let manualOn = false, manualX = 0, manualY = 0, drag = null;
  let frame = null, timer = null, disposed = false;
  const neutralized = new WeakSet();
  function message(text) { status.textContent = text; status.className = 'distance-status'; }
  function updateControls() {
    manual.disabled = state !== 'unavailable';
    manual.hidden = state !== 'unavailable';
    manual.setAttribute('aria-pressed', String(manualOn));
    gyro.hidden = state === 'unavailable';
    gyro.disabled = requesting; allow.disabled = requesting; later.disabled = requesting;
    for (const control of [gyro,allow]) {
      control.title = state === 'denied' ? '자이로 반짝임 권한 다시 확인' : enabled ? '자이로 반짝임 끄기' : '자이로 반짝임 켜기';
      control.setAttribute('aria-label',control.title);
      control.setAttribute('aria-checked',String(state === 'active' && enabled));
      control.setAttribute('aria-busy',String(requesting || state === 'checking'));
    }
    board.style.touchAction = manualOn ? 'none' : '';
  }
  function stopManual() { manualOn = false; manualX = manualY = 0; drag = null; updateControls(); }
  function paint() {
    frame = null;
    if (disposed) return;
    lightX += (targetX - lightX) * .2; lightY += (targetY - lightY) * .2;
    if (Math.abs(targetX-lightX) < .04) lightX = targetX;
    if (Math.abs(targetY-lightY) < .04) lightY = targetY;
    const x = manualOn && !draft ? manualX : 0, y = manualOn && !draft ? manualY : 0;
    for (const style of [board.style, board.parentElement.style]) {
      style.setProperty('--tilt-x', `${-y}deg`); style.setProperty('--tilt-y', `${x}deg`);
      style.setProperty('--book-zoom', '1'); style.setProperty('--book-pan-x', '0px'); style.setProperty('--book-pan-y', '0px');
    }
    for (const view of views.values()) {
      if (!diaryOpen) continue;
      if (!view.model) mountBoardModel(view);
      if (!view.ready || !view.model) continue;
      if (view.previewFirst) {
        const show = fitBoardAsset(view);
        view.node.classList.toggle('model-ready', Boolean(show));
        if (!show) continue;
      }
      if (!neutralized.has(view.model)) { view.model.setAngle?.(0, 0); neutralized.add(view.model); }
      view.model.setDisplayScale?.(view.liveScale ?? 1);
      view.model.setLightAngle?.(manualOn ? x : lightX, manualOn ? y : lightY);
    }
    if (lightX !== targetX || lightY !== targetY) scheduleBoard();
  }
  scheduleBoard = () => { if (!disposed && frame === null) frame = requestAnimationFrame(paint); };
  stopBoardEffects = () => { stopManual(); scheduleBoard(); };
  function unavailable() {
    if (hasSensor || disposed || document.hidden || state === 'denied' || state === 'permission') return;
    state = 'unavailable'; updateControls();
    message('센서 값을 받지 못했어요. 수동 기울이기를 사용할 수 있어요.');
  }
  function armTimeout() { clearTimeout(timer); timer = setTimeout(unavailable, 6000); }
  function move(event) {
    if (disposed || !enabled || document.hidden || !Number.isFinite(event.beta) || !Number.isFinite(event.gamma)) return;
    const justConnected = !hasSensor || state !== 'active';
    hasSensor = true; clearTimeout(timer); state = 'active';
    if (manualOn) stopManual();
    if (justConnected) updateControls();
    if (!enabled) return;
    if (!origin) origin = { beta: event.beta, gamma: event.gamma };
    const delta = (v, start) => ((v-start+540)%360)-180;
    const dx = delta(event.gamma, origin.gamma), dy = delta(event.beta, origin.beta);
    const angle = (screen.orientation?.angle ?? window.orientation ?? 0) * Math.PI / 180;
    targetX = clamp(dx*Math.cos(angle) + dy*Math.sin(angle), -32, 32);
    targetY = clamp(dy*Math.cos(angle) - dx*Math.sin(angle), -32, 32);
    if (justConnected) message('휴대폰을 기울이면 스티커의 반짝임이 움직여요.');
    scheduleBoard();
  }
  async function detectPermission() {
    for (const name of ['accelerometer', 'gyroscope']) {
      try { if ((await navigator.permissions.query({name})).state === 'denied') return false; } catch {}
    }
    return true;
  }
  function denied() {
    state = 'denied'; enabled = false; clearTimeout(timer); stopManual();
    window.removeEventListener('deviceorientation',move);
    targetX = targetY = 0; scheduleBoard(); remember('denied'); intro.hidden = true;
    message('동작 센서가 허용되지 않았어요. 다이어리는 그대로 사용할 수 있어요. 켜려면 브라우저 사이트 설정에서 센서를 허용한 뒤 반짝임 스위치를 다시 켜 주세요.');
  }
  async function begin(fromClick = false) {
    if (disposed || requesting) return;
    if (!window.isSecureContext) {
      state = 'insecure'; intro.hidden = true; updateControls();
      message('동작 센서는 HTTPS 주소에서 사용할 수 있어요. 다이어리 꾸미기는 계속할 수 있어요.'); return;
    }
    if (!Orientation) { state = 'idle'; intro.hidden = true; unavailable(); return; }
    if (typeof Orientation.requestPermission === 'function' && !fromClick) {
      state = 'permission'; updateControls();
      message('반짝임 스위치를 켜서 이 화면의 동작 센서 권한을 확인해 주세요.'); return;
    }
    const current = ++attempt; requesting = true; updateControls();
    try {
      // Keep this call before any await, directly inside the user's click turn.
      if (typeof Orientation.requestPermission === 'function') {
        const result = await Orientation.requestPermission();
        if (disposed || current !== attempt) return;
        if (result !== 'granted') { denied(); return; }
      }
      if (!await detectPermission()) {
        if (!disposed && current === attempt) denied();
        return;
      }
      if (disposed || current !== attempt) return;
      remember('on'); intro.hidden = true;
      state = hasSensor ? 'active' : 'checking'; enabled = true; origin = null;
      stopManual(); window.addEventListener('deviceorientation', move);
      message(hasSensor ? '휴대폰을 기울이면 스티커의 반짝임이 움직여요.' : '휴대폰 동작 센서를 확인하고 있어요.'); armTimeout();
    } catch {
      if (!disposed && current === attempt) denied();
    } finally {
      if (!disposed && current === attempt) { requesting = false; updateControls(); }
    }
  }
  function turnOff(choice) {
    attempt++; requesting = false; enabled = false; state = 'idle';
    clearTimeout(timer); window.removeEventListener('deviceorientation',move);
    targetX = targetY = 0; origin = null; intro.hidden = true; remember(choice);
    stopManual(); scheduleBoard();
    message(choice === 'later' ? '나중에 위쪽 반짝임 스위치를 켜면 반짝임을 켤 수 있어요.' : '반짝임 움직임을 껐어요. 위쪽 반짝임 스위치로 다시 켤 수 있어요.');
  }
  allow.addEventListener('click', () => { void begin(true); });
  later.addEventListener('click', () => { turnOff('later'); gyro.focus({preventScroll:true}); });
  gyro.addEventListener('click', () => {
    if (enabled && ['active','checking'].includes(state)) turnOff('off');
    else void begin(true);
  });
  manual.addEventListener('click', () => {
    if (state !== 'unavailable') return;
    manualOn = !manualOn; manualX = manualY = 0; drag = null;
    updateControls(); scheduleBoard();
    message(manualOn ? '다이어리를 드래그하거나 방향키로 기울여 보세요. 편집 중에는 기울이지 않아요.' : '수동 기울이기를 껐어요.');
  });
  board.tabIndex = 0;
  board.addEventListener('pointerdown', event => {
    if (!manualOn || draft || !event.isPrimary || event.button !== 0 || event.target.closest('button,a,input,select,textarea')) return;
    drag = { id:event.pointerId, sx:event.clientX, sy:event.clientY, x:manualX, y:manualY };
    board.setPointerCapture(event.pointerId); event.preventDefault();
  });
  board.addEventListener('pointermove', event => {
    if (!manualOn || draft || drag?.id !== event.pointerId) return;
    manualX = clamp(drag.x+(event.clientX-drag.sx)*.25,-32,32);
    manualY = clamp(drag.y+(event.clientY-drag.sy)*.25,-32,32); scheduleBoard();
  });
  for (const type of ['pointerup','pointercancel','lostpointercapture']) board.addEventListener(type, () => { drag=null; });
  board.addEventListener('keydown', event => {
    if (!manualOn || draft || event.target !== board) return;
    if (event.key === 'Escape') { stopManual(); scheduleBoard(); return; }
    const step = {ArrowLeft:[-3,0],ArrowRight:[3,0],ArrowUp:[0,-3],ArrowDown:[0,3]}[event.key];
    if (!step) return;
    event.preventDefault(); manualX=clamp(manualX+step[0],-32,32); manualY=clamp(manualY+step[1],-32,32); scheduleBoard();
  });
  function readingMode(active) {
    document.body.classList.toggle('reading-mode',active); reading.setAttribute('aria-pressed',String(active));
    reading.innerHTML='<span class="gm-material" data-icon="'+(active?'close':'fullscreen')+'" aria-hidden="true"></span>';
    reading.title = active ? '전체화면 닫기' : '전체화면 켜기'; reading.setAttribute('aria-label',reading.title);
  }
  reading.classList.add('gm-icon-button'); readingMode(false); reading.hidden=false;
  reading.addEventListener('click',async()=>{
    const active=!document.body.classList.contains('reading-mode'); readingMode(active);
    try { if(active) await document.documentElement.requestFullscreen?.(); else if(document.fullscreenElement) await document.exitFullscreen?.(); } catch {}
  });
  document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)readingMode(false);});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')readingMode(false);});
  const rebase=()=>{origin=null; targetX=targetY=0; scheduleBoard();};
  window.addEventListener('orientationchange',rebase);
  screen.orientation?.addEventListener('change',rebase);
  document.addEventListener('visibilitychange',()=>{
    clearTimeout(timer); if(!document.hidden){rebase();if(state==='checking')armTimeout();}
  });
  window.addEventListener('pagehide',()=>{
    disposed=true; attempt++; clearTimeout(timer); cancelAnimationFrame(frame); window.removeEventListener('deviceorientation',move);
    window.removeEventListener('orientationchange',rebase); screen.orientation?.removeEventListener('change',rebase);
  });
  updateControls(); scheduleBoard();
  if (!Orientation || !window.isSecureContext) void begin();
  else if (preference === 'on') void begin();
  else if (preference === 'denied') denied();
  else if (preference) message('위쪽 반짝임 스위치를 켜면 스티커 반짝임을 켤 수 있어요.');
  else if (!visitingDiary) intro.hidden = false;
  else message('위쪽 반짝임 스위치로 스티커 반짝임을 체험할 수 있어요.');
})();
