import hashlib,io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fsmart.app import create_app
from fsmart.config import Settings
from fsmart.images import decode_image,image_digest
from test_app import TestModels,wait


def png(size=(64,64)):
    out=io.BytesIO()
    with Image.new('RGB',size,'#46856a') as image:image.save(out,'PNG',compress_level=1)
    return out.getvalue()


def test_upload_over_25mp_preserves_dimensions_original_and_duplicate_identity(tmp_path):
    data=png((6000,5000))
    app=create_app(Settings(data_dir=tmp_path/'runtime',weights_dir=tmp_path/'weights'),TestModels())
    with TestClient(app) as client:
        album=client.post('/api/albums',json={'name':'Large images'}).json()['id']
        upload=client.post(f'/api/albums/{album}/photos',files={'files':('30mp.png',data,'image/png')}).json()
        assert upload['accepted']==1 and upload['errors']==[]
        wait(client,upload['job_id'])
        photo=client.get(f'/api/albums/{album}/photos').json()[0]
        assert (photo['width'],photo['height'])==(6000,5000)
        assert client.get(f'/api/photos/{photo["id"]}/original').content==data
        with Image.open(io.BytesIO(client.get(f'/api/photos/{photo["id"]}/image').content)) as full:assert full.size==(6000,5000)
        with Image.open(io.BytesIO(client.get(f'/api/photos/{photo["id"]}/image?thumbnail=true').content)) as thumb:assert thumb.width<=640 and thumb.height<=480
        repeated=client.post(f'/api/albums/{album}/photos',files={'files':('again.png',data,'image/png')}).json()
        assert repeated['duplicates']==1 and repeated['accepted']==0
        assert client.get('/api/system/status').json()['limits']['image_pixels'] is None
        verified=client.post('/api/system/verify').json()
        assert verified['passed'] and verified['counts']['missing_photos']==0


def test_explicit_api_reference_limit_is_checked_before_decoding(monkeypatch):
    data=png((65,64))
    monkeypatch.setattr('fsmart.images.ImageOps.exif_transpose',lambda *a,**k:pytest.fail('Oversized API reference decoded'))
    with pytest.raises(ValueError,match='giới hạn'):decode_image(data,4096)


def test_chunked_digest_matches_existing_photos():
    with Image.effect_noise((173,301),24).convert('RGB') as image:
        old=hashlib.sha256(image.tobytes()+str(image.size).encode()).hexdigest()
        assert image_digest(image)==old


def test_large_image_support_retains_orientation_and_rgb_conversion():
    out=io.BytesIO()
    with Image.new('RGB',(400,200),'green') as image:
        exif=Image.Exif();exif[274]=6
        image.save(out,'JPEG',exif=exif)
    with decode_image(out.getvalue()) as image:assert image.size==(200,400) and image.mode=='RGB'


def test_out_of_memory_is_an_actionable_upload_error(tmp_path,monkeypatch):
    def fail(*a,**k):raise MemoryError('native allocator failure')
    data=png()
    monkeypatch.setattr('fsmart.images.ImageOps.exif_transpose',fail)
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'),TestModels())) as client:
        album=client.post('/api/albums',json={'name':'Memory failure'}).json()['id']
        result=client.post(f'/api/albums/{album}/photos',files={'files':('a.png',data,'image/png')}).json()
        assert result['accepted']==0 and 'RAM' in result['errors'][0]['message']
