"""Curation, local visual discovery and non-destructive colour recipes."""
import io
import threading
from collections import OrderedDict
from typing import Literal

from fastapi import HTTPException, Query
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field, model_validator

from .assets import save_output, valid_output
from .library import BatchFavorite, MetadataInput, list_photos, metadata, update_metadata
from .looks import LOOKS, finish
from .semantic import SemanticIndex
from .subjects import Subjects,SegmentInput,EffectInput

Look = Literal['original','cinema','portra','noir','cool','sunset']


class LookInput(BaseModel):
    model_config={'extra':'forbid'}
    photo_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    look: Look
    strength: float = Field(default=.8,ge=0,le=1,allow_inf_nan=False)
    source_output: str | None = Field(default=None,pattern=r'^[0-9a-f]{32}$')


class SemanticQuery(BaseModel):
    model_config={'extra':'forbid'}
    album_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    text: str | None = Field(default=None,max_length=300)
    photo_id: str | None = Field(default=None,pattern=r'^[0-9a-f]{32}$')
    limit: int = Field(default=24,ge=1,le=100)

    @model_validator(mode='after')
    def check_query(self):
        self.text=self.text.strip() if self.text else None
        if bool(self.text)==bool(self.photo_id):
            raise ValueError('Cần một mô tả hoặc một ảnh để tìm tương tự.')
        return self


class IndexInput(BaseModel):
    album_id: str = Field(pattern=r'^[0-9a-f]{32}$')


def install(app,store,settings,file_lock):
    semantic=SemanticIndex(store,settings,file_lock)
    app.state.semantic=semantic
    look_lock=threading.Lock()
    subjects=Subjects(store,settings,file_lock)
    app.state.subjects=subjects
    preview_lock=threading.Lock()
    previews=OrderedDict()

    def check_album(album):
        if album and not store.one('SELECT 1 FROM albums WHERE id=?',(album,)):
            raise HTTPException(404,'Không tìm thấy bộ ảnh.')

    @app.get('/api/library')
    def library(album_id:str|None=None,q:str=Query('',max_length=300),favorite:bool=False,
                orientation:Literal['all','landscape','portrait']='all',min_faces:int=Query(0,ge=0,le=100),
                sort:Literal['newest','oldest','name']='newest',limit:int=Query(100,ge=1,le=100),offset:int=Query(0,ge=0)):
        check_album(album_id)
        return list_photos(store,album_id,q,favorite,orientation,min_faces,sort,limit,offset)

    @app.get('/api/photos/{photo_id}/metadata')
    def read_metadata(photo_id:str):
        return metadata(store,photo_id)

    @app.patch('/api/photos/{photo_id}/metadata')
    def edit_metadata(photo_id:str,payload:MetadataInput):
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            update_metadata(db,photo_id,payload)
        return metadata(store,photo_id)

    @app.post('/api/library/favorites')
    def favorites(payload:BatchFavorite):
        ids=list(dict.fromkeys(payload.photo_ids))
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for photo in ids:
                update_metadata(db,photo,MetadataInput(favorite=payload.favorite))
        return {'updated':len(ids),'favorite':payload.favorite}

    @app.get('/api/discovery/status')
    def discovery_status(album_id:str|None=None):
        check_album(album_id)
        return semantic.status(album_id)

    @app.post('/api/discovery/index')
    def discovery_index(payload:IndexInput):
        check_album(payload.album_id)
        return semantic.start(payload.album_id)

    @app.post('/api/discovery/search')
    def discovery_search(payload:SemanticQuery):
        check_album(payload.album_id)
        return semantic.search(payload.album_id,payload.text,payload.photo_id,payload.limit)

    @app.get('/api/looks')
    def looks():
        return LOOKS

    @app.get('/api/subjects/status')
    def subject_status():return {'installed':subjects.engine.installed,'busy':subjects.lock.locked(),'model':'Meta SAM 2.1 Tiny'}

    @app.post('/api/subjects/segment')
    def segment(payload:SegmentInput):return subjects.segment(payload)

    @app.get('/api/subjects/{mask_id}/overlay')
    def subject_overlay(mask_id:str):return Response(subjects.overlay(mask_id),media_type='image/png')

    @app.post('/api/subjects/render')
    def subject_render(payload:EffectInput):return subjects.render(payload)

    @app.get('/api/photos/{photo_id}/style-preview')
    def style_preview(photo_id:str,style:Literal['candy','mosaic','rain_princess','udnie'],strength:float=Query(.8,ge=0,le=1,allow_inf_nan=False)):
        photo=metadata(store,photo_id)
        key=(photo['id'],photo['digest'],style,strength)
        if not preview_lock.acquire(blocking=False):raise HTTPException(429,'Đang chuẩn bị mẫu. Chờ một chút.')
        try:
            if key not in previews:
                with file_lock:image=source(photo_id,max_side=512)
                rendered=app.state.models.preset(image,style,strength,lambda *_:None,profile='fast')
                output=io.BytesIO();rendered.convert('RGB').save(output,'JPEG',quality=88)
                previews[key]=output.getvalue()
                while len(previews)>16:previews.popitem(last=False)
            previews.move_to_end(key)
            metadata(store,photo_id)
            return Response(previews[key],media_type='image/jpeg',headers={'X-Preview-Style':style})
        finally:preview_lock.release()

    def source(photo_id,source_output=None,max_side=2048):
        metadata(store,photo_id)
        if source_output:
            if not store.one('SELECT 1 FROM outputs WHERE id=? AND photo_id=?',(source_output,photo_id)):
                raise HTTPException(404,'Tác phẩm không thuộc ảnh đang chọn.')
            if not valid_output(store,settings.data_dir,source_output):
                raise HTTPException(409,'Tác phẩm nguồn thiếu hoặc sai checksum.')
            path=settings.data_dir/'outputs'/f'{source_output}.png'
        else:
            path=settings.data_dir/'photos'/f'{photo_id}.jpg'
        try:
            with Image.open(path) as image:
                image=image.convert('RGB')
                image.thumbnail((max_side,max_side))
                return image
        except OSError as exc:
            raise HTTPException(409,'File ảnh nguồn thiếu hoặc hỏng.') from exc

    @app.get('/api/photos/{photo_id}/look-preview')
    def preview(photo_id:str,look:Look,strength:float=Query(.8,ge=0,le=1,allow_inf_nan=False),
                source_output:str|None=Query(None,pattern=r'^[0-9a-f]{32}$')):
        with file_lock:
            image=source(photo_id,source_output,640)
        output=io.BytesIO()
        finish(image,look,strength).save(output,'JPEG',quality=85)
        return Response(output.getvalue(),media_type='image/jpeg')

    @app.post('/api/looks')
    def render_look(payload:LookInput):
        if not look_lock.acquire(blocking=False):
            raise HTTPException(429,'Đang lưu phiên bản màu. Đợi một chút rồi thử lại.')
        try:
            with file_lock:
                image=finish(source(payload.photo_id,payload.source_output),payload.look,payload.strength)
                title=next(row['name'] for row in LOOKS if row['id']==payload.look)
                output=save_output(store,settings,image,payload.photo_id,'look:'+payload.look,title,
                    {'profile':'colour2048','look':payload.look,'strength':payload.strength,'source_output':payload.source_output,'engine':'pillow-v1'})
            return {'output_id':output,'image_url':f'/api/outputs/{output}/image',
                    'download_url':f'/api/outputs/{output}/image?download=true','style_label':title}
        finally:
            look_lock.release()

    return semantic
