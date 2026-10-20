"""Persistent, bounded CPU style queue. Yield between images so single jobs can run."""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time

from PIL import Image

from .store import now, uid
from .assets import save_output, valid_output
from .storage import ensure_space
from .fast_style import PROFILES

log = logging.getLogger('fsmart')


class BulkStyles:
    def __init__(self, store, settings, models, executor):
        self.store, self.settings, self.models, self.executor = store, settings, models, executor
        self.lock = threading.RLock()
        self.scheduled = set()
        self.stopping = False

    def create(self, photo_ids, style, strength, profile, album=None):
        ensure_space(self.settings,len(photo_ids)*(PROFILES[profile]**2*3+16384))
        with self.lock, self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            marks=','.join('?' for _ in photo_ids)
            rows=db.execute(f'SELECT id,album_id FROM active_photos WHERE id IN ({marks})',photo_ids).fetchall()
            if len(rows)!=len(set(photo_ids)) or (album and any(row['album_id']!=album['id'] for row in rows)):
                raise ValueError('Có ảnh đã chuyển bộ hoặc vào thùng rác. Chọn lại ảnh trước khi tạo lô.')
            active = db.execute("SELECT count(*) FROM jobs WHERE kind='bulk-style' AND status IN ('queued','running')").fetchone()[0]
            if active >= 4:
                raise ValueError('Đang có 4 lô xử lý. Chờ hoặc dừng bớt trước khi thêm lô mới.')
            job_id = uid()
            db.execute('INSERT INTO jobs(id,kind,status,message,created) VALUES(?,?,?,?,?)', (job_id, 'bulk-style', 'queued', 'Đang chờ xử lý lô', now()))
            db.execute('INSERT INTO style_batches VALUES(?,?,?,?,?,?)', (job_id, style, strength, profile, 0, 0))
            if album:
                db.execute('INSERT INTO batch_context VALUES(?,?,?,0)', (job_id, album['id'], album['name']))
            db.executemany('INSERT INTO style_items(job_id,photo_id,position,status) VALUES(?,?,?,?)', [(job_id, photo, index, 'pending') for index, photo in enumerate(photo_ids)])
        self.store.update_job(job_id,'queued',0,'Đang chờ xử lý lô',self.stats(job_id))
        self.schedule(job_id)
        return job_id

    def recover(self):
        self.store.execute("UPDATE style_items SET status='pending' WHERE status='running'")
        for row in self.store.all("SELECT id FROM jobs WHERE kind='bulk-style' AND status IN ('queued','running')"):
            self.schedule(row['id'])

    def schedule(self, job_id):
        with self.lock:
            if self.stopping or job_id in self.scheduled:
                return
            self.scheduled.add(job_id)
            self.executor.submit(self._step, job_id)

    def stop(self):
        with self.lock:
            self.stopping = True

    def stats(self, job_id):
        batch = self.store.one('SELECT * FROM style_batches WHERE job_id=?', (job_id,))
        counts = self.store.one("SELECT count(*) total,coalesce(sum(status='done'),0) completed,coalesce(sum(status='error'),0) failed,coalesce(sum(cache_hit),0) cached FROM style_items WHERE job_id=?", (job_id,))
        processed = counts['completed'] + counts['failed']
        seconds = batch['elapsed']
        rate = processed / seconds if seconds > 0 else 0
        return {**counts, 'processed': processed, 'elapsed_seconds': round(seconds, 3),
                'images_per_second': round(rate, 3),
                'eta_seconds': round((counts['total']-processed)/rate) if rate else None,
                'style': batch['style'], 'profile': batch['profile'],
                'skipped': self.store.one("SELECT count(*) n FROM style_items WHERE job_id=? AND status='skipped'", (job_id,))['n'],
                'context': self.store.one('SELECT album_id,album_name,closed FROM batch_context WHERE job_id=?', (job_id,)),
                'download_url': f'/api/batches/{job_id}/download' if counts['completed'] else None}

    def report(self, job_id):
        stats = self.stats(job_id)
        job = self.store.job(job_id)
        status = job['status']
        if status not in {'cancelled', 'done', 'error'}:
            if stats['processed'] + stats['skipped'] == stats['total']:
                status = 'error' if stats['failed'] and not stats['completed'] else 'done'
            else:
                status = 'running'
        message = f"{stats['completed']}/{stats['total']} ảnh · {stats['failed']} lỗi · {stats['cached']} dùng lại"
        if status=='cancelled' and job['message'].startswith('Tạm dừng vì') and not (stats['context'] and stats['context']['closed']):
            message=job['message'].split(' · ')[0]+' · '+message
        if stats['skipped']:
            message += f" · {stats['skipped']} bỏ qua"
        self.store.update_job(job_id, status, (stats['processed']+stats['skipped'])/max(1, stats['total']), message, stats)

    def cancel(self, job_id):
        with self.lock:
            # An in-flight image finishes; pending items stay on disk for resume.
            self.store.execute("UPDATE jobs SET status='cancelled',message='Đã yêu cầu dừng sau ảnh hiện tại' WHERE id=? AND status IN ('queued','running')", (job_id,))

    def resume(self, job_id):
        with self.lock:
            context = self.store.one('SELECT closed FROM batch_context WHERE job_id=?', (job_id,))
            if context and context['closed']:
                raise ValueError('Lô đã kết thúc. Tạo lô mới để xử lý các ảnh còn lại.')
            active = self.store.one("SELECT count(*) n FROM jobs WHERE kind='bulk-style' AND status IN ('queued','running') AND id!=?", (job_id,))['n']
            if active >= 4:
                raise ValueError('Đang có 4 lô xử lý. Chờ hoặc dừng bớt trước khi tiếp tục.')
            for row in self.store.all("SELECT photo_id,output_id FROM style_items WHERE job_id=? AND status='done'", (job_id,)):
                if not row['output_id'] or not valid_output(self.store, self.settings.data_dir, row['output_id']):
                    self.store.execute("UPDATE style_items SET status='error',error='File kết quả thiếu hoặc hỏng' WHERE job_id=? AND photo_id=?", (job_id,row['photo_id']))
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                context=db.execute('SELECT closed FROM batch_context WHERE job_id=?',(job_id,)).fetchone()
                if context and context['closed']:
                    raise ValueError('Lô đã kết thúc. Tạo lô mới để xử lý tiếp.')
                active=db.execute("SELECT count(*) FROM jobs WHERE kind='bulk-style' AND status IN ('queued','running') AND id!=?",(job_id,)).fetchone()[0]
                if active>=4:
                    raise ValueError('Đang có 4 lô xử lý. Chờ bớt trước khi tiếp tục.')
                if db.execute("SELECT 1 FROM style_items i LEFT JOIN active_photos p ON p.id=i.photo_id WHERE i.job_id=? AND i.status IN ('pending','error') AND p.id IS NULL LIMIT 1",(job_id,)).fetchone():
                    raise ValueError('Có ảnh đang ở Thùng rác. Khôi phục ảnh trước khi tiếp tục lô.')
                db.execute("UPDATE style_items SET status='pending',error=NULL WHERE job_id=? AND status='error'", (job_id,))
                db.execute("UPDATE jobs SET status='queued',message='Đang tiếp tục lô' WHERE id=?", (job_id,))
        self.schedule(job_id)

    def finish(self, job_id):
        with self.lock:
            with self.store.connection() as db:
                db.execute('INSERT OR IGNORE INTO batch_context(job_id,album_name,closed) VALUES(?,?,1)', (job_id, 'Album'))
                db.execute('UPDATE batch_context SET closed=1 WHERE job_id=?', (job_id,))
                db.execute("UPDATE style_items SET status='skipped' WHERE job_id=? AND status IN ('pending','error')", (job_id,))
                db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))
            self.report(job_id)

    def render(self, photo, style, strength, profile, progress, title=None):
        engine = getattr(self.models, 'fast_style', None)
        fingerprint = engine.fingerprint(style) if engine else 'test-model'
        # Profile and model content are part of identity. Never reuse a different resolution.
        key = hashlib.sha256(json.dumps([photo['id'], photo['digest'], style, strength, profile, fingerprint, title, 'style-output-v1'], separators=(',', ':')).encode()).hexdigest()
        cached = self.store.one('SELECT output_id FROM style_cache WHERE cache_key=?', (key,))
        if cached and valid_output(self.store, self.settings.data_dir, cached['output_id']):
            return cached['output_id'], True
        if cached:
            self.store.execute('DELETE FROM style_cache WHERE cache_key=?', (key,))
        ensure_space(self.settings,PROFILES[profile]**2*3+16384)
        with Image.open(self.settings.data_dir/'photos'/f'{photo["id"]}.jpg') as source:
            output = self.models.preset(source.convert('RGB'), style, strength, progress, profile=profile)
        output_id = save_output(self.store, self.settings, output, photo['id'], style, title,
                                {'profile':profile,'backend':self.models.status().get('style_backend','test'),'model':fingerprint})
        self.store.execute('INSERT OR REPLACE INTO style_cache VALUES(?,?)', (key, output_id))
        return output_id, False

    def _step(self, job_id):
        try:
            with self.lock:
                job = self.store.job(job_id)
                if self.stopping or job['status'] not in {'queued', 'running'}:
                    return
                batch = self.store.one('SELECT * FROM style_batches WHERE job_id=?', (job_id,))
                item = self.store.one("SELECT * FROM style_items WHERE job_id=? AND status='pending' ORDER BY position LIMIT 1", (job_id,))
                if not item:
                    self.report(job_id)
                    return
                self.store.execute("UPDATE style_items SET status='running' WHERE job_id=? AND photo_id=?", (job_id, item['photo_id']))
                self.store.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
            start = time.perf_counter()
            try:
                photo = self.store.one('SELECT * FROM active_photos WHERE id=?', (item['photo_id'],))
                output_id, cached = self.render(photo, batch['style'], batch['strength'], batch['profile'], lambda *args: None)
                self.store.execute("UPDATE style_items SET status='done',output_id=?,cache_hit=?,error=NULL WHERE job_id=? AND photo_id=?", (output_id, int(cached), job_id, item['photo_id']))
            except Exception as exc:
                log.exception('Bulk image failed')
                self.store.execute("UPDATE style_items SET status='error',error=? WHERE job_id=? AND photo_id=?", (str(exc)[:300], job_id, item['photo_id']))
                if getattr(exc,'status_code',None)==507:
                    self.store.execute("UPDATE jobs SET status='cancelled',message=? WHERE id=?",('Tạm dừng vì không đủ dung lượng. Giải phóng ổ đĩa rồi tiếp tục.',job_id))
            self.store.execute('UPDATE style_batches SET elapsed=elapsed+? WHERE job_id=?', (time.perf_counter()-start, job_id))
            with self.lock:
                self.report(job_id)
        except Exception as exc:
            log.exception('Bulk queue failed')
            self.store.update_job(job_id, 'error', 1, str(exc)[:300])
        finally:
            with self.lock:
                self.scheduled.discard(job_id)
                job = self.store.job(job_id)
                if job and job['status'] in {'queued', 'running'}:
                    self.schedule(job_id)
