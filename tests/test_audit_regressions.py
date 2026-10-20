"""User-visible failure cases found during the strict system review."""
import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fsmart.app import create_app
from fsmart.config import Settings
from test_app import TestModels, image_bytes, wait


def album_with_photo(client):
    album = client.post('/api/albums', json={'name': 'Audit'}).json()['id']
    uploaded = client.post(f'/api/albums/{album}/photos', files={'files':('a.png',image_bytes('red'),'image/png')}).json()
    wait(client, uploaded['job_id'])
    return album, client.get(f'/api/albums/{album}/photos').json()[0]['id']


@pytest.fixture
def audit_client(tmp_path):
    app = create_app(Settings(data_dir=tmp_path/'runtime'), TestModels())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def style(client, photo, headers=None):
    response = client.post('/api/stylize', data={'photo_id':photo,'style_id':'mosaic'},headers=headers or {})
    assert response.status_code == 202, response.text
    return response.json()['job_id']


def test_all_failed_batch_must_not_claim_success(audit_client):
    client=audit_client
    album, photo=album_with_photo(client)
    def fail(*args, **kwargs):
        raise RuntimeError('Intentional failure')
    client.app.state.models.preset=fail
    job_id=client.post('/api/stylize/batch',json={'album_id':album,'style':'mosaic'}).json()['job_id']
    for _ in range(100):
        job=client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'error','done'}:
            break
        time.sleep(.02)
    assert job['status']=='error', job
    assert job['result']['failed']==1 and job['result']['completed']==0


def test_corrupt_cached_png_is_recomputed_instead_of_served(audit_client):
    client=audit_client
    _,photo=album_with_photo(client)
    first=wait(client,style(client,photo))['result']
    path=client.app.state.settings.data_dir/'outputs'/f'{first["output_id"]}.png'
    path.write_bytes(b'not a PNG')
    second=wait(client,style(client,photo))['result']
    assert not second['cached']
    response=client.get(second['image_url'])
    with Image.open(io.BytesIO(response.content)) as result:
        result.verify()


def test_missing_output_is_actionable_404_not_server_error(audit_client):
    client=audit_client
    _,photo=album_with_photo(client)
    result=wait(client,style(client,photo))['result']
    (client.app.state.settings.data_dir/'outputs'/f'{result["output_id"]}.png').unlink()
    response=client.get(result['image_url'])
    assert response.status_code==404, response.text


def test_repeated_request_key_does_not_duplicate_work(audit_client):
    client=audit_client
    _,photo=album_with_photo(client)
    headers={'Idempotency-Key':'audit-request-12345678'}
    first=style(client,photo,headers)
    wait(client,first)
    second=style(client,photo,headers)
    assert first==second


def test_corrupt_embedding_returns_reindex_instruction(audit_client):
    import numpy as np
    client=audit_client
    album,photo=album_with_photo(client)
    query=client.post('/api/query',files={'file':('q.png',image_bytes('red'),'image/png')}).json()
    client.app.state.store.execute('UPDATE faces SET embedding=? WHERE photo_id=?',(np.array([float('nan'),0,0],dtype=np.float32).tobytes(),photo))
    result=client.post('/api/search',json={'album_id':album,'query_id':query['id']})
    assert result.status_code==409, result.text
    assert 'chỉ mục' in result.json()['detail']
