"""Built-in style library: public-domain artworks applied on this machine by VGG19 (GPU when available)."""
import hashlib, io, threading

from PIL import Image

from .artworks import ARTWORK
from .style_library_data import GROUPS, STYLES as _STYLES

STYLES = _STYLES + [{'key': 'van-gogh-wheat-field', 'name': 'Cánh đồng lúa và cây bách · Van Gogh', 'group': 'Hậu ấn tượng',
                     'title': 'Wheat Field with Cypresses', 'artist': ARTWORK['artist'], 'date': '1889', 'source': ARTWORK['id'],
                     'licence': 'CC0 (The Met Open Access)', 'source_url': ARTWORK['source_url'], 'download_url': ARTWORK['download_url'],
                     'sha256': ARTWORK['sha256'], 'filename': ARTWORK['filename']}]
BY_KEY = {item['key']: item for item in STYLES}
_verified, _thumbs, _lock = {}, {}, threading.Lock()


def path(settings, item):
    return settings.weights_dir / 'artworks' / item['filename']


def ready(settings, item):
    return path(settings, item).is_file()


def _verified_bytes(settings, item):
    """File bytes after a SHA-256 check (cached per size and mtime so the grid stays fast)."""
    file = path(settings, item)
    try:
        stat = file.stat()
        data = file.read_bytes()
    except OSError:
        raise FileNotFoundError(item['key']) from None
    stamp = (stat.st_size, stat.st_mtime_ns)
    with _lock:
        known = _verified.get(item['key']) == stamp
    if not known:
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError(f"Checksum mismatch for {item['key']}")
        with _lock:
            _verified[item['key']] = stamp
    return data


def load(settings, key):
    item = BY_KEY[key]
    with Image.open(io.BytesIO(_verified_bytes(settings, item))) as source:
        return source.convert('RGB')


def thumbnail(settings, key, size=360):
    with _lock:
        if key in _thumbs:
            return _thumbs[key]
    image = load(settings, key)
    image.thumbnail((size, size))
    buffer = io.BytesIO(); image.save(buffer, 'JPEG', quality=84)
    with _lock:
        _thumbs[key] = buffer.getvalue()
    return _thumbs[key]


def listing(settings):
    return {'groups': GROUPS, 'styles': [{'key': item['key'], 'name': item['name'], 'group': item['group'], 'title': item['title'],
                                          'artist': item['artist'], 'date': item['date'], 'licence': item['licence'],
                                          'source_url': item['source_url'], 'ready': ready(settings, item),
                                          'thumb_url': f"/api/style-library/{item['key']}/thumb"} for item in STYLES]}
