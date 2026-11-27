"""Single-photo depth with Ultralytics YOLO26n-depth (ONNX, AGPL-3.0).

The model takes the photo stretched to 768x768 RGB and returns a depth map in
meters; smaller values are nearer the camera. Runs on DirectML when available,
otherwise on the CPU, like the SAM 2 segmenter.
"""
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

SIZE = 768
MODEL = 'yolo26n-depth.onnx'


class DepthEstimator:
    def __init__(self, folder: Path, device_id: int = 0):
        self.path = Path(folder) / MODEL
        self.device_id = device_id
        self.session = None

    def ready(self):
        return self.path.is_file()

    def provider(self):
        return 'directml' if self.session and 'DmlExecutionProvider' in self.session.get_providers() else 'cpu'

    def load(self):
        if self.session is None:
            providers = ['CPUExecutionProvider']
            if 'DmlExecutionProvider' in ort.get_available_providers():
                providers.insert(0, ('DmlExecutionProvider', {'device_id': self.device_id}))
            options = ort.SessionOptions()
            options.enable_mem_pattern = False
            self.session = ort.InferenceSession(str(self.path), sess_options=options, providers=providers)
        return self.session

    def depth(self, image: Image.Image) -> np.ndarray:
        """Depth in meters at the photo's own size (H, W)."""
        session = self.load()
        rgb = image.convert('RGB')
        pixels = np.asarray(rgb.resize((SIZE, SIZE), Image.Resampling.BILINEAR), dtype=np.float32) / 255
        output = session.run(None, {session.get_inputs()[0].name: pixels.transpose(2, 0, 1)[None].copy()})[0]
        result = Image.fromarray(output[0, 0].astype(np.float32)).resize(rgb.size, Image.Resampling.BILINEAR)
        depth = np.asarray(result, dtype=np.float64)
        if not np.all(np.isfinite(depth)):
            raise ValueError('깊이를 추정하지 못했어요. 다른 사진을 선택해 주세요.')
        return depth
