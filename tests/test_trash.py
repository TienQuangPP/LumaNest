import io

from test_collections import client, new_album, move
from test_audit_regressions import album_with_photo, style
from test_app import image_bytes, upload, wait


def put(client,album,ids):
    return client.post(f'/api/albums/{album}/trash',json={'photo_ids':ids})


def test_trash_hides_every_active_surface_and_restore_is_lossless(client):
    album,photo=album_with_photo(client)
    original=client.get(f'/api/photos/{photo}/original').content
    output=wait(client,style(client,photo))['result']
    png=client.get(output['image_url']).content
    query=client.post('/api/query',files={'file':('q.png',image_bytes('red'),'image/png')}).json()
    search={'album_id':album,'query_id':query['id'],'threshold':.5}
    assert len(client.post('/api/search',json=search).json()['results'])==1
    ticket=client.post('/api/exports',json={'photo_ids':[photo]}).json()['download_url']
    assert put(client,album,[photo,photo]).json()['trashed']==1
    assert client.get(f'/api/albums/{album}/photos').json()==[]
    stats=client.get('/api/albums').json()[0]
    assert stats['photo_count']==0 and stats['trash_count']==1 and stats['cover_photo_id'] is None
    assert client.post('/api/search',json=search).json()['results']==[]
    assert client.get('/api/outputs').json()==[]
    for path in [f'/api/photos/{photo}',f'/api/photos/{photo}/image',f'/api/photos/{photo}/original',output['image_url'],ticket]:
        assert client.get(path).status_code==404,path
    assert client.get(f'/api/trash/{photo}/thumbnail').status_code==200
    assert client.post('/api/stylize',data={'photo_id':photo,'style_id':'mosaic'}).status_code==404
    assert client.post('/api/stylize/batch',json={'album_id':album,'style':'mosaic'}).status_code==422
    restored=client.post('/api/trash/restore',json={'photo_ids':[photo]})
    assert restored.json()['restored']==1
    assert client.get(f'/api/photos/{photo}/original').content==original
    assert client.get(output['image_url']).content==png
    assert len(client.post('/api/search',json=search).json()['results'])==1
    assert client.get(f'/api/albums/{album}/trash').json()==[]


def test_trash_and_restore_validate_entire_selection_before_changing_anything(client):
    first,one=album_with_photo(client)
    other,two=album_with_photo(client)
    assert put(client,first,[one,two]).status_code==422
    assert len(client.get(f'/api/albums/{first}/photos').json())==1
    assert put(client,first,[one]).status_code==200
    assert client.post('/api/trash/restore',json={'photo_ids':[one,two]}).status_code==422
    assert len(client.get(f'/api/albums/{first}/trash').json())==1
    assert move(client,first,[one],destination_album_id=other).status_code==422


def test_purge_is_only_for_trash_and_removes_source_outputs_and_vectors(client):
    album,photo=album_with_photo(client)
    output=wait(client,style(client,photo))['result']
    assert client.post('/api/trash/purge',json={'photo_ids':[photo]}).status_code==422
    assert put(client,album,[photo]).status_code==200
    response=client.post('/api/trash/purge',json={'photo_ids':[photo]})
    assert response.json()=={'purged':1,'file_cleanup_errors':0}
    store=client.app.state.store
    assert store.one('SELECT count(*) n FROM faces')['n']==0
    assert store.one('SELECT count(*) n FROM outputs')['n']==0
    assert store.one('SELECT count(*) n FROM photos')['n']==0
    for folder,filename in [('originals',photo+'.png'),('photos',photo+'.jpg'),('thumbs',photo+'.jpg'),('outputs',output['output_id']+'.png')]:
        assert not (client.app.state.settings.data_dir/folder/filename).exists()
    assert client.post('/api/trash/restore',json={'photo_ids':[photo]}).status_code==422


def test_reimport_trashed_duplicate_gives_restore_instruction(client):
    album,photo=album_with_photo(client)
    assert put(client,album,[photo]).status_code==200
    result=client.post(f'/api/albums/{album}/photos',files={'files':('again.png',image_bytes('red'),'image/png')}).json()
    assert result['accepted']==0 and result['duplicates']==0
    assert 'Khôi phục' in result['errors'][0]['message']
    assert len(client.get(f'/api/albums/{album}/trash').json())==1


def test_trash_blocks_index_and_unfinished_batch(client,monkeypatch):
    album,photo=album_with_photo(client)
    client.app.state.store.execute("UPDATE photos SET status='queued' WHERE id=?",(photo,))
    assert put(client,album,[photo]).status_code==409
    client.app.state.store.execute("UPDATE photos SET status='ready' WHERE id=?",(photo,))
    monkeypatch.setattr(client.app.state.bulk,'schedule',lambda _:None)
    job=client.post('/api/stylize/batch',json={'album_id':album,'style':'mosaic'}).json()['job_id']
    assert put(client,album,[photo]).status_code==409
    client.post(f'/api/batches/{job}/cancel')
    assert put(client,album,[photo]).status_code==409
    client.post(f'/api/batches/{job}/finish')
    assert put(client,album,[photo]).status_code==200


def test_completed_batch_zip_does_not_include_trashed_photo(client):
    album,photo=album_with_photo(client)
    job=client.post('/api/stylize/batch',json={'album_id':album,'style':'mosaic'}).json()['job_id']
    result=wait(client,job)
    assert client.get(result['result']['download_url']).status_code==200
    assert put(client,album,[photo]).status_code==200
    assert client.get(result['result']['download_url']).status_code==409
    output=client.app.state.store.one('SELECT id FROM outputs')['id']
    (client.app.state.settings.data_dir/'outputs'/f'{output}.png').unlink()
    assert client.post(f'/api/batches/{job}/resume').status_code==409
    client.post('/api/trash/restore',json={'photo_ids':[photo]})
    assert client.post(f'/api/batches/{job}/resume').status_code==202
    wait(client,job)


def test_photo_picker_search_is_scoped_and_treats_wildcards_literally(client):
    first=new_album(client,'A');second=new_album(client,'B')
    upload(client,first,'group_100%.PNG','red')
    upload(client,first,'another.png','green')
    upload(client,second,'group_100%.PNG','red')
    result=client.get(f'/api/albums/{first}/photos',params={'q':'100%','limit':1}).json()
    assert len(result)==1 and result[0]['album_id']==first
    assert client.get(f'/api/albums/{first}/photos',params={'q':'_'}).json()[0]['name']=='group_100%.PNG'
    assert client.get(f'/api/albums/{first}/photos',params={'q':'absent'}).json()==[]
    assert client.get(f'/api/albums/{first}/photos',params={'q':'x'*161}).status_code==422
