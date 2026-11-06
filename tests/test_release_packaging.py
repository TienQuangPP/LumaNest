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


def test_release_ships_bundled_fonts(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, 'ROOT', tmp_path)
    (tmp_path / 'VERSION').write_text('1.0.0')
    font = tmp_path / 'fsmart' / 'static' / 'fonts' / 'Face.ttf'
    font.parent.mkdir(parents=True)
    font.write_bytes(b'\x00\x01\x00\x00' + bytes(range(256)))
    with zipfile.ZipFile(package_release.build()[0]) as source:
        assert 'LumaNest/fsmart/static/fonts/Face.ttf' in source.namelist()


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


def test_ui_update_package_and_asset_integrity(tmp_path, monkeypatch):
    monkeypatch.setattr(package_release, 'ROOT', tmp_path)
    (tmp_path / 'VERSION').write_text('1.1.0')
    (tmp_path / 'README.md').write_text('# F Smart Memories')

    # Create UI assets
    static_dir = tmp_path / 'fsmart' / 'static'
    fonts_dir = static_dir / 'fonts'
    illus_dir = static_dir / 'illustrations'
    fonts_dir.mkdir(parents=True)
    illus_dir.mkdir(parents=True)

    (static_dir / 'index.html').write_text('<html>UI</html>')
    (static_dir / 'style.css').write_text('body { color: red; }')
    (static_dir / 'app.js').write_text('console.log("ok");')
    (static_dir / 'fsmart-logo.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'mock')
    (static_dir / 'favicon.ico').write_bytes(b'\x00\x00\x01\x00' + b'mock')
    (static_dir / 'fsmart-cover.jpg').write_bytes(b'\xff\xd8\xff' + b'mock')
    (fonts_dir / 'Font.ttf').write_bytes(b'\x00\x01\x00\x00' + b'font')
    (illus_dir / 'icon.svg').write_text('<svg></svg>')

    # Backend and launch scripts
    (tmp_path / 'fsmart' / 'app.py').write_text('app = 1')
    (tmp_path / 'scripts').mkdir()
    (tmp_path / 'scripts' / 'launch.py').write_text('print("launch")')
    (tmp_path / 'Chay-LumaNest.cmd').write_text('echo run')

    # Stray personal image outside asset folders
    (tmp_path / 'fsmart' / 'personal_photo.jpg').write_bytes(b'\xff\xd8\xff' + b'private')
    (tmp_path / 'scripts' / 'selfie.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'private')

    archives = package_release.build()
    assert len(archives) == 2

    # Check Full package (index 0)
    with zipfile.ZipFile(archives[0]) as full_zip:
        names = set(full_zip.namelist())
        assert 'LumaNest/fsmart/static/fsmart-logo.png' in names
        assert 'LumaNest/fsmart/static/favicon.ico' in names
        assert 'LumaNest/fsmart/static/fsmart-cover.jpg' in names
        assert 'LumaNest/fsmart/static/fonts/Font.ttf' in names
        assert 'LumaNest/fsmart/static/illustrations/icon.svg' in names
        assert 'LumaNest/fsmart/static/index.html' in names
        assert 'LumaNest/Chay-LumaNest.cmd' in names
        # Ensure stray personal photos outside assets were rejected
        assert 'LumaNest/fsmart/personal_photo.jpg' not in names
        assert 'LumaNest/scripts/selfie.png' not in names
        assert full_zip.testzip() is None

    # Check UI Update package (index 1)
    with zipfile.ZipFile(archives[1]) as update_zip:
        names = set(update_zip.namelist())
        # Update package uses root-relative paths for seamless in-place extraction
        assert 'fsmart/static/fsmart-logo.png' in names
        assert 'fsmart/static/favicon.ico' in names
        assert 'fsmart/static/fonts/Font.ttf' in names
        assert 'fsmart/static/index.html' in names
        assert 'fsmart/app.py' in names
        assert 'scripts/launch.py' in names
        assert 'Chay-LumaNest.cmd' in names
        assert 'HUONG_DAN_CAP_NHAT.txt' in names
        assert 'VERSION' in names
        # Excludes tests, docs, and stray photos
        assert not any(n.startswith('tests/') for n in names)
        assert not any(n.startswith('docs/') for n in names)
        assert 'fsmart/personal_photo.jpg' not in names
        assert update_zip.testzip() is None


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
