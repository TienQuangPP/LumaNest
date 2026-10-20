"""One-pass style inference; original PyTorch weights stay authoritative."""
from __future__ import annotations

import hashlib
import importlib.util
import importlib.metadata
import logging
import os
from collections import OrderedDict

import numpy as np
from PIL import Image

from .images import resized

PROFILES = {'fast': 512, 'balanced': 768, 'quality': 1024}
log = logging.getLogger('fsmart')


class FastStyle:
    def __init__(self, models):
        self.models = models
        self.compiled = OrderedDict()
        self.backend = None
        self.fallback_reason = None
        self.disabled = False
        self.fingerprints = {}
        self.preference = os.getenv('FSM_STYLE_BACKEND', 'auto')
        if self.preference not in {'auto', 'torch', 'openvino'}:
            raise ValueError('FSM_STYLE_BACKEND must be auto, torch or openvino')

    def fingerprint(self, style):
        if style in self.fingerprints:
            return self.fingerprints[style]
        directory = self.models.settings.weights_dir / 'style'
        digest = hashlib.sha256(('fast-style-v2-rgb255-pad4-f32-pillow-'+importlib.metadata.version('pillow')).encode())
        for path in [directory/'architecture.py', directory/f'{style}.pth']:
            with self.models.require(path).open('rb') as source:
                while block := source.read(1024*1024):
                    digest.update(block)
        self.fingerprints[style] = digest.hexdigest()[:24]
        return self.fingerprints[style]

    def _openvino(self, style, network):
        import openvino as ov
        key = (style, self.fingerprint(style))
        if key in self.compiled:
            self.compiled.move_to_end(key)
            return self.compiled[key]
        directory = self.models.settings.weights_dir/'optimized'/ov.__version__/key[1]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory/f'{style}.xml'
        if not path.is_file():
            torch = self.models.torch()
            converted = ov.convert_model(network, example_input=torch.zeros(1, 3, 128, 128), input=[ov.PartialShape([1, 3, -1, -1])])
            temporary = directory/f'{style}.tmp.xml'
            ov.save_model(converted, temporary, compress_to_fp16=False)
            temporary.with_suffix('.bin').replace(path.with_suffix('.bin'))
            temporary.replace(path)
        model = ov.Core().compile_model(path, 'CPU', {
            'PERFORMANCE_HINT': 'LATENCY', 'NUM_STREAMS': 1,
            'INFERENCE_NUM_THREADS': int(os.getenv('FSM_STYLE_THREADS', '4')),
            'INFERENCE_PRECISION_HINT': 'f32', 'CACHE_DIR': str(directory/'cache'),
        })
        self.compiled[key] = model
        while len(self.compiled) > 2:
            self.compiled.popitem(last=False)
        return model

    def render(self, image, style, strength, progress, profile='fast'):
        if profile not in PROFILES:
            raise ValueError('Chế độ tốc độ không hợp lệ.')
        torch = self.models.torch()
        network = self.models.load_style(style)
        content = resized(image, PROFILES[profile])
        pixels = np.asarray(content, dtype=np.float32).transpose(2, 0, 1)[None]
        pixels = np.pad(pixels, ((0, 0), (0, 0), (0, (-content.height) % 4), (0, (-content.width) % 4)), mode='reflect')
        use_ov = (self.preference != 'torch' and self.models.device.type == 'cpu'
                  and not self.disabled and importlib.util.find_spec('openvino') is not None)
        if self.preference == 'openvino' and not use_ov:
            raise RuntimeError('OpenVINO CPU chưa khả dụng. Cài requirements-cpu.txt hoặc chọn FSM_STYLE_BACKEND=auto.')
        output = None
        if use_ov:
            try:
                progress(.15, 'Đang chuẩn bị OpenVINO CPU (lần đầu cần biên dịch model)')
                compiled = self._openvino(style, network)
                progress(.35, f'Đang chuyển style · OpenVINO CPU · {PROFILES[profile]} px')
                output = compiled(pixels)[0][0]
                self.backend = 'openvino-cpu-f32'
            except Exception as exc:
                if self.preference == 'openvino':
                    raise
                self.disabled = True
                self.fallback_reason = type(exc).__name__
                log.exception('OpenVINO unavailable; using PyTorch for this session')
        if output is None:
            progress(.35, f'Đang chuyển style · PyTorch · {PROFILES[profile]} px')
            x = torch.from_numpy(pixels).to(self.models.device)
            with torch.inference_mode():
                output = network(x)[0].cpu().numpy()
            self.backend = f'pytorch-{self.models.device.type}'
        array = np.clip(output[:, :content.height, :content.width], 0, 255).transpose(1, 2, 0).astype(np.uint8)
        return Image.blend(content, Image.fromarray(array), strength)

    def status(self):
        return {'style_backend': self.backend or 'chưa nạp', 'style_backend_preference': self.preference,
                'openvino_installed': importlib.util.find_spec('openvino') is not None,
                'style_backend_fallback': self.fallback_reason, 'style_profiles': PROFILES}
