import io
import json
import threading
import time
import zipfile

import pytest
from fastapi.testclient import TestClient

from fsmart.app import create_app
from fsmart.config import Settings
from test_app import TestModels, image_bytes, wait
from fsmart.store import now, uid
from PIL import Image


class BlockingModels(TestModels):
    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.calls = []
        self.fail = False

    def preset(self, image, style, strength, progress, profile='fast'):
        self.calls.append((style, profile))
        if self.block:
            self.block = False
            self.entered.set()
            assert self.release.wait(5), 'Test did not release inference'
        if self.fail and image.getpixel((0, 0))[0] > 200:
            raise RuntimeError('Deliberate per-image failure')
        return image


def setup_album(client):
    album = client.post('/api/albums', json={'name': 'Bulk CPU test'}).json()['id']
    response = client.post(f'/api/albums/{album}/photos', files=[
        ('files', ('red.png', image_bytes('red'), 'image/png')),
        ('files', ('green.png', image_bytes('green'), 'image/png')),
    ]).json()
    wait(client, response['job_id'])
    return album


def until_terminal(client, job_id):
    for _ in range(200):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done', 'error', 'cancelled'}:
            return job
        time.sleep(.01)
    pytest.fail('Bulk task did not finish')


def submit(client, album, **kwargs):
    response = client.post('/api/stylize/batch', json={'album_id': album, 'style': 'mosaic', **kwargs})
    assert response.status_code == 202, response.text
    return response.json()['job_id']


def test_bulk_cache_profile_identity_zip_and_deletion(tmp_path):
    models = BlockingModels()
    app = create_app(Settings(data_dir=tmp_path/'runtime'), models)
    with TestClient(app) as client:
        album = setup_album(client)
        first = submit(client, album)
        job = until_terminal(client, first)
        assert job['status'] == 'done' and job['result']['completed'] == 2
        assert job['result']['cached'] == 0
        second = until_terminal(client, submit(client, album))
        assert second['result']['cached'] == 2 and len(models.calls) == 2
        changed = until_terminal(client, submit(client, album, profile='quality'))
        assert changed['result']['cached'] == 0 and len(models.calls) == 4
        response = client.get(job['result']['download_url'])
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len([name for name in archive.namelist() if name.endswith('.png')]) == 2
            assert len(json.loads(archive.read('report.json'))) == 2
        assert not list((tmp_path/'runtime/exports').glob('*.zip'))
        photos = client.get(f'/api/albums/{album}/photos').json()
        assert client.delete(f'/api/photos/{photos[0]["id"]}').status_code == 200
        assert client.get('/api/batches').json()[0]['kind'] == 'bulk-style'


def test_cancel_preserves_completed_work_and_resume_skips_it(tmp_path):
    models = BlockingModels()
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'), models)) as client:
        album = setup_album(client)
        models.block = True
        job_id = submit(client, album)
        try:
            assert models.entered.wait(3)
            assert client.post(f'/api/batches/{job_id}/cancel').json()['status'] == 'cancelled'
        finally:
            models.release.set()
        # The in-flight image finishes before a resumed step can run.
        assert client.post(f'/api/batches/{job_id}/resume').status_code == 202
        job = until_terminal(client, job_id)
        assert job['status'] == 'done' and job['result']['completed'] == 2
        assert len(models.calls) == 2


def test_failure_continues_other_images_and_retry_only_failed(tmp_path):
    models = BlockingModels()
    models.fail = True
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'), models)) as client:
        album = setup_album(client)
        job_id = submit(client, album)
        result = until_terminal(client, job_id)['result']
        assert result['failed'] == 1 and result['completed'] == 1
        models.fail = False
        client.post(f'/api/batches/{job_id}/resume')
        result = until_terminal(client, job_id)['result']
        assert result['completed'] == 2 and result['failed'] == 0
        assert len(models.calls) == 3


def test_restart_recovers_running_item_without_repeating_output(tmp_path):
    settings = Settings(data_dir=tmp_path/'runtime')
    models = BlockingModels()
    app = create_app(settings, models)
    with TestClient(app) as client:
        album = setup_album(client)
        job_id = submit(client, album)
        assert until_terminal(client, job_id)['result']['completed'] == 2
    store = app.state.store
    store.execute("UPDATE style_items SET status='running' WHERE job_id=? AND position=0", (job_id,))
    store.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
    replacement = BlockingModels()
    with TestClient(create_app(settings, replacement)) as client:
        job = until_terminal(client, job_id)
        assert job['status'] == 'done' and job['result']['completed'] == 2
        assert job['result']['cached'] == 1 and replacement.calls == []


def test_album_isolation_validation_and_fairness(tmp_path):
    models = BlockingModels()
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'), models)) as client:
        album = setup_album(client)
        photos = client.get(f'/api/albums/{album}/photos').json()
        other = client.post('/api/albums', json={'name': 'Other'}).json()['id']
        assert client.post('/api/stylize/batch', json={'album_id':other, 'photo_ids':[photos[0]['id']], 'style':'mosaic'}).status_code == 422
        assert client.post('/api/stylize/batch', json={'album_id':album, 'style':'custom'}).status_code == 422
        assert client.post('/api/stylize/batch', json={'album_id':album, 'style':'mosaic','profile':'unbounded'}).status_code == 422
        assert client.post('/api/batches/missing/resume').status_code == 404
        models.block = True
        job_id = submit(client, album)
        try:
            assert models.entered.wait(3)
            single = client.post('/api/stylize', data={'photo_id':photos[0]['id'], 'style_id':'candy'}).json()['job_id']
            assert client.delete(f'/api/photos/{photos[0]["id"]}').status_code == 409
        finally:
            models.release.set()
        wait(client, single)
        assert until_terminal(client, job_id)['result']['completed'] == 2
        assert [call[0] for call in models.calls] == ['mosaic', 'candy', 'mosaic']


def test_queue_200_images_has_complete_persistent_results(tmp_path):
    models = BlockingModels()
    app = create_app(Settings(data_dir=tmp_path/'runtime'), models)
    with TestClient(app) as client:
        album = client.post('/api/albums', json={'name':'200-image queue test'}).json()['id']
        rows = []
        for index in range(200):
            photo_id = uid()
            Image.new('RGB', (32, 32), (index, 90, 50)).save(tmp_path/'runtime/photos'/f'{photo_id}.jpg')
            rows.append((photo_id, album, str(index), str(index), 32, 32, 'ready', now()))
        with app.state.store.connection() as db:
            db.executemany('INSERT INTO photos(id,album_id,name,digest,width,height,status,created) VALUES(?,?,?,?,?,?,?,?)', rows)
        job_id = submit(client, album)
        # This tests scheduler/SQLite scale with a cheap model double, not ML throughput.
        for _ in range(900):
            job = client.get(f'/api/jobs/{job_id}').json()
            if job['status'] == 'done':
                break
            time.sleep(.05)
        assert job['status'] == 'done' and job['result']['completed'] == 200
        assert len(models.calls) == 200
        assert app.state.store.one("SELECT count(*) n FROM style_items WHERE job_id=? AND status='pending'", (job_id,))['n'] == 0
