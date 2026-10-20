from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

# User uploads have no pixel ceiling, including when reopened by background jobs.
# Externally generated references still pass their own explicit limit to decode_image.
Image.MAX_IMAGE_PIXELS = None


def decode_image(data: bytes, max_pixels: int | None = None) -> Image.Image:
    try:
        with Image.open(io.BytesIO(data), formats=('JPEG','PNG','WEBP')) as source:
            if min(source.size) < 16:
                raise ValueError('Mỗi chiều ảnh cần ít nhất 16 pixel.')
            if max_pixels is not None and source.width * source.height > max_pixels:
                raise ValueError(f'Ảnh tham chiếu vượt giới hạn {max_pixels:,} pixel của tác vụ này.')
            oriented = ImageOps.exif_transpose(source)
            if oriented.mode == 'RGB':
                return oriented
            with oriented:
                return oriented.convert('RGB')
    except MemoryError:
        raise ValueError('Không đủ RAM để đọc ảnh này ở kích thước gốc. Đóng bớt tác vụ hoặc thử lại trên máy có nhiều RAM hơn.') from None
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError('File ảnh không hợp lệ hoặc bộ giải mã không đọc được ảnh.') from exc


def image_digest(image: Image.Image) -> str:
    """Preserve existing duplicate IDs without making a full-size bytes copy."""
    digest = hashlib.sha256()
    for top in range(0,image.height,128):
        with image.crop((0,top,image.width,min(top+128,image.height))) as strip:
            digest.update(strip.tobytes())
    digest.update(str(image.size).encode())
    return digest.hexdigest()


def save_photo(image: Image.Image, original: Path, thumbnail: Path) -> str:
    # Decode/re-encode removes arbitrary filenames, embedded payloads and EXIF metadata.
    pending = [original.with_suffix('.tmp'),thumbnail.with_suffix('.tmp')]
    try:
        image.save(pending[0], 'JPEG', quality=95)
        thumb = image.copy()
        thumb.thumbnail((640, 480), Image.Resampling.LANCZOS)
        thumb.save(pending[1], 'JPEG', quality=86)
        pending[0].replace(original)
        pending[1].replace(thumbnail)
    finally:
        for path in pending:
            path.unlink(missing_ok=True)
    return image_digest(image)


def save_source(data, path):
    pending = path.with_suffix('.tmp')
    try:
        pending.write_bytes(data)
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def resized(image: Image.Image, max_side: int) -> Image.Image:
    image = image.copy()
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image
