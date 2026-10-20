"""Persistent photo curation and accent-insensitive full-text search."""
import json
import re
import unicodedata

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from .store import now


SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS photo_metadata(
 photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
 favorite INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL DEFAULT '[]',
 notes TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 0, updated TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS photo_search USING fts5(
 photo_id UNINDEXED,name,tags,notes,tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS search_photo_insert AFTER INSERT ON photos BEGIN
 INSERT INTO photo_search(photo_id,name,tags,notes) VALUES(new.id,new.name,'',''); END;
CREATE TRIGGER IF NOT EXISTS search_photo_delete AFTER DELETE ON photos BEGIN
 DELETE FROM photo_search WHERE photo_id=old.id; END;
CREATE TRIGGER IF NOT EXISTS search_photo_rename AFTER UPDATE OF name ON photos BEGIN
 UPDATE photo_search SET name=new.name WHERE photo_id=new.id; END;
CREATE TRIGGER IF NOT EXISTS search_meta_insert AFTER INSERT ON photo_metadata BEGIN
 UPDATE photo_search SET tags=new.tags,notes=new.notes WHERE photo_id=new.photo_id; END;
CREATE TRIGGER IF NOT EXISTS search_meta_update AFTER UPDATE ON photo_metadata BEGIN
 UPDATE photo_search SET tags=new.tags,notes=new.notes WHERE photo_id=new.photo_id; END;
INSERT INTO photo_search(photo_id,name,tags,notes)
 SELECT p.id,p.name,coalesce(m.tags,''),coalesce(m.notes,'') FROM photos p
 LEFT JOIN photo_metadata m ON m.photo_id=p.id
 WHERE NOT EXISTS(SELECT 1 FROM schema_migrations WHERE version='002-library-discovery')
 AND NOT EXISTS(SELECT 1 FROM photo_search s WHERE s.photo_id=p.id);
CREATE TABLE IF NOT EXISTS semantic_embeddings(
 photo_id TEXT PRIMARY KEY REFERENCES photos(id) ON DELETE CASCADE,
 digest TEXT NOT NULL,model_key TEXT NOT NULL,embedding BLOB NOT NULL,created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS semantic_model ON semantic_embeddings(model_key);
CREATE INDEX IF NOT EXISTS photo_favorites ON photo_metadata(favorite,photo_id);
CREATE INDEX IF NOT EXISTS faces_photo ON faces(photo_id);
CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY,applied TEXT NOT NULL);
INSERT OR IGNORE INTO schema_migrations VALUES('002-library-discovery',datetime('now'));
'''


class MetadataInput(BaseModel):
    model_config = {'extra': 'forbid'}
    favorite: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)
    expected_version: int | None = Field(default=None, ge=0)

    @field_validator('tags')
    @classmethod
    def clean_tags(cls, value):
        if value is None:
            return value
        result, seen = [], set()
        for tag in value:
            tag = unicodedata.normalize('NFC', tag.strip())
            if not tag or len(tag) > 40:
                raise ValueError('Mỗi nhãn cần từ 1 đến 40 ký tự.')
            if tag.casefold() not in seen:
                seen.add(tag.casefold())
                result.append(tag)
        return result


class BatchFavorite(BaseModel):
    model_config = {'extra': 'forbid'}
    photo_ids: list[str] = Field(min_length=1, max_length=10000)
    favorite: bool


def record(row):
    row = dict(row)
    row['favorite'] = bool(row.get('favorite'))
    row['tags'] = json.loads(row.get('tags') or '[]')
    row['notes'] = row.get('notes') or ''
    row['version'] = row.get('version') or 0
    return row


def metadata(store, photo_id):
    row = store.one('''SELECT p.*,coalesce(m.favorite,0) favorite,m.tags,m.notes,m.version,
      (SELECT count(*) FROM faces f WHERE f.photo_id=p.id) face_count
      FROM active_photos p LEFT JOIN photo_metadata m ON m.photo_id=p.id WHERE p.id=?''', (photo_id,))
    if not row:
        raise HTTPException(404, 'Không tìm thấy ảnh trong thư viện.')
    return record(row)


def update_metadata(db, photo_id, payload):
    if not db.execute('SELECT 1 FROM active_photos WHERE id=?', (photo_id,)).fetchone():
        raise HTTPException(404, 'Không tìm thấy ảnh trong thư viện.')
    previous = db.execute('SELECT * FROM photo_metadata WHERE photo_id=?', (photo_id,)).fetchone()
    version = previous['version'] if previous else 0
    if payload.expected_version is not None and payload.expected_version != version:
        raise HTTPException(409, 'Ảnh vừa được chỉnh ở nơi khác. Mở lại thông tin rồi lưu.')
    favorite = int(payload.favorite) if payload.favorite is not None else previous['favorite'] if previous else 0
    tags = json.dumps(payload.tags, ensure_ascii=False) if payload.tags is not None else previous['tags'] if previous else '[]'
    notes = payload.notes if payload.notes is not None else previous['notes'] if previous else ''
    db.execute('''INSERT INTO photo_metadata VALUES(?,?,?,?,?,?) ON CONFLICT(photo_id) DO UPDATE SET
      favorite=excluded.favorite,tags=excluded.tags,notes=excluded.notes,version=excluded.version,updated=excluded.updated''',
      (photo_id, favorite, tags, notes, version + 1, now()))


def list_photos(store, album_id=None, q='', favorite=False, orientation='all', min_faces=0,
                sort='newest', limit=100, offset=0):
    conditions, args = ['1=1'], []
    if album_id:
        conditions.append('p.album_id=?'); args.append(album_id)
    if favorite:
        conditions.append('m.favorite=1')
    if orientation == 'landscape':
        conditions.append('p.width>p.height')
    elif orientation == 'portrait':
        conditions.append('p.height>p.width')
    if min_faces:
        conditions.append('(SELECT count(*) FROM faces f WHERE f.photo_id=p.id)>=?'); args.append(min_faces)
    if q.strip():
        words = re.findall(r'\w+', unicodedata.normalize('NFC', q), re.UNICODE)
        if not words:
            conditions.append('0=1')
        else:
            conditions.append('p.id IN (SELECT photo_id FROM photo_search WHERE photo_search MATCH ?)')
            args.append(' AND '.join('"' + word.replace('"', '""') + '"*' for word in words[:30]))
    join = 'FROM active_photos p LEFT JOIN photo_metadata m ON m.photo_id=p.id WHERE ' + ' AND '.join(conditions)
    total = store.one('SELECT count(*) n ' + join, args)['n']
    order = {'newest': 'p.created DESC,p.id', 'oldest': 'p.created,p.id', 'name': 'p.name COLLATE NOCASE,p.id'}[sort]
    rows = store.all('SELECT p.*,coalesce(m.favorite,0) favorite,m.tags,m.notes,m.version,'
                     '(SELECT count(*) FROM faces f WHERE f.photo_id=p.id) face_count ' + join + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                     (*args, limit, offset))
    return {'items': [record(row) for row in rows], 'total': total, 'offset': offset}
