"""Local ONNX segmentation. No image is sent to an external service."""
import ctypes as c
import os
import sys
import uuid
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image
from .segmentation import alpha_from_logits


def adapters():
    if sys.platform != 'win32':
        return []
    class Desc(c.Structure):
        _fields_ = [('description', c.c_wchar * 128), ('vendor', c.c_uint), ('device', c.c_uint),
                    ('subsys', c.c_uint), ('revision', c.c_uint), ('vram', c.c_size_t),
                    ('system', c.c_size_t), ('shared', c.c_size_t), ('luid', c.c_ulonglong), ('flags', c.c_uint)]
    def method(obj, index, restype, *argtypes):
        table = c.cast(obj, c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(restype, c.c_void_p, *argtypes)(table[index])
    factory = c.c_void_p()
    iid = (c.c_byte * 16).from_buffer_copy(uuid.UUID('770aae78-f26f-4dba-a829-253c83d1b387').bytes_le)
    create = c.WinDLL('dxgi').CreateDXGIFactory1
    create.argtypes = [c.c_void_p, c.POINTER(c.c_void_p)]
    create.restype = c.c_long
    if create(c.byref(iid), c.byref(factory)) != 0:
        return []
    found = []
    try:
        for index in range(16):
            adapter = c.c_void_p()
            if method(factory, 12, c.c_long, c.c_uint, c.POINTER(c.c_void_p))(factory, index, c.byref(adapter)) != 0:
                break
            try:
                desc = Desc()
                if method(adapter, 10, c.c_long, c.POINTER(Desc))(adapter, c.byref(desc)) == 0:
                    found.append({'id': index, 'name': desc.description, 'vram_bytes': desc.vram, 'software': bool(desc.flags & 2)})
            finally:
                method(adapter, 2, c.c_ulong)(adapter)
    finally:
        method(factory, 2, c.c_ulong)(factory)
    return found


class Segmenter:
    def __init__(self, model: Path):
        self.model = model
        self.session = None
        self.decoder = None
        self.error = None
        try:
            self.devices = adapters()
        except Exception as error:
            self.devices = []
            self.error = f'GPU enumeration: {error}'
        hardware = [a for a in self.devices if not a['software']]
        self.device = max(hardware, key=lambda a: a['vram_bytes'], default={'id': 0, 'name': 'Default DirectX adapter'})
        self.device_id = int(os.getenv('GOODMORNING_DML_DEVICE_ID', self.device['id']))

    def status(self):
        available = ort.get_available_providers()
        return {'available_providers': available, 'providers': self.session.get_providers() if self.session else [],
                'adapter': self.device, 'device_id': self.device_id, 'model_ready': all((self.model / name).is_file() for name in ('vision_encoder.onnx', 'vision_encoder.onnx_data', 'prompt_encoder_mask_decoder.onnx', 'prompt_encoder_mask_decoder.onnx_data')),
                'error': self.error, 'initialized': self.session is not None}

    def load(self, profile_prefix=None):
        if self.session:
            return self.session
        if not self.status()['model_ready']:
            raise RuntimeError('SAM 2 모델이 없습니다. 모델 설치를 먼저 완료해 주세요.')
        options = ort.SessionOptions()
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        if profile_prefix:
            options.enable_profiling = True
            options.profile_file_prefix = str(profile_prefix)
        providers = ['CPUExecutionProvider']
        if 'DmlExecutionProvider' in ort.get_available_providers():
            providers.insert(0, ('DmlExecutionProvider', {'device_id': self.device_id}))
        try:
            self.session = ort.InferenceSession(str(self.model / 'vision_encoder.onnx'), sess_options=options, providers=providers)
            self.decoder = ort.InferenceSession(str(self.model / 'prompt_encoder_mask_decoder.onnx'), sess_options=options, providers=providers)
        except Exception as error:
            self.error = str(error)
            raise RuntimeError('로컬 GPU 초기화에 실패했습니다. 서버 로그를 확인해 주세요.') from error
        return self.session

    def mask(self, image: Image.Image, box=None):
        session = self.load()
        image = image.convert('RGB')
        inp = np.asarray(image.resize((1024, 1024), Image.Resampling.BILINEAR), dtype=np.float32) / 255
        inp = (inp - np.array([.485, .456, .406], np.float32)) / np.array([.229, .224, .225], np.float32)
        embeddings = session.run(None, {'pixel_values': inp.transpose(2, 0, 1)[None].copy()})
        feed = {o.name: value for o, value in zip(session.get_outputs(), embeddings)}
        box = box or [.05, .05, .95, .95]
        feed.update({'input_points': np.zeros((1, 1, 1, 2), np.float32),
                     'input_labels': np.full((1, 1, 1), -1, np.int64),
                     'input_boxes': np.array([[box]], np.float32) * 1024})
        scores, masks, _ = self.decoder.run(None, feed)
        pred = masks[0, 0, int(np.argmax(scores[0, 0]))]
        return alpha_from_logits(pred, image.size)
