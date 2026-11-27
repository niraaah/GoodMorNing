"""Convert SAM2 logits to an opaque cutout with subpixel boundary coverage."""
import numpy as np
from PIL import Image


def alpha_from_logits(logits, size):
    logits = np.asarray(logits, dtype=np.float32)
    if logits.ndim != 2 or not np.isfinite(logits).all():
        raise ValueError('분리 결과를 읽지 못했어요. 사진을 다시 선택해 주세요.')
    # SAM2's zero logit threshold decides foreground. Confidence is NOT opacity:
    # sigmoid(logits) leaks low-confidence background and washes out the object.
    # Threshold at 2x target resolution, then area-resample boundary coverage.
    # Solid foreground/background remain exactly 1/0; no whole-surface feathering.
    width, height = size
    up = np.asarray(Image.fromarray(logits).resize((width * 2, height * 2), Image.Resampling.BILINEAR))
    binary = Image.fromarray((up > 0).astype(np.uint8) * 255)
    return np.asarray(binary.resize(size, Image.Resampling.BOX), dtype=np.float64) / 255
