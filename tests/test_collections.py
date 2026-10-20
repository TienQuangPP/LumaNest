"""Collection membership changes must preserve assets and remain atomic."""
import hashlib

import pytest
from fastapi.testclient import TestClient

from fsmart.app import create_app
from fsmart.config import Settings
from test_app import TestModels, image_bytes, upload, wait
from test_audit_regressions import album_with_photo, style


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'),TestModels())) as result:
        yield result


def new_album(client,name):
    response=client.post('/api/albums',json={'name':name})
    assert response.status_code==201
    return response.json()['id']


def move(client,source,ids,**target):
    return client.post(f'/api/albums/{source}/move-photos',json={'photo_ids':ids,**target})


def test_overview_has_independent_counts_and_cover_for_each_collection(client):
    first,photo=album_with_photo(client)
    empty=new_album(client,'Chuyến đi')
    albums={row['id']:row for row in client.get('/api/albums').json()}
    assert albums[first]['photo_count']==albums[first]['indexed_count']==1
    assert albums[first]['cover_photo_id']==photo
    assert albums[empty]['photo_count']==0 and albums[empty]['cover_photo_id'] is None


def test_move_to_new_collection_keeps_original_faces_outputs_and_search(client):
    source,photo=album_with_photo(client)
    store=client.app.state.store
    faces=store.all('SELECT * FROM faces WHERE photo_id=?',(photo,))
    original=client.get(f'/api/photos/{photo}/original').content
    output=wait(client,style(client,photo))['result']
    digest=hashlib.sha256(client.get(output['image_url']).content).hexdigest()
    response=move(client,source,[photo,photo],new_album_name='  Kỷ yếu lớp  ')
    assert response.status_code==200,response.text
    destination=response.json()['destination_album_id']
    assert response.json()['moved']==1
    assert client.get(f'/api/albums/{source}/photos').json()==[]
    assert client.get(f'/api/albums/{destination}/photos').json()[0]['id']==photo
    assert store.all('SELECT * FROM faces WHERE photo_id=?',(photo,))==faces
    assert client.get(f'/api/photos/{photo}/original').content==original
    assert hashlib.sha256(client.get(output['image_url']).content).hexdigest()==digest
    assert client.get(f'/api/outputs?album_id={source}').json()==[]
    assert client.get(f'/api/outputs?album_id={destination}').json()[0]['id']==output['output_id']
    query=client.post('/api/query',files={'file':('q.png',image_bytes('red'),'image/png')}).json()
    payload={'query_id':query['id'],'threshold':.5}
    assert client.post('/api/search',json={**payload,'album_id':source}).json()['results']==[]
    assert client.post('/api/search',json={**payload,'album_id':destination}).json()['results'][0]['id']==photo
    assert client.post('/api/system/verify').json()['passed']


def test_duplicate_destination_rejects_entire_selection(client):
    source,red=album_with_photo(client)
    upload(client,source,'green.png','green')
    destination=new_album(client,'Đích')
    upload(client,destination,'duplicate-red.png','red')
    ids=[row['id'] for row in client.get(f'/api/albums/{source}/photos').json()]
    response=move(client,source,ids,destination_album_id=destination)
    assert response.status_code==409
    assert {row['id'] for row in client.get(f'/api/albums/{source}/photos').json()}==set(ids)
    assert len(client.get(f'/api/albums/{destination}/photos').json())==1


def test_invalid_selection_rolls_back_new_collection_as_well(client):
    source,photo=album_with_photo(client)
    unrelated,other=album_with_photo(client)
    before=client.get('/api/albums').json()
    response=move(client,source,[photo,other],new_album_name='Không được tạo dở')
    assert response.status_code==422
    assert client.get('/api/albums').json()==before
    assert client.get(f'/api/photos/{photo}').json()['album_id']==source


def test_move_rejects_invalid_destinations(client):
    source,photo=album_with_photo(client)
    assert move(client,source,[photo]).status_code==422
    assert move(client,source,[photo],new_album_name='   ').status_code==422
    assert move(client,source,[photo],destination_album_id=source).status_code==422
    assert move(client,source,[photo],destination_album_id='0'*32).status_code==404
    assert move(client,source,[photo],destination_album_id='1'*32,new_album_name='Both').status_code==422


def test_move_blocks_indexing_and_active_single_style_job(client):
    source,photo=album_with_photo(client)
    destination=new_album(client,'Đích')
    store=client.app.state.store
    store.execute("UPDATE photos SET status='queued' WHERE id=?",(photo,))
    assert move(client,source,[photo],destination_album_id=destination).status_code==409
    store.execute("UPDATE photos SET status='ready' WHERE id=?",(photo,))
    job=store.create_job('stylize')
    store.execute('INSERT INTO job_targets VALUES(?,?)',(job,photo))
    assert move(client,source,[photo],destination_album_id=destination).status_code==409
    store.update_job(job,'done',1,'Done')
    assert move(client,source,[photo],destination_album_id=destination).status_code==200


def test_paused_batch_protects_membership_until_closed(client,monkeypatch):
    source,photo=album_with_photo(client)
    destination=new_album(client,'Đích')
    monkeypatch.setattr(client.app.state.bulk,'schedule',lambda _:None)
    job=client.post('/api/stylize/batch',json={'album_id':source,'style':'mosaic'}).json()['job_id']
    assert move(client,source,[photo],destination_album_id=destination).status_code==409
    assert client.post(f'/api/batches/{job}/cancel').status_code==200
    assert move(client,source,[photo],destination_album_id=destination).status_code==409
    assert client.post(f'/api/batches/{job}/finish').status_code==200
    assert move(client,source,[photo],destination_album_id=destination).status_code==200


def test_batch_list_is_filtered_per_collection_including_legacy_context(client):
    first,photo=album_with_photo(client)
    second=new_album(client,'Khác')
    upload(client,second,'green.png','green')
    jobs=[]
    for album in [first,second]:
        job=client.post('/api/stylize/batch',json={'album_id':album,'style':'mosaic'}).json()['job_id']
        wait(client,job);jobs.append(job)
    client.app.state.store.execute('DELETE FROM batch_context WHERE job_id=?',(jobs[0],))
    assert [row['id'] for row in client.get(f'/api/batches?album_id={first}').json()]==[jobs[0]]
    assert [row['id'] for row in client.get(f'/api/batches?album_id={second}').json()]==[jobs[1]]
    assert {row['id'] for row in client.get('/api/batches').json()}==set(jobs)
    assert client.get('/api/batches?album_id=missing').status_code==404
