"""Recoverable photo deletion; originals, embeddings and outputs stay until purge."""
import logging

from fastapi import HTTPException

from .store import now

log=logging.getLogger('fsmart')


def require_idle(db,ids,rows):
    marks=','.join('?' for _ in ids)
    if any(row['status']=='queued' for row in rows):
        raise HTTPException(409,'Chờ lập chỉ mục hoàn tất trước khi xóa ảnh.')
    if db.execute(f"SELECT 1 FROM job_targets t JOIN jobs j ON j.id=t.job_id WHERE t.photo_id IN ({marks}) AND j.status IN ('queued','running') LIMIT 1",ids).fetchone():
        raise HTTPException(409,'Chờ tác vụ tạo ảnh hoàn tất trước khi xóa.')
    if db.execute(f"SELECT 1 FROM style_items i JOIN jobs j ON j.id=i.job_id LEFT JOIN batch_context c ON c.job_id=j.id WHERE i.photo_id IN ({marks}) AND j.status IN ('queued','running','cancelled','error') AND coalesce(c.closed,0)=0 LIMIT 1",ids).fetchone():
        raise HTTPException(409,'Ảnh thuộc lô chưa kết thúc. Hoàn tất hoặc kết thúc lô trước khi xóa.')


class PhotoTrash:
    def __init__(self,store,settings,lock):
        self.store,self.settings,self.lock=store,settings,lock

    def put(self,album_id,photo_ids):
        ids=list(dict.fromkeys(photo_ids));marks=','.join('?' for _ in ids)
        with self.lock,self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute(f'SELECT id,status FROM active_photos WHERE album_id=? AND id IN ({marks})',[album_id,*ids]).fetchall()
            if len(rows)!=len(ids):
                raise HTTPException(422,'Có ảnh không còn trong bộ đang mở. Chưa chuyển ảnh nào vào thùng rác.')
            require_idle(db,ids,rows)
            db.executemany('INSERT INTO photo_trash VALUES(?,?)',[(photo,now()) for photo in ids])
        return {'trashed':len(ids),'photo_ids':ids}

    def restore(self,photo_ids):
        ids=list(dict.fromkeys(photo_ids));marks=','.join('?' for _ in ids)
        with self.lock,self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute(f'SELECT p.id,p.album_id FROM photos p JOIN photo_trash t ON t.photo_id=p.id WHERE p.id IN ({marks})',ids).fetchall()
            if len(rows)!=len(ids):
                raise HTTPException(422,'Có ảnh không còn trong thùng rác. Chưa khôi phục ảnh nào.')
            db.execute(f'DELETE FROM photo_trash WHERE photo_id IN ({marks})',ids)
        return {'restored':len(ids),'photo_ids':ids,'album_ids':list(dict.fromkeys(row['album_id'] for row in rows))}

    def purge(self,photo_ids):
        ids=list(dict.fromkeys(photo_ids));marks=','.join('?' for _ in ids)
        with self.lock:
            with self.store.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                rows=db.execute(f'SELECT p.id,p.status,s.extension FROM photos p JOIN photo_trash t ON t.photo_id=p.id LEFT JOIN photo_sources s ON s.photo_id=p.id WHERE p.id IN ({marks})',ids).fetchall()
                if len(rows)!=len(ids):
                    raise HTTPException(422,'Chỉ xóa vĩnh viễn ảnh đang trong thùng rác. Chưa xóa ảnh nào.')
                require_idle(db,ids,rows)
                outputs=db.execute(f'SELECT id FROM outputs WHERE photo_id IN ({marks})',ids).fetchall()
                masks=db.execute(f'SELECT id FROM subject_masks WHERE photo_id IN ({marks})',ids).fetchall()
                affected=[row[0] for row in db.execute(f'SELECT DISTINCT job_id FROM style_items WHERE photo_id IN ({marks})',ids)]
                paths=[]
                for row in rows:
                    paths.extend(self.settings.data_dir/folder/f'{row["id"]}.jpg' for folder in ['photos','thumbs'])
                    if row['extension']:
                        paths.append(self.settings.data_dir/'originals'/f'{row["id"]}.{row["extension"]}')
                paths.extend(self.settings.data_dir/'outputs'/f'{row["id"]}.png' for row in outputs)
                paths.extend(self.settings.data_dir/'masks'/f'{row["id"]}.png' for row in masks)
                db.execute(f'DELETE FROM photos WHERE id IN ({marks})',ids)
            failures=0
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    failures+=1;log.exception('Purge file cleanup failed: %s',path.name)
        return {'purged':len(ids),'file_cleanup_errors':failures,'affected_batch_ids':affected}
