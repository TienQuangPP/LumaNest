"""Read actual DB/filesystem state; never label model accuracy as verified here."""
import importlib.metadata
import json
import os
import platform
import shutil
import time

import numpy as np
from PIL import Image

from .assets import valid_output, file_digest
from .images import resized
from .store import now


def cpu_name():
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'HARDWARE\DESCRIPTION\System\CentralProcessor\0') as key:
                return winreg.QueryValueEx(key,'ProcessorNameString')[0].strip()
        except OSError:
            pass
    return platform.processor() or platform.machine()


def status(store,settings,models,chat):
    disk = shutil.disk_usage(settings.data_dir)
    counts = store.one("SELECT count(*) photos,coalesce(sum(status='queued'),0) pending,coalesce(sum(status='error'),0) failed,coalesce(sum(status='ready'),0) ready FROM active_photos")
    counts['faces'] = store.one('SELECT count(*) n FROM faces f JOIN active_photos p ON p.id=f.photo_id')['n']
    counts['trashed']=store.one('SELECT count(*) n FROM photo_trash')['n']
    counts['outputs'] = store.one('SELECT count(*) n FROM outputs')['n']
    versions = {}
    for name in ['torch','openvino','fastapi','pillow']:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {'checked_at':now(),'cpu':cpu_name(),'logical_cpus':os.cpu_count(),'disk_free_gb':round(disk.free/1024**3,2),
            'disk_total_gb':round(disk.total/1024**3,2),'counts':counts,'models':models.status(),
            'versions':versions,'chat_configured':chat.status()['configured'],'chat':chat.status(),
            'subject_model_installed':(settings.weights_dir/'sam2/model.safetensors').is_file(),
            'jobs':store.all("SELECT kind,status,count(*) count FROM jobs WHERE status IN ('running','queued') GROUP BY kind,status"),
            'limits':{'batch_images':10000,'active_batches':4,'single_style_jobs':20,'upload_mb':settings.max_upload_bytes/1024**2,'image_pixels':settings.max_image_pixels,'request_mb':128},
            'accuracy_evaluated':False}


def _readable(path):
    try:
        with Image.open(path) as image:
            image.load()
        return True
    except (OSError, ValueError):
        return False


def verify(store,settings,models):
    started = time.perf_counter()
    checks,issues = [],[]
    with store.connection() as db:
        database_ok = db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        foreign_keys_ok = db.execute('PRAGMA foreign_key_check').fetchone() is None
    checks.append({'id':'database','ok':database_ok and foreign_keys_ok,'label':'Cấu trúc SQLite và liên kết dữ liệu'})
    counts = {'missing_photos':0,'missing_thumbnails':0,'invalid_outputs':0,'invalid_sources':0,'legacy_sources':0,'invalid_embeddings':0}
    photos=store.all('SELECT id,name FROM photos')
    for photo in photos:
        for folder,key in [('photos','missing_photos'),('thumbs','missing_thumbnails')]:
            if not _readable(settings.data_dir/folder/f'{photo["id"]}.jpg'):
                counts[key]+=1
                if len(issues)<40:
                    issues.append({'kind':key,'photo_id':photo['id'],'name':photo['name']})
        source = store.one('SELECT * FROM photo_sources WHERE photo_id=?',(photo['id'],))
        if not source:
            counts['legacy_sources']+=1
        else:
            path=settings.data_dir/'originals'/f'{photo["id"]}.{source["extension"]}'
            if not path.is_file() or path.stat().st_size!=source['bytes'] or file_digest(path)!=source['sha256']:
                counts['invalid_sources']+=1
    outputs=store.all('SELECT id FROM outputs')
    for output in outputs:
        counts['invalid_outputs'] += not valid_output(store,settings.data_dir,output['id'])
    dimensions,face_count = {},0
    with store.connection() as db:
        for row in db.execute('SELECT model_key,embedding FROM faces'):
            face_count+=1
            try:
                vector=np.frombuffer(row['embedding'],dtype=np.float32)
                dimension=dimensions.setdefault(row['model_key'],len(vector))
                good=(len(vector)>0 and len(vector)==dimension and np.isfinite(vector).all() and np.linalg.norm(vector)>1e-12)
            except ValueError:
                good=False
            counts['invalid_embeddings']+=not good
    labels = {'missing_photos':'Ảnh xử lý đọc được','missing_thumbnails':'Ảnh thu nhỏ đọc được','invalid_outputs':'PNG kết quả đúng checksum','invalid_sources':'Bản upload gốc đúng checksum','invalid_embeddings':'Embedding hữu hạn và cùng số chiều'}
    checked={'missing_photos':len(photos),'missing_thumbnails':len(photos),
             'invalid_outputs':len(outputs),'invalid_sources':len(photos)-counts['legacy_sources'],
             'invalid_embeddings':face_count}
    checks += [{'id':key,'ok':counts[key]==0,'label':label,'count':counts[key],
                'checked_count':checked[key],'applicable':checked[key]>0} for key,label in labels.items()]
    semantic_count,invalid_semantic=0,0
    from .semantic import MODEL_KEY
    with store.connection() as db:
        for row in db.execute('SELECT model_key,embedding FROM semantic_embeddings'):
            semantic_count+=1
            try:
                vector=np.frombuffer(row['embedding'],dtype=np.float32)
                good=(vector.ndim==1 and len(vector)>0 and np.isfinite(vector).all()
                      and abs(np.linalg.norm(vector)-1)<1e-4 and (row['model_key']!=MODEL_KEY or len(vector)==768))
            except (ValueError,TypeError):
                good=False
            invalid_semantic+=not good
        missing_search=db.execute('SELECT count(*) FROM photos p WHERE (SELECT count(*) FROM photo_search s WHERE s.photo_id=p.id)!=1').fetchone()[0]
        orphan_search=db.execute('SELECT count(*) FROM photo_search s WHERE NOT EXISTS(SELECT 1 FROM photos p WHERE p.id=s.photo_id)').fetchone()[0]
        invalid_metadata=0
        for row in db.execute('SELECT tags,notes,favorite FROM photo_metadata'):
            try:
                tags=json.loads(row['tags'])
                good=isinstance(tags,list) and all(isinstance(tag,str) for tag in tags) and row['favorite'] in (0,1)
            except (ValueError,TypeError):
                good=False
            invalid_metadata+=not good
    counts.update(invalid_semantic_embeddings=invalid_semantic,invalid_search_rows=missing_search+orphan_search,invalid_metadata=invalid_metadata)
    checks.extend([
        {'id':'semantic','ok':invalid_semantic==0,'label':'Vector tìm nội dung hữu hạn, chuẩn hóa và đúng số chiều','checked_count':semantic_count,'count':invalid_semantic,'applicable':semantic_count>0},
        {'id':'curation','ok':not (missing_search or orphan_search or invalid_metadata),'label':'Nhãn, yêu thích và chỉ mục toàn văn khớp thư viện'}])
    warnings=[]
    invalid_masks=0
    mask_rows=store.all('SELECT id,sha256 FROM subject_masks')
    for row in mask_rows:
        path=settings.data_dir/'masks'/f'{row["id"]}.png'
        invalid_masks+=not (path.is_file() and _readable(path) and file_digest(path)==row['sha256'])
    counts['invalid_subject_masks']=invalid_masks
    checks.append({'id':'subjects','ok':not invalid_masks,'label':'Vùng chọn chủ thể đúng checksum',
                   'checked_count':len(mask_rows),'count':invalid_masks,'applicable':bool(mask_rows)})
    free=shutil.disk_usage(settings.data_dir).free
    checks.append({'id':'disk','ok':free>=128*1024*1024,'label':'Dung lượng trống trên mức dự phòng 128 MB'})
    if free<2*1024**3:
        warnings.append(f'Ổ dữ liệu còn {free/1024**3:.2f} GB. Kiểm tra dung lượng trước khi xử lý hoặc đóng ZIP lớn.')
    if counts['legacy_sources']:
        warnings.append(f"{counts['legacy_sources']} ảnh nhập từ bản cũ chỉ còn JPEG đã lưu; không thể khôi phục byte upload gốc từ bản đó.")
    warnings.append('Chưa có bộ test độc lập được gán nhãn để xác nhận độ chính xác nhận diện. Kiểm tra file không xác nhận accuracy.')
    return {'checked_at':now(),'seconds':round(time.perf_counter()-started,3),'passed':all(check['ok'] for check in checks),
            'checks':checks,'counts':counts,'warnings':warnings,'issues':issues,'accuracy_evaluated':False}


def repair_thumbnails(store,settings):
    repaired,failed=0,0
    for photo in store.all('SELECT id FROM photos'):
        path=settings.data_dir/'thumbs'/f'{photo["id"]}.jpg'
        if _readable(path):
            continue
        pending=path.with_suffix('.tmp')
        try:
            with Image.open(settings.data_dir/'photos'/f'{photo["id"]}.jpg') as source:
                thumb=resized(source.convert('RGB'),640)
                thumb.thumbnail((640,480))
                thumb.save(pending,'JPEG',quality=86)
            pending.replace(path)
            repaired+=1
        except (OSError,ValueError):
            failed+=1
        finally:
            pending.unlink(missing_ok=True)
    return {'repaired':repaired,'failed':failed}
