"""Atomic PNG outputs and integrity checks, shared by single and bulk jobs."""
import hashlib
import json
from pathlib import Path

from PIL import Image

from .store import now, uid
from .storage import ensure_space


def file_digest(path: Path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def valid_output(store, directory, output_id):
    path = directory/'outputs'/f'{output_id}.png'
    try:
        metadata = store.one('SELECT * FROM output_assets WHERE output_id=?', (output_id,))
        if metadata:
            return path.stat().st_size == metadata['bytes'] and file_digest(path) == metadata['sha256']
        # Outputs created before integrity metadata existed must also be decoded.
        with Image.open(path) as image:
            if image.format != 'PNG':
                return False
            width, height = image.size
            image.verify()
        store.execute('INSERT OR IGNORE INTO output_assets VALUES(?,?,?,?,?,?,?)',
                      (output_id, file_digest(path), path.stat().st_size, width, height, 'legacy', '{}'))
        return True
    except (OSError, ValueError):
        return False


def save_output(store, settings, image, photo_id, style, title=None, metadata=None):
    ensure_space(settings,image.width*image.height*3+16384)
    output_id = uid()
    path = settings.data_dir/'outputs'/f'{output_id}.png'
    temporary = path.with_suffix('.tmp')
    try:
        image.save(temporary, 'PNG', compress_level=1)
        digest, size = file_digest(temporary), temporary.stat().st_size
        temporary.replace(path)
        info = metadata or {}
        with store.connection() as db:
            db.execute('INSERT INTO outputs(id,photo_id,style,created) VALUES(?,?,?,?)', (output_id, photo_id, style, now()))
            if title:
                db.execute('INSERT INTO output_details VALUES(?,?)', (output_id, title))
            db.execute('INSERT INTO output_assets VALUES(?,?,?,?,?,?,?)',
                       (output_id, digest, size, image.width, image.height, info.get('profile', 'custom'), json.dumps(info)))
        return output_id
    except BaseException:
        temporary.unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        raise
