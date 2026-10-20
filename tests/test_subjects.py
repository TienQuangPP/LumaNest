import io,json
import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image,ImageDraw
from fsmart.app import create_app
from fsmart.config import Settings
from test_app import TestModels,upload


class PreviewModels(TestModels):
    def __init__(self):self.calls=[]
    def preset(self,image,style,strength,progress,profile='fast'):
        self.calls.append((style,strength))
        return Image.new('RGB',image.size,{'candy':'red','mosaic':'green','rain_princess':'blue','udnie':'yellow'}[style])


class FakeSam:
    installed=True
    calls=0
    def segment(self,image,points):
        self.calls+=1
        masks=[]
        for fraction in [.25,.3,.35]:
            mask=Image.new('L',image.size);ImageDraw.Draw(mask).rectangle((image.width*fraction,image.height*fraction,image.width*(1-fraction),image.height*(1-fraction)),fill=255);masks.append(mask)
        return masks


@pytest.fixture
def client(tmp_path):
    app=create_app(Settings(data_dir=tmp_path/'runtime',weights_dir=tmp_path/'weights'),PreviewModels())
    app.state.subjects.engine=FakeSam()
    with TestClient(app) as result:yield result


def seed(client):
    album=client.post('/api/albums',json={'name':'Subject tests'}).json()['id']
    upload(client,album,'red.png','red');upload(client,album,'green.png','green')
    rows=client.get(f'/api/albums/{album}/photos').json()
    return album,next(p['id'] for p in rows if p['name']=='red.png'),next(p['id'] for p in rows if p['name']=='green.png')


def segment(client,photo):
    return client.post('/api/subjects/segment',json={'photo_id':photo,'points':[{'x':.5,'y':.5,'label':1}]})


def test_actual_style_selected_determines_preview_and_never_creates_history(client):
    _,photo,_=seed(client)
    original=client.get(f'/api/photos/{photo}/image').content
    images=[]
    for style in ['candy','mosaic','rain_princess','udnie']:
        result=client.get(f'/api/photos/{photo}/style-preview',params={'style':style,'strength':.6})
        assert result.status_code==200 and result.headers['x-preview-style']==style
        images.append(result.content)
    assert len(set(images))==4
    previous=len(client.app.state.models.calls)
    assert client.get(f'/api/photos/{photo}/style-preview',params={'style':'udnie','strength':.6}).content==images[-1]
    assert len(client.app.state.models.calls)==previous
    assert client.get('/api/outputs').json()==[] and client.get(f'/api/photos/{photo}/image').content==original
    assert client.get(f'/api/photos/{photo}/style-preview',params={'style':'custom'}).status_code==422


def test_masks_cached_overlay_and_alpha_export_are_lossless(client):
    _,photo,_=seed(client)
    source=client.get(f'/api/photos/{photo}/original').content
    first=segment(client,photo);assert first.status_code==200,first.text
    masks=first.json()['masks'];assert len(masks)==3
    assert not first.json()['cached']
    assert segment(client,photo).json()['cached'] and client.app.state.subjects.engine.calls==1
    overlay=client.get(masks[0]['image_url'])
    assert overlay.status_code==200 and Image.open(io.BytesIO(overlay.content)).mode=='RGBA'
    result=client.post('/api/subjects/render',json={'mask_id':masks[0]['id'],'effect':'cutout'}).json()
    image=Image.open(io.BytesIO(client.get(result['image_url']).content))
    assert image.mode=='RGBA' and image.getpixel((0,0))[3]==0 and image.getpixel((32,32))[3]==255
    assert client.get(f'/api/photos/{photo}/original').content==source
    recipe=json.loads(client.app.state.store.one('SELECT metadata FROM output_assets WHERE output_id=?',(result['output_id'],))['metadata'])
    assert recipe['points']==[{'x':.5,'y':.5,'label':1}] and recipe['effect']=='cutout'


def test_effects_work_and_art_background_must_belong_to_same_photo(client):
    _,photo,other=seed(client)
    mask=segment(client,photo).json()['masks'][0]['id']
    for effect in ['colorpop','blur']:
        assert client.post('/api/subjects/render',json={'mask_id':mask,'effect':effect}).status_code==200
    foreign=client.post('/api/looks',json={'photo_id':other,'look':'cinema'}).json()['output_id']
    assert client.post('/api/subjects/render',json={'mask_id':mask,'effect':'art-background','source_output':foreign}).status_code==422
    owned=client.post('/api/looks',json={'photo_id':photo,'look':'cinema'}).json()['output_id']
    assert client.post('/api/subjects/render',json={'mask_id':mask,'effect':'art-background','source_output':owned}).status_code==200


def test_masks_follow_trash_restore_and_purge(client):
    album,photo,_=seed(client)
    masks=segment(client,photo).json()['masks'];paths=[client.app.state.subjects.mask_path(m['id']) for m in masks]
    result=client.delete(f'/api/photos/{photo}');assert result.status_code==200 and result.json()['recoverable']
    assert all(path.exists() for path in paths)
    assert client.get(masks[0]['image_url']).status_code==404
    assert client.get(f'/api/photos/{photo}/style-preview',params={'style':'candy'}).status_code==404
    assert client.post('/api/trash/restore',json={'photo_ids':[photo]}).status_code==200
    assert client.get(masks[0]['image_url']).status_code==200
    client.post(f'/api/albums/{album}/trash',json={'photo_ids':[photo]})
    assert client.post('/api/trash/purge',json={'photo_ids':[photo]}).status_code==200
    assert all(not path.exists() for path in paths) and not client.app.state.store.all('SELECT * FROM subject_masks WHERE photo_id=?',(photo,))


def test_invalid_points_busy_and_missing_weights_are_explicit(client):
    _,photo,_=seed(client)
    for points in [[],[{'x':2,'y':.5}], [{'x':.5,'y':.5,'label':0}], [{'x':.2,'y':.3}]*13]:
        assert client.post('/api/subjects/segment',json={'photo_id':photo,'points':points}).status_code==422
    service=client.app.state.subjects;service.lock.acquire()
    try:assert segment(client,photo).status_code==429
    finally:service.lock.release()
    service.engine.installed=False
    assert segment(client,photo).status_code==503


def test_cross_site_and_malformed_origin_fail_closed_without_echoing_secrets(client):
    for origin in ['https://evil.example','null','http://[','https://testserver@evil.example']:
        result=client.post('/api/albums',json={'name':'No'},headers={'Origin':origin})
        assert result.status_code==403
    assert client.get('/api/albums',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    good=client.get('/api/albums')
    assert good.status_code==200 and good.headers['cross-origin-resource-policy']=='same-origin'
