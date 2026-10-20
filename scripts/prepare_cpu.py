"""Compile and warm all trusted preset models on the local Intel/CPU backend."""
import os
import sys
import time
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fsmart.models import Models
from fsmart.config import Settings

if __name__ == '__main__':
    os.environ['FSM_STYLE_BACKEND'] = 'openvino'
    os.environ['FSM_DEVICE'] = 'cpu'
    models = Models(Settings())
    for style in ['candy', 'mosaic', 'rain_princess', 'udnie']:
        start = time.perf_counter()
        models.preset(Image.new('RGB', (512, 341), '#436777'), style, .8, lambda *args: None)
        print(style, round(time.perf_counter()-start, 3), 'seconds (compile + warmup)', flush=True)
