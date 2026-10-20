"""Fetch data-only SAM 2.1 Tiny weights from Meta's official model repository."""
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault('HF_HUB_DISABLE_XET','1')
from huggingface_hub import HfApi, snapshot_download

REPO='facebook/sam2.1-hiera-tiny'
ROOT=Path(__file__).resolve().parents[1]
target=ROOT/'weights/sam2'
revision='de431c4043854a71d8101e17995dfe596bf101a5'
info=HfApi().model_info(REPO,revision=revision,files_metadata=True)
snapshot_download(REPO,revision=revision,local_dir=target,
                  allow_patterns=['config.json','model.safetensors','preprocessor_config.json','processor_config.json'],
                  ignore_patterns=['*.py','*.pt','*.bin'],max_workers=2)
files={}
for name in ['config.json','model.safetensors','preprocessor_config.json','processor_config.json']:
    path=target/name
    with path.open('rb') as source:
        digest=hashlib.file_digest(source,'sha256').hexdigest()
    upstream=next(f for f in info.siblings if f.rfilename==name)
    if upstream.lfs and upstream.lfs.sha256!=digest:
        raise ValueError('Upstream checksum mismatch: '+name)
    files[name]={'sha256':digest,'bytes':path.stat().st_size}
(target/'provenance.json').write_text(json.dumps({'repo':REPO,'revision':revision,'files':files},indent=2),'utf-8')
print(json.dumps({'repo':REPO,'revision':revision,'bytes':sum(f['bytes'] for f in files.values())}))
