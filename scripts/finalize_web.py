"""Give executable bundles content-based URLs to avoid mixed cached releases."""
import hashlib
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parent.parent / 'app/build/web'
main = (root / 'main.dart.js').read_bytes()
release = hashlib.sha256(main)
for name in ('reference/index.html', 'reference/diary_bridge.js', 'scene/scene.js', 'auth/callback.js'):
    source = root / name
    if source.exists():
        release.update(source.read_bytes())
revision = release.hexdigest()[:16]
main_name = f'main.{revision}.dart.js'
(root / main_name).write_bytes(main)
bootstrap = (root / 'flutter_bootstrap.js').read_text(encoding='utf-8')
bootstrap = bootstrap.replace('"main.dart.js"', json.dumps(main_name))
bootstrap_name = f'flutter_bootstrap.{hashlib.sha256(bootstrap.encode()).hexdigest()[:16]}.js'
(root / bootstrap_name).write_text(bootstrap, encoding='utf-8')
index = (root / 'index.html').read_text(encoding='utf-8')
index = index.replace("'flutter_bootstrap.js'", repr(bootstrap_name))
index = index.replace('<html lang="ko">', f'<html lang="ko" data-build="{revision}">')
(root / 'index.html').write_text(index, encoding='utf-8')
(root / 'build-info.json').write_text(json.dumps({'revision': revision, 'commit': os.getenv('GITHUB_SHA', 'local')}), encoding='utf-8')
bridge = root / 'reference/diary_bridge.js'
if bridge.exists():
    bridge_name = f'diary_bridge.{hashlib.sha256(bridge.read_bytes()).hexdigest()[:16]}.js'
    (bridge.parent / bridge_name).write_bytes(bridge.read_bytes())
    reference = bridge.parent / 'index.html'
    reference.write_text(reference.read_text(encoding='utf-8').replace('./diary_bridge.js', './'+bridge_name), encoding='utf-8')
callback = root / 'auth/callback.js'
if callback.exists():
    callback_name = f'callback.{hashlib.sha256(callback.read_bytes()).hexdigest()[:16]}.js'
    (callback.parent / callback_name).write_bytes(callback.read_bytes())
    for provider in ('google', 'kakao', 'naver'):
        page = callback.parent / (provider+'.html')
        page.write_text(page.read_text(encoding='utf-8').replace('src="callback.js"', f'src="{callback_name}"'), encoding='utf-8')
print(f'Published immutable JavaScript bundles: {revision}')
