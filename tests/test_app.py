import io
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fsmart.app import create_app
from fsmart.config import Settings


class TestModels:
    __test__ = False
    key = 'test-encoder:1'

    def analyze(self, image):
        # Deliberate API test double; actual inference is tested separately.
        red, green, blue = image.getpixel((0, 0))
        embedding = [1., 0., 0.] if red > green else [0., 1., 0.]
        return [{'bbox': [0, 0, 30, 30], 'confidence': .99, 'embedding': embedding}, {'bbox': [32, 0, 60, 30], 'confidence': .98, 'embedding': embedding}]

    def status(self):
        return {'face_ready': True, 'presets_ready': True, 'custom_ready': True, 'face_model': 'test', 'device': 'cpu'}

    def preset(self, image, style, strength, progress, profile='fast'):
        progress(.5, 'Testing output persistence')
        return image

    def custom(self, image, style, strength, steps, progress):
        return image


def image_bytes(color):
    out = io.BytesIO()
    Image.new('RGB', (64, 64), color).save(out, 'PNG')
    return out.getvalue()


def wait(client, job_id):
    for _ in range(100):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ['done', 'error']:
            assert job['status'] == 'done', job
            return job
        time.sleep(.03)
    pytest.fail('Background job did not finish')


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / 'runtime', weights_dir=tmp_path / 'weights'), TestModels())
    with TestClient(app) as client:
        yield client


def upload(client, album, name, color):
    response = client.post(f'/api/albums/{album}/photos', files=[('files', (name, image_bytes(color), 'image/png'))])
    assert response.status_code == 202
    if response.json()['job_id']:
        wait(client, response.json()['job_id'])
    return response.json()


def test_end_to_end_album_search_style_download_and_delete(client):
    album = client.post('/api/albums', json={'name': 'F-Camp'}).json()['id']
    upload(client, album, '../../red.png', 'red')
    upload(client, album, 'green.png', 'green')
    assert upload(client, album, 'duplicate.png', 'red')['duplicates'] == 1
    photos = client.get(f'/api/albums/{album}/photos').json()
    assert len(photos) == 2
    assert all(row['face_count'] == 2 for row in photos)
    assert any(row['name'] == 'red.png' for row in photos)
    query = client.post('/api/query', files={'file': ('query.png', image_bytes('red'), 'image/png')}).json()
    found = client.post('/api/search', json={'album_id': album, 'query_id': query['id'], 'threshold': .5}).json()['results']
    assert len(found) == 1  # multiple matching faces collapse to one photo
    assert found[0]['name'] == 'red.png'
    response = client.post('/api/stylize', data={'photo_id': found[0]['id'], 'style_id': 'mosaic', 'strength': .8})
    assert response.status_code == 202
    result = wait(client, response.json()['job_id'])['result']
    rendered = client.get(result['download_url'])
    assert rendered.status_code == 200 and rendered.content.startswith(b'\x89PNG')
    assert 'attachment' in rendered.headers['content-disposition']
    assert len(client.get('/api/outputs').json()) == 1
    archive = client.post('/api/export', json={'photo_ids': [found[0]['id']]} )
    assert archive.content.startswith(b'PK')
    assert client.delete(f'/api/photos/{found[0]["id"]}').status_code == 200
    assert client.get(result['image_url']).status_code == 404
    assert client.get(f'/api/photos/{found[0]["id"]}/image').status_code == 404


def test_validation_isolation_and_cross_origin(client):
    assert client.post('/api/albums', json={'name': '   '}).status_code == 422
    assert client.post('/api/albums', json={'name': 'Injected'}, headers={'Origin': 'https://external.example'}).status_code == 403
    album = client.post('/api/albums', json={'name': 'A'}).json()['id']
    other = client.post('/api/albums', json={'name': 'B'}).json()['id']
    upload(client, album, 'red.png', 'red')
    bad = client.post(f'/api/albums/{album}/photos', files=[('files', ('fake.jpg', b'not an image', 'image/jpeg'))]).json()
    assert bad['accepted'] == 0 and len(bad['errors']) == 1
    query = client.post('/api/query', files={'file': ('q.png', image_bytes('red'), 'image/png')}).json()
    assert client.post('/api/search', json={'album_id': other, 'query_id': query['id']}).json()['results'] == []
    assert client.post('/api/search', json={'album_id': album, 'query_id': query['id'], 'face_index': 100}).status_code == 422
    assert client.post('/api/search', json={'album_id': album, 'query_id': query['id'], 'threshold': 5}).status_code == 422
    assert client.get('/api/photos/not-a-photo/image').status_code == 404
    assert client.post('/api/stylize', data={'photo_id': 'missing', 'style_id': 'mosaic'}).status_code == 404


def test_cosine_threshold_and_model_version_are_enforced(client):
    album = client.post('/api/albums', json={'name': 'A'}).json()['id']
    upload(client, album, 'green.png', 'green')
    query = client.post('/api/query', files={'file': ('q.png', image_bytes('red'), 'image/png')}).json()
    assert client.post('/api/search', json={'album_id': album, 'query_id': query['id'], 'threshold': .3}).json()['results'] == []
    client.app.state.models.key = 'new-encoder'
    assert client.post('/api/search', json={'album_id': album, 'query_id': query['id']}).status_code == 409


def test_source_image_alignment_identity_transform():
    from fsmart.models import align_face
    points = [[38.2946, 51.6963], [73.5318, 51.5014], [56.0252, 71.7366], [41.5493, 92.3655], [70.7299, 92.2041]]
    array = np.zeros((112, 112, 3), dtype=np.uint8)
    array[30:80, 25:75] = [220, 20, 100]
    output = np.asarray(align_face(Image.fromarray(array), points))
    assert np.abs(output.astype(float) - array).mean() < 1


def test_saved_reference_restores_without_exposing_embeddings_and_can_refresh(client):
    assert client.get('/api/query/latest').json() is None
    first = client.post('/api/query', files={'file': ('q1.png', image_bytes('red'), 'image/png')}).json()
    second = client.post('/api/query', files={'file': ('q2.png', image_bytes('green'), 'image/png')}).json()
    assert client.get('/api/query/latest').json()['id'] == second['id']
    saved = client.get(f'/api/query/{first["id"]}').json()
    assert saved['width'] == 64 and saved['height'] == 64 and saved['model_current']
    assert len(saved['faces']) == 2 and 'embedding' not in str(saved)
    client.app.state.models.key = 'new-pipeline'
    assert not client.get(f'/api/query/{first["id"]}').json()['model_current']
    refreshed = client.post(f'/api/query/{first["id"]}/refresh')
    assert refreshed.status_code == 200 and refreshed.json()['model_current']
    assert refreshed.json()['id'] == first['id']
    assert client.get('/api/query/missing').status_code == 404
    assert client.post('/api/query/missing/refresh').status_code == 404


def test_search_reports_pending_photos_and_outdated_index_instead_of_silent_empty(client):
    album = client.post('/api/albums', json={'name': 'A'}).json()['id']
    upload(client, album, 'red.png', 'red')
    upload(client, album, 'green.png', 'green')
    query = client.post('/api/query', files={'file': ('q.png', image_bytes('red'), 'image/png')}).json()
    payload = {'album_id': album, 'query_id': query['id']}
    store = client.app.state.store
    green = store.one('SELECT id FROM photos WHERE name=?', ('green.png',))['id']
    store.execute("UPDATE photos SET status='queued' WHERE id=?", (green,))
    result = client.post('/api/search', json=payload).json()
    assert len(result['results']) == 1
    assert result['album_status'] == {'total': 2, 'processing': 1, 'failed': 0, 'indexed': 1, 'outdated': 0}
    store.execute("UPDATE photos SET status='ready',model_key='old'", ())
    assert client.post('/api/search', json=payload).status_code == 409
    job = client.post(f'/api/albums/{album}/reindex').json()['job_id']
    wait(client, job)
    result = client.post('/api/search', json=payload).json()
    assert result['album_status']['outdated'] == 0 and len(result['results']) == 1


def test_detection_resize_does_not_reduce_alignment_source_resolution(tmp_path, monkeypatch):
    torch = pytest.importorskip('torch')
    import fsmart.models as module
    models = module.Models(Settings(data_dir=tmp_path/'runtime', weights_dir=tmp_path/'weights'))
    models._torch, models.device = torch, torch.device('cpu')
    original_points = np.array([[500, 400], [550, 400], [525, 425], [505, 450], [545, 450]], dtype=float)
    calls = []

    class Detector:
        def detect(self, image, landmarks=True):
            assert image.size == (2560, 1280)
            return np.array([[480, 380, 570, 470]])*.8, np.array([.99]), np.array([original_points*.8])

    class Encoder:
        def __call__(self, batch):
            calls.append(batch.clone())
            return batch.mean(dim=(2, 3)) + torch.tensor([2., 3., 4.])

    def alignment(image, points):
        assert image.size == (3200, 1600)
        assert np.allclose(points, original_points)
        pixels = np.zeros((112, 112, 3), dtype=np.uint8)
        pixels[:, :40, 0] = 255
        return Image.fromarray(pixels)

    models._detector, models._encoder = Detector(), Encoder()
    monkeypatch.setattr(module, 'align_face', alignment)
    result = models.analyze(Image.new('RGB', (3200, 1600)))
    assert len(result) == 1 and result[0]['bbox'] == [480, 380, 570, 470]
    assert torch.equal(calls[1], torch.flip(calls[0], [3]))
    assert np.linalg.norm(result[0]['embedding']) == pytest.approx(1.)
