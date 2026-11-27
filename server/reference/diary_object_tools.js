// Selection chrome lives above both content planes; it never raises a photo above stickers.
const diaryObjectEditor = demo && !visitingDiary ? createDiaryObjectEditor() : null;
function createDiaryObjectEditor() {
  document.querySelector('.edit-hint').textContent = '개체를 선택한 뒤 모서리로 크기 조절 · 위 툴바에서 회전·교체·삭제';
  const plane = elements.post.querySelector('.diary-content-plane');
  const overlay = document.createElement('div');
  overlay.className = 'diary-object-tools'; overlay.hidden = true;
  const frame = document.createElement('div'); frame.className = 'object-selection-frame';
  const toolbar = document.createElement('div'); toolbar.className = 'object-toolbar';
  toolbar.setAttribute('role', 'toolbar'); toolbar.setAttribute('aria-label', '선택한 개체 편집');
  overlay.append(frame, toolbar); plane.append(overlay);
  let selection = null, rotationStart = null, gesture = null, animation = null, replaceSerial = 0;
  const button = (text, label, action, parent = toolbar) => {
    const node = document.createElement('button'); node.type = 'button';
    node.textContent = text; node.title = label; node.setAttribute('aria-label', label);
    node.addEventListener('click', action); parent.append(node); return node;
  };
  const rotate = button('↻ 회전', '모서리를 드래그하는 회전 모드 열기', startRotation);
  const swap = button('바꾸기', '선택한 사진 또는 스티커 바꾸기', replaceObject);
  const forward = button('앞으로', '폴라로이드를 한 단계 앞으로 이동', () => movePhotoLayer(1));
  const backward = button('뒤로', '폴라로이드를 한 단계 뒤로 이동', () => movePhotoLayer(-1));
  forward.hidden = backward.hidden = true;
  const remove = button('삭제', '이 페이지에서 선택한 개체 제거', removeObject);
  const rotationPanel = document.createElement('div'); rotationPanel.className = 'object-rotation';
  rotationPanel.hidden = true; toolbar.append(rotationPanel);
  button('적용', '회전 각도 적용', () => finishRotation(true), rotationPanel).className = 'object-apply';
  button('취소', '회전 취소', () => finishRotation(false), rotationPanel);
  const handles = [];
  for (const [name, sx, sy] of [['nw', -1, -1], ['ne', 1, -1], ['sw', -1, 1], ['se', 1, 1]]) {
    const handle = button('', '모서리를 드래그해 크기 조절. 방향키로도 조절할 수 있어요.', () => {}, frame);
    handle.className = 'object-resize-handle ' + name;
    handles.push(handle);
    handle.addEventListener('pointerdown', event => startResize(event, handle, sx, sy));
    handle.addEventListener('pointermove', resize);
    handle.addEventListener('pointerup', endResize);
    handle.addEventListener('pointercancel', cancelResize);
    handle.addEventListener('lostpointercapture', endResize);
    handle.addEventListener('keydown', event => {
      const step = {ArrowUp:1, ArrowRight:1, ArrowDown:-1, ArrowLeft:-1}[event.key];
      if (!step || !valid()) return;
      event.preventDefault(); event.stopPropagation();
      if (rotationStart !== null) setRotation((selection.item.rotation ?? 0) + step * (event.shiftKey ? 15 : 1));
      else changeSize(selection.item.size + step * (event.shiftKey ? 5 : 1));
    });
  }
  for (const type of ['pointerdown', 'pointermove', 'pointerup', 'click', 'keydown']) {
    overlay.addEventListener(type, event => event.stopPropagation());
  }
  function valid() {
    return Boolean(draft && !saving && diaryOpen && selection && selection.node.isConnected &&
      (selection.kind === 'sticker' ? draft.includes(selection.item) : draftDiary?.[selection.index] === selection.item && !selection.item.removed));
  }
  function choose(next) {
    if (selection?.item !== next?.item) { finishRotation(false); endResize(); }
    selection = next; sync();
  }
  function selectSticker(id) {
    const item = draft?.find(item => item.id === id), view = views.get(id);
    if (item && view) choose({kind:'sticker', item, node:view.node, view});
    else choose(null);
  }
  function selectPhoto(index) {
    const item = draftDiary?.[index], node = diaryCards[index];
    if (item && node && !node.hidden && !node.classList.contains('blank-diary-card')) {
      choose({kind:'photo', item, node, index});
    }
  }
  function repaint() {
    if (!valid()) return;
    if (selection.kind === 'sticker') {
      positionView(selection.view, selection.item); updateTransformControls(selection.item);
    } else { renderDiary(); syncDiaryControls(); }
    sync();
  }
  function rotationControls() {
    const active = rotationStart !== null;
    overlay.classList.toggle('is-rotating', active);
    rotate.hidden = swap.hidden = remove.hidden = active;
    rotationPanel.hidden = !active;
    layerControls();
    toolbar.setAttribute('aria-label', active ? '모서리를 드래그해 회전한 뒤 적용 또는 취소' : '선택한 개체 편집');
    for (const handle of handles) {
      const label = active ? '모서리를 드래그해 회전. 방향키로도 조절할 수 있어요.' : '모서리를 드래그해 크기 조절. 방향키로도 조절할 수 있어요.';
      handle.title = label; handle.setAttribute('aria-label', label);
    }
    sync();
  }
  function layerControls() {
    const visible = selection?.kind === 'photo' && rotationStart === null;
    forward.hidden = backward.hidden = !visible;
    if (!visible) return;
    const stack = diaryPhotoStack(draftDiary ?? []), index = stack.findIndex(entry => entry.photo === selection.item);
    backward.disabled = index <= 0;
    forward.disabled = index < 0 || index >= stack.length-1;
  }
  function movePhotoLayer(direction) {
    if (!valid() || selection.kind !== 'photo' || rotationStart !== null) return;
    const stack = diaryPhotoStack(draftDiary), index = stack.findIndex(entry => entry.photo === selection.item);
    const next = index+direction;
    if (index < 0 || next < 0 || next >= stack.length) return;
    endResize(); resetPlacement();
    [stack[index],stack[next]] = [stack[next],stack[index]];
    stack.forEach(({photo},rank) => { photo.layerOrder = rank; });
    layerControls(); repaint();
  }
  function startRotation() {
    if (!valid() || rotationStart !== null) return;
    endResize(); resetPlacement();
    rotationStart = selection.item.rotation ?? 0;
    rotationControls(); handles[0].focus({preventScroll:true});
  }
  function setRotation(value) {
    if (!valid() || rotationStart === null) return;
    selection.item.rotation = Math.round(((((value + 180) % 360) + 360) % 360 - 180) * 10) / 10;
    repaint();
  }
  function finishRotation(apply) {
    if (rotationStart !== null && selection) {
      endResize();
      if (!apply) selection.item.rotation = rotationStart;
      rotationStart = null; rotationControls(); repaint();
    }
  }
  function geometry() {
    const bounds = plane.getBoundingClientRect(), rect = selection.node.getBoundingClientRect();
    const scaleX = bounds.width / plane.clientWidth, scaleY = bounds.height / plane.clientHeight;
    const matrix = new DOMMatrixReadOnly(getComputedStyle(selection.node).transform);
    return {cx:(rect.left + rect.width/2 - bounds.left)/scaleX,
      cy:(rect.top + rect.height/2 - bounds.top)/scaleY,
      width:selection.node.offsetWidth, height:selection.node.offsetHeight,
      angle:Math.atan2(matrix.b, matrix.a), scaleX, scaleY};
  }
  function changeSize(size) {
    const item = selection.item, photo = selection.kind === 'photo';
    item.size = clamp(size, photo ? 20 : 12, photo ? 85 : 86);
    if (photo) {
      item.x = clamp(item.x, 0, 100-item.size);
      item.y = clamp(item.y, 0, Math.max(0, 100-item.size*plane.clientWidth/plane.clientHeight));
    }
    repaint();
  }
  function startResize(event, handle, sx, sy) {
    if (!valid() || gesture || !event.isPrimary || event.button !== 0) return;
    event.preventDefault(); event.stopPropagation(); resetPlacement();
    const g = geometry(), cos = Math.cos(g.angle), sin = Math.sin(g.angle);
    const vx = cos*sx*g.width - sin*sy*g.height, vy = sin*sx*g.width + cos*sy*g.height;
    gesture = {handle, id:event.pointerId, startX:event.clientX, startY:event.clientY,
      item:selection.item, origin:{...selection.item}, g, vx, vy, ax:g.cx-vx/2, ay:g.cy-vy/2};
    if (rotationStart !== null) {
      const bounds = plane.getBoundingClientRect();
      gesture.rotating = true;
      gesture.radians = Math.atan2((event.clientY-bounds.top)/g.scaleY-g.cy, (event.clientX-bounds.left)/g.scaleX-g.cx);
      gesture.degrees = selection.item.rotation ?? 0;
    }
    handle.setPointerCapture(event.pointerId);
  }
  function resize(event) {
    if (!gesture || event.pointerId !== gesture.id || !valid()) return;
    event.preventDefault();
    const {g, vx, vy, ax, ay, origin, startX, startY} = gesture;
    if (gesture.rotating) {
      const bounds = plane.getBoundingClientRect();
      const dx = (event.clientX-bounds.left)/g.scaleX-g.cx, dy = (event.clientY-bounds.top)/g.scaleY-g.cy;
      // Ignore the undefined angle at the center; unwrap each step across +/-180 degrees.
      if (Math.hypot(dx,dy) < 8) return;
      const radians = Math.atan2(dy,dx);
      const delta = Math.atan2(Math.sin(radians-gesture.radians),Math.cos(radians-gesture.radians));
      gesture.degrees += delta*180/Math.PI; gesture.radians = radians;
      setRotation(gesture.degrees); return;
    }
    const dx = (event.clientX-startX)/g.scaleX, dy = (event.clientY-startY)/g.scaleY;
    const photo = selection.kind === 'photo';
    const size = clamp(origin.size*(1+(dx*vx+dy*vy)/(vx*vx+vy*vy)), photo?20:12, photo?85:86);
    const factor = size/origin.size, cx = ax+vx*factor/2, cy = ay+vy*factor/2;
    const width = plane.clientWidth, height = plane.clientHeight;
    Object.assign(selection.item, {size:Math.round(size*10)/10,
      x:photo ? clamp((cx-g.width*factor/2)*100/width, 0, 100-size) : clamp(cx*100/width, 8, 92),
      y:photo ? clamp((cy-g.height*factor/2)*100/height, 0, Math.max(0,100-g.height*factor*100/height)) : clamp(cy*100/height, 8, 92)});
    repaint();
  }
  function endResize(event) {
    if (!gesture || event && event.pointerId !== gesture.id) return;
    const previous = gesture; gesture = null;
    if (previous.handle.hasPointerCapture(previous.id)) previous.handle.releasePointerCapture(previous.id);
  }
  function cancelResize(event) {
    if (!gesture || event && event.pointerId !== gesture.id) return;
    Object.assign(gesture.item, gesture.origin); endResize(); repaint();
  }
  function removeObject() {
    if (!valid()) return;
    finishRotation(false); resetPlacement();
    if (selection.kind === 'photo') {
      selectedDiaryPhoto = selection.index;
      document.getElementById('diary-photo-remove').click();
    } else {
      selectedId = selection.item.id; elements.remove.click();
    }
    choose(null);
  }
  const picker = document.createElement('dialog'); picker.className = 'object-swap-dialog';
  picker.setAttribute('aria-label', '교체할 스티커 선택');
  const heading = document.createElement('h2'); heading.textContent = '어떤 스티커로 바꿀까요?';
  const close = document.createElement('button'); close.type = 'button'; close.className='button gm-icon-button'; close.title='닫기'; close.setAttribute('aria-label','닫기'); close.innerHTML='<span class="gm-material" data-icon="close" aria-hidden="true"></span>';
  close.addEventListener('click', () => picker.close());
  const result = document.createElement('p'); result.setAttribute('role','status');
  const choices = document.createElement('div'); choices.className = 'object-swap-grid';
  picker.append(heading, close, result, choices); document.body.append(picker);
  let thumbnails = [];
  picker.addEventListener('close', () => { replaceSerial++; thumbnails.forEach(URL.revokeObjectURL); thumbnails=[]; });
  async function replaceObject() {
    if (!valid()) return;
    finishRotation(false);
    if (selection.kind === 'photo') {
      selectedDiaryPhoto=selection.index; document.getElementById('diary-photo-replace').click(); return;
    }
    const target=selection.item, editing=draft, serial=++replaceSerial;
    choices.replaceChildren(); choices.inert=false; result.textContent='스티커를 불러오고 있어요.'; picker.showModal();
    const current=()=>serial===replaceSerial && picker.open && draft===editing && draft.includes(target);
    try {
      const assets=await window.goodmorningBridge.stickers();
      if(!current()) return;
      result.textContent=assets.length?'위치와 크기, 적용한 각도는 유지돼요.':'에셋함에 스티커를 먼저 추가해 주세요.';
      for(const asset of assets) {
        const tile=button('', asset.name, async()=>{
          if(!current()) return;
          choices.inert=true; const token=beginDiaryLoad(); result.textContent='스티커를 바꾸고 있어요.';
          try {
            const loaded=await window.goodmorningBridge.materialize(asset);
            if(!current()) return;
            const index=draft.indexOf(target), view=views.get(target.id);
            cancelAnimationFrame(view?.returnFrame); view?.model?.dispose(); view?.node.remove(); views.delete(target.id);
            draft[index]={...loaded,id:target.id,sourceId:asset.id,x:target.x,y:target.y,size:target.size,rotation:target.rotation??0};
            choose(null); renderItems(); selectItem(target.id); renderPicker(); picker.close();
          } catch(error) { if(current()) result.textContent=error.message || '교체하지 못했어요. 다시 골라 주세요.'; }
          finally { endDiaryLoad(token); if(serial===replaceSerial) choices.inert=false; }
        }, choices);
        const image=new Image(); image.alt=''; const url=URL.createObjectURL(asset.preview);
        thumbnails.push(url); image.src=url;
        const label=document.createElement('span'); label.textContent=asset.name; tile.append(image,label);
      }
    } catch(error) { if(current()) result.textContent=error.message || '스티커를 불러오지 못했어요.'; }
  }
  function paint() {
    animation=null;
    if (!valid()) { overlay.hidden=true; return; }
    overlay.hidden=false;
    layerControls();
    swap.textContent=selection.kind==='photo'?'사진 바꾸기':'스티커 바꾸기';
    const g=geometry();
    Object.assign(frame.style,{left:g.cx+'px',top:g.cy+'px',width:g.width+'px',height:g.height+'px',
      transform:`translate(-50%, -50%) rotate(${g.angle}rad)`});
    const rect=selection.node.getBoundingClientRect(), bounds=plane.getBoundingClientRect();
    const left=clamp(g.cx-toolbar.offsetWidth/2, 2, Math.max(2,plane.clientWidth-toolbar.offsetWidth-2));
    const top=Math.max(2,(rect.top-bounds.top)/g.scaleY-toolbar.offsetHeight-12);
    toolbar.style.left=left+'px'; toolbar.style.top=top+'px';
  }
  function sync() { if(animation===null) animation=requestAnimationFrame(paint); }
  elements.post.addEventListener('pointerdown',event=>{
    if(!draft || saving || event.target.closest('.diary-object-tools')) return;
    const photo=event.target.closest('.diary figure');
    if(photo) selectPhoto(Number(photo.dataset.photoIndex));
    else if(!event.target.closest('.model,button,input,textarea,a')) choose(null);
  },true);
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape' && !picker.open && valid()) {
      if(rotationStart!==null) finishRotation(false); else if(gesture) cancelResize(); else choose(null);
    }
  },true);
  window.addEventListener('blur',()=>{endResize();});
  window.addEventListener('resize',sync);
  new ResizeObserver(sync).observe(plane);
  return {sync,selectSticker,selectPhoto,
    reset(){finishRotation(false);endResize();selection=null;overlay.hidden=true;if(picker.open)picker.close();},
    canPublish(){if(rotationStart!==null){notice('회전 각도를 적용하거나 취소한 뒤 게시해 주세요.');return false;}return true;}};
}
