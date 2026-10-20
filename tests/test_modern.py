"""Independent curation, discovery ranking and non-destructive recipe checks."""
import hashlib
import io
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fsmart.app import create_app
from fsmart.config import Settings
from fsmart.semantic import MODEL_KEY
from fsmart.store import Store
from test_app import TestModels, upload, wait


class FakeSemantic:
    installed=True
    dimension=3
    calls=0
    def encode(self,image=None,text=None):
        self.calls+=1
        if text:
            return np.array([1,0,0] if 'đỏ' in text else [0,1,0],dtype=np.float32)
        rgb=np.array(image).mean((0,1)).astype(np.float32)
        return rgb/np.linalg.norm(rgb)


@pytest.fixture
def client(tmp_path):
    app=create_app(Settings(data_dir=tmp_path/'runtime',weights_dir=tmp_path/'weights'),TestModels())
    app.state.semantic.engine=FakeSemantic()
    with TestClient(app) as client:
        yield client


def seed(client):
    album=client.post('/api/albums',json={'name':'Thử hiện đại'}).json()['id']
    upload(client,album,'Ảnh đỏ.png','red');upload(client,album,'Ảnh xanh.png','green')
    photos=client.get('/api/library',params={'album_id':album,'sort':'name'}).json()['items']
    red=next(p['id'] for p in photos if 'đỏ' in p['name'])
    green=next(p['id'] for p in photos if 'xanh' in p['name'])
    return album,red,green


def patch(client,photo,**payload):
    return client.patch(f'/api/photos/{photo}/metadata',json=payload)


def test_curation_persists_and_fulltext_matches_accentless_tags_notes(client):
    album,red,green=seed(client)
    assert patch(client,red,favorite=True,tags=[' Kỷ yếu ','KỶ YẾU','Bạn bè'],notes='Chuyến đi Hà Nội',expected_version=0).status_code==200
    data=client.get(f'/api/photos/{red}/metadata').json()
    assert data['tags']==['Kỷ yếu','Bạn bè'] and data['favorite'] and data['version']==1
    for query in ['ky yeu','ha noi','ban be','"ky" OR *']:
        result=client.get('/api/library',params={'album_id':album,'q':query}).json()['items']
        assert ([p['id'] for p in result]==[red]) if query!='"ky" OR *' else result==[]
    assert [p['id'] for p in client.get('/api/library',params={'favorite':True}).json()['items']]==[red]
    assert patch(client,red,notes='Stale',expected_version=0).status_code==409
    assert client.get(f'/api/photos/{red}/metadata').json()['notes']=='Chuyến đi Hà Nội'
    reopened=Store(client.app.state.store.path)
    assert reopened.one('SELECT favorite FROM photo_metadata WHERE photo_id=?',(red,))['favorite']==1
    assert reopened.one('SELECT count(*) n FROM photo_search WHERE photo_id=?',(red,))['n']==1
    reopened.close()


def test_atomic_batch_favorites_and_validation(client):
    album,red,green=seed(client)
    assert client.post('/api/library/favorites',json={'photo_ids':[red,'missing'],'favorite':True}).status_code==404
    assert not client.get(f'/api/photos/{red}/metadata').json()['favorite']
    assert client.post('/api/library/favorites',json={'photo_ids':[red,green,red],'favorite':True}).json()['updated']==2
    assert patch(client,red,tags=['']).status_code==422
    assert patch(client,red,tags=['x'*41]).status_code==422
    assert patch(client,red,notes='x'*2001).status_code==422
    assert patch(client,red,unexpected=1).status_code==422


def test_library_filters_pagination_and_trash_scope(client):
    album,red,green=seed(client)
    client.app.state.store.execute('UPDATE photos SET width=100,height=200 WHERE id=?',(red,))
    assert client.get('/api/library',params={'album_id':album,'orientation':'portrait'}).json()['items'][0]['id']==red
    assert client.get('/api/library',params={'min_faces':3}).json()['total']==0
    first=client.get('/api/library',params={'limit':1,'sort':'name'}).json()
    second=client.get('/api/library',params={'limit':1,'offset':1,'sort':'name'}).json()
    assert first['total']==second['total']==2 and first['items'][0]['id']!=second['items'][0]['id']
    assert client.get('/api/library',params={'sort':'name; DELETE'}).status_code==422
    assert client.get('/api/library',params={'album_id':'missing'}).status_code==404
    patch(client,red,tags=['Khôi phục'],favorite=True)
    assert client.post(f'/api/albums/{album}/trash',json={'photo_ids':[red]}).status_code==200
    assert client.get('/api/library',params={'favorite':True}).json()['total']==0
    assert client.get(f'/api/photos/{red}/metadata').status_code==404
    assert patch(client,red,notes='hidden').status_code==404
    assert client.post('/api/trash/restore',json={'photo_ids':[red]}).status_code==200
    assert client.get(f'/api/photos/{red}/metadata').json()['tags']==['Khôi phục']


def test_incremental_index_text_similar_ranking_and_stale_digest(client):
    album,red,green=seed(client)
    job=client.post('/api/discovery/index',json={'album_id':album}).json()['job_id']
    assert wait(client,job)['result']['indexed']==2
    engine=client.app.state.semantic.engine
    previous=engine.calls
    job=client.post('/api/discovery/index',json={'album_id':album}).json()['job_id']
    assert wait(client,job)['result']['indexed']==0 and engine.calls==previous
    found=client.post('/api/discovery/search',json={'album_id':album,'text':'ảnh đỏ','limit':1}).json()
    assert found['items'][0]['id']==red and found['coverage']['indexed']==2
    similar=client.post('/api/discovery/search',json={'album_id':album,'photo_id':red}).json()
    assert [p['id'] for p in similar['items']]==[green]
    client.app.state.store.execute('UPDATE semantic_embeddings SET digest=? WHERE photo_id=?',('stale',red))
    found=client.post('/api/discovery/search',json={'album_id':album,'text':'đỏ'}).json()
    assert found['coverage']['indexed']==1 and [p['id'] for p in found['items']]==[green]
    assert client.post('/api/discovery/search',json={'album_id':album,'photo_id':red}).status_code==409


def test_corrupt_semantic_vector_rejected_then_repaired_and_busy_guard(client):
    album,red,green=seed(client)
    semantic=client.app.state.semantic
    job=client.post('/api/discovery/index',json={'album_id':album}).json()['job_id'];wait(client,job)
    client.app.state.store.execute('UPDATE semantic_embeddings SET embedding=? WHERE photo_id=?',(np.array([np.nan,0,0],np.float32).tobytes(),red))
    assert client.post('/api/discovery/search',json={'album_id':album,'text':'đỏ'}).status_code==409
    job=client.post('/api/discovery/index',json={'album_id':album}).json()['job_id']
    assert wait(client,job)['result']['indexed']==1
    semantic.lock.acquire()
    try:
        assert client.post('/api/discovery/search',json={'album_id':album,'text':'đỏ'}).status_code==429
        assert client.post('/api/discovery/index',json={'album_id':album}).status_code==429
    finally: semantic.lock.release()
    for payload in [{},{'text':'  '},{'text':'x','photo_id':red},{'text':'x'*301}]:
        assert client.post('/api/discovery/search',json={'album_id':album,**payload}).status_code==422


def test_discovery_excludes_trash_and_other_collection(client):
    album,red,green=seed(client)
    job=client.post('/api/discovery/index',json={'album_id':album}).json()['job_id'];wait(client,job)
    other=client.post('/api/albums',json={'name':'Bộ khác'}).json()['id']
    assert client.post('/api/discovery/search',json={'album_id':other,'photo_id':red}).status_code==409
    assert client.post('/api/discovery/search',json={'album_id':other,'text':'đỏ'}).json()['items']==[]
    client.post(f'/api/albums/{album}/trash',json={'photo_ids':[red]})
    found=client.post('/api/discovery/search',json={'album_id':album,'text':'đỏ'}).json()
    assert [p['id'] for p in found['items']]==[green] and found['coverage']['indexed']==1


def test_missing_model_is_explicit_and_new_assistant_help_is_local(client,monkeypatch):
    album,red,green=seed(client)
    client.app.state.semantic.engine.installed=False
    assert client.post('/api/discovery/index',json={'album_id':album}).status_code==503
    monkeypatch.setattr(client.app.state.chat,'_post',lambda *args,**kwargs:pytest.fail('Help must remain local'))
    reply=client.post('/api/chat',json={'message':'Tìm ảnh bằng mô tả thế nào?'}).json()
    assert reply['provider']=='local' and 'SigLIP 2' in reply['reply']
    reply=client.post('/api/chat',json={'message':'Thêm nhãn ảnh và ghi chú thế nào?'}).json()
    assert 'Lưu thông tin' in reply['reply'] and 'Ctrl K' in reply['reply']


def test_diagnostics_detects_corrupt_semantic_and_search_index(client):
    from fsmart.store import now
    album,red,green=seed(client)
    store=client.app.state.store
    store.execute('INSERT INTO semantic_embeddings VALUES(?,?,?,?,?)',(red,'digest',MODEL_KEY,np.full(768,np.nan,np.float32).tobytes(),now()))
    store.execute('DELETE FROM photo_search WHERE photo_id=?',(green,))
    result=client.post('/api/system/verify').json()
    assert not result['passed']
    assert result['counts']['invalid_semantic_embeddings']==1 and result['counts']['invalid_search_rows']==1


@pytest.mark.parametrize('look',['original','cinema','portra','noir','cool','sunset'])
def test_colour_preserves_source_and_saves_recipe(client,look):
    album,red,green=seed(client)
    source=client.get(f'/api/photos/{red}/image').content
    response=client.post('/api/looks',json={'photo_id':red,'look':look,'strength':.7})
    assert response.status_code==200,response.text
    output=response.json()
    assert client.get(output['image_url']).content.startswith(b'\x89PNG')
    assert client.get(f'/api/photos/{red}/image').content==source
    asset=client.app.state.store.one('SELECT * FROM output_assets WHERE output_id=?',(output['output_id'],))
    assert json.loads(asset['metadata'])['look']==look
    assert hashlib.sha256(client.get(output['image_url']).content).hexdigest()==asset['sha256']
    preview=client.get(f'/api/photos/{red}/look-preview',params={'look':look,'strength':.7})
    assert preview.status_code==200 and Image.open(io.BytesIO(preview.content)).format=='JPEG'


def test_colour_can_finish_an_existing_output_but_cannot_cross_photo_or_trash(client):
    album,red,green=seed(client)
    first=client.post('/api/looks',json={'photo_id':red,'look':'cinema'}).json()
    body={'photo_id':red,'look':'noir','strength':1,'source_output':first['output_id']}
    final=client.post('/api/looks',json=body)
    assert final.status_code==200
    image=np.array(Image.open(io.BytesIO(client.get(final.json()['image_url']).content)))
    assert np.array_equal(image[:,:,0],image[:,:,1]) and np.array_equal(image[:,:,1],image[:,:,2])
    assert client.post('/api/looks',json={**body,'photo_id':green}).status_code==404
    assert client.post('/api/looks',json={**body,'strength':1.1}).status_code==422
    assert client.get(f'/api/photos/{red}/look-preview',params={'look':'x'}).status_code==422
    client.post(f'/api/albums/{album}/trash',json={'photo_ids':[red]})
    assert client.post('/api/looks',json=body).status_code==404
