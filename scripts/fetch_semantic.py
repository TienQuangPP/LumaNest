"""Fetch only data files from Google's official SigLIP 2 repository."""
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault('HF_HUB_DISABLE_XET', '1')
from huggingface_hub import HfApi, snapshot_download

ROOT = Path(__file__).resolve().parents[1]
REPO = 'google/siglip2-base-patch16-224'
target = ROOT / 'weights/siglip2'
target.mkdir(parents=True, exist_ok=True)
revision = '75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2'
info = HfApi().model_info(REPO, revision=revision, files_metadata=True)
snapshot_download(REPO, revision=revision, local_dir=target,
                  allow_patterns=['*.json', '*.safetensors', '*.model', '*.txt'],
                  ignore_patterns=['*.py', '*.bin', '*.h5', '*.msgpack'], max_workers=3)
files = {}
for path in target.iterdir():
    if path.is_file() and path.name != 'provenance.json':
        with path.open('rb') as source:
            files[path.name] = {'sha256': hashlib.file_digest(source, 'sha256').hexdigest(), 'bytes': path.stat().st_size}
        upstream = next((f for f in info.siblings if f.rfilename == path.name), None)
        if upstream and upstream.lfs and upstream.lfs.sha256 != files[path.name]['sha256']:
            raise ValueError('Upstream LFS checksum mismatch: ' + path.name)
(target / 'provenance.json').write_text(json.dumps({'repo': REPO, 'revision': revision, 'files': files}, indent=2), encoding='utf-8')
print(json.dumps({'repo': REPO, 'revision': revision, 'bytes': sum(f['bytes'] for f in files.values())}))
