// Page-local paper preferences use the same save/cancel lifecycle as placements.
const diaryPaperEditor = demo && !visitingDiary ? createDiaryPaperEditor() : null;
function createDiaryPaperEditor() {
  const colors = [
    ['auto','사진에 맞춤',null], ['cream','크림','#fff9eb'],
    ['pink','연분홍','#fce9ed'], ['sky','하늘','#e7f3fb'],
    ['mint','민트','#e9f5ed'], ['lavender','라벤더','#f0ebfa'],
  ];
  const patterns = [['original','기본 줄노트'],['plain','무지'],['grid','모눈'],['dots','도트']];
  const defaults = () => ({color:'auto',pattern:'original'});
  const normalize = value => ({
    color: colors.some(([id]) => id === value?.color) ? value.color : 'auto',
    pattern: patterns.some(([id]) => id === value?.pattern) ? value.pattern : 'original',
  });
  let saved = defaults(), editing = null;
  const panel = document.createElement('fieldset'); panel.className = 'diary-paper-editor'; panel.hidden = true;
  const legend = document.createElement('legend'); legend.textContent = '이 장의 속지'; panel.append(legend);
  const buttons = [];
  function choices(label, key, options) {
    const group = document.createElement('div'); group.className = 'paper-options';
    group.setAttribute('role','group'); group.setAttribute('aria-label',label);
    for (const [id,name,color] of options) {
      const button = document.createElement('button'); button.type = 'button';
      button.className = 'paper-choice'; button.setAttribute('aria-label',name);
      const preview = document.createElement('span'); preview.className = 'paper-swatch'; preview.setAttribute('aria-hidden','true');
      if (key === 'color') preview.style.backgroundColor = color ?? '#f5efe1';
      else preview.dataset.pattern = id;
      const text = document.createElement('span'); text.textContent = name;
      button.append(preview,text);
      button.addEventListener('click', () => {
        if (!editing || !draftDiary || saving) return;
        editing[key] = id; sync();
      });
      buttons.push({button,key,id}); group.append(button);
    }
    panel.append(group);
  }
  choices('속지 색','color',colors); choices('속지 무늬','pattern',patterns);
  const footer = document.createElement('div'); footer.className = 'paper-footer';
  const hint = document.createElement('span'); hint.textContent = '게시하면 이 장에 저장돼요.';
  const reset = document.createElement('button'); reset.type = 'button'; reset.className = 'button'; reset.textContent = '기본 속지';
  reset.addEventListener('click', () => { if (editing && draftDiary && !saving) { editing=defaults(); sync(); } });
  footer.append(hint,reset); panel.append(footer);
  document.getElementById('diary-controls').before(panel);
  function sync() {
    const value = editing ?? saved;
    diary.dataset.paperPattern = value.pattern;
    const color = colors.find(([id]) => id === value.color)?.[2];
    if (color) diary.style.setProperty('--user-paper',color);
    else diary.style.removeProperty('--user-paper');
    panel.hidden = !draftDiary; panel.disabled = saving || !draftDiary;
    for (const {button,key,id} of buttons) button.setAttribute('aria-pressed',String(value[key] === id));
  }
  return {
    sync,
    load(value) { saved=normalize(value); sync(); },
    start() { editing={...saved}; sync(); },
    cancel() { editing=null; sync(); },
    commit() { saved=normalize(editing ?? saved); editing=null; sync(); },
    snapshot() { return {...(editing ?? saved)}; },
  };
}
