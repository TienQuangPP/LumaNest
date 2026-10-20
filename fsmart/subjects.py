"""Point-guided local segmentation and non-destructive subject effects."""
import hashlib
import io
import json
import threading
import time
from typing import Literal

import numpy as np
from fastapi import HTTPException
from PIL import Image,ImageFilter,ImageOps
from pydantic import BaseModel,Field,model_validator

from .assets import file_digest,save_output,valid_output
from .library import metadata
from .storage import ensure_space
from .store import now,uid

REPO='facebook/sam2.1-hiera-tiny'
REVISION='de431c4043854a71d8101e17995dfe596bf101a5'
MODEL_KEY=REPO+'@'+REVISION
SCHEMA='''CREATE TABLE IF NOT EXISTS subject_masks(
 id TEXT PRIMARY KEY,photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE,
 digest TEXT NOT NULL,cache_key TEXT NOT NULL,candidate INTEGER NOT NULL,
 width INTEGER NOT NULL,height INTEGER NOT NULL,sha256 TEXT NOT NULL,
 points TEXT NOT NULL,model_key TEXT NOT NULL,created TEXT NOT NULL);
 CREATE INDEX IF NOT EXISTS masks_photo ON subject_masks(photo_id,cache_key,candidate);'''


class Point(BaseModel):
    model_config={'extra':'forbid'}
    x:float=Field(ge=0,le=1,allow_inf_nan=False)
    y:float=Field(ge=0,le=1,allow_inf_nan=False)
    label:Literal[0,1]=1


class SegmentInput(BaseModel):
    model_config={'extra':'forbid'}
    photo_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    points:list[Point]=Field(min_length=1,max_length=12)
    @model_validator(mode='after')
    def positive_required(self):
        if not any(p.label==1 for p in self.points):raise ValueError('Cần ít nhất một điểm chọn đối tượng.')
        return self


class EffectInput(BaseModel):
    model_config={'extra':'forbid'}
    mask_id:str=Field(pattern=r'^[0-9a-f]{32}$')
    effect:Literal['cutout','colorpop','blur','art-background']='cutout'
    source_output:str|None=Field(default=None,pattern=r'^[0-9a-f]{32}$')


class SamEngine:
    def __init__(self,directory):self.directory,self.model,self.processor=directory,None,None
    @property
    def installed(self):return (self.directory/'model.safetensors').is_file() and (self.directory/'provenance.json').is_file()
    def load(self):
        if self.model is not None:return
        if not self.installed:raise RuntimeError('Chưa tải SAM 2. Chạy scripts/fetch_segmentation.py.')
        manifest=json.loads((self.directory/'provenance.json').read_text('utf-8'))
        if manifest['repo']!=REPO or manifest['revision']!=REVISION:raise RuntimeError('Phiên bản SAM 2 chưa được kiểm tra.')
        for name,item in manifest['files'].items():
            path=self.directory/name
            if path.parent!=self.directory or not path.is_file() or file_digest(path)!=item['sha256']:
                raise RuntimeError('File SAM 2 thiếu hoặc sai checksum. Tải lại model.')
        import torch
        from transformers import Sam2Model,Sam2Processor
        torch.set_num_threads(4)
        self.processor=Sam2Processor.from_pretrained(self.directory,local_files_only=True,trust_remote_code=False)
        self.model=Sam2Model.from_pretrained(self.directory,local_files_only=True,trust_remote_code=False,use_safetensors=True).eval()
    def segment(self,image,points):
        self.load()
        import torch
        coordinates=[[p.x*max(1,image.width-1),p.y*max(1,image.height-1)] for p in points]
        inputs=self.processor(images=image,input_points=[[coordinates]],input_labels=[[[p.label for p in points]]],return_tensors='pt')
        with torch.inference_mode():outputs=self.model(**inputs)
        masks=self.processor.post_process_masks(outputs.pred_masks.cpu(),inputs['original_sizes'])[0][0]
        scores=outputs.iou_scores[0,0].float().cpu().numpy()
        order=np.argsort(-scores)
        return [Image.fromarray(masks[int(index)].cpu().numpy().astype(np.uint8)*255) for index in order]


class Subjects:
    def __init__(self,store,settings,file_lock,engine=None):
        self.store,self.settings,self.file_lock=store,settings,file_lock
        self.engine=engine or SamEngine(settings.weights_dir/'sam2')
        self.lock=threading.Lock()
        (settings.data_dir/'masks').mkdir(exist_ok=True)
    def mask_path(self,mask_id):return self.settings.data_dir/'masks'/f'{mask_id}.png'
    def read(self,mask_id):
        row=self.store.one('''SELECT m.* FROM subject_masks m JOIN active_photos p ON p.id=m.photo_id
          WHERE m.id=? AND m.digest=p.digest AND m.model_key=?''',(mask_id,MODEL_KEY))
        if not row:raise HTTPException(404,'Vùng chọn không còn trong thư viện hoặc cần tạo lại.')
        path=self.mask_path(row['id'])
        if not path.is_file() or file_digest(path)!=row['sha256']:raise HTTPException(409,'Vùng chọn thiếu hoặc hỏng. Phân vùng lại ảnh.')
        with Image.open(path) as mask:return row,mask.convert('L')
    def segment(self,payload):
        if not self.lock.acquire(blocking=False):raise HTTPException(429,'Đang phân vùng ảnh. Chờ một chút rồi thử lại.')
        began=time.perf_counter()
        try:
            with self.file_lock:
                photo=metadata(self.store,payload.photo_id)
                point_data=[point.model_dump() for point in payload.points]
                key=hashlib.sha256(json.dumps([photo['digest'],MODEL_KEY,point_data],sort_keys=True).encode()).hexdigest()
                cached=self.store.all('SELECT id,candidate FROM subject_masks WHERE photo_id=? AND cache_key=? ORDER BY candidate',(photo['id'],key))
                if len(cached)==3:
                    try:
                        for row in cached:self.read(row['id'])
                        return {'masks':[{'id':row['id'],'image_url':f"/api/subjects/{row['id']}/overlay"} for row in cached],'cached':True,'seconds':round(time.perf_counter()-began,3)}
                    except HTTPException:pass
                with Image.open(self.settings.data_dir/'photos'/f"{photo['id']}.jpg") as image:
                    image=image.convert('RGB');image.thumbnail((1024,1024))
            if not self.engine.installed:raise HTTPException(503,'Chưa có model phân vùng. Chạy scripts/fetch_segmentation.py.')
            masks=self.engine.segment(image,payload.points)
            if len(masks)!=3 or any(mask.size!=image.size for mask in masks):raise RuntimeError('Model trả vùng chọn không hợp lệ.')
            rows=[]
            with self.file_lock:
                if metadata(self.store,photo['id'])['digest']!=photo['digest']:raise HTTPException(409,'Ảnh nguồn đã thay đổi. Chọn lại ảnh.')
                ensure_space(self.settings,image.width*image.height*3+16384)
                written=[]
                try:
                    with self.store.connection() as db:
                        db.execute('BEGIN IMMEDIATE')
                        for candidate,mask in enumerate(masks):
                            mask_id=uid();path=self.mask_path(mask_id);pending=path.with_suffix('.tmp');written.extend([path,pending])
                            mask.save(pending,'PNG');pending.replace(path)
                            db.execute('INSERT INTO subject_masks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (mask_id,photo['id'],photo['digest'],key,candidate,image.width,image.height,file_digest(path),json.dumps(point_data),MODEL_KEY,now()))
                            rows.append({'id':mask_id,'image_url':f'/api/subjects/{mask_id}/overlay'})
                        if cached:
                            db.executemany('DELETE FROM subject_masks WHERE id=?',[(row['id'],) for row in cached])
                except BaseException:
                    for path in written:path.unlink(missing_ok=True)
                    raise
                for row in cached:self.mask_path(row['id']).unlink(missing_ok=True)
            return {'masks':rows,'cached':False,'seconds':round(time.perf_counter()-began,3)}
        except (RuntimeError,ImportError,OSError) as exc:raise HTTPException(503,f'Chưa phân vùng được ảnh: {str(exc)[:220]}') from exc
        finally:self.lock.release()
    def overlay(self,mask_id):
        with self.file_lock:_,mask=self.read(mask_id)
        result=Image.new('RGBA',mask.size,(70,210,150,0));result.putalpha(mask.point(lambda value:round(value*.42)))
        out=io.BytesIO();result.save(out,'PNG');return out.getvalue()
    def render(self,payload):
        with self.file_lock:
            row,mask=self.read(payload.mask_id)
            with Image.open(self.settings.data_dir/'photos'/f"{row['photo_id']}.jpg") as source:
                image=source.convert('RGB');image.thumbnail((2048,2048))
            if payload.effect=='art-background':
                if not payload.source_output or not self.store.one('SELECT 1 FROM outputs WHERE id=? AND photo_id=?',(payload.source_output,row['photo_id'])):
                    raise HTTPException(422,'Chọn một tác phẩm của ảnh này để dùng làm nền.')
                if not valid_output(self.store,self.settings.data_dir,payload.source_output):raise HTTPException(409,'Tác phẩm nền thiếu hoặc hỏng.')
                with Image.open(self.settings.data_dir/'outputs'/f'{payload.source_output}.png') as art:
                    image.thumbnail((max(art.size),max(art.size)));background=art.convert('RGB').resize(image.size,Image.Resampling.LANCZOS)
            elif payload.effect=='blur':background=image.filter(ImageFilter.GaussianBlur(max(image.size)*.015))
            else:background=ImageOps.grayscale(image).convert('RGB')
            alpha=mask.resize(image.size,Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(.7))
            if not alpha.getbbox():raise HTTPException(422,'Vùng chọn đang trống. Bổ sung điểm và phân vùng lại.')
            if payload.effect=='cutout':result=image.convert('RGBA');result.putalpha(alpha)
            else:result=Image.composite(image,background,alpha)
            title={'cutout':'PNG tách chủ thể','colorpop':'Chủ thể nổi bật','blur':'Làm mờ nền','art-background':'Chủ thể trên nền nghệ thuật'}[payload.effect]
            output=save_output(self.store,self.settings,result,row['photo_id'],'subject:'+payload.effect,title,
                {'profile':'subject2048','model':MODEL_KEY,'points':json.loads(row['points']),'mask_sha256':row['sha256'],'mask_id':row['id'],'effect':payload.effect,'source_output':payload.source_output})
        return {'output_id':output,'image_url':f'/api/outputs/{output}/image','download_url':f'/api/outputs/{output}/image?download=true','title':title}
