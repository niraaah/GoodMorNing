import io
import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from PIL import Image, ImageOps

from .vendor import sticker_geometry as geometry
from .gaussian import build_gaussian_sticker
from .process import Recorder


def normalized_image(raw: bytes):
    try:
        image = Image.open(io.BytesIO(raw))
        if image.width * image.height > 24_000_000:
            raise ValueError('사진은 2,400만 화소 이하로 올려 주세요.')
        image = ImageOps.exif_transpose(image).convert('RGBA')
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        if min(image.size) < 32:
            raise ValueError('사진의 가로·세로는 32px 이상이어야 합니다.')
        return image
    except (OSError, Image.DecompressionBombError) as error:
        raise ValueError('읽을 수 없는 사진입니다. PNG, JPEG 또는 WebP 파일을 선택해 주세요.') from error


def generate(image_path, output, segmenter, options, progress, estimator=None):
    """SAM 2 cutout -> YOLO depth of the cutout -> Gaussian relief -> glossy sticker.

    Each stage writes an image to process/ as it ends (see server/process.py).
    Without the depth model the relief falls back to the silhouette distance.
    """
    output = Path(output)
    image = Image.open(image_path).convert('RGBA')
    image.thumbnail((640, 640), Image.Resampling.LANCZOS)
    rgba = np.asarray(image, dtype=np.float64) / 255
    record = Recorder(output)
    record.photo(image, options.get('box') if options['background'] != 'keep' else None)
    seconds, clock = {}, time.perf_counter()

    def lap(name):
        nonlocal clock
        now = time.perf_counter()
        seconds[name] = round(now - clock, 3)
        clock = now

    progress(15, '사진에서 굿즈를 분리하고 있어요')
    alpha = rgba[..., 3]
    segmentation = 'image-alpha'
    if options['background'] == 'keep':
        alpha = np.ones(alpha.shape)
        segmentation = 'full-photo'
    elif np.all(alpha > .99):
        alpha = segmenter.mask(image, options.get('box'))
        segmentation = 'sam2.1-' + ('directml' if 'DmlExecutionProvider' in segmenter.session.get_providers() else 'cpu')
    if np.count_nonzero(alpha > .5) < 80:
        raise ValueError('분리된 굿즈가 너무 작아요. 다른 사진이나 ‘배경 유지’를 선택해 주세요.')
    record.segment(image, alpha)
    lap('segment')
    depth = None
    depth_source = 'silhouette-distance'
    if estimator is not None and estimator.ready():
        progress(35, '굿즈의 깊이를 추정하고 있어요')
        # Learned single-photo depth in meters: nearer parts of the goods rise higher.
        depth = estimator.depth(image)
        depth_source = 'yolo26n-depth-' + estimator.provider()
        record.depth(depth, alpha)
        lap('depth')
    progress(50, '흰 테두리와 볼록한 표면을 만들고 있어요')
    L = max(image.size)
    pad = round(L * .13)
    alpha = np.pad(alpha, pad)
    color = np.pad(rgba[..., :3], ((pad, pad), (pad, pad), (0, 0)))
    if depth is None:
        # Geometric silhouette distance makes a smooth dome; it is not learned 3D depth.
        distance = cv2.distanceTransform((alpha > .5).astype('uint8'), cv2.DIST_L2, 5)
        depth = 1.0 - distance / max(float(distance.max()), 1.0)
    else:
        depth = np.pad(depth, pad, mode='edge')
    # Learned depth gets the relief of the SAM 3D sample stickers (goodmorning-3d): 5% of the
    # goods' own long side, not of the whole photo, so a small object is not over-inflated.
    relief = .025
    if depth_source != 'silhouette-distance':
        ys, xs = np.nonzero(alpha > .5)
        relief = .05 * max(np.ptp(ys) + 1, np.ptp(xs) + 1) / L
    args = SimpleNamespace(border=.035, smooth=.05, round=.04, base=.03, relief=relief, fade=.06)
    maps = geometry.crop_to(geometry.make_maps(color * alpha[..., None], alpha, depth, L, args), 8)
    if not np.all(np.isfinite(maps['height'])):
        raise ValueError('표면을 계산하지 못했습니다. 다른 사진을 선택해 주세요.')
    gaussian_info = build_gaussian_sticker(maps, output)
    record.height(maps)
    lap('relief')
    texture = np.clip(np.dstack([maps['color'], maps['alpha']]) * 255, 0, 255).round().astype('uint8')
    png = io.BytesIO()
    Image.fromarray(texture).save(png, 'PNG')
    mesh = geometry.build_mesh(maps, 4, .06)
    progress(80, '유광 스티커를 에셋함에 저장하고 있어요')
    geometry.write_glb(output / 'sticker.glb', mesh, png.getvalue(), options['name'], .45, .04)
    thumb = Image.fromarray(texture)
    thumb.thumbnail((420, 420), Image.Resampling.LANCZOS)
    thumb.save(output / 'sticker.png')
    record.sticker(maps)
    record.compose()
    lap('sticker')
    info = {'engine': 'sam2-gaussian', 'reconstruction': 'single-photo-gaussian-relief', 'segmentation': segmentation,
            'depth': depth_source, 'process': {'image': 'process.jpg', 'stages': record.stages, 'seconds': seconds},
            'gaussians': gaussian_info,
            'vertices': len(mesh['pos']), 'triangles': len(mesh['idx']) // 3, 'max_height_mm': mesh['max_height_mm'],
            'size_m': mesh['size_m'], 'source': 'goodmorning-3d/pipeline/sticker.py'}
    (output / 'sticker.json').write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    return info


