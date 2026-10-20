import subprocess
import zipfile

import pytest

from scripts import bootstrap, package_release


def test_release_excludes_private_data_and_generated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, 'ROOT', tmp_path)
    files = {
        'VERSION': '1.0.0', 'README.md': 'LumaNest', 'fsmart/app.py': 'pass',
        'fsmart/__pycache__/app.pyc': 'compiled', 'fsmart/accidental.db': 'private',
        'fsmart/report.pdf': 'private', 'runtime/photos/personal.jpg': 'private',
        'weights/model.safetensors': 'model', 'data/gallery.jpg': 'private',
        '.env': 'secret', '.local-archive/backup.zip': 'private',
        'artifacts/trace.json': 'private', '.cache/test.json': 'private',
    }
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    archives = package_release.build()
    with zipfile.ZipFile(archives[0]) as source:
        assert set(source.namelist()) == {'LumaNest/VERSION', 'LumaNest/README.md', 'LumaNest/fsmart/app.py'}
        assert source.testzip() is None


def test_release_blocks_private_key_material(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, 'ROOT', tmp_path)
    (tmp_path / 'VERSION').write_text('1.0.0')
    (tmp_path / 'README.md').write_text('-----BEGIN ' + 'PRIVATE KEY-----')
    with pytest.raises(ValueError, match='Possible credential'):
        package_release.build()
    assert not (tmp_path / 'dist').exists()


def test_windows_release_needs_launcher(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, 'ROOT', tmp_path)
    (tmp_path / 'VERSION').write_text('1.0.0')
    with pytest.raises(ValueError, match='Build LumaNest.exe'):
        package_release.build(windows=True)


def test_install_preserves_library_and_skips_demo_and_development_tools(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, 'ROOT', tmp_path)
    monkeypatch.chdir(tmp_path)
    for name in ['TEMP', 'TMP', 'PYTHONIOENCODING']:
        monkeypatch.setenv(name, '')
    python = tmp_path / '.venv' / ('Scripts/python.exe' if bootstrap.os.name == 'nt' else 'bin/python')
    python.parent.mkdir(parents=True)
    python.touch()
    personal = tmp_path / 'runtime' / 'photos' / 'kept.jpg'
    personal.parent.mkdir(parents=True)
    personal.write_bytes(b'existing photo')
    calls = []

    def fake_run(command, **kwargs):
        command = list(map(str, command))
        calls.append(command)
        return subprocess.CompletedProcess(command, 1 if '-c' in command else 0)

    monkeypatch.setattr(bootstrap.subprocess, 'run', fake_run)
    bootstrap.main(['--with-local-chat', '--with-subject-tools'])
    flat = '\n'.join(' '.join(command) for command in calls)
    assert 'requirements-dev.txt' not in flat
    assert 'https://download.pytorch.org/whl/cpu' in flat
    assert 'scripts/fetch_chat_cpu.py' in flat
    assert 'scripts/fetch_segmentation.py' in flat
    assert 'scripts/fetch_semantic.py' in flat
    assert 'prepare_demo' not in flat and '--only demo' not in flat
    assert personal.read_bytes() == b'existing photo'


def test_install_without_models_never_fetches_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, 'ROOT', tmp_path)
    monkeypatch.chdir(tmp_path)
    for name in ['TEMP', 'TMP', 'PYTHONIOENCODING']:
        monkeypatch.setenv(name, '')
    calls = []
    monkeypatch.setattr(bootstrap.subprocess, 'run', lambda cmd, **kw: calls.append(list(map(str, cmd))) or subprocess.CompletedProcess(cmd, 0))
    bootstrap.main(['--skip-models', '--skip-cpu-optimization', '--skip-semantic-search', '--with-dev'])
    flat = '\n'.join(' '.join(command) for command in calls)
    assert 'requirements-dev.txt' in flat
    assert 'fetch_' not in flat
    assert 'requirements-cpu.txt' not in flat
    assert 'requirements-semantic.txt' not in flat
