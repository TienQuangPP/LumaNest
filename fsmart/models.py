from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from .images import resized


class ModelUnavailable(RuntimeError):
    pass


def import_source(name: str, source: Path, package=False):
    spec = importlib.util.spec_from_file_location(name, source, submodule_search_locations=[str(source.parent)] if package else None)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def align_face(image: Image.Image, landmarks, size=112):
    """Least-squares similarity alignment to the standard 112px ArcFace template."""
    source = np.asarray(landmarks, dtype=np.float64)
    target = np.array([[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]]) * size / 112
    # Solve output-to-input mapping directly for Pillow's inverse affine sampler.
    design = np.zeros((10, 4))
    design[0::2, 0] = target[:, 0]
    design[0::2, 1] = -target[:, 1]
    design[0::2, 2] = 1
    design[1::2, 0] = target[:, 1]
    design[1::2, 1] = target[:, 0]
    design[1::2, 3] = 1
    a, b, tx, ty = np.linalg.lstsq(design, source.reshape(-1), rcond=None)[0]
    return image.transform((size, size), Image.Transform.AFFINE, (a, -b, tx, b, a, ty), Image.Resampling.BILINEAR)


class Models:
    def __init__(self, settings):
        self.settings = settings
        self.lock = threading.RLock()
        self.style_lock = threading.RLock()
        self.init_lock = threading.RLock()
        self._detector = None
        self._encoder = None
        self._torch = None
        self._styles = {}
        self._vgg = None
        self._key = None
        from .fast_style import FastStyle
        self.fast_style = FastStyle(self)

    def torch(self):
        with self.init_lock:
            return self._load_torch()

    def _load_torch(self):
        if self._torch is None:
            try:
                import torch
            except ImportError as exc:
                raise ModelUnavailable('Chưa cài PyTorch. Chạy hướng dẫn trong README.md.') from exc
            torch.set_num_threads(int(os.getenv('FSM_TORCH_THREADS', '4')))
            self._torch = torch
            device = self.settings.device
            self.device = torch.device(('cuda' if torch.cuda.is_available() else 'cpu') if device == 'auto' else device)
        return self._torch

    def require(self, path: Path):
        if not path.is_file():
            raise ModelUnavailable(f'Thiếu trọng số {path.name}. Chạy: python scripts/fetch_assets.py')
        return path

    @property
    def key(self):
        if self._key is None:
            if self.settings.face_model == 'adaface':
                path = self.require(self.settings.weights_dir / 'adaface/model.safetensors')
            else:
                path = self.require(self.settings.weights_dir / 'facenet/vggface2.pt')
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()[:16]
            self._key = f'{self.settings.face_model}:{digest}:align-v2-fullres-flip'
        return self._key

    def load_faces(self):
        if self._encoder is not None:
            return
        torch = self.torch()
        detector_dir = self.settings.weights_dir / 'facenet'
        package = import_source('fsm_facenet', self.require(detector_dir / '__init__.py'), package=True)
        self._detector = package.MTCNN(keep_all=True, select_largest=False, min_face_size=20, device=self.device).eval()
        if self.settings.face_model == 'adaface':
            from safetensors.torch import load_file
            directory = self.settings.weights_dir / 'adaface'
            source = import_source('fsm_adaface_ir50', self.require(directory / 'architecture.py'))
            encoder = source.IR_50((112, 112))
            state = load_file(str(self.require(directory / 'model.safetensors')))
            expected = set(encoder.state_dict())
            for prefix in ['model.net.', 'net.', 'model.', '']:
                candidate = {key[len(prefix):]: value for key, value in state.items() if key.startswith(prefix)}
                if set(candidate) == expected:
                    encoder.load_state_dict(candidate, strict=True)
                    break
            else:
                raise ModelUnavailable('Checkpoint AdaFace không khớp kiến trúc. Không dùng trọng số thay thế ngẫu nhiên.')
            self._encoder = encoder.to(self.device).eval().requires_grad_(False)
        else:
            encoder = package.InceptionResnetV1(pretrained=None)
            state = torch.load(self.require(detector_dir / 'vggface2.pt'), map_location='cpu', weights_only=True)
            # The upstream VGGFace2 checkpoint includes its unused classification head.
            encoder.logits = torch.nn.Linear(512, 8631)
            encoder.load_state_dict(state, strict=True)
            self._encoder = encoder.to(self.device).eval().requires_grad_(False)

    def analyze(self, image: Image.Image):
        with self.lock:
            self.load_faces()
            torch = self.torch()
            sample = resized(image, 2560)
            sx, sy = image.width / sample.width, image.height / sample.height
            boxes, probabilities, landmarks = self._detector.detect(sample, landmarks=True)
            if boxes is None:
                return []
            crops, metadata = [], []
            for box, confidence, points in zip(boxes, probabilities, landmarks):
                # Upstream MTCNN returns object arrays when the number of faces varies.
                points = np.asarray(points, dtype=np.float64)
                box = np.asarray(box, dtype=np.float64)
                confidence = float(confidence)
                if confidence < 0.90 or not np.isfinite(points).all():
                    continue
                if self.settings.face_model == 'adaface':
                    # Align from source pixels; detection resizing must not discard face detail.
                    crop = align_face(image, points * np.array([sx, sy]))
                    tensor = torch.from_numpy(np.array(crop, copy=True)).permute(2, 0, 1).float() / 127.5 - 1
                else:
                    from fsm_facenet.models.utils.detect_face import extract_face
                    tensor = (extract_face(image, box * np.array([sx, sy, sx, sy]), image_size=160, margin=0).float() - 127.5) / 128
                crops.append(tensor)
                metadata.append({'bbox': [round(max(0, float(box[0])) * sx), round(max(0, float(box[1])) * sy), round(min(sample.width, float(box[2])) * sx), round(min(sample.height, float(box[3])) * sy)], 'confidence': confidence})
            if not crops:
                return []
            with torch.inference_mode():
                embeddings = []
                for start in range(0, len(crops), 16):
                    batch = torch.stack(crops[start:start + 16]).to(self.device)
                    encoded = self._encoder(batch) + self._encoder(torch.flip(batch, [3]))
                    embeddings.extend(torch.nn.functional.normalize(encoded, dim=1).cpu().numpy())
            for row, embedding in zip(metadata, embeddings):
                row['embedding'] = embedding.tolist()
            return metadata

    def load_style(self, style):
        torch = self.torch()
        if style not in {'candy', 'mosaic', 'rain_princess', 'udnie'}:
            raise ValueError('Phong cách không hợp lệ.')
        if style not in self._styles:
            directory = self.settings.weights_dir / 'style'
            source = import_source('fsm_transformer_net', self.require(directory / 'architecture.py'))
            network = source.TransformerNet()
            state = torch.load(self.require(directory / f'{style}.pth'), map_location='cpu', weights_only=True)
            state = {key: value for key, value in state.items() if not re.search(r'in\d+\.running_(mean|var)$', key)}
            network.load_state_dict(state, strict=True)
            self._styles[style] = network.to(self.device).eval().requires_grad_(False)
        return self._styles[style]

    def preset(self, image: Image.Image, style: str, strength: float, progress, profile='fast'):
        with self.style_lock:
            return self.fast_style.render(image, style, strength, progress, profile)

    def custom(self, image: Image.Image, style: Image.Image, strength: float, steps: int, progress):
        """Colour transfer then Gatys et al. style transfer: ReLU features, L-BFGS, coarse-to-fine (half size, then 512 px).

        strength sets how much of the painting's palette is taken and the style weight (0.05 keeps the photo,
        1 lets the painting dominate); steps is the L-BFGS iteration budget split 40/60 between the two scales.
        """
        with self.style_lock:
            torch = self.torch()
            if self._vgg is None:
                from torchvision.models import vgg19
                state = torch.load(self.require(self.settings.weights_dir / 'style/vgg19-dcbb9e9d.pth'), map_location='cpu', weights_only=True)
                network = vgg19(weights=None)
                network.load_state_dict(state)
                self._vgg = network.features[:30].to(self.device).eval().requires_grad_(False)
            side = 512
            content = resized(image, side)
            mix = min(1., max(.05, strength))
            # Take the painting's palette first (mean and covariance of RGB), so each painting gives its own colours;
            # the optimisation below then adds its brushwork and texture.
            painted = _match_colours(np.asarray(content, np.float32) / 255, np.asarray(resized(style, 256), np.float32) / 255)
            base = Image.fromarray((np.clip((1 - mix) * np.asarray(content, np.float32) / 255 + mix * painted, 0, 1) * 255).astype(np.uint8))
            def tensor(pil):
                return (torch.from_numpy(np.array(pil, copy=True)).permute(2, 0, 1).float().unsqueeze(0) / 255).contiguous().to(self.device)
            mean = torch.tensor([.485, .456, .406], device=self.device).view(1, 3, 1, 1)
            std = torch.tensor([.229, .224, .225], device=self.device).view(1, 3, 1, 1)
            style_layers = (1, 6, 11, 20, 29)   # relu1_1 … relu5_1
            content_layer = 22                  # relu4_2
            def features(x):
                out = {}
                x = (x - mean) / std
                for index, layer in enumerate(self._vgg):
                    x = layer(x)
                    if index in style_layers or index == content_layer:
                        out[index] = x
                return out
            def gram(x):
                _, channels, height, width = x.shape
                flat = x.reshape(channels, height * width)
                return flat @ flat.t() / (height * width)
            style_weight = 10 ** (3 + 3 * min(1., max(.05, strength)))   # 0.5 → 3e4, 0.8 → 2.5e5, 1 → 1e6
            budget = max(20, steps)
            stages = [(side // 2, max(8, budget * 2 // 5)), (side, max(12, budget - budget * 2 // 5))]
            evaluations, total = [0], sum(iterations for _, iterations in stages) * 1.25
            output = None
            for scale, iterations in stages:
                target = tensor(resized(base, scale))
                with torch.no_grad():
                    content_features = features(target)[content_layer]
                    style_features = features(tensor(resized(style, max(scale, 384))))
                    style_grams = {index: gram(style_features[index]) for index in style_layers}
                output = target.clone() if output is None else torch.nn.functional.interpolate(output.detach(), size=target.shape[-2:], mode='bilinear', align_corners=False).contiguous()
                output.requires_grad_(True)
                optimizer = torch.optim.LBFGS([output], lr=1, max_iter=iterations, history_size=20, line_search_fn='strong_wolfe')
                def closure():
                    optimizer.zero_grad()
                    current = features(output)
                    content_loss = torch.nn.functional.mse_loss(current[content_layer], content_features)
                    style_loss = sum(torch.nn.functional.mse_loss(gram(current[index]), style_grams[index]) for index in style_layers)
                    smooth = (output[:, :, 1:] - output[:, :, :-1]).pow(2).mean() + (output[:, :, :, 1:] - output[:, :, :, :-1]).pow(2).mean()
                    loss = content_loss + style_weight * style_loss + .3 * smooth
                    loss.backward()
                    evaluations[0] += 1
                    if evaluations[0] % 10 == 0:
                        progress(.1 + .85 * min(1., evaluations[0] / total), f'Đang vẽ theo tranh mẫu · bước {evaluations[0]} · 1 ảnh')
                    return loss
                optimizer.step(closure)
                with torch.no_grad():
                    output.clamp_(0, 1)
            array = output.detach()[0].clamp(0, 1).permute(1, 2, 0).cpu().numpy()
            return Image.fromarray((array * 255).astype(np.uint8)).resize(content.size)

    def status(self):
        directory = self.settings.weights_dir
        return {**self.fast_style.status(), 'face_model': self.settings.face_model, 'face_ready': all((directory / path).is_file() for path in ['facenet/data/pnet.pt', 'facenet/data/rnet.pt', 'facenet/data/onet.pt', 'adaface/model.safetensors' if self.settings.face_model == 'adaface' else 'facenet/vggface2.pt']), 'presets_ready': all((directory / f'style/{name}.pth').is_file() for name in ['candy', 'mosaic', 'rain_princess', 'udnie']), 'custom_ready': (directory / 'style/vgg19-dcbb9e9d.pth').is_file(), 'device': str(getattr(self, 'device', self.settings.device))}


def _match_colours(content, style):
    """Linear colour transfer: map content RGB mean/covariance onto the painting's (both float arrays in 0..1)."""
    pixels, reference = content.reshape(-1, 3).astype(np.float64), style.reshape(-1, 3).astype(np.float64)
    mean_c, mean_s = pixels.mean(0), reference.mean(0)
    cov_c = np.cov(pixels, rowvar=False) + np.eye(3) * 1e-4
    cov_s = np.cov(reference, rowvar=False) + np.eye(3) * 1e-4
    def root(matrix, power):
        values, vectors = np.linalg.eigh(matrix)
        return vectors @ np.diag(np.clip(values, 1e-8, None) ** power) @ vectors.T
    transform = root(cov_s, .5) @ root(cov_c, -.5)
    return np.clip((pixels - mean_c) @ transform.T + mean_s, 0, 1).reshape(content.shape).astype(np.float32)
