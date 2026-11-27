"""Checked substitutions for the pinned prototype's editing defects."""
from pathlib import Path


def repair(html):
    def replace(old, new):
        nonlocal html
        if html.count(old) != 1:
            raise ValueError('Pinned diary source changed; review editing substitution.')
        html = html.replace(old, new, 1)

    helper = (Path(__file__).resolve().parent.parent / 'server/reference/diary_editing.js').read_text(encoding='utf-8')
    reference = Path(__file__).resolve().parent.parent / 'server/reference'
    helper += '\n' + (reference / 'diary_object_tools.js').read_text(encoding='utf-8')
    helper += '\n' + (reference / 'diary_paper.js').read_text(encoding='utf-8')
    html = html.replace('</head>', '<style>' + (reference / 'diary_paper.css').read_text(encoding='utf-8') + '</style>\n</head>', 1)
    html = html.replace('</head>', '<style>' + (reference / 'diary_object_tools.css').read_text(encoding='utf-8') + '</style>\n</head>', 1)
    replace('const homeLayoutVersion = 3;', helper + '\nconst homeLayoutVersion = 3;')
    replace('color-mix(in srgb, var(--paper, #fdf8ed) 85%, #f8edd7);',
            'color-mix(in srgb, var(--user-paper, var(--paper, #fdf8ed)) 85%, #f8edd7);')
    replace('  pageExists = Boolean(post);', '  pageExists = Boolean(post);\n  diaryPaperEditor?.load(post?.paperStyle);')
    replace('    draftDiary = diaryPhotos.map(photo => ({ ...photo }));',
            '    draftDiary = diaryPhotos.map(photo => ({ ...photo }));\n    diaryPaperEditor?.start();')
    replace("elements.cancel.addEventListener('click', () => {\n  notice();",
            "elements.cancel.addEventListener('click', () => {\n  diaryPaperEditor?.cancel();\n  notice();")
    replace('    if (draftDiary) diaryPhotos = draftDiary;',
            '    if (draftDiary) diaryPhotos = draftDiary;\n    diaryPaperEditor?.commit();')
    replace('{items, photo, diaryLayout, diaryLayoutVersion});',
            '{items, photo, diaryLayout, diaryLayoutVersion, paperStyle: diaryPaperEditor?.snapshot()});')
    replace('home ? safeSlots[count] : [count ? 74 : 50, count ? 72 - (count - 1) * 46 : 50]',
            'home ? safeSlots[count] : demo ? diaryStickerPosition(count) : [count ? 74 : 50, count ? 72 - (count - 1) * 46 : 50]')
    replace('  const items = activeItems();\n  for (const [id, view] of views)',
            '  const items = activeItems();\n  keepDiaryItemsOnPage(items);\n  for (const [id, view] of views)')
    replace('  if (!editing) placement = null;', '  resetPlacement();\n  if (!editing) cancelDiaryLoads();')
    replace('  if (!editing) cancelDiaryLoads();', '  if (!editing) { cancelDiaryLoads(); diaryObjectEditor?.reset(); }')
    replace('function selectItem(id) {\n  selectedId = id;', 'function selectItem(id) {\n  selectedId = id;\n  diaryObjectEditor?.selectSticker(id);')
    replace("  view.node.style.setProperty('--placement-angle', `${item.rotation ?? 0}deg`);",
            "  view.node.style.setProperty('--placement-angle', `${item.rotation ?? 0}deg`);\n  diaryObjectEditor?.sync();")
    replace('function renderDiary() {\n  if (!demo) return;', 'function renderDiary() {\n  if (!demo) return;\n  diaryObjectEditor?.sync();\n  diaryPaperEditor?.sync();')
    replace('  const photos = draftDiary ?? diaryPhotos;\n  photos.forEach((photo, index) => {',
            '  const photos = draftDiary ?? diaryPhotos;\n  const photoLayers = new Map(diaryPhotoStack(photos).map(({index}, rank) => [index, rank + 1]));\n  photos.forEach((photo, index) => {')
    replace('    card.dataset.photoIndex = index;',
            "    card.dataset.photoIndex = index;\n    card.style.zIndex = String(photoLayers.get(index) ?? 0);")
    replace("  picker.addEventListener('change', () => {\n    selectedDiaryPhoto = Number(picker.value);\n    syncDiaryControls();\n    renderDiary();\n  });",
            "  picker.addEventListener('change', () => {\n    selectedDiaryPhoto = Number(picker.value);\n    syncDiaryControls();\n    renderDiary();\n    diaryObjectEditor?.selectPhoto(selectedDiaryPhoto);\n  });")
    replace('  diary.inert = layers.inert = !diaryOpen;', '  diary.inert = layers.inert = !diaryOpen;\n  if (!diaryOpen) diaryObjectEditor?.reset();')
    replace("  if (!draft || saving || event.button !== 0) return;\n  if (placement)",
            "  if (!draft || saving || event.button !== 0 || event.target.closest('input,textarea,button,a,select')) return;\n  if (placement)")
    replace('  post.setPointerCapture(event.pointerId);\n  rebasePlacement();',
            "  event.preventDefault();\n  post.setPointerCapture(event.pointerId);\n  placement.node.classList.add('dragging');\n  rebasePlacement();")
    replace('  const { item, view, node, origin, pose, points, width, height } = placement;',
            '  event.preventDefault();\n  const { item, view, node, origin, pose, points, width, height } = placement;')
    replace("    placement = null;\n    elements.post.classList.remove('safe-placement-blocked');",
            "    placement.node.classList.remove('dragging');\n    placement = null;\n    elements.post.classList.remove('safe-placement-blocked');")
    replace("post.addEventListener('lostpointercapture', endPlacement);",
            "post.addEventListener('lostpointercapture', endPlacement);\nwindow.addEventListener('blur', resetPlacement);\ndocument.addEventListener('visibilitychange', () => { if (document.hidden) resetPlacement(); });\npost.addEventListener('dragstart', event => { if (draft) event.preventDefault(); });")
    start = html.index('  function choosePhoto(index) {')
    end = html.index('\n\nfunction setProductPhoto', start)
    html = html[:start] + '  wireDiaryPhotoUpload(postInput);\n}\n' + html[end:]
    replace("elements.publish.addEventListener('click', async () => {\n  if (saving) return;",
            "elements.publish.addEventListener('click', async () => {\n  if (saving || !draft) return;\n  if (diaryObjectEditor && !diaryObjectEditor.canPublish()) return;\n  if (diaryLoads.size) { notice('사진과 스티커를 불러오는 중이에요. 잠시 뒤 게시해 주세요.'); return; }\n  resetPlacement();")
    return html
