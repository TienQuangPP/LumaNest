from __future__ import annotations

import json
import heapq
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def uid() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IndexCorruptError(ValueError):
    pass


class _Candidate:
    def __init__(self, row):
        self.row = row

    def __lt__(self, other):
        a, b = self.row, other.row
        return a['similarity'] < b['similarity'] or (a['similarity'] == b['similarity'] and a['id'] > b['id'])


class Store:
    def __init__(self, path: Path):
        self.path = path
        with self.connection() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS albums(id TEXT PRIMARY KEY, name TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS photos(id TEXT PRIMARY KEY, album_id TEXT NOT NULL REFERENCES albums(id), name TEXT NOT NULL, digest TEXT NOT NULL, width INTEGER, height INTEGER, status TEXT NOT NULL, error TEXT, model_key TEXT, created TEXT NOT NULL, UNIQUE(album_id,digest));
                CREATE TABLE IF NOT EXISTS photo_sources(photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE, extension TEXT NOT NULL, mime TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS photo_trash(photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,deleted_at TEXT NOT NULL);
                CREATE VIEW IF NOT EXISTS active_photos AS SELECT p.* FROM photos p WHERE NOT EXISTS(SELECT 1 FROM photo_trash t WHERE t.photo_id=p.id);
                CREATE TABLE IF NOT EXISTS faces(id TEXT PRIMARY KEY, photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE, bbox TEXT NOT NULL, confidence REAL NOT NULL, embedding BLOB NOT NULL, model_key TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS queries(id TEXT PRIMARY KEY, faces TEXT NOT NULL, model_key TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL, result TEXT, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outputs(id TEXT PRIMARY KEY, photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE, style TEXT NOT NULL, created TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS output_details(output_id TEXT PRIMARY KEY REFERENCES outputs(id) ON DELETE CASCADE, title TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS output_assets(output_id TEXT PRIMARY KEY REFERENCES outputs(id) ON DELETE CASCADE, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, profile TEXT NOT NULL, metadata TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS job_requests(request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id));
                CREATE TABLE IF NOT EXISTS job_targets(job_id TEXT NOT NULL REFERENCES jobs(id), photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE, PRIMARY KEY(job_id,photo_id));
                CREATE TABLE IF NOT EXISTS index_items(job_id TEXT NOT NULL REFERENCES jobs(id), photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE, status TEXT NOT NULL, faces INTEGER NOT NULL DEFAULT 0, error TEXT, PRIMARY KEY(job_id,photo_id));
                CREATE INDEX IF NOT EXISTS index_items_pending ON index_items(job_id,status);
                CREATE TABLE IF NOT EXISTS batch_context(job_id TEXT PRIMARY KEY REFERENCES jobs(id), album_id TEXT REFERENCES albums(id), album_name TEXT NOT NULL, closed INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS style_batches(job_id TEXT PRIMARY KEY REFERENCES jobs(id), style TEXT NOT NULL, strength REAL NOT NULL, profile TEXT NOT NULL, elapsed REAL NOT NULL, reserved INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS style_items(job_id TEXT NOT NULL REFERENCES style_batches(job_id), photo_id TEXT NOT NULL REFERENCES photos(id) ON DELETE CASCADE, position INTEGER NOT NULL, status TEXT NOT NULL, output_id TEXT REFERENCES outputs(id) ON DELETE SET NULL, cache_hit INTEGER NOT NULL DEFAULT 0, error TEXT, PRIMARY KEY(job_id,photo_id));
                CREATE INDEX IF NOT EXISTS style_items_pending ON style_items(job_id,status,position);
                CREATE TABLE IF NOT EXISTS style_cache(cache_key TEXT PRIMARY KEY, output_id TEXT NOT NULL REFERENCES outputs(id) ON DELETE CASCADE);
                CREATE INDEX IF NOT EXISTS faces_model ON faces(model_key);
                CREATE INDEX IF NOT EXISTS photos_album ON photos(album_id);
            ''')
            from .library import SCHEMA
            db.executescript(SCHEMA)
            from .subjects import SCHEMA as SUBJECT_SCHEMA
            db.executescript(SUBJECT_SCHEMA)
        # Keep WAL open between short API/worker transactions. Otherwise SQLite
        # checkpoints and removes it whenever the last per-request connection closes.
        self._keeper = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        self._keeper.execute('PRAGMA journal_mode=WAL')

    def close(self):
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def all(self, sql, args=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connection() as db:
            db.execute(sql, args)

    def create_job(self, kind):
        job_id = uid()
        self.execute('INSERT INTO jobs(id,kind,status,message,created) VALUES(?,?,?,?,?)', (job_id, kind, 'queued', 'Đang chờ xử lý', now()))
        return job_id

    def update_job(self, job_id, status, progress, message, result=None):
        self.execute('UPDATE jobs SET status=?,progress=?,message=?,result=? WHERE id=?', (status, progress, message, json.dumps(result, ensure_ascii=False) if result is not None else None, job_id))

    def job(self, job_id):
        row = self.one('SELECT * FROM jobs WHERE id=?', (job_id,))
        if row and row['result']:
            row['result'] = json.loads(row['result'])
        return row

    def save_faces(self, photo_id, faces, model_key):
        with self.connection() as db:
            db.execute('DELETE FROM faces WHERE photo_id=?', (photo_id,))
            for face in faces:
                db.execute('INSERT INTO faces VALUES(?,?,?,?,?,?)', (uid(), photo_id, json.dumps(face['bbox']), face['confidence'], np.asarray(face['embedding'], dtype=np.float32).tobytes(), model_key))
            db.execute('UPDATE photos SET status=?,error=NULL,model_key=? WHERE id=?', ('ready', model_key, photo_id))

    def corrupt_face_photos(self, album_id=None):
        dimensions={}
        for row in self.all('SELECT model_key,length(embedding)/4 dimension,count(*) n FROM faces GROUP BY model_key,length(embedding) ORDER BY n DESC'):
            dimensions.setdefault(row['model_key'],512 if row['model_key'].startswith(('adaface:','facenet:')) else row['dimension'])
        invalid=set()
        with self.connection() as db:
            for row in db.execute('SELECT f.photo_id,f.model_key,f.embedding FROM faces f JOIN active_photos p ON p.id=f.photo_id WHERE (? IS NULL OR p.album_id=?)',(album_id,album_id)):
                try:
                    vector=np.frombuffer(row['embedding'],dtype=np.float32)
                    good=(len(vector)==dimensions[row['model_key']] and len(vector)>0 and np.isfinite(vector).all() and np.linalg.norm(vector)>1e-12)
                except (ValueError,TypeError):
                    good=False
                if not good:
                    invalid.add(row['photo_id'])
        return invalid

    def rank(self, album_id, query, model_key, threshold, top_k):
        q = np.asarray(query, dtype=np.float32)
        if q.ndim != 1 or not q.size or not np.isfinite(q).all() or np.linalg.norm(q) < 1e-12:
            raise IndexCorruptError('Ảnh tham chiếu có embedding không hợp lệ. Trích lại khuôn mặt và lập chỉ mục album.')
        q = q / np.linalg.norm(q)
        heap, current, best = [], None, None

        def keep(candidate):
            if candidate is None:
                return
            heapq.heappush(heap, _Candidate(candidate))
            if len(heap) > top_k:
                heapq.heappop(heap)

        # Ordered streaming retains one photo's best face and at most K candidates.
        # The matrix is bounded to 1024 faces rather than the entire album.
        with self.connection() as db:
            cursor = db.execute('SELECT f.photo_id,f.bbox,f.embedding,p.name,p.width,p.height FROM faces f JOIN active_photos p ON p.id=f.photo_id WHERE p.album_id=? AND f.model_key=? AND p.status=? ORDER BY f.photo_id,f.id', (album_id, model_key, 'ready'))
            while rows := cursor.fetchmany(1024):
                try:
                    vectors = [np.frombuffer(row['embedding'], dtype=np.float32) for row in rows]
                    if any(v.shape != q.shape for v in vectors):
                        raise ValueError('dimension mismatch')
                    matrix = np.stack(vectors)
                    norms = np.linalg.norm(matrix, axis=1)
                    if not np.isfinite(matrix).all() or np.any(norms < 1e-12):
                        raise ValueError('invalid vector')
                    scores = (matrix / norms[:, None]) @ q
                except (ValueError, TypeError) as exc:
                    raise IndexCorruptError('Chỉ mục khuôn mặt bị hỏng. Bấm Lập chỉ mục lại trong Thư viện ảnh.') from exc
                for row, score in zip(rows, scores):
                    if row['photo_id'] != current:
                        keep(best)
                        current, best = row['photo_id'], None
                    score = float(np.clip(score, -1, 1))
                    if score >= threshold and (best is None or score > best['similarity']):
                        best = {'id': current, 'name': row['name'], 'width': row['width'], 'height': row['height'], 'bbox': json.loads(row['bbox']), 'similarity': score}
            keep(best)
        return sorted((item.row for item in heap), key=lambda row: (-row['similarity'], row['id']))
