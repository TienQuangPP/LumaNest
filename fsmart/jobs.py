"""Durable face indexing and bounded, idempotent single-style admission."""
import hashlib
import json
import logging
import re
import threading

from PIL import Image

from .store import now, uid

log = logging.getLogger('fsmart')


class AdmissionError(ValueError):
    def __init__(self, message, status_code=409):
        super().__init__(message)
        self.status_code = status_code


class StyleAdmission:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()

    def admit(self, photo_id, parameters, request_key=None):
        if request_key and not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', request_key):
            raise AdmissionError('Mã yêu cầu không hợp lệ.', 422)
        fingerprint = hashlib.sha256(json.dumps([photo_id, parameters], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        # One DB transaction covers the limit and the request key, including retries
        # sent from two browser tabs at the same time.
        with self.lock, self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if request_key:
                existing = db.execute('SELECT * FROM job_requests WHERE request_key=?', (request_key,)).fetchone()
                if existing:
                    if existing['fingerprint'] != fingerprint:
                        raise AdmissionError('Mã yêu cầu đã được dùng cho lựa chọn khác. Gửi một yêu cầu mới.')
                    return existing['job_id'], False
            active = db.execute("SELECT count(*) FROM jobs WHERE kind='stylize' AND status IN ('queued','running')").fetchone()[0]
            if active >= 20:
                raise AdmissionError('Hàng đợi đã có 20 tác vụ tạo ảnh. Chờ bớt tác vụ rồi thử lại.', 429)
            if not db.execute('SELECT 1 FROM active_photos WHERE id=?', (photo_id,)).fetchone():
                raise AdmissionError('Ảnh không còn trong thư viện.', 404)
            job_id = uid()
            db.execute('INSERT INTO jobs(id,kind,status,message,created) VALUES(?,?,?,?,?)', (job_id,'stylize','queued','Đang chờ xử lý',now()))
            db.execute('INSERT INTO job_targets VALUES(?,?)', (job_id,photo_id))
            if request_key:
                db.execute('INSERT INTO job_requests VALUES(?,?,?)', (request_key,fingerprint,job_id))
            return job_id, True


class FaceIndexQueue:
    def __init__(self, store, settings, models, executor):
        self.store, self.settings, self.models, self.executor = store, settings, models, executor
        self.lock = threading.RLock()
        self.scheduled = set()
        self.stopping = False

    def create(self, photo_ids):
        ids = list(dict.fromkeys(photo_ids))
        with self.store.connection() as db:
            job_id = uid()
            db.execute('INSERT INTO jobs(id,kind,status,message,created) VALUES(?,?,?,?,?)', (job_id,'index','queued','Đang chờ lập chỉ mục',now()))
            db.executemany('INSERT INTO index_items(job_id,photo_id,status) VALUES(?,?,?)', [(job_id,photo,'pending') for photo in ids])
        self.schedule(job_id)
        return job_id

    def recover(self):
        self.store.execute("UPDATE index_items SET status='pending' WHERE status='running'")
        # Older builds had no per-photo job journal. Preserve and requeue those
        # source images instead of permanently marking them failed at startup.
        unowned = self.store.all("SELECT p.id FROM photos p WHERE p.status='queued' AND NOT EXISTS(SELECT 1 FROM index_items i JOIN jobs j ON j.id=i.job_id WHERE i.photo_id=p.id AND j.status IN ('queued','running'))")
        if unowned:
            self.create([row['id'] for row in unowned])
        for row in self.store.all("SELECT id FROM jobs WHERE kind='index' AND status IN ('queued','running')"):
            if self.store.one('SELECT 1 FROM index_items WHERE job_id=?', (row['id'],)):
                self.schedule(row['id'])
            else:
                self.store.update_job(row['id'],'error',1,'Tác vụ cũ đã chuyển sang hàng đợi phục hồi ảnh.')

    def schedule(self, job_id):
        with self.lock:
            if self.stopping or job_id in self.scheduled:
                return
            self.scheduled.add(job_id)
            self.executor.submit(self._step, job_id)

    def stop(self):
        with self.lock:
            self.stopping = True

    def _step(self, job_id):
        try:
            with self.lock:
                if self.stopping:
                    return
                item = self.store.one("SELECT * FROM index_items WHERE job_id=? AND status='pending' ORDER BY photo_id LIMIT 1", (job_id,))
                if not item:
                    self._report(job_id)
                    return
                self.store.execute("UPDATE index_items SET status='running' WHERE job_id=? AND photo_id=?", (job_id,item['photo_id']))
                self.store.execute("UPDATE jobs SET status='running',message='Đang nhận diện khuôn mặt' WHERE id=?", (job_id,))
            photo_id = item['photo_id']
            try:
                with Image.open(self.settings.data_dir/'photos'/f'{photo_id}.jpg') as image:
                    faces = self.models.analyze(image.convert('RGB'))
                self.store.save_faces(photo_id,faces,self.models.key)
                self.store.execute("UPDATE index_items SET status='done',faces=?,error=NULL WHERE job_id=? AND photo_id=?", (len(faces),job_id,photo_id))
            except Exception as exc:
                log.exception('Face indexing failed')
                with self.store.connection() as db:
                    db.execute("UPDATE photos SET status='error',error=? WHERE id=?", (str(exc)[:300],photo_id))
                    db.execute("UPDATE index_items SET status='error',error=? WHERE job_id=? AND photo_id=?", (str(exc)[:300],job_id,photo_id))
            self._report(job_id)
        except Exception as exc:
            log.exception('Index queue failed')
            self.store.update_job(job_id,'error',1,str(exc)[:300])
        finally:
            with self.lock:
                self.scheduled.discard(job_id)
                job = self.store.job(job_id)
                if job and job['status'] in {'queued','running'}:
                    self.schedule(job_id)

    def _report(self, job_id):
        counts = self.store.one("SELECT count(*) total,coalesce(sum(status='done'),0) AS [indexed],coalesce(sum(status='error'),0) failed,coalesce(sum(status='done' AND faces=0),0) without_faces FROM index_items WHERE job_id=?", (job_id,))
        processed = counts['indexed']+counts['failed']
        status = 'running' if processed < counts['total'] else ('done' if counts['indexed'] else 'error')
        self.store.update_job(job_id,status,processed/max(1,counts['total']),
                              f"Đã xử lý {counts['indexed']}/{counts['total']} ảnh; {counts['failed']} lỗi; {counts['without_faces']} ảnh không có mặt.", counts)
