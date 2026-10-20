"""Fetch only upstream pretrained assets; record revisions and content hashes."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / 'weights'
HF_REV = '60a65befbcf7e19284c4f3ac730f56867ed29594'
HF = f'https://huggingface.co/minchul/cvlface_adaface_ir50_webface4m/resolve/{HF_REV}'
manifest: dict = {}


def download(url: str, target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        print(f'Downloading {target.name}', flush=True)
        request = urllib.request.Request(url, headers={'User-Agent': 'LumaNest/1.0'})
        partial = target.with_suffix(target.suffix + '.part')
        try:
            with urllib.request.urlopen(request, timeout=180) as source, partial.open('wb') as out:
                shutil.copyfileobj(source, out)
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
    with target.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    manifest[str(target.relative_to(ROOT))] = {'url': url, 'sha256': digest, 'bytes': target.stat().st_size}
    return target


def github_revision(repo: str) -> str:
    request = urllib.request.Request(f'https://api.github.com/repos/{repo}/commits/HEAD', headers={'User-Agent': 'LumaNest/1.0'})
    with urllib.request.urlopen(request, timeout=60) as source:
        return json.load(source)['sha']


def face_assets() -> None:
    directory = WEIGHTS / 'adaface'
    for source, destination in [('models/iresnet/model.py', 'architecture.py'), ('model.safetensors', 'model.safetensors'), ('config.json', 'config.json'), ('pretrained_model/model.yaml', 'model.yaml'), ('models/base/__init__.py', 'base_reference.txt')]:
        download(f'{HF}/{source}', directory / destination)
    download('https://raw.githubusercontent.com/mk-minchul/CVLface/main/LICENSE', directory / 'LICENSE')
    (directory / 'revision.txt').write_text(HF_REV, encoding='utf-8')
    detector = WEIGHTS / 'facenet'
    metadata = detector / 'revision.txt'
    revision = metadata.read_text().strip() if metadata.exists() else github_revision('timesler/facenet-pytorch')
    files = ['__init__.py', 'models/mtcnn.py', 'models/inception_resnet_v1.py', 'models/utils/detect_face.py', 'models/utils/download.py', 'models/utils/training.py', 'data/pnet.pt', 'data/rnet.pt', 'data/onet.pt', 'LICENSE.md']
    for name in files:
        download(f'https://raw.githubusercontent.com/timesler/facenet-pytorch/{revision}/{name}', detector / name)
    metadata.write_text(revision, encoding='utf-8')


def style_assets() -> None:
    directory = WEIGHTS / 'style'
    metadata = directory / 'revision.txt'
    revision = metadata.read_text().strip() if metadata.exists() else github_revision('pytorch/examples')
    download(f'https://raw.githubusercontent.com/pytorch/examples/{revision}/fast_neural_style/neural_style/transformer_net.py', directory / 'architecture.py')
    download(f'https://raw.githubusercontent.com/pytorch/examples/{revision}/LICENSE', directory / 'LICENSE')
    archive = download('https://www.dropbox.com/s/lrvwfehqdcxoza8/saved_models.zip?dl=1', directory / 'saved_models.zip')
    wanted = {'candy.pth', 'mosaic.pth', 'rain_princess.pth', 'udnie.pth'}
    found = set()
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            name = PurePosixPath(member.filename.replace('\\', '/')).name
            if name in wanted and not member.is_dir():
                if name in found:
                    raise ValueError(f'Duplicate checkpoint: {name}')
                found.add(name)
                target = directory / name
                with source.open(member) as data, target.open('wb') as out:
                    shutil.copyfileobj(data, out)
                manifest[str(target.relative_to(ROOT))] = {'archive': str(archive.relative_to(ROOT)), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest()}
    if wanted - found:
        raise ValueError(f'Missing style checkpoints: {wanted - found}')
    metadata.write_text(revision, encoding='utf-8')


def vgg_assets() -> None:
    download('https://download.pytorch.org/models/vgg19-dcbb9e9d.pth', WEIGHTS / 'style/vgg19-dcbb9e9d.pth')


def artwork_assets() -> None:
    sys.path.insert(0,str(ROOT))
    from fsmart.artworks import ARTWORK
    path=download(ARTWORK['download_url'],WEIGHTS/'artworks'/ARTWORK['filename'])
    with path.open('rb') as stream:
        if hashlib.file_digest(stream,'sha256').hexdigest()!=ARTWORK['sha256']:raise ValueError('Artwork checksum mismatch; upstream may have changed')
    (WEIGHTS/'artworks/provenance.json').write_text(json.dumps(ARTWORK,ensure_ascii=False,indent=2),'utf-8')


def baseline_assets() -> None:
    face_assets()
    download('https://github.com/timesler/facenet-pytorch/releases/download/v2.2.9/20180402-114759-vggface2.pt', WEIGHTS / 'facenet/vggface2.pt')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--only', choices=['all', 'face', 'style', 'vgg', 'artworks', 'baseline'], default='all')
    args = parser.parse_args()
    WEIGHTS.mkdir(parents=True, exist_ok=True)
    manifest_path = WEIGHTS / 'provenance.json'
    if manifest_path.exists():
        manifest.update(json.loads(manifest_path.read_text(encoding='utf-8')))
    try:
        for name, operation in [('face', face_assets), ('style', style_assets), ('vgg', vgg_assets), ('artworks',artwork_assets)]:
            if args.only in ['all', name]:
                operation()
        if args.only == 'baseline':
            baseline_assets()
    finally:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Assets ready. Provenance:', manifest_path)


if __name__ == '__main__':
    main()
