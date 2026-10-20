"""Local, incremental SigLIP 2 search. Loading never executes Hub Python code."""
import hashlib
import heapq
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import HTTPException
from PIL import Image

from .library import record
from .store import now

REPO = 'google/siglip2-base-patch16-224'
REVISION = '75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2'
MODEL_KEY = REPO + '@' + REVISION


class SiglipEngine:
    dimension = 768
    def __init__(self, directory):
        self.directory, self.model, self.processor = directory, None, None

    @property
    def installed(self):
        return (self.directory/'model.safetensors').is_file() and (self.directory/'provenance.json').is_file()

    def load(self):
        if self.model is not None:
            return
        if not self.installed:
            raise RuntimeError('Chưa có SigLIP 2. Chạy scripts/fetch_semantic.py theo hướng dẫn cài đặt.')
        manifest = json.loads((self.directory/'provenance.json').read_text('utf-8'))
        if manifest['revision'] != REVISION or manifest['repo'] != REPO:
            raise RuntimeError('Phiên bản model không khớp bản đã kiểm tra.')
        for name,item in manifest['files'].items():
            path = self.directory/name
            if path.parent != self.directory or not path.is_file():
                raise RuntimeError('Thiếu file model trong manifest.')
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if digest != item['sha256']:
                raise RuntimeError('Checksum model không khớp. Tải lại trọng số.')
        import torch
        from transformers import AutoModel, AutoProcessor
        torch.set_num_threads(4)
        self.processor = AutoProcessor.from_pretrained(self.directory, local_files_only=True, trust_remote_code=False)
        self.model = AutoModel.from_pretrained(self.directory, local_files_only=True,
                                              trust_remote_code=False, use_safetensors=True).eval()

    def encode(self, image=None, text=None):
        self.load()
        import torch
        with torch.inference_mode():
            if image is not None:
                inputs = self.processor(images=image, return_tensors='pt')
                vector = self.model.get_image_features(**inputs)
            else:
                inputs = self.processor(text=[text.lower()], padding='max_length', max_length=64,
                                        truncation=True, return_tensors='pt')
                vector = self.model.get_text_features(**inputs)
            if not torch.is_tensor(vector):
                vector = vector.pooler_output
            result = vector[0].float().cpu().numpy()
        return normalized(result)


def normalized(vector):
    vector = np.asarray(vector, dtype=np.float32)
    norm = np.linalg.norm(vector)
    if vector.ndim != 1 or not vector.size or not np.isfinite(vector).all() or norm < 1e-12:
        raise ValueError('Embedding không hợp lệ. Cập nhật chỉ mục AI.')
    return vector/norm


class SemanticIndex:
    def __init__(self, store, settings, file_lock, engine=None):
        self.store, self.settings, self.file_lock = store, settings, file_lock
        self.engine = engine or SiglipEngine(settings.weights_dir/'siglip2')
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fsm-discovery')
        previous=store.one("SELECT id FROM jobs WHERE kind='semantic-index' ORDER BY created DESC,id DESC LIMIT 1")
        self.job_id=previous['id'] if previous else None

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def status(self, album_id=None):
        total = self.store.one('SELECT count(*) n FROM active_photos WHERE (? IS NULL OR album_id=?)', (album_id,album_id))['n']
        count = self.store.one('''SELECT count(*) n FROM semantic_embeddings e JOIN active_photos p ON p.id=e.photo_id
          WHERE e.model_key=? AND e.digest=p.digest AND (? IS NULL OR p.album_id=?)''', (MODEL_KEY,album_id,album_id))['n']
        job = self.store.job(self.job_id) if self.job_id else None
        return {'installed':self.engine.installed, 'indexed':count, 'total':total, 'model':REPO,
                'revision':REVISION, 'busy':self.lock.locked(), 'job':job}

    def start(self, album_id):
        if not self.engine.installed:
            raise HTTPException(503, 'Chưa có trọng số SigLIP 2. Xem hướng dẫn cài tìm kiếm AI.')
        if not self.lock.acquire(blocking=False):
            raise HTTPException(429, 'AI đang xử lý. Đợi tác vụ hiện tại hoàn tất.')
        try:
            self.job_id = self.store.create_job('semantic-index')
            self.executor.submit(self._index, album_id, self.job_id)
            return {'job_id':self.job_id}
        except BaseException:
            self.lock.release()
            raise

    def _index(self, album_id, job):
        started, done, errors = time.perf_counter(), 0, []
        try:
            candidates = self.store.all('''SELECT p.id,p.digest,e.embedding FROM active_photos p
              LEFT JOIN semantic_embeddings e ON e.photo_id=p.id AND e.model_key=? AND e.digest=p.digest
              WHERE p.album_id=? ORDER BY p.id''', (MODEL_KEY,album_id))
            rows=[]
            for row in candidates:
                try:
                    vector=normalized(np.frombuffer(row['embedding'],dtype=np.float32))
                    if vector.size!=self.engine.dimension:
                        raise ValueError('dimension')
                except (ValueError,TypeError):
                    rows.append(row)
            self.store.update_job(job,'running',0,'Đang chuẩn bị tìm kiếm AI cục bộ…')
            for i, row in enumerate(rows):
                try:
                    with self.file_lock:
                        if not self.store.one('SELECT 1 FROM active_photos WHERE id=?',(row['id'],)):
                            continue
                        with Image.open(self.settings.data_dir/'photos'/f"{row['id']}.jpg") as source:
                            image = source.convert('RGB')
                            image.thumbnail((1024,1024))
                    vector = self.engine.encode(image=image)
                    with self.store.connection() as db:
                        db.execute('BEGIN IMMEDIATE')
                        active = db.execute('SELECT digest FROM active_photos WHERE id=?',(row['id'],)).fetchone()
                        if active and active['digest']==row['digest']:
                            db.execute('INSERT OR REPLACE INTO semantic_embeddings VALUES(?,?,?,?,?)',
                                       (row['id'],row['digest'],MODEL_KEY,vector.astype(np.float32).tobytes(),now()))
                            done += 1
                except Exception as exc:
                    errors.append({'photo_id':row['id'],'error':str(exc)[:250]})
                    # A model loading failure affects every row; avoid repeating expensive loads.
                    if getattr(self.engine,'model',True) is None:
                        raise
                self.store.update_job(job,'running',(i+1)/max(1,len(rows)),f'Tìm kiếm AI: {i+1}/{len(rows)} ảnh · {len(errors)} lỗi')
            result={'indexed':done,'errors':errors,'elapsed':round(time.perf_counter()-started,3)}
            self.store.update_job(job,'done',1,f'Đã cập nhật {done} ảnh cho tìm kiếm AI · {len(errors)} lỗi.',result)
        except Exception as exc:
            self.store.update_job(job,'error',0,f'Không cập nhật được AI: {str(exc)[:350]}')
        finally:
            self.lock.release()

    def search(self, album_id, text=None, photo_id=None, limit=24):
        if not self.lock.acquire(blocking=False):
            raise HTTPException(429, 'AI đang xử lý. Đợi tác vụ hiện tại hoàn tất.')
        started = time.perf_counter()
        try:
            if photo_id:
                row=self.store.one('''SELECT e.embedding FROM semantic_embeddings e JOIN active_photos p ON p.id=e.photo_id
                  WHERE p.id=? AND p.album_id=? AND e.model_key=? AND e.digest=p.digest''',(photo_id,album_id,MODEL_KEY))
                if not row:
                    raise HTTPException(409,'Ảnh này chưa có chỉ mục AI trong bộ hiện tại. Bấm cập nhật AI.')
                query=normalized(np.frombuffer(row['embedding'],dtype=np.float32))
            else:
                query=self.engine.encode(text=text)
            heap=[]
            with self.store.connection() as db:
                cursor=db.execute('''SELECT p.*,coalesce(m.favorite,0) favorite,m.tags,m.notes,m.version,e.embedding,
                  (SELECT count(*) FROM faces f WHERE f.photo_id=p.id) face_count
                  FROM active_photos p JOIN semantic_embeddings e ON p.id=e.photo_id
                  LEFT JOIN photo_metadata m ON m.photo_id=p.id
                  WHERE p.album_id=? AND e.model_key=? AND e.digest=p.digest AND p.id!=?''',(album_id,MODEL_KEY,photo_id or ''))
                while rows:=cursor.fetchmany(256):
                    for row in rows:
                        item=dict(row)
                        vector=normalized(np.frombuffer(item.pop('embedding'),dtype=np.float32))
                        if vector.shape!=query.shape:
                            raise ValueError('Kích thước chỉ mục AI sai. Cập nhật lại trọng số và chỉ mục.')
                        score=float(np.clip(vector@query,-1,1))
                        candidate=(score,item['id'],item)
                        if len(heap)<limit: heapq.heappush(heap,candidate)
                        elif candidate[:2]>heap[0][:2]: heapq.heapreplace(heap,candidate)
            items=[{**record(item),'similarity':score} for score,_,item in sorted(heap,reverse=True)]
            return {'items':items,'elapsed':round(time.perf_counter()-started,3),'coverage':self.status(album_id),
                    'notice':'Kết quả được xếp hạng theo nội dung gần nhất; điểm cosine không phải xác suất đúng.'}
        except (ImportError,RuntimeError,OSError) as exc:
            raise HTTPException(503,f'Không nạp được tìm kiếm AI: {str(exc)[:300]}') from exc
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc
        finally:
            self.lock.release()
