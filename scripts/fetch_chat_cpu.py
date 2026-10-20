"""Fetch pinned official Qwen GGUF + official llama.cpp Windows CPU runtime."""
import hashlib,json,os,zipfile
from pathlib import Path
os.environ.setdefault('HF_HUB_DISABLE_XET','1')
from huggingface_hub import HfApi,hf_hub_download
import requests
ROOT=Path(__file__).resolve().parents[1]
REPO='Qwen/Qwen3-1.7B-GGUF'
REVISION='90862c4b9d2787eaed51d12237eafdfe7c5f6077'
MODEL='Qwen3-1.7B-Q8_0.gguf'
RELEASE='b11669'
URL=f'https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/llama-{RELEASE}-bin-win-cpu-x64.zip'
ZIP_SHA='37b3efcf962847ca869745fd4ccf7f5e7e8dacfeff9fa3523b4ca8cdc66d632b'
target=ROOT/'weights/chat-cpu';target.mkdir(parents=True,exist_ok=True)
info=HfApi().model_info(REPO,revision=REVISION,files_metadata=True)
hf_hub_download(REPO,MODEL,revision=REVISION,local_dir=target)
with (target/MODEL).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
expected=next(f.lfs.sha256 for f in info.siblings if f.rfilename==MODEL)
if digest!=expected:raise ValueError('Model checksum mismatch')
archive=target/'runtime.zip';session=requests.Session();session.trust_env=False
with session.get(URL,stream=True,timeout=(15,60)) as response:
    response.raise_for_status()
    with archive.open('wb') as stream:
        for block in response.iter_content(1024*1024):stream.write(block)
with archive.open('rb') as stream:
    if hashlib.file_digest(stream,'sha256').hexdigest()!=ZIP_SHA:raise ValueError('Runtime archive checksum mismatch')
runtime=target/'bin';runtime.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as package:
    for item in package.infolist():
        if item.is_dir():continue
        name=Path(item.filename)
        if name.is_absolute() or '..' in name.parts:raise ValueError('Invalid archive path')
        if name.suffix.lower() not in {'.exe','.dll','.txt','.md'}:continue
        destination=runtime/name.name
        destination.write_bytes(package.read(item))
files={}
for path in [target/MODEL,*runtime.iterdir()]:
    if path.is_file():
        with path.open('rb') as stream:sha=hashlib.file_digest(stream,'sha256').hexdigest()
        files[path.relative_to(target).as_posix()]={'sha256':sha,'bytes':path.stat().st_size}
(target/'provenance.json').write_text(json.dumps({'repo':REPO,'revision':REVISION,'release':RELEASE,'archive_sha256':ZIP_SHA,'files':files},indent=2),'utf-8')
archive.unlink()
print(json.dumps({'repo':REPO,'revision':REVISION,'release':RELEASE,'bytes':sum(v['bytes'] for v in files.values())}))
