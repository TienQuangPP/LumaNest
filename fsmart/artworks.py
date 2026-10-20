"""Curated public-domain style reference; never resolve paths or URLs from chat."""
import hashlib
from PIL import Image

ARTWORK={'id':'met:436535','title':'Van Gogh · Wheat Field with Cypresses','artist':'Vincent van Gogh',
         'source_url':'https://www.metmuseum.org/art/collection/search/436535',
         'download_url':'https://images.metmuseum.org/CRDImages/ep/web-large/DP-42549-001.jpg',
         'sha256':'af0e3486621c210b54932d055294051b5601aa3362af4b84ab97e2831f8163bc',
         'filename':'van_gogh_436535.jpg','public_domain':True}

def reference(settings):
    from .chat import ChatUnavailable
    path=settings.weights_dir/'artworks'/ARTWORK['filename']
    try:
        with path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=ARTWORK['sha256']:raise ValueError('Checksum mismatch')
        with Image.open(path) as source:return source.convert('RGB')
    except (OSError,ValueError):
        raise ChatUnavailable('Thiếu hoặc hỏng tranh tham chiếu Van Gogh. Chạy scripts/fetch_assets.py --only artworks.') from None
