from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    root: Path = Path(__file__).resolve().parents[1]
    data_dir: Path | None = None
    weights_dir: Path | None = None
    face_model: str = 'adaface'
    device: str = 'auto'
    max_upload_bytes: int = 20 * 1024 * 1024
    max_image_pixels: int | None = None

    def __post_init__(self):
        self.data_dir = Path(self.data_dir or os.getenv('FSM_DATA_DIR', str(self.root / 'runtime'))).resolve()
        self.weights_dir = Path(self.weights_dir or os.getenv('FSM_WEIGHTS_DIR', str(self.root / 'weights'))).resolve()
        self.face_model = os.getenv('FSM_FACE_MODEL', self.face_model)
        self.device = os.getenv('FSM_DEVICE', self.device)
        if self.face_model not in {'adaface', 'facenet'}:
            raise ValueError('FSM_FACE_MODEL must be adaface or facenet')
        for folder in ['photos', 'originals', 'thumbs', 'queries', 'outputs', 'styles', 'exports', 'logs']:
            (self.data_dir / folder).mkdir(parents=True, exist_ok=True)
