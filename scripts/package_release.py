"""Build allowlisted F Smart Memories archives, excluding personal data and runtime assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

# Base folders for full release
FOLDERS = ('fsmart', 'scripts', 'tests', 'docs', 'desktop', '.github')

# Specific files at root to include in full release
FILES = (
    'README.md', 'THIRD_PARTY.md', 'SECURITY.md', 'VERSION', '.gitignore',
    '.gitattributes', 'requirements.txt', 'requirements-ml.txt', 'requirements-cpu.txt',
    'requirements-semantic.txt', 'requirements-dev.txt', 'requirements-lock.txt',
    'run.ps1', 'setup.ps1', 'Chay-LumaNest.cmd', 'Dong-Goi.cmd',
    'docs/assets/lumanest-cover.jpg'
)

# Allowed file extensions for source and assets
SUFFIXES = {
    '.py', '.js', '.css', '.html', '.svg', '.ico', '.png', '.jpg', '.jpeg',
    '.webp', '.ttf', '.otf', '.woff', '.woff2', '.md', '.json', '.txt',
    '.cs', '.ps1', '.cmd', '.bat', '.yml', '.yaml', '.toml'
}

# Image extensions
IMAGE_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff', '.gif'}
BINARY_SUFFIXES = IMAGE_SUFFIXES | {'.ico', '.ttf', '.otf', '.woff', '.woff2', '.exe'}

# Forbidden directories that must NEVER be packaged
EXCLUDE_DIRS = {
    '.venv', 'venv', 'weights', 'runtime', 'cache', '.cache', '.pytest_cache',
    '__pycache__', 'logs', 'log', 'dist', '.git', '.local-archive',
    'artifacts', 'data', '.idea', '.vscode'
}

# Secret detection patterns
SECRET = re.compile(
    rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|'
    rb'gh[pousr]_[A-Za-z0-9]{36,}|'
    rb'github_pat_[A-Za-z0-9_]{60,}|'
    rb'AIza[A-Za-z0-9_-]{35}(?![A-Za-z0-9_-])|'
    rb'sk-(?:proj-)?[A-Za-z0-9_-]{32,}|'
    rb'sk-ant-[A-Za-z0-9_-]{32,}|'
    rb'AKIA[0-9A-Z]{16}'
)

UPDATE_GUIDE = """======================================================================
HƯỚNG DẪN CẬP NHẬT GIAO DIỆN & TÍNH NĂNG F SMART MEMORIES
======================================================================

Gói cập nhật này chỉ chứa mã nguồn, giao diện và trình khởi chạy mới,
cho phép bạn nâng cấp ngay mà KHÔNG mất dữ liệu và KHÔNG phải tải lại model.

CÁCH THỰC HIỆN:
1. Đóng ứng dụng F Smart Memories (và cửa sổ dòng lệnh) nếu đang chạy.
2. Giải nén toàn bộ nội dung file ZIP này vào thư mục đã cài đặt F Smart Memories
   (chọn 'Replace / Ghi đè tất cả' khi Windows hỏi).
3. Các thư mục quan trọng sau được GIỮ NGUYÊN HOÀN TOÀN:
   - .venv (môi trường Python và các thư viện đã cài)
   - weights (toàn bộ trọng số AI đã tải: SAM2, SigLIP2, AdaFace, Chat...)
   - runtime (ảnh cá nhân, album, thumbnail, cơ sở dữ liệu memories.db)
4. Mở file Chay-LumaNest.cmd hoặc LumaNest.exe để khởi động phiên bản mới!
======================================================================
"""


def is_allowed_file(path: Path, root: Path | None = None) -> bool:
    """Determine whether a file is safe and eligible for release packaging."""
    root = root or ROOT
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False

    rel_parts = rel.parts
    # Exclude files in forbidden directory trees
    for part in rel_parts[:-1]:
        if part in EXCLUDE_DIRS or part.startswith('.git') or part == '__pycache__':
            return False

    # Exclude forbidden file patterns
    name = path.name
    if name.startswith('.env') or name in ('.DS_Store', 'Thumbs.db'):
        return False

    suffix = path.suffix.lower()
    if suffix in {'.pyc', '.pyo', '.pyd', '.log', '.db', '.db-shm', '.db-wal',
                  '.sqlite', '.sqlite3', '.safetensors', '.pt', '.pth', '.bin',
                  '.onnx', '.gguf', '.zip', '.tar', '.gz', '.rar', '.7z'}:
        return False

    # Strictly protect against packaging personal photos outside approved static asset folders
    if suffix in IMAGE_SUFFIXES:
        rel_posix = rel.as_posix()
        if not (rel_posix.startswith('fsmart/static/') or rel_posix.startswith('docs/assets/')):
            return False

    return True


def source_files(root: Path | None = None) -> list[Path]:
    """Gather all source and asset files for the full fresh-install release package."""
    root = root or ROOT
    paths: list[Path] = []
    for name in FILES:
        target = root / name
        if target.is_file() and is_allowed_file(target, root):
            paths.append(target)

    for name in FOLDERS:
        folder = root / name
        if not folder.is_dir():
            continue
        for path in folder.rglob('*'):
            if (path.is_file() and not path.is_symlink()
                    and path.suffix.lower() in SUFFIXES
                    and is_allowed_file(path, root)):
                paths.append(path)

    unique_paths = list(dict.fromkeys(paths))
    return sorted(unique_paths, key=lambda p: p.relative_to(root).as_posix())


def ui_update_files(root: Path | None = None) -> list[Path]:
    """Gather files for the lightweight UI and application update package."""
    root = root or ROOT
    paths: list[Path] = []

    # 1. Complete fsmart package: static assets (CSS, JS, fonts, images, HTML) + backend code
    fsmart_dir = root / 'fsmart'
    if fsmart_dir.is_dir():
        for path in fsmart_dir.rglob('*'):
            if (path.is_file() and not path.is_symlink()
                    and path.suffix.lower() in SUFFIXES
                    and is_allowed_file(path, root)):
                paths.append(path)

    # 2. Key launchers, version metadata, and entry scripts
    entry_files = [
        'scripts/launch.py',
        'Chay-LumaNest.cmd',
        'Dong-Goi.cmd',
        'VERSION',
        'README.md',
        'requirements.txt',
    ]
    for rel in entry_files:
        p = root / rel
        if p.is_file() and is_allowed_file(p, root):
            paths.append(p)

    unique_paths = list(dict.fromkeys(paths))
    return sorted(unique_paths, key=lambda p: p.relative_to(root).as_posix())


def validate_file(path: Path) -> None:
    """Ensure no private key or credential tokens exist in text/source files."""
    if path.suffix.lower() not in BINARY_SUFFIXES:
        content = path.read_bytes()
        if SECRET.search(content):
            raise ValueError(f'Possible credential in {path.relative_to(ROOT)}; refusing to publish.')


def verify_archive(target: Path, is_update: bool = False, root: Path | None = None) -> dict:
    """Check archive integrity and ensure all expected UI assets and launchers are present."""
    root = root or ROOT
    with zipfile.ZipFile(target, 'r') as archive:
        bad_file = archive.testzip()
        if bad_file:
            raise ValueError(f'Corrupt file in archive {target.name}: {bad_file}')

        namelist = archive.namelist()

        # Check for strictly forbidden patterns
        forbidden_substrings = [
            '/.venv/', '/weights/', '/runtime/', '/__pycache__/', '/.cache/',
            '/.pytest_cache/', '/.git/', 'memories.db'
        ]
        for name in namelist:
            norm_name = '/' + name.strip('/') + '/'
            for forbidden in forbidden_substrings:
                if forbidden in norm_name:
                    raise ValueError(f'Security violation: {forbidden} found in archive: {name}')
            if any(name.endswith(ext) for ext in ('.pyc', '.pyo', '.pyd', '.log', '.db', '.safetensors', '.pt', '.pth')):
                raise ValueError(f'Forbidden file extension in archive: {name}')
            if '.env' in name.split('/'):
                raise ValueError(f'Credential violation: .env found in archive: {name}')

        # Verify presence of UI assets when source static exists
        static_dir = root / 'fsmart' / 'static'
        has_source_static = static_dir.is_dir()

        def find_in_archive(pattern: str) -> list[str]:
            return [n for n in namelist if re.search(pattern, n, re.IGNORECASE)]

        logo_matches = find_in_archive(r'fsmart-logo\.png|fsmart\.svg|lumanest\.svg')
        favicon_matches = find_in_archive(r'favicon\.ico|lumanest\.ico|fsmart-icon')
        cover_matches = find_in_archive(r'fsmart-cover\.jpg|lumanest-cover\.jpg')
        font_matches = find_in_archive(r'fonts/.*\.ttf')
        illustration_matches = find_in_archive(r'illustrations/.*\.svg')
        core_ui_matches = find_in_archive(r'index\.html|style\.css|app\.js')

        if has_source_static:
            if ((static_dir / 'fsmart-logo.png').is_file() or (static_dir / 'fsmart.svg').is_file()) and not logo_matches:
                raise ValueError(f'Missing UI Logo in archive {target.name}')
            if ((static_dir / 'favicon.ico').is_file() or (static_dir / 'lumanest.ico').is_file()) and not favicon_matches:
                raise ValueError(f'Missing Favicon in archive {target.name}')
            if (static_dir / 'fonts').is_dir() and any((static_dir / 'fonts').glob('*.ttf')) and not font_matches:
                raise ValueError(f'Missing Fonts in archive {target.name}')
            if ((static_dir / 'fsmart-cover.jpg').is_file() or (static_dir / 'lumanest-cover.jpg').is_file()) and not cover_matches:
                raise ValueError(f'Missing Cover in archive {target.name}')
            if (static_dir / 'index.html').is_file() and not core_ui_matches:
                raise ValueError(f'Missing core UI files (index.html/style.css/app.js) in {target.name}')

        return {
            'file': target.name,
            'path': str(target.resolve()),
            'bytes': target.stat().st_size,
            'total_files': len(namelist),
            'logos': len(logo_matches),
            'favicons': len(favicon_matches),
            'covers': len(cover_matches),
            'fonts': len(font_matches),
            'illustrations': len(illustration_matches),
        }


def format_size(size_bytes: int) -> str:
    """Format bytes into readable MB/KB string."""
    if size_bytes >= 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.2f} MB'
    if size_bytes >= 1024:
        return f'{size_bytes / 1024:.1f} KB'
    return f'{size_bytes} B'


def print_report(version: str, manifests: list[dict]) -> None:
    """Print an informative release summary report."""
    print('\n' + '=' * 74)
    print(f'   F SMART MEMORIES v{version} - ĐÓNG GÓI HOÀN TẤT THÀNH CÔNG')
    print('=' * 74)
    for idx, item in enumerate(manifests, 1):
        v = item['ui_verification']
        is_update = 'update' in item['file']
        label = 'BẢN CẬP NHẬT GIAO DIỆN (UI Update)' if is_update else 'BẢN DÀNH CHO NGƯỜI MỚI (Full / Windows x64)'
        print(f'\n{idx}. {label}:')
        print(f'   - Tên gói   : {item["file"]}')
        print(f'   - Đường dẫn : {item["path"]}')
        print(f'   - Dung lượng: {item["bytes"]:,} bytes ({format_size(item["bytes"])})')
        print(f'   - SHA-256   : {item["sha256"]}')
        print(f'   - Số tệp tin: {item["total_files"]} files')
        print(f'   - Tài nguyên: Logo ({v["logos"]}), Favicon ({v["favicons"]}), Cover ({v["covers"]}), Font ({v["fonts"]}), SVG ({v["illustrations"]})')
        if is_update:
            print('   - Mục đích  : Cập nhật đè vào thư mục cài đặt, giữ nguyên .venv, weights, runtime.')
        else:
            print('   - Mục đích  : Bản cài đặt trọn gói cho máy mới (đầy đủ code, launchers, requirements).')

    print('\n' + '-' * 74)
    print('Đã ghi nhận chữ ký và danh mục phân phối:')
    print(f'   - {ROOT / "dist" / "SHA256SUMS.txt"}')
    print(f'   - {ROOT / "dist" / "release-manifest.json"}')
    print('=' * 74 + '\n')


def build(windows: bool = False, package_type: str = 'all', app_name: str = 'FSmartMemories') -> list[Path]:
    """Build release zip archives for F Smart Memories."""
    version_file = ROOT / 'VERSION'
    if not version_file.is_file():
        raise ValueError('Missing VERSION file')
    version = version_file.read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid VERSION')

    full_paths = source_files(ROOT)
    update_paths = ui_update_files(ROOT)

    # Validate credential leaks before creating output dist
    for path in set(full_paths + update_paths):
        validate_file(path)

    has_launcher = (ROOT / 'LumaNest.exe').is_file()
    if windows and not has_launcher:
        raise ValueError('Build LumaNest.exe with desktop/build.ps1 first.')

    output = ROOT / 'dist'
    output.mkdir(exist_ok=True)

    targets: list[Path] = []
    manifests: list[dict] = []

    # 1. Full package (Bản dành cho người mới)
    if package_type in ('all', 'full'):
        full_target = output / f'{app_name}-{version}-windows-x64.zip'
        prefix = 'LumaNest/'
        with zipfile.ZipFile(full_target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in full_paths:
                archive.write(path, prefix + path.relative_to(ROOT).as_posix())
            if has_launcher:
                archive.write(ROOT / 'LumaNest.exe', prefix + 'LumaNest.exe')
        targets.append(full_target)

    # 2. UI update package (Bản cập nhật giao diện)
    if package_type in ('all', 'update'):
        update_target = output / f'{app_name}-{version}-ui-update.zip'
        with zipfile.ZipFile(update_target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in update_paths:
                archive.write(path, path.relative_to(ROOT).as_posix())
            if has_launcher:
                archive.write(ROOT / 'LumaNest.exe', 'LumaNest.exe')
            archive.writestr('HUONG_DAN_CAP_NHAT.txt', UPDATE_GUIDE)
        targets.append(update_target)

    # Verify each created archive and compute checksums
    for target in targets:
        is_upd = 'update' in target.name
        v_info = verify_archive(target, is_update=is_upd, root=ROOT)
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        manifests.append({
            'file': target.name,
            'path': str(target.resolve()),
            'bytes': target.stat().st_size,
            'sha256': digest,
            'total_files': v_info['total_files'],
            'ui_verification': v_info,
        })

    (output / 'SHA256SUMS.txt').write_text(
        ''.join(f"{item['sha256']}  {item['file']}\n" for item in manifests),
        encoding='utf-8'
    )
    (output / 'release-manifest.json').write_text(
        json.dumps({'version': version, 'files': manifests}, indent=2),
        encoding='utf-8'
    )

    print_report(version, manifests)
    return targets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--windows', action='store_true', help='Enforce presence of Windows launcher LumaNest.exe')
    parser.add_argument('--type', choices=['all', 'full', 'update'], default='all',
                        help='Choose package type: all (both), full (new users), update (UI update)')
    parser.add_argument('--name', default='FSmartMemories', help='Package base name (default: FSmartMemories)')
    args = parser.parse_args()
    build(windows=args.windows, package_type=args.type, app_name=args.name)
