"""Install LumaNest on Windows using an existing Python 3.10-3.12 interpreter."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-models', action='store_true')
    parser.add_argument('--skip-cpu-optimization', action='store_true')
    parser.add_argument('--skip-semantic-search', action='store_true')
    parser.add_argument('--with-local-chat', action='store_true')
    parser.add_argument('--with-subject-tools', action='store_true')
    parser.add_argument('--with-dev', action='store_true')
    args = parser.parse_args(argv)
    if not (3, 10) <= sys.version_info[:2] <= (3, 12):
        parser.error('LumaNest requires Python 3.10-3.12 (64-bit).')
    if sys.maxsize <= 2**32:
        parser.error('Install the 64-bit version of Python.')
    os.chdir(ROOT)
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    cache = ROOT / '.cache' / 'tmp'
    cache.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(cache)
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')

    def run(*command):
        print('\n> ' + ' '.join(map(str, command)), flush=True)
        subprocess.run(list(map(str, command)), cwd=ROOT, check=True)

    if not python.is_file():
        run(sys.executable, '-m', 'venv', ROOT / '.venv')
    requirements = ['-r', 'requirements.txt']
    if args.with_dev:
        requirements += ['-r', 'requirements-dev.txt']
    run(python, '-m', 'pip', 'install', *requirements)
    if subprocess.run([str(python), '-c', 'import torch, torchvision'], cwd=ROOT).returncode:
        run(python, '-m', 'pip', 'install', '-r', 'requirements-ml.txt',
            '--index-url', 'https://download.pytorch.org/whl/cpu')
    if not args.skip_models:
        run(python, 'scripts/fetch_assets.py')
    if not args.skip_cpu_optimization:
        run(python, '-m', 'pip', 'install', '-r', 'requirements-cpu.txt')
        if not args.skip_models:
            run(python, 'scripts/prepare_cpu.py')
    if not args.skip_semantic_search or args.with_local_chat or args.with_subject_tools:
        run(python, '-m', 'pip', 'install', '-r', 'requirements-semantic.txt')
    if not args.skip_models:
        if not args.skip_semantic_search:
            run(python, 'scripts/fetch_semantic.py')
        if args.with_local_chat:
            run(python, 'scripts/fetch_chat_cpu.py')
        if args.with_subject_tools:
            run(python, 'scripts/fetch_segmentation.py')
    print('\nLumaNest ready. Open LumaNest.exe or run: python scripts/launch.py', flush=True)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f'Installation failed (exit {error.returncode}). Fix the error above and retry.')
