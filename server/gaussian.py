"""Smooth an existing relief map and export auxiliary Gaussian files.

This module does not infer geometry from a photo or train Gaussian Splatting.
The caller has already built the height field from YOLO depth (or an explicitly
reported silhouette fallback). We filter color/height, export PLY/SPLAT, and the
caller writes the GLB mesh used by the diary from the same processed maps.
"""
from pathlib import Path
import numpy as np
from scipy.ndimage import gaussian_filter


def build_gaussian_sticker(maps, output: Path):
    # Smooth the existing texture and height, weighted by the cutout; no depth inference.
    cut = maps['alpha'].astype(np.float64)
    mass = gaussian_filter(cut, .7)
    for key in ('color', 'height'):
        array = maps[key]
        weight = cut[..., None] if array.ndim == 3 else cut
        norm = mass[..., None] if array.ndim == 3 else mass
        sigma = (.7, .7, 0) if array.ndim == 3 else .7
        maps[key] = gaussian_filter(array * weight, sigma) / np.maximum(norm, 1e-8)
    h, w = cut.shape
    ys, xs = np.mgrid[0:h:2, 0:w:2]
    keep = cut[ys, xs] > .1
    ys, xs = ys[keep], xs[keep]
    scale = .06 / max(h, w)
    position = np.stack([(xs - w/2)*scale, -(ys-h/2)*scale, maps['height'][ys,xs]*scale], 1)
    colors = maps['color'][ys, xs].clip(0, 1)
    opacity = cut[ys,xs].clip(.001, .999)
    scales = np.tile([scale*1.1, scale*1.1, scale*.35], (len(xs), 1))
    rotation = np.tile([1,0,0,0], (len(xs), 1))
    names = ['x','y','z','nx','ny','nz','f_dc_0','f_dc_1','f_dc_2','opacity','scale_0','scale_1','scale_2','rot_0','rot_1','rot_2','rot_3']
    values = np.concatenate([position, np.zeros_like(position), (colors-.5)/.28209479177387814,
                             np.log(opacity/(1-opacity))[:,None], np.log(scales), rotation], 1).astype('<f4')
    header = 'ply\nformat binary_little_endian 1.0\ncomment goodmorning single-photo Gaussian relief\n'
    header += f'element vertex {len(xs)}\n' + ''.join(f'property float {n}\n' for n in names) + 'end_header\n'
    (output / 'sticker.ply').write_bytes(header.encode('ascii') + values.tobytes())
    packed = np.zeros(len(xs), dtype=[('position','<f4',3),('scale','<f4',3),('color','u1',4),('rotation','u1',4)])
    packed['position'] = position
    packed['scale'] = scales
    packed['color'] = np.column_stack([colors, opacity])*255
    packed['rotation'] = [255,128,128,128]
    (output / 'sticker.splat').write_bytes(packed.tobytes())
    return {'count': len(xs), 'method': 'single-view parametric relief', 'ply': 'sticker.ply', 'splat': 'sticker.splat'}
