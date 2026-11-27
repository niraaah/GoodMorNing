"""Small storage/navigation substitutions around the original diary UI."""
from pathlib import Path
from repair_diary import repair

def adapt(html):
    html = html.replace('    const product = productCatalog[key] ?? {', '''    const product = (item.goods && isWebUrl(item.url) ? {
      title: item.goods.title || item.name,
      note: item.goods.affiliate ? '쿠팡 파트너스 링크를 통해 구매하면 운영자가 일정액의 수수료를 제공받을 수 있습니다. 가격·옵션·배송비는 판매처에서 확인해 주세요.' : '내가 확인하고 연결한 굿즈예요.',
      facts: [['판매처', item.goods.source || '직접 연결']],
      links: [['연결한 상품', item.goods.source || '판매 페이지', item.url]],
    } : null) ?? productCatalog[key] ?? {''')
    reference = Path(__file__).resolve().parent.parent / 'server/reference'
    photos = (reference / 'diary_photos.js').read_text(encoding='utf-8')
    photo_css = (reference / 'diary_photos.css').read_text(encoding='utf-8')
    photo_css += '\n' + (reference / 'diary_permissions.css').read_text(encoding='utf-8')
    photo_css += '\n' + (reference / 'diary_controls.css').read_text(encoding='utf-8')
    html = html.replace('</head>', '<style>' + photo_css + '</style>\n</head>', 1)
    html = html.replace('const homeLayoutVersion = 3;', photos + '\nconst homeLayoutVersion = 3;', 1)
    html = html.replace("    caption.textContent = photo.caption ?? (index === storyIndex && !newDiaryPage ? story.title : '');\n    caption.title = caption.textContent;", "    renderPolaroidCaption(card, photo, index, blank);")
    html = html.replace("!photo.removed && (index === storyIndex || index >= stories.length) ? [index] : []", "!photo.removed && hasPolaroidImage(photo, index) && (index === storyIndex || index >= stories.length) ? [index] : []")
    html = html.replace("caption.addEventListener('input', () => { const photo = selected(); if (photo) { photo.caption = caption.value; renderDiary(); } });", "caption.addEventListener('input', () => { const photo = selected(); if (photo && hasPolaroidImage(photo, selectedDiaryPhoto)) { photo.caption = caption.value; renderDiary(); } });")
    html = html.replace('>사진 추가</button>', '>폴라로이드 추가</button>')
    html = html.replace('사진 메모 <input id="diary-caption-input"', '폴라로이드 아래 메모 <input id="diary-caption-input"')
    html = html.replace('placeholder="이 사진에 남길 말"', 'placeholder="사진 아래 흰 여백에 남길 말"')
    html = html.replace('        layout[index].file = file;', "        layout[index].file = file;\n        layout[index].caption ??= '';")
    html = html.replace('          base.file = file;', "          base.file = file;\n          base.caption ??= '';")
    html = html.replace('if (mountedBoard) {\n  const tiltButton', 'if (mountedBoard && !demo) {\n  const tiltButton', 1)
    motion = (Path(__file__).resolve().parent.parent / 'server/reference/diary_motion.js').read_text(encoding='utf-8')
    html = html.replace('const homeLayoutVersion = 3;', motion + '\nconst homeLayoutVersion = 3;', 1)
    html = html.replace('</head>', '<script src="./diary_bridge.js"></script>\n</head>')
    html = html.replace('async function readPost() {', '''async function readPost() {
  if (demo && !visitingDiary) return window.goodmorningBridge.readPost(postKey);''')
    html = html.replace('async function writePost(items, photo, diaryLayout) {', '''async function writePost(items, photo, diaryLayout) {
  if (demo && !visitingDiary) return window.goodmorningBridge.writePost(postKey, {items, photo, diaryLayout, diaryLayoutVersion});''')
    start = html.index('async function renderDiaryPages() {')
    tail = html.index('  diaryPages.replaceChildren();', start)
    html = html[:start] + '''async function renderDiaryPages() {
  if (!numberedDiary) return;
  const keys = await window.goodmorningBridge.pageKeys();
  let maxPage = 1;
  for (const key of keys) {
    if (typeof key === 'string' && /^page:\\d+$/.test(key)) maxPage = Math.max(maxPage, Number(key.slice(5)));
  }
''' + html[tail:]
    html = html.replace("function stickerLibrary(mode = 'readonly', asset) {", """function stickerLibrary(mode = 'readonly', asset) {
  if (demo && !visitingDiary && mode === 'readonly') return window.goodmorningBridge.stickers();""")
    html = html.replace('function addItem(asset) {', '''function addItem(asset) {
  if (!draft || saving) return;
  if (asset.backendAssetId && !asset.file) {
    const editing = draft, token = beginDiaryLoad();
    void window.goodmorningBridge.materialize(asset).then(loaded => {
      if (draft === editing && !saving) addItem(loaded);
    }).catch(error => { if (draft === editing) notice(error.message); }).finally(() => endDiaryLoad(token));
    return;
  }''')
    start = html.index("elements.publish.addEventListener('click', async () => {")
    end = html.index('\nfunction wireAssetPreview()', start)
    block = html[start:end]
    block = block.replace('  const photo = draftPhoto;\n', '  const photo = draftPhoto;\n  let stored = false;\n')
    block = block.replace('    await writePost(items, photo, draftDiary);', '    await writePost(items, photo, draftDiary);\n    stored = true;')
    block = block.replace("  } catch {\n    notice('이 브라우저에 저장하지 못했습니다. 현재 화면에서만 게시물이 유지됩니다.');", "  } catch (error) {\n    notice(error.message || '저장하지 못했어요. 편집 내용은 그대로 있으니 다시 게시해 주세요.');")
    block = block.replace('    published = items;', '    if (stored) {\n    published = items;')
    block = block.replace('    draft = null;', '    draft = null;\n    }')
    block = block.replace('    elements.edit.focus();', '    if (stored) elements.edit.focus();')
    html = html[:start] + block + html[end:]
    html = html.replace('}).catch(() => {}).finally(() => {', """}).catch(error => {
  if (demo && !visitingDiary) {
    window.goodmorningReadFailed = true;
    notice(error.message || '다이어리를 불러오지 못했어요. 다시 열어 주세요.');
  }
}).finally(() => {""")
    html = html.replace('  elements.edit.disabled = false;\n  if (newDiaryPage && !pageExists) elements.edit.click();', '''  elements.edit.disabled = Boolean(window.goodmorningReadFailed);
  if (newDiaryPage && !pageExists && !window.goodmorningReadFailed) elements.edit.click();
  if (demo && !visitingDiary && !window.goodmorningReadFailed) window.goodmorningBridge.markReady();''')
    # App-owned controls; the pinned prototype is unchanged.
    import re
    def icon_button(match):
        attrs=match.group(1).replace('class="button"','class="button gm-icon-button"')
        return '<button'+attrs+' aria-label="닫기" title="닫기"><span class="gm-material" data-icon="close" aria-hidden="true"></span></button>'
    html=re.sub(r'<button([^>]*?)>닫기</button>',icon_button,html)
    html=html.replace('<button class="button" id="edit" type="button">편집</button>', '<button class="button gm-icon-button" id="edit" type="button" aria-label="다이어리 편집" title="편집"><span class="gm-material" data-icon="edit" aria-hidden="true"></span></button>')
    return repair(html)
