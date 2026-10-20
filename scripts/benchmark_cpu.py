"""Measure real style work, without output-cache hits or changing the user's album."""
import argparse
import io
import json
import os
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fsmart.config import Settings
from fsmart.models import Models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', type=Path, default=ROOT/'runtime/photos')
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/performance/after.json')
    args = parser.parse_args()
    paths = sorted(args.images.glob('*.jpg'))[:args.limit]
    if not paths:
        parser.error('Need local JPEG inputs in --images')
    os.environ['FSM_DEVICE'] = 'cpu'
    os.environ['FSM_TORCH_THREADS'] = '4'
    os.environ['FSM_STYLE_THREADS'] = '4'
    engines = {}
    report = {'processor': platform.processor(), 'device': 'cpu', 'threads_per_engine': 4,
              'style': 'mosaic', 'photos': len(paths), 'rounds': args.rounds,
              'includes': 'JPEG decode + resize + inference + blend + PNG encode; no output cache',
              'cold_seconds': {}, 'runs': {}}
    for backend in ['torch', 'openvino']:
        os.environ['FSM_STYLE_BACKEND'] = backend
        start = time.perf_counter()
        engine = Models(Settings(data_dir=ROOT/'artifacts/performance/isolated-runtime'))
        engine.preset(Image.new('RGB', (256, 256), '#436777'), 'mosaic', .65, lambda *a: None)
        report['cold_seconds'][backend] = time.perf_counter()-start
        engines[backend] = engine
    errors = []
    for profile in ['fast', 'quality']:
        for compression in [6, 1]:
            if profile == 'quality' and compression == 6:
                continue
            timings = {key: [] for key in engines}
            for round_index in range(args.rounds):
                for path in paths:
                    outputs = {}
                    # Alternate order to reduce thermal/order bias.
                    for backend in (list(engines) if round_index % 2 == 0 else list(reversed(engines))):
                        start = time.perf_counter()
                        with Image.open(path) as source:
                            image = source.convert('RGB')
                        output = engines[backend].preset(image, 'mosaic', .65, lambda *a: None, profile=profile)
                        buffer = io.BytesIO()
                        output.save(buffer, 'PNG', compress_level=compression)
                        elapsed = time.perf_counter()-start
                        timings[backend].append(elapsed)
                        outputs[backend] = np.asarray(output, dtype=np.float32)
                    errors.append(float(np.abs(outputs['torch']-outputs['openvino']).mean()))
            for backend, values in timings.items():
                key = f'{backend}-{profile}-png{compression}'
                report['runs'][key] = {'seconds': values, 'median_seconds': statistics.median(values),
                                       'total_seconds': sum(values), 'images_per_second': len(values)/sum(values)}
                print(json.dumps({key: report['runs'][key]}), flush=True)
    import openvino as ov
    report['versions'] = {'openvino': ov.__version__, 'torch': engines['torch'].torch().__version__}
    report['max_image_mean_absolute_error_0_255'] = max(errors)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(args.output, flush=True)


if __name__ == '__main__':
    main()
