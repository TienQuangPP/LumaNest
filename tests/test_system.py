import hashlib
import base64
import re
import io
import json
import time
import zipfile

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fsmart.app import create_app
from fsmart.config import Settings
from fsmart.jobs import StyleAdmission, AdmissionError
from fsmart.store import now, uid
from test_app import TestModels, image_bytes, wait
from test_audit_regressions import album_with_photo, style


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'),TestModels())) as client:
        yield client


def test_api_docs_csp_allows_exact_boot_code_without_relaxing_the_app(client):
    for path in ['/docs','/redoc','/docs/oauth2-redirect']:
        response=client.get(path)
        assert response.status_code==200
        policy=response.headers['content-security-policy']
        assert "'unsafe-inline'" not in policy.split(';')[1]
        for script in re.findall(rb'<script>(.*?)</script>',response.content,re.S):
            digest=base64.b64encode(hashlib.sha256(script).digest()).decode('ascii')
            assert f"'sha256-{digest}'" in policy
    assert 'cdn.jsdelivr.net' not in client.get('/').headers['content-security-policy']


def test_original_upload_is_byte_exact_and_zip_reports_it(client):
    album=client.post('/api/albums',json={'name':'Original test'}).json()['id']
    original=image_bytes('red')
    imported=client.post(f'/api/albums/{album}/photos',files={'files':('original.png',original,'image/png')}).json()
    wait(client,imported['job_id'])
    photo=client.get(f'/api/albums/{album}/photos').json()[0]['id']
    assert client.get(f'/api/photos/{photo}/original').content==original
    assert client.get(f'/api/photos/{photo}').json()['original_available']
    check=next(item for item in client.post('/api/system/verify').json()['checks'] if item['id']=='invalid_sources')
    assert check['applicable'] is True and check['checked_count']==1
    archive=client.post('/api/export',json={'photo_ids':[photo]})
    with zipfile.ZipFile(io.BytesIO(archive.content)) as result:
        assert result.read(f'{photo}.png')==original
        assert json.loads(result.read('manifest.json'))[0]['byte_original'] is True


def test_exif_orientation_preserved_in_original_and_normalized_for_processing(client):
    album=client.post('/api/albums',json={'name':'EXIF'}).json()['id']
    image=Image.new('RGB',(80,40),'red');exif=image.getexif();exif[274]=6
    buffer=io.BytesIO();image.save(buffer,'JPEG',exif=exif)
    imported=client.post(f'/api/albums/{album}/photos',files={'files':('rotated.jpg',buffer.getvalue(),'image/jpeg')}).json()
    wait(client,imported['job_id'])
    row=client.get(f'/api/albums/{album}/photos').json()[0]
    assert (row['width'],row['height'])==(40,80)
    assert client.get(f'/api/photos/{row["id"]}/original').content==buffer.getvalue()


def test_legacy_source_is_explicitly_labeled(client):
    _,photo=album_with_photo(client)
    client.app.state.store.execute('DELETE FROM photo_sources WHERE photo_id=?',(photo,))
    response=client.get(f'/api/photos/{photo}/original')
    assert response.status_code==200 and response.headers['x-original-available']=='false'
    report=client.post('/api/system/verify').json()
    assert report['counts']['legacy_sources']==1 and any('bản cũ' in text for text in report['warnings'])
    check=next(item for item in report['checks'] if item['id']=='invalid_sources')
    assert check['applicable'] is False and check['checked_count']==0


def test_verify_detects_corruption_and_repairs_only_thumbnail(client):
    album,photo=album_with_photo(client)
    source=client.get(f'/api/photos/{photo}/original').content
    thumb=client.app.state.settings.data_dir/'thumbs'/f'{photo}.jpg'
    thumb.write_bytes(b'broken')
    report=client.post('/api/system/verify').json()
    assert not report['passed'] and report['counts']['missing_thumbnails']==1
    assert not report['accuracy_evaluated']
    repaired=client.post('/api/system/repair-thumbnails').json()
    assert repaired=={'repaired':1,'failed':0}
    assert client.get(f'/api/photos/{photo}/original').content==source
    assert client.post('/api/system/verify').json()['passed']


def test_export_ticket_streams_same_bytes_and_can_resume(client):
    _,photo=album_with_photo(client)
    ticket=client.post('/api/exports',json={'photo_ids':[photo]}).json()
    response=client.get(ticket['download_url'])
    assert response.status_code==200 and response.content[:2]==b'PK'
    partial=client.get(ticket['download_url'],headers={'Range':'bytes=0-15'})
    assert partial.status_code==206 and partial.content==response.content[:16]


def test_host_body_limits_and_security_headers(client):
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==400
    response=client.get('/api/health')
    assert response.headers['x-content-type-options']=='nosniff'
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert response.headers['cache-control']=='no-store'
    assert client.post('/api/albums',json={'name':'A'},headers={'Content-Length':str(2*1024*1024)}).status_code==413
    def chunks():
        yield b'{"name":"'
        yield b'x'*(1024*1024)
        yield b'"}'
    result=client.post('/api/albums',content=chunks(),headers={'Content-Type':'application/json'})
    assert result.status_code==413, result.text


def test_request_identity_rejects_parameter_changes(client):
    _,photo=album_with_photo(client)
    key={'Idempotency-Key':'unique-audit-request-98765'}
    first=style(client,photo,key);wait(client,first)
    conflict=client.post('/api/stylize',data={'photo_id':photo,'style_id':'candy'},headers=key)
    assert conflict.status_code==409
    assert client.post('/api/stylize',data={'photo_id':photo,'style_id':'candy'},headers={'Idempotency-Key':'bad'}).status_code==422


def test_admission_has_a_hard_queue_limit(client):
    _,photo=album_with_photo(client)
    admission=StyleAdmission(client.app.state.store)
    for i in range(20):
        admission.admit(photo,{'request':i},f'audit-request-key-{i:04d}')
    with pytest.raises(AdmissionError) as error:
        admission.admit(photo,{'request':21})
    assert error.value.status_code==429


def test_reindex_outdated_includes_logically_corrupt_embeddings(client):
    album,photo=album_with_photo(client)
    client.app.state.store.execute('UPDATE faces SET embedding=? WHERE photo_id=?',(np.array([float('nan'),0,0],dtype=np.float32).tobytes(),photo))
    response=client.post(f'/api/albums/{album}/reindex',json={'scope':'outdated'})
    assert response.status_code==202
    wait(client,response.json()['job_id'])
    assert not client.app.state.store.corrupt_face_photos(album)


def test_reindex_failed_does_not_recompute_healthy_photos(client):
    album,photo=album_with_photo(client)
    response=client.post(f'/api/albums/{album}/reindex',json={'scope':'failed'})
    assert response.status_code==422
    client.app.state.store.execute("UPDATE photos SET status='error' WHERE id=?",(photo,))
    response=client.post(f'/api/albums/{album}/reindex',json={'scope':'failed'})
    assert response.status_code==202 and response.json()['total']==1
    wait(client,response.json()['job_id'])


def test_output_pagination_and_album_isolation(client):
    album,photo=album_with_photo(client)
    wait(client,style(client,photo))
    other=client.post('/api/albums',json={'name':'Other'}).json()['id']
    assert len(client.get(f'/api/outputs?album_id={album}&limit=1').json())==1
    assert client.get(f'/api/outputs?album_id={other}').json()==[]
    assert client.get('/api/outputs?offset=-1').status_code==422
    assert client.get('/api/outputs?limit=101').status_code==422


def test_rename_album_does_not_change_photos_or_faces(client):
    album,photo=album_with_photo(client)
    response=client.patch(f'/api/albums/{album}',json={'name':'New name'})
    assert response.status_code==200
    assert client.get(f'/api/albums/{album}/photos').json()[0]['id']==photo
    assert client.get(f'/api/albums/{album}/photos').json()[0]['face_count']==2
    assert client.patch(f'/api/albums/{album}',json={'name':'   '}).status_code==422


def test_rank_streaming_matches_bruteforce_across_chunks(client):
    album,photo=album_with_photo(client)
    store=client.app.state.store
    store.execute('DELETE FROM faces')
    rng=np.random.default_rng(14)
    vectors=rng.normal(size=(1100,3)).astype(np.float32)
    vectors/=np.linalg.norm(vectors,axis=1,keepdims=True)
    # One photo spans the 1024-face block boundary.
    with store.connection() as db:
        db.executemany('INSERT INTO faces VALUES(?,?,?,?,?,?)',[(uid(),photo,'[0,0,20,20]',.99,v.tobytes(),TestModels.key) for v in vectors])
    q=np.array([1,2,3],dtype=np.float32);q/=np.linalg.norm(q)
    results=store.rank(album,q,TestModels.key,-1,10)
    assert len(results)==1
    assert results[0]['similarity']==pytest.approx(float((vectors@q).max()),abs=1e-6)


def test_face_index_recovery_reuses_completed_items(tmp_path):
    settings=Settings(data_dir=tmp_path/'runtime')
    app=create_app(settings,TestModels())
    with TestClient(app) as client:
        album,photo=album_with_photo(client)
        job=app.state.store.one("SELECT id FROM jobs WHERE kind='index'")['id']
    store=app.state.store
    store.execute("UPDATE photos SET status='queued' WHERE id=?",(photo,))
    store.execute("UPDATE index_items SET status='running' WHERE job_id=?",(job,))
    store.execute("UPDATE jobs SET status='running' WHERE id=?",(job,))
    with TestClient(create_app(settings,TestModels())) as client:
        result=wait(client,job)
        assert result['result']['indexed']==1
        assert client.get(f'/api/albums/{album}/photos').json()[0]['status']=='ready'


def test_disk_pressure_rejects_import_without_partial_files(client,monkeypatch):
    from collections import namedtuple
    import fsmart.storage as storage
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:usage(1_000_000,999_000,1000))
    album=client.post('/api/albums',json={'name':'Low disk'}).json()['id']
    response=client.post(f'/api/albums/{album}/photos',files={'files':('a.png',image_bytes('red'),'image/png')})
    data=response.json()
    assert data['accepted']==0 and data['job_id'] is None
    assert 'dung lượng' in data['errors'][0]['message']
    assert not list((client.app.state.settings.data_dir/'photos').glob('*'))
    assert not list((client.app.state.settings.data_dir/'originals').glob('*'))


def test_disk_pressure_rejects_bulk_and_export_before_growing_files(client,monkeypatch):
    from collections import namedtuple
    import fsmart.storage as storage
    album,photo=album_with_photo(client)
    usage=namedtuple('usage','total used free')
    monkeypatch.setattr(storage.shutil,'disk_usage',lambda path:usage(1000,999,1))
    assert client.post('/api/stylize/batch',json={'album_id':album,'style':'mosaic'}).status_code==507
    assert client.post('/api/export',json={'photo_ids':[photo]}).status_code==507
    assert not list((client.app.state.settings.data_dir/'exports').glob('*'))


def test_chat_recipe_profile_is_part_of_identity(tmp_path):
    from fsmart.chat import ChatService
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'),TestModels(),ChatService(api_key=''))) as client:
        _,photo=album_with_photo(client)
        plan=client.post('/api/chat',json={'mode':'style','message':'Mosaic 65%'}).json()['style_plan']['id']
        first=client.post('/api/stylize/from-chat',json={'photo_id':photo,'plan_id':plan,'profile':'fast'}).json()['job_id']
        second=client.post('/api/stylize/from-chat',json={'photo_id':photo,'plan_id':plan,'profile':'quality'}).json()['job_id']
        assert first!=second
        assert wait(client,first)['result']['profile']=='fast'
        assert wait(client,second)['result']['profile']=='quality'


def test_finish_releases_paused_photos_and_cannot_resume(client):
    class Noop:
        def submit(self,*args): pass
    album,photo=album_with_photo(client)
    client.app.state.bulk.executor=Noop()
    job=client.post('/api/stylize/batch',json={'album_id':album,'style':'mosaic'}).json()['job_id']
    client.post(f'/api/batches/{job}/cancel')
    assert client.delete(f'/api/photos/{photo}').status_code==409
    finished=client.post(f'/api/batches/{job}/finish').json()
    assert finished['result']['context']['closed'] and finished['result']['skipped']==1
    assert client.post(f'/api/batches/{job}/resume').status_code==409
    assert client.delete(f'/api/photos/{photo}').status_code==200


def test_concurrent_resume_keeps_four_batch_limit(client):
    from concurrent.futures import ThreadPoolExecutor
    class Noop:
        def submit(self,*args): pass
    album,photo=album_with_photo(client)
    bulk=client.app.state.bulk;bulk.executor=Noop()
    jobs=[bulk.create([photo],'mosaic',.8,'fast') for _ in range(4)]
    bulk.cancel(jobs[2]);bulk.cancel(jobs[3])
    bulk.create([photo],'mosaic',.7,'fast')
    def resume(job):
        try:bulk.resume(job);return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(resume,jobs[2:]))
    assert sum(results)==1
    assert client.app.state.store.one("SELECT count(*) n FROM jobs WHERE kind='bulk-style' AND status IN ('queued','running')")['n']==4
