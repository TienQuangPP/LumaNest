import hashlib, io, re
from urllib.parse import urlsplit

import pytest
from PIL import Image

import fsmart.style_library as library
from fsmart.chat import ChatService
from test_style_chat import client_for, upload, wait_job


def test_catalog_is_pinned_public_domain_and_unique():
    keys = [item['key'] for item in library.STYLES]
    assert len(keys) == len(set(keys)) >= 40
    assert {item['group'] for item in library.STYLES} <= set(library.GROUPS)
    for item in library.STYLES:
        host = urlsplit(item['download_url'])
        assert host.scheme == 'https' and host.hostname in {'images.metmuseum.org', 'upload.wikimedia.org', 'thumb.wikimedia.org'}, item['key']
        assert re.fullmatch(r'[0-9a-f]{64}', item['sha256']) and re.fullmatch(r'[\w.-]+\.jpg', item['filename'])
        assert 'public domain' in item['licence'].lower() or 'cc0' in item['licence'].lower(), item['key']
        assert item['name'] and item['artist'] and item['source_url'].startswith('https://')


def install(tmp_path, monkeypatch, key, color):
    """Put a tiny painting in the test weights and pin the catalog entry to it."""
    buffer = io.BytesIO(); Image.new('RGB', (40, 30), color).save(buffer, 'JPEG', quality=95)
    data = buffer.getvalue()
    item = dict(library.BY_KEY[key], sha256=hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(library.BY_KEY, key, item)
    monkeypatch.setattr(library, 'STYLES', [item if s['key'] == key else s for s in library.STYLES])
    library._verified.clear(); library._thumbs.clear()
    folder = tmp_path / 'weights' / 'artworks'; folder.mkdir(parents=True, exist_ok=True)
    (folder / item['filename']).write_bytes(data)
    return item


def test_library_painting_is_applied_locally_with_its_name(tmp_path, monkeypatch):
    item = install(tmp_path, monkeypatch, 'klimt-kiss', (200, 160, 20))
    service = ChatService(api_key='', post=lambda *a, **k: pytest.fail('the library never calls an API'))
    with client_for(tmp_path, service) as client:
        listing = client.get('/api/style-library').json()
        ready = {s['key']: s['ready'] for s in listing['styles']}
        assert ready['klimt-kiss'] and not ready['munch-scream'] and len(listing['styles']) == len(library.STYLES)
        thumb = client.get('/api/style-library/klimt-kiss/thumb')
        assert thumb.status_code == 200 and thumb.headers['content-type'] == 'image/jpeg'
        assert client.get('/api/style-library/munch-scream/thumb').status_code == 404
        photo = upload(client)
        job = client.post('/api/stylize', data={'photo_id': photo, 'style_id': 'custom', 'strength': '.7', 'steps': '50', 'library_key': 'klimt-kiss'})
        done = wait_job(client, job.json()['job_id'])
        assert done['status'] == 'done' and done['result']['style_label'] == item['name']
        (call,) = client.app.state.models.calls
        assert call[0] == 'custom' and call[2] == .7 and call[3] == 50 and max(abs(a - b) for a, b in zip(call[1], (200, 160, 20))) < 8
        assert client.get('/api/outputs').json()[0]['title'] == item['name']
        assert list((tmp_path / 'runtime' / 'styles').iterdir()) == []  # temporary reference is cleaned


def test_unknown_missing_or_tampered_paintings_are_refused(tmp_path, monkeypatch):
    install(tmp_path, monkeypatch, 'klimt-kiss', 'red')
    (tmp_path / 'weights' / 'artworks' / library.BY_KEY['klimt-kiss']['filename']).write_bytes(b'tampered')
    with client_for(tmp_path, ChatService(api_key='')) as client:
        photo = upload(client)
        form = {'photo_id': photo, 'style_id': 'custom', 'steps': '50'}
        assert client.post('/api/stylize', data={**form, 'library_key': '../../etc/passwd'}).status_code == 422
        assert client.post('/api/stylize', data={**form, 'library_key': 'munch-scream'}).status_code == 503
        assert client.post('/api/stylize', data={**form, 'library_key': 'klimt-kiss'}).status_code == 503
        assert client.post('/api/stylize', data=form).status_code == 422  # neither an upload nor a library painting
        assert not client.app.state.models.calls
