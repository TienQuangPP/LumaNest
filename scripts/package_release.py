"""Build allowlisted LumaNest archives, excluding personal data and runtime assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ('fsmart', 'scripts', 'tests', 'docs', 'desktop', '.github')
FILES = ('README.md', 'THIRD_PARTY.md', 'SECURITY.md', 'VERSION', '.gitignore',
         '.gitattributes', 'requirements.txt', 'requirements-ml.txt', 'requirements-cpu.txt',
         'requirements-semantic.txt', 'requirements-dev.txt', 'requirements-lock.txt',
         'run.ps1', 'setup.ps1', 'Chay-LumaNest.cmd', 'docs/assets/lumanest-cover.jpg')
SUFFIXES = {'.py', '.js', '.css', '.html', '.svg', '.ico', '.md', '.json', '.txt', '.cs', '.ps1', '.cmd', '.yml'}
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,}|AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])')


def source_files(root=None):
    root = root or ROOT
    paths = [root / name for name in FILES if (root / name).is_file()]
    for name in FOLDERS:
        paths.extend(path for path in (root / name).rglob('*')
                     if path.is_file() and not path.is_symlink()
                     and '__pycache__' not in path.parts and path.suffix in SUFFIXES)
    return sorted(paths, key=lambda path: path.relative_to(root).as_posix())


def validate_file(path):
    if path.suffix not in {'.ico', '.jpg'} and SECRET.search(path.read_bytes()):
        raise ValueError(f'Possible credential in {path.relative_to(ROOT)}; refusing to publish.')


def build(windows=False):
    version = (ROOT / 'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid VERSION')
    paths = source_files()
    for path in paths:
        validate_file(path)
    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)
    targets = [output / f'LumaNest-{version}-source.zip']
    if windows:
        if not (ROOT / 'LumaNest.exe').is_file():
            raise ValueError('Build LumaNest.exe with desktop/build.ps1 first.')
        targets.append(output / f'LumaNest-{version}-windows-x64.zip')
    manifests = []
    for target in targets:
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in paths:
                archive.write(path, 'LumaNest/' + path.relative_to(ROOT).as_posix())
            if 'windows-x64' in target.name:
                archive.write(ROOT / 'LumaNest.exe', 'LumaNest/LumaNest.exe')
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifests.append({'file': target.name, 'bytes': target.stat().st_size, 'sha256': digest})
    (output / 'SHA256SUMS.txt').write_text(''.join(f"{item['sha256']}  {item['file']}\n" for item in manifests))
    (output / 'release-manifest.json').write_text(json.dumps({'version': version, 'files': manifests}, indent=2))
    for item in manifests:
        print(item['file'], item['bytes'], 'bytes', item['sha256'])
    return targets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true')
    build(parser.parse_args().windows)
