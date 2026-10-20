"""Run the real face retrieval pipeline on a manually labeled held-out manifest."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from PIL import Image, ImageOps
from fsmart.config import Settings
from fsmart.evaluation import retrieval_metrics
from fsmart.models import Models


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--threshold', type=float, default=.4, help='Choose on validation before independent test')
    parser.add_argument('--k', type=int, default=20)
    parser.add_argument('--output', type=Path, default=Path('artifacts/benchmark'))
    args = parser.parse_args()
    if not -1 <= args.threshold <= 1 or args.k < 1:
        parser.error('threshold must be in [-1,1] and k must be positive')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    directory = args.manifest.resolve().parent
    models = Models(Settings())
    models.load_faces()
    def analyze(path):
        with Image.open(directory / path) as source:
            return models.analyze(ImageOps.exif_transpose(source).convert('RGB'))
    gallery, errors = [], []
    ids = [item['id'] for item in manifest['gallery']]
    if len(set(ids)) != len(ids):
        raise ValueError('Gallery photo IDs must be unique')
    started = time.perf_counter()
    for item in manifest['gallery']:
        try:
            for face in analyze(item['path']):
                gallery.append((item['id'], np.asarray(face['embedding'], dtype=np.float32)))
        except Exception as exc:
            errors.append({'gallery': item['id'], 'error': str(exc)})
    index_seconds = time.perf_counter() - started
    matrix = np.stack([row[1] for row in gallery]) if gallery else np.empty((0,512),dtype=np.float32)
    predictions, truth, latencies = {}, {}, []
    for item in manifest['queries']:
        query_id = item['id']
        if query_id in truth:
            raise ValueError('Query IDs must be unique')
        truth[query_id] = item['relevant_photo_ids']
        if not set(truth[query_id]).issubset(ids):
            raise ValueError(f'Unknown relevant photo IDs in {query_id}')
        started = time.perf_counter()
        try:
            faces = analyze(item['path'])
            if not faces or (len(faces) > 1 and 'face_index' not in item):
                raise ValueError('No face, or multiple faces without explicit face_index')
            embedding = np.asarray(faces[item.get('face_index',0)]['embedding'],dtype=np.float32)
            grouped = {}
            for (photo_id,_), similarity in zip(gallery, matrix @ embedding):
                if similarity >= args.threshold:
                    grouped[photo_id] = max(grouped.get(photo_id,-1),float(similarity))
            predictions[query_id] = sorted(grouped,key=lambda key:(-grouped[key],key))[:args.k]
        except Exception as exc:
            predictions[query_id] = []
            errors.append({'query':query_id,'error':str(exc)})
        latencies.append(time.perf_counter()-started)
    report = {**retrieval_metrics(truth,predictions,args.k),'model_key':models.key,'threshold':args.threshold,'gallery_photos':len(ids),'gallery_faces':len(gallery),'index_seconds':index_seconds,'query_p50_seconds':float(np.median(latencies)) if latencies else None,'query_p95_seconds':float(np.percentile(latencies,95)) if latencies else None,'errors':errors,'device':models.status()['device']}
    args.output.mkdir(parents=True,exist_ok=True)
    for name,value in [('report',report),('predictions',predictions)]:
        (args.output / f'{name}.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
