from __future__ import annotations

import hashlib
import io
import json
import logging
import sqlite3
import tempfile
import time
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .chat import ChatConfigInput, ChatInput, ChatService, ChatUnavailable, GeminiConfigInput, ChatProviderInput
from .images import decode_image, save_photo, save_source, image_digest
from .models import Models, ModelUnavailable
from .store import Store, now, uid, IndexCorruptError
from .bulk import BulkStyles
from .assets import save_output, valid_output, file_digest
from .jobs import StyleAdmission, FaceIndexQueue, AdmissionError
from .http_guard import RequestSizeGuard
from . import diagnostics
from .storage import ensure_space
from .api_docs import documentation
from .trash import PhotoTrash
from .modern import install as install_modern

log = logging.getLogger('fsmart')


class AlbumInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ReindexInput(BaseModel):
    scope: Literal['all', 'failed', 'outdated'] = 'all'


class MovePhotosInput(BaseModel):
    photo_ids: list[str] = Field(min_length=1,max_length=10000)
    destination_album_id: str | None = Field(default=None,pattern=r'^[0-9a-f]{32}$')
    new_album_name: str | None = Field(default=None,min_length=1,max_length=100)


class SearchInput(BaseModel):
    album_id: str
    query_id: str
    face_index: int = Field(default=0, ge=0)
    threshold: float | None = Field(default=None, ge=-1, le=1)
    top_k: int = Field(default=20, ge=1, le=100)


class ExportInput(BaseModel):
    photo_ids: list[str] = Field(min_length=1, max_length=10000)


class ChatStyleInput(BaseModel):
    model_config = {'extra': 'forbid'}
    photo_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    plan_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    profile: Literal['fast', 'balanced', 'quality'] = 'fast'


class BatchStyleInput(BaseModel):
    album_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    photo_ids: list[str] | None = Field(default=None, min_length=1, max_length=10000)
    style: Literal['candy', 'mosaic', 'rain_princess', 'udnie']
    strength: float = Field(default=.8, ge=0, le=1)
    profile: Literal['fast', 'balanced', 'quality'] = 'fast'


def create_app(settings: Settings | None = None, model_service=None, chat_service=None):
    settings = settings or Settings()
    store = Store(settings.data_dir / 'memories.db')
    models = model_service or Models(settings)
    if chat_service is None and model_service is None:
        from .local_chat import LocalChat
        chat_service = ChatService(local_engine=LocalChat(settings.weights_dir / 'chat-cpu',settings.data_dir/'logs'))
    chat = chat_service or ChatService()
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fsm-style')
    index_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fsm-faces')
    bulk = BulkStyles(store, settings, models, executor)
    index_queue = FaceIndexQueue(store, settings, models, index_executor)
    admission = StyleAdmission(store)
    file_lock = threading.RLock()
    semantic = None
    export_tickets = {}

    @asynccontextmanager
    async def lifespan(app):
        store.execute("UPDATE jobs SET status='error',message='Tác vụ tạo ảnh bị gián đoạn. Kiểm tra kết quả trước khi gửi lại; tác vụ API không tự gọi lại để tránh phát sinh phí.' WHERE status IN ('running','queued') AND kind NOT IN ('bulk-style','index','semantic-index')")
        store.execute("UPDATE jobs SET status='error',message='Cập nhật AI bị gián đoạn. Bấm Cập nhật AI để tiếp tục phần thiếu; vector đã lưu được giữ lại.' WHERE status IN ('running','queued') AND kind='semantic-index'")
        bulk.recover()
        index_queue.recover()
        try:
            yield
        finally:
            if chat.local_engine is not None:
                chat.local_engine.close()
            if semantic is not None:
                semantic.close()
            bulk.stop()
            index_queue.stop()
            index_executor.shutdown(wait=True, cancel_futures=True)
            executor.shutdown(wait=True, cancel_futures=True)
            store.close()

    app = FastAPI(title='LumaNest', version='1.0.1', lifespan=lifespan,docs_url=None,redoc_url=None)
    app.state.store, app.state.models, app.state.settings = store, models, settings
    app.state.chat = chat
    app.state.bulk = bulk
    app.state.index_queue = index_queue
    semantic = install_modern(app, store, settings, file_lock)
    app.add_middleware(RequestSizeGuard)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','[::1]','testserver'])

    @app.middleware('http')
    async def same_origin(request: Request, call_next):
        if request.url.path.startswith('/api/') and request.headers.get('sec-fetch-site')=='cross-site':
            return JSONResponse({'detail':'Yêu cầu khác nguồn bị từ chối.'},status_code=403)
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.headers.get('origin'):
            try:
                origin = urlparse(request.headers['origin'])
                valid=origin.netloc==request.headers.get('host') and origin.scheme in {'http','https'}
            except ValueError:
                valid=False
            if not valid:
                return JSONResponse({'detail': 'Yêu cầu khác nguồn bị từ chối.'}, status_code=403)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if request.url.path.startswith('/api/'):
            response.headers.setdefault('Cache-Control','no-store')
        return response

    @app.get('/docs',include_in_schema=False)
    def api_docs():
        return documentation('swagger',app.title+' — API')

    @app.get('/redoc',include_in_schema=False)
    def api_redoc():
        return documentation('redoc',app.title+' — API')

    @app.get('/docs/oauth2-redirect',include_in_schema=False)
    def api_oauth_redirect():
        return documentation('redirect',app.title)

    @app.exception_handler(AdmissionError)
    async def admission_error(request, exc):
        return JSONResponse({'detail':str(exc)},status_code=exc.status_code,headers={'Retry-After':'3'} if exc.status_code==429 else None)

    @app.exception_handler(IndexCorruptError)
    async def corrupt_index(request, exc):
        return JSONResponse({'detail':str(exc)},status_code=409)

    @app.exception_handler(ModelUnavailable)
    async def unavailable_handler(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=503)

    @app.exception_handler(ChatUnavailable)
    async def chat_unavailable_handler(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=exc.status_code,headers={'Cache-Control':'no-store'})

    @app.exception_handler(RequestValidationError)
    async def safe_validation_handler(request, exc):
        if request.url.path.startswith('/api/chat'):
            # FastAPI's default validation body echoes input, including malformed keys.
            return JSONResponse({'detail': 'Thông tin chưa hợp lệ. Câu hỏi tối đa 1.800 ký tự; kiểm tra key và tên model nếu đang cấu hình trợ lý.'}, status_code=422)
        return await request_validation_exception_handler(request, exc)

    @app.get('/api/chat/status')
    def chat_status():
        return JSONResponse(chat.status(), headers={'Cache-Control': 'no-store'})

    @app.post('/api/chat/config')
    def chat_config(payload: ChatConfigInput):
        return JSONResponse(chat.configure(payload), headers={'Cache-Control': 'no-store'})

    @app.delete('/api/chat/config')
    def chat_clear():
        return JSONResponse(chat.clear(), headers={'Cache-Control': 'no-store'})

    @app.post('/api/chat/provider')
    def chat_provider(payload:ChatProviderInput):
        return JSONResponse(chat.select_provider(payload),headers={'Cache-Control':'no-store'})

    @app.post('/api/chat/gemini/config')
    def gemini_config(payload:GeminiConfigInput):
        return JSONResponse(chat.configure_gemini(payload),headers={'Cache-Control':'no-store'})

    @app.delete('/api/chat/gemini/config')
    def gemini_clear():
        return JSONResponse(chat.clear_gemini(),headers={'Cache-Control':'no-store'})

    @app.post('/api/chat/gemini/check')
    def gemini_check():
        return JSONResponse(chat.check_gemini(),headers={'Cache-Control':'no-store'})

    @app.post('/api/chat')
    def chat_reply(payload: ChatInput):
        return JSONResponse(chat.reply(payload), headers={'Cache-Control': 'no-store'})

    def album_or_404(album_id):
        row = store.one('SELECT * FROM albums WHERE id=?', (album_id,))
        if not row:
            raise HTTPException(404, 'Không tìm thấy album.')
        return row

    def photo_or_404(photo_id):
        row = store.one('SELECT * FROM active_photos WHERE id=?', (photo_id,))
        if not row:
            raise HTTPException(404, 'Không tìm thấy ảnh.')
        return row

    async def read_upload(file: UploadFile, with_source=False):
        data = await file.read(settings.max_upload_bytes + 1)
        await file.close()
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, 'Ảnh vượt quá giới hạn 20 MB.')
        try:
            image = await run_in_threadpool(decode_image, data, settings.max_image_pixels)
            if with_source:
                with Image.open(io.BytesIO(data)) as header:
                    return image,data,header.format
            return image
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def calibration():
        path = settings.root / 'config/calibration.json'
        try:
            result = json.loads(path.read_text(encoding='utf-8'))
            if result['model_key'] == models.key and -1 <= float(result['threshold']) <= 1:
                return float(result['threshold']), True
        except (OSError, ValueError, KeyError, ModelUnavailable):
            pass
        return .4, False

    def index_job(job_id, photo_ids):
        good, failed, no_faces = 0, 0, 0
        try:
            model_key = models.key
            for index, photo_id in enumerate(photo_ids):
                store.update_job(job_id, 'running', index / max(1, len(photo_ids)), f'Đang đọc ảnh {index + 1}/{len(photo_ids)}')
                try:
                    with Image.open(settings.data_dir / 'photos' / f'{photo_id}.jpg') as image:
                        faces = models.analyze(image.convert('RGB'))
                    store.save_faces(photo_id, faces, model_key)
                    good += 1
                    no_faces += not bool(faces)
                except Exception as exc:
                    log.exception('Indexing failed for %s', photo_id)
                    store.execute('UPDATE photos SET status=?,error=? WHERE id=?', ('error', str(exc)[:300], photo_id))
                    failed += 1
            result = {'indexed': good, 'failed': failed, 'without_faces': int(no_faces)}
            store.update_job(job_id, 'done' if good else 'error', 1, f'Đã xử lý {good}/{len(photo_ids)} ảnh; {failed} lỗi; {no_faces} ảnh không có mặt.', result)
        except Exception as exc:
            for photo_id in photo_ids:
                store.execute("UPDATE photos SET status='error',error=? WHERE id=? AND status='queued'", (str(exc)[:300], photo_id))
            store.update_job(job_id, 'error', 1, str(exc)[:300])

    @app.get('/api/health')
    def health():
        threshold, calibrated = calibration()
        return {'status': 'ok', **models.status(), 'threshold': threshold, 'threshold_calibrated': calibrated}

    @app.get('/api/system/status')
    def system_status():
        return diagnostics.status(store,settings,models,chat)

    @app.post('/api/system/verify')
    def verify_system():
        return diagnostics.verify(store,settings,models)

    @app.post('/api/system/repair-thumbnails')
    def repair_thumbnails():
        with file_lock:
            return diagnostics.repair_thumbnails(store,settings)

    @app.get('/api/albums')
    def albums():
        return store.all('SELECT a.*,COUNT(p.id) AS photo_count,COALESCE(SUM(p.status="ready"),0) AS indexed_count,(SELECT cover.id FROM active_photos cover WHERE cover.album_id=a.id ORDER BY cover.created DESC,cover.id LIMIT 1) AS cover_photo_id,(SELECT count(*) FROM photo_trash t JOIN photos old ON old.id=t.photo_id WHERE old.album_id=a.id) AS trash_count FROM albums a LEFT JOIN active_photos p ON p.album_id=a.id GROUP BY a.id ORDER BY a.created DESC,a.id')

    @app.post('/api/albums', status_code=201)
    def create_album(payload: AlbumInput):
        name = payload.name.strip()
        if not name:
            raise HTTPException(422, 'Tên album không được để trống.')
        album_id = uid()
        store.execute('INSERT INTO albums VALUES(?,?,?)', (album_id, name, now()))
        return {'id': album_id, 'name': name}

    @app.patch('/api/albums/{album_id}')
    def rename_album(album_id: str, payload: AlbumInput):
        album_or_404(album_id)
        name = payload.name.strip()
        if not name:
            raise HTTPException(422,'Tên album không được để trống.')
        store.execute('UPDATE albums SET name=? WHERE id=?',(name,album_id))
        return {'id':album_id,'name':name}

    @app.get('/api/albums/{album_id}/photos')
    def photos(album_id: str, limit: int = 200, offset: int = 0,q: str = ''):
        album_or_404(album_id)
        if not 1 <= limit <= 500 or offset < 0 or len(q)>160:
            raise HTTPException(422, 'Phân trang không hợp lệ.')
        pattern='%'+q.strip().replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        return store.all("SELECT p.*,COUNT(f.id) AS face_count FROM active_photos p LEFT JOIN faces f ON f.photo_id=p.id WHERE p.album_id=? AND p.name LIKE ? ESCAPE '\\' GROUP BY p.id ORDER BY p.created DESC,p.id LIMIT ? OFFSET ?", (album_id,pattern,limit,offset))

    trash=PhotoTrash(store,settings,file_lock)

    @app.get('/api/albums/{album_id}/trash')
    def list_trash(album_id: str,limit: int = 100,offset: int = 0):
        album_or_404(album_id)
        if not 1<=limit<=500 or offset<0:
            raise HTTPException(422,'Phân trang không hợp lệ.')
        return store.all('SELECT p.id,p.name,p.album_id,p.width,p.height,t.deleted_at FROM photos p JOIN photo_trash t ON t.photo_id=p.id WHERE p.album_id=? ORDER BY t.deleted_at DESC,p.id LIMIT ? OFFSET ?',(album_id,limit,offset))

    @app.post('/api/albums/{album_id}/trash')
    def trash_photos(album_id: str,payload: ExportInput):
        album_or_404(album_id)
        result=trash.put(album_id,payload.photo_ids)
        result['export_cleanup_errors']=invalidate_exports(payload.photo_ids)
        return result

    @app.post('/api/trash/restore')
    def restore_photos(payload: ExportInput):
        return trash.restore(payload.photo_ids)

    @app.post('/api/trash/purge')
    def purge_photos(payload: ExportInput):
        result=trash.purge(payload.photo_ids)
        result['file_cleanup_errors']+=invalidate_exports(payload.photo_ids)
        for job_id in result.pop('affected_batch_ids'):
            bulk.report(job_id)
        return result

    @app.get('/api/trash/{photo_id}/thumbnail')
    def trash_thumbnail(photo_id: str):
        if not store.one('SELECT photo_id FROM photo_trash WHERE photo_id=?',(photo_id,)):
            raise HTTPException(404,'Không tìm thấy ảnh trong thùng rác.')
        path=settings.data_dir/'thumbs'/f'{photo_id}.jpg'
        if not path.is_file():
            raise HTTPException(404,'Ảnh thu nhỏ không còn trên ổ đĩa.')
        return FileResponse(path,media_type='image/jpeg',headers={'Cache-Control':'no-store'})

    @app.post('/api/albums/{album_id}/move-photos')
    def move_photos(album_id: str,payload: MovePhotosInput):
        new_name=(payload.new_album_name or '').strip()
        if bool(payload.destination_album_id)==bool(new_name):
            raise HTTPException(422,'Chọn bộ ảnh đích hoặc nhập tên bộ ảnh mới.')
        destination=payload.destination_album_id or uid()
        if album_id==destination:
            raise HTTPException(422,'Chọn một bộ ảnh đích khác bộ ảnh hiện tại.')
        ids=list(dict.fromkeys(payload.photo_ids))
        placeholders=','.join('?' for _ in ids)
        with file_lock,store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if new_name:
                db.execute('INSERT INTO albums VALUES(?,?,?)',(destination,new_name,now()))
            for identity in [album_id,destination]:
                if not db.execute('SELECT id FROM albums WHERE id=?',(identity,)).fetchone():
                    raise HTTPException(404,'Không tìm thấy bộ ảnh nguồn hoặc đích.')
            rows=db.execute(f'SELECT id,status FROM active_photos WHERE album_id=? AND id IN ({placeholders})',[album_id,*ids]).fetchall()
            if len(rows)!=len(ids):
                raise HTTPException(422,'Có ảnh không thuộc bộ ảnh nguồn. Chưa chuyển ảnh nào.')
            if any(row['status']=='queued' for row in rows):
                raise HTTPException(409,'Chờ lập chỉ mục hoàn tất trước khi chuyển ảnh.')
            if db.execute(f"SELECT 1 FROM job_targets t JOIN jobs j ON j.id=t.job_id WHERE t.photo_id IN ({placeholders}) AND j.status IN ('queued','running') LIMIT 1",ids).fetchone():
                raise HTTPException(409,'Chờ tác vụ tạo ảnh hoàn tất trước khi chuyển ảnh.')
            if db.execute(f"SELECT 1 FROM style_items i JOIN jobs j ON j.id=i.job_id LEFT JOIN batch_context c ON c.job_id=j.id WHERE i.photo_id IN ({placeholders}) AND j.status IN ('queued','running','cancelled','error') AND coalesce(c.closed,0)=0 LIMIT 1",ids).fetchone():
                raise HTTPException(409,'Ảnh thuộc lô chưa kết thúc. Hoàn tất hoặc kết thúc lô trước khi chuyển.')
            if db.execute(f'SELECT 1 FROM photos src JOIN photos dst ON dst.digest=src.digest AND dst.album_id=? WHERE src.id IN ({placeholders}) LIMIT 1',[destination,*ids]).fetchone():
                raise HTTPException(409,'Bộ ảnh đích đã có ảnh trùng. Chưa chuyển ảnh nào; bỏ chọn ảnh trùng rồi thử lại.')
            db.execute(f'UPDATE photos SET album_id=? WHERE id IN ({placeholders})',[destination,*ids])
        return {'moved':len(ids),'source_album_id':album_id,'destination_album_id':destination}

    @app.post('/api/albums/{album_id}/photos', status_code=202)
    async def upload_photos(album_id: str, files: list[UploadFile] = File(...)):
        album_or_404(album_id)
        if len(files) > 50:
            raise HTTPException(422, 'Mỗi lần tải tối đa 50 ảnh.')
        accepted, errors, duplicates = [], [], 0
        for file in files:
            name = (file.filename or 'photo').replace('\\', '/').split('/')[-1][:160]
            written = []
            try:
                image,raw,format_name = await read_upload(file,True)
                ensure_space(settings,len(raw)+image.width*image.height*3+1024*1024)
                digest = await run_in_threadpool(image_digest,image)
                existing=store.one('SELECT id FROM photos WHERE album_id=? AND digest=?',(album_id,digest))
                if existing and store.one('SELECT photo_id FROM photo_trash WHERE photo_id=?',(existing['id'],)):
                    raise HTTPException(409,'Ảnh trùng đang ở Thùng rác của bộ này. Khôi phục ảnh đó trước khi nhập lại.')
                if existing:
                    duplicates += 1
                    continue
                photo_id = uid()
                original = settings.data_dir / 'photos' / f'{photo_id}.jpg'
                thumbnail = settings.data_dir / 'thumbs' / f'{photo_id}.jpg'
                extension,mime = {'JPEG':('jpg','image/jpeg'),'PNG':('png','image/png'),'WEBP':('webp','image/webp')}[format_name]
                source_path = settings.data_dir/'originals'/f'{photo_id}.{extension}'
                written = [original,thumbnail,source_path]
                await run_in_threadpool(save_photo, image, original, thumbnail)
                await run_in_threadpool(save_source, raw, source_path)
                try:
                    with store.connection() as db:
                        db.execute('INSERT INTO photos(id,album_id,name,digest,width,height,status,created) VALUES(?,?,?,?,?,?,?,?)', (photo_id, album_id, name, digest, image.width, image.height, 'queued', now()))
                        db.execute('INSERT INTO photo_sources VALUES(?,?,?,?,?)',(photo_id,extension,mime,hashlib.sha256(raw).hexdigest(),len(raw)))
                except sqlite3.IntegrityError:
                    for path in written:
                        path.unlink(missing_ok=True)
                    duplicates += 1
                    continue
                accepted.append(photo_id)
            except HTTPException as exc:
                errors.append({'name': name, 'message': exc.detail})
            except (OSError,MemoryError):
                log.exception('Photo storage failed')
                for path in written:
                    path.unlink(missing_ok=True)
                errors.append({'name':name,'message':'Không lưu được ảnh. Kiểm tra RAM, dung lượng và quyền ghi ổ đĩa.'})
        job_id = None
        if accepted:
            job_id = index_queue.create(accepted)
        return {'accepted': len(accepted), 'duplicates': duplicates, 'errors': errors, 'job_id': job_id}

    @app.post('/api/albums/{album_id}/reindex', status_code=202)
    def reindex(album_id: str, payload: ReindexInput | None = None):
        album_or_404(album_id)
        pending = store.one("SELECT id FROM active_photos WHERE album_id=? AND status='queued'", (album_id,))
        if pending:
            raise HTTPException(409, 'Album đang được xử lý; chờ tác vụ hiện tại hoàn tất.')
        scope = payload.scope if payload else 'all'
        condition, args = '1=1', [album_id]
        if scope == 'failed':
            condition = "status='error'"
        elif scope == 'outdated':
            condition = "(status!='ready' OR model_key IS NULL OR model_key!=?)"
            args.append(models.key)
        ids = [row['id'] for row in store.all(f'SELECT id FROM active_photos WHERE album_id=? AND {condition}', args)]
        if scope=='outdated':
            ids=list(dict.fromkeys(ids+sorted(store.corrupt_face_photos(album_id))))
        if not ids:
            raise HTTPException(422, 'Không có ảnh cần xử lý theo lựa chọn này.')
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            marks=','.join('?' for _ in ids)
            if db.execute(f'SELECT count(*) FROM active_photos WHERE id IN ({marks})',ids).fetchone()[0]!=len(ids):
                raise HTTPException(409,'Có ảnh vừa chuyển vào thùng rác. Chọn lại phạm vi lập chỉ mục.')
            db.executemany("UPDATE photos SET status='queued',error=NULL WHERE id=?",[(photo,) for photo in ids])
        job_id = index_queue.create(ids)
        return {'job_id': job_id,'total':len(ids)}

    @app.get('/api/photos/{photo_id}/image')
    def photo_image(photo_id: str, thumbnail: bool = False):
        photo_or_404(photo_id)
        path = settings.data_dir / ('thumbs' if thumbnail else 'photos') / f'{photo_id}.jpg'
        if not path.is_file():
            raise HTTPException(404,'File ảnh thiếu trên ổ đĩa. Kiểm tra hệ thống hoặc nhập lại ảnh.')
        return FileResponse(path, media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=3600'})

    @app.get('/api/photos/{photo_id}')
    def photo_metadata(photo_id: str):
        return {**photo_or_404(photo_id),'original_available':bool(store.one('SELECT 1 FROM photo_sources WHERE photo_id=?',(photo_id,)))}

    def source_file(photo_id):
        row = store.one('SELECT * FROM photo_sources WHERE photo_id=?',(photo_id,))
        if row:
            path = settings.data_dir/'originals'/f'{photo_id}.{row["extension"]}'
            if not path.is_file() or file_digest(path)!=row['sha256']:
                raise HTTPException(404,'Ảnh nguồn thiếu hoặc hỏng. Nhập lại ảnh để khôi phục bản gốc.')
            return path,row['extension'],row['mime'],True
        path = settings.data_dir/'photos'/f'{photo_id}.jpg'
        if not path.is_file():
            raise HTTPException(404,'Không còn file ảnh trên ổ đĩa. Nhập lại ảnh.')
        return path,'jpg','image/jpeg',False

    @app.get('/api/photos/{photo_id}/original')
    def original_photo(photo_id: str):
        photo_or_404(photo_id)
        path,extension,mime,exact = source_file(photo_id)
        return FileResponse(path,media_type=mime,filename=f'LumaNest-source-{photo_id[:8]}.{extension}',headers={'X-Original-Available':str(exact).lower()})

    @app.delete('/api/photos/{photo_id}')
    def delete_photo(photo_id: str):
        with file_lock:
            photo=photo_or_404(photo_id)
            result=trash.put(photo['album_id'],[photo_id])
            result['export_cleanup_errors']=invalidate_exports([photo_id])
            return {**result,'deleted':photo_id,'recoverable':True}

    def delete_photo_files(photo_id):
        with store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            photo=db.execute('SELECT * FROM photos WHERE id=?',(photo_id,)).fetchone()
            if not photo:
                raise HTTPException(404,'Không tìm thấy ảnh.')
            if photo['status']=='queued':
                raise HTTPException(409,'Chờ ảnh xử lý xong trước khi xóa.')
            if db.execute("SELECT j.id FROM jobs j JOIN job_targets t ON t.job_id=j.id WHERE t.photo_id=? AND j.status IN ('queued','running')",(photo_id,)).fetchone():
                raise HTTPException(409,'Chờ tác vụ tạo ảnh hoàn tất trước khi xóa.')
            if db.execute("SELECT i.photo_id FROM style_items i JOIN jobs j ON j.id=i.job_id WHERE i.photo_id=? AND i.status IN ('pending','running') AND j.status IN ('queued','running','cancelled')",(photo_id,)).fetchone():
                raise HTTPException(409,'Ảnh thuộc lô đang chạy hoặc tạm dừng. Kết thúc lô trước khi xóa.')
            outputs=[dict(row) for row in db.execute('SELECT id FROM outputs WHERE photo_id=?',(photo_id,))]
            source=db.execute('SELECT extension FROM photo_sources WHERE photo_id=?',(photo_id,)).fetchone()
            affected=[row[0] for row in db.execute('SELECT job_id FROM style_items WHERE photo_id=?',(photo_id,))]
            db.execute('DELETE FROM photos WHERE id=?',(photo_id,))
        for directory in ['photos', 'thumbs']:
            (settings.data_dir / directory / f'{photo_id}.jpg').unlink(missing_ok=True)
        for output in outputs:
            (settings.data_dir / 'outputs' / f'{output["id"]}.png').unlink(missing_ok=True)
        if source:
            (settings.data_dir/'originals'/f'{photo_id}.{source["extension"]}').unlink(missing_ok=True)
        for job_id in affected:
            bulk.report(job_id)
        return {'deleted': photo_id}

    @app.post('/api/query')
    async def query(file: UploadFile = File(...)):
        from starlette.concurrency import run_in_threadpool
        image = await read_upload(file)
        faces = await run_in_threadpool(models.analyze, image)
        query_id = uid()
        if not faces:
            raise HTTPException(422, 'Không tìm thấy khuôn mặt rõ. Hãy thử ảnh khác.')
        store.execute('INSERT INTO queries VALUES(?,?,?,?)', (query_id, json.dumps(faces), models.key, now()))
        image.save(settings.data_dir / 'queries' / f'{query_id}.jpg', 'JPEG', quality=90)
        return {'id': query_id, 'width': image.width, 'height': image.height, 'faces': [{'index': i, 'bbox': face['bbox'], 'confidence': face['confidence']} for i, face in enumerate(faces)]}

    @app.get('/api/query/{query_id}/image')
    def query_image(query_id: str):
        if not store.one('SELECT id FROM queries WHERE id=?', (query_id,)):
            raise HTTPException(404, 'Không tìm thấy ảnh tham chiếu.')
        return FileResponse(settings.data_dir / 'queries' / f'{query_id}.jpg', media_type='image/jpeg')

    def query_metadata(row):
        faces = json.loads(row['faces'])
        with Image.open(settings.data_dir / 'queries' / f'{row["id"]}.jpg') as image:
            width, height = image.size
        return {'id': row['id'], 'width': width, 'height': height,
                'model_current': row['model_key'] == models.key,
                'faces': [{'index': i, 'bbox': face['bbox'], 'confidence': face['confidence']} for i, face in enumerate(faces)]}

    @app.get('/api/query/latest')
    def latest_query():
        row = store.one('SELECT * FROM queries ORDER BY created DESC LIMIT 1')
        return query_metadata(row) if row else None

    @app.get('/api/query/{query_id}')
    def saved_query(query_id: str):
        row = store.one('SELECT * FROM queries WHERE id=?', (query_id,))
        if not row:
            raise HTTPException(404, 'Không tìm thấy ảnh tham chiếu đã lưu.')
        return query_metadata(row)

    @app.post('/api/query/{query_id}/refresh')
    async def refresh_query(query_id: str):
        from starlette.concurrency import run_in_threadpool
        row = store.one('SELECT * FROM queries WHERE id=?', (query_id,))
        if not row:
            raise HTTPException(404, 'Không tìm thấy ảnh tham chiếu đã lưu.')
        with Image.open(settings.data_dir / 'queries' / f'{query_id}.jpg') as source:
            image = source.convert('RGB')
        faces = await run_in_threadpool(models.analyze, image)
        if not faces:
            raise HTTPException(422, 'Không tìm thấy khuôn mặt rõ trong ảnh đã lưu. Chọn ảnh khác.')
        store.execute('UPDATE queries SET faces=?,model_key=? WHERE id=?', (json.dumps(faces), models.key, query_id))
        return query_metadata(store.one('SELECT * FROM queries WHERE id=?', (query_id,)))

    @app.post('/api/search')
    def search(payload: SearchInput):
        album_or_404(payload.album_id)
        query = store.one('SELECT * FROM queries WHERE id=?', (payload.query_id,))
        if not query:
            raise HTTPException(404, 'Không tìm thấy ảnh tham chiếu.')
        if query['model_key'] != models.key:
            raise HTTPException(409, 'Model đã thay đổi. Tải lại ảnh tham chiếu và lập chỉ mục album.')
        faces = json.loads(query['faces'])
        if payload.face_index >= len(faces):
            raise HTTPException(422, 'Khuôn mặt được chọn không tồn tại.')
        default, calibrated = calibration()
        threshold = default if payload.threshold is None else payload.threshold
        counts = store.one('''SELECT count(*) total,
            coalesce(sum(status='queued'),0) processing,
            coalesce(sum(status='error'),0) failed,
            coalesce(sum(status='ready' AND model_key=?),0) AS "indexed",
            coalesce(sum(status='ready' AND (model_key IS NULL OR model_key!=?)),0) outdated
            FROM active_photos WHERE album_id=?''', (models.key, models.key, payload.album_id))
        if counts['outdated'] and not counts['indexed']:
            raise HTTPException(409, 'Album dùng phiên bản nhận diện cũ. Bấm Lập chỉ mục lại trong Thư viện ảnh.')
        rows = store.rank(payload.album_id, faces[payload.face_index]['embedding'], models.key, threshold, payload.top_k)
        return {'results': rows, 'threshold': threshold, 'threshold_calibrated': calibrated and threshold == default, 'model_key': models.key, 'album_status': counts}

    @app.get('/api/styles')
    def styles():
        return [{'id': key, 'name': name, 'description': description} for key, name, description in [('candy', 'Candy', 'Màu rực rỡ, nét cọ mềm'), ('mosaic', 'Mosaic', 'Họa tiết tranh ghép'), ('rain_princess', 'Rain Princess', 'Nét cọ dày, gam màu ấm'), ('udnie', 'Udnie', 'Hình khối và màu trừu tượng'), ('custom', 'Style của bạn', 'Tải ảnh style, tối ưu bằng VGG19')]]

    @app.get('/api/style-artworks/van-gogh/image')
    def van_gogh_preview():
        from .artworks import reference
        image=reference(settings);image.thumbnail((640,640))
        data=io.BytesIO();image.save(data,'JPEG',quality=88);data.seek(0)
        return StreamingResponse(data,media_type='image/jpeg')

    def style_job(job_id, photo_id, style_id, strength, steps, reference_path, recipe=None, plan_id=None, profile='fast'):
        try:
            started = time.perf_counter()
            store.update_job(job_id, 'running', .05, 'Đang nạp model')
            def progress(value, message):
                store.update_job(job_id, 'running', .2 + .75*value if recipe and recipe.engine == 'reference' else value, message)
            if recipe and recipe.engine == 'reference':
                store.update_job(job_id, 'running', .08, 'AI đang tạo ảnh phong cách từ mô tả; ảnh gốc vẫn ở trên máy')
                generated = chat.generate_style_reference(recipe,chat.plans.provider(plan_id))
                reference_path = settings.data_dir / 'styles' / f'{uid()}.png'
                generated.save(reference_path, 'PNG')
                store.update_job(job_id, 'running', .15, 'Đã có ảnh phong cách. VGG19 đang chuyển style trên máy')
            if recipe and recipe.engine=='artwork':
                from .artworks import reference
                reference_path=settings.data_dir/'styles'/f'{uid()}.png'
                reference(settings).save(reference_path,'PNG')
                store.update_job(job_id,'running',.1,'Đang chuyển nét cọ từ tranh Van Gogh bằng VGG19 trên máy')
            if style_id == 'custom':
                with Image.open(settings.data_dir / 'photos' / f'{photo_id}.jpg') as source:
                    image = source.convert('RGB')
                with Image.open(reference_path) as source:
                    output = models.custom(image, source.convert('RGB'), strength, steps, progress)
            else:
                output_id, cached = bulk.render(photo_or_404(photo_id), style_id, strength, profile, progress, recipe.title if recipe else None)
            if style_id == 'custom':
                cached = False
                details={'profile':'vgg512','steps':steps,'strength':strength}
                if recipe and recipe.engine=='artwork':
                    from .artworks import ARTWORK
                    details.update(engine='artwork',reference=ARTWORK)
                output_id = save_output(store,settings,output,photo_id,style_id,recipe.title if recipe else None,details)
            store.update_job(job_id, 'done', 1, 'Ảnh đã sẵn sàng', {'output_id': output_id, 'cached': cached, 'seconds': round(time.perf_counter()-started, 3), 'profile': profile if style_id!='custom' else 'vgg512', 'style_label': recipe.title if recipe else None, 'image_url': f'/api/outputs/{output_id}/image', 'download_url': f'/api/outputs/{output_id}/image?download=true'})
        except Exception as exc:
            if isinstance(exc, ChatUnavailable):
                log.warning('Style reference generation failed: %s', exc)
            else:
                log.exception('Stylization failed')
            if plan_id:
                chat.plans.failed(plan_id, photo_id, job_id)
            store.update_job(job_id, 'error', 1, str(exc)[:300])
        finally:
            if reference_path:
                reference_path.unlink(missing_ok=True)

    @app.post('/api/stylize/from-chat', status_code=202)
    def stylize_from_chat(payload: ChatStyleInput):
        photo_or_404(payload.photo_id)
        recipe = chat.get_style_plan(payload.plan_id)
        if recipe.engine in {'reference','artwork'}:
            if recipe.engine=='reference':chat.require_image_key(chat.plans.provider(payload.plan_id))
            else:
                from .artworks import reference
                reference(settings)
            if not models.status().get('custom_ready'):
                raise HTTPException(503, 'Cần tải trọng số VGG19 để dùng ảnh phong cách tham chiếu. Chạy scripts/fetch_assets.py --only vgg.')
        elif not models.status().get('presets_ready'):
            raise HTTPException(503, 'Chưa có trọng số preset. Chạy scripts/fetch_assets.py --only style.')
        variant = payload.profile if recipe.engine=='preset' else 'vgg512'
        job_id, created = chat.begin_style_plan(payload.plan_id, payload.photo_id,
            lambda kind: admission.admit(payload.photo_id,{'plan':payload.plan_id,'profile':variant})[0],variant)
        if created:
            style_id = 'custom' if recipe.engine in {'reference','artwork'} else recipe.preset
            executor.submit(style_job, job_id, payload.photo_id, style_id, recipe.strength, recipe.steps, None, recipe, payload.plan_id, payload.profile)
        return {'job_id': job_id}

    @app.post('/api/stylize', status_code=202)
    async def stylize(request: Request, photo_id: str = Form(...), style_id: str = Form(...), strength: float = Form(.8, ge=0, le=1), steps: int = Form(150, ge=20, le=300), style_image: UploadFile | None = File(None), profile: Literal['fast', 'balanced', 'quality'] = Form('fast')):
        photo_or_404(photo_id)
        if style_id not in {'candy', 'mosaic', 'rain_princess', 'udnie', 'custom'}:
            raise HTTPException(422, 'Phong cách không hợp lệ.')
        reference_path = None
        reference_hash = None
        if style_id == 'custom':
            if not style_image:
                raise HTTPException(422, 'Cần tải ảnh phong cách.')
            image = await read_upload(style_image)
            reference_hash = hashlib.sha256(image.tobytes()).hexdigest()
            reference_path = settings.data_dir / 'styles' / f'{uid()}.jpg'
            image.save(reference_path, 'JPEG')
        try:
            job_id,created = admission.admit(photo_id,{'style':style_id,'strength':strength,'steps':steps,'profile':profile,'reference':reference_hash},request.headers.get('Idempotency-Key'))
        except BaseException:
            if reference_path:
                reference_path.unlink(missing_ok=True)
            raise
        if created:
            executor.submit(style_job, job_id, photo_id, style_id, strength, steps, reference_path, profile=profile)
        elif reference_path:
            reference_path.unlink(missing_ok=True)
        return {'job_id': job_id}

    @app.post('/api/stylize/batch', status_code=202)
    def stylize_batch(payload: BatchStyleInput):
        album = album_or_404(payload.album_id)
        rows = store.all('SELECT id FROM active_photos WHERE album_id=? ORDER BY created,id', (payload.album_id,))
        ids = list(dict.fromkeys(payload.photo_ids)) if payload.photo_ids else [row['id'] for row in rows]
        allowed = {row['id'] for row in rows}
        if not ids or len(ids) > 10000:
            raise HTTPException(422, 'Chọn từ 1 đến 10.000 ảnh mỗi lô.')
        if any(photo not in allowed for photo in ids):
            raise HTTPException(422, 'Có ảnh không thuộc album đã chọn.')
        if not models.status().get('presets_ready'):
            raise HTTPException(503, 'Cần tải trọng số preset trước khi chạy lô.')
        try:
            job_id = bulk.create(ids, payload.style, payload.strength, payload.profile, album)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {'job_id': job_id, 'total': len(ids)}

    @app.get('/api/batches')
    def batches(album_id: str | None = None):
        if album_id:
            album_or_404(album_id)
        rows=store.all("SELECT j.id FROM jobs j LEFT JOIN batch_context c ON c.job_id=j.id WHERE j.kind='bulk-style' AND (? IS NULL OR c.album_id=? OR (c.album_id IS NULL AND EXISTS(SELECT 1 FROM style_items i JOIN photos p ON p.id=i.photo_id WHERE i.job_id=j.id AND p.album_id=?))) ORDER BY CASE WHEN j.status IN ('queued','running') THEN 0 ELSE 1 END,j.created DESC LIMIT 20",(album_id,album_id,album_id))
        return [store.job(row['id']) for row in rows]

    def batch_or_404(job_id):
        result = store.job(job_id)
        if not result or result['kind'] != 'bulk-style':
            raise HTTPException(404, 'Không tìm thấy lô xử lý.')
        return result

    @app.post('/api/batches/{job_id}/cancel')
    def cancel_batch(job_id: str):
        batch_or_404(job_id)
        bulk.cancel(job_id)
        return store.job(job_id)

    @app.post('/api/batches/{job_id}/resume', status_code=202)
    def resume_batch(job_id: str):
        batch = batch_or_404(job_id)
        if batch['status'] in {'queued', 'running'}:
            return {'job_id': job_id}
        if store.one("SELECT count(*) n FROM jobs WHERE kind='bulk-style' AND status IN ('queued','running')")['n'] >= 4:
            raise HTTPException(409, 'Đang có 4 lô xử lý. Chờ hoặc dừng bớt trước khi tiếp tục.')
        try:
            bulk.resume(job_id)
        except ValueError as exc:
            raise HTTPException(409,str(exc)) from exc
        return {'job_id': job_id}

    @app.post('/api/batches/{job_id}/finish')
    def finish_batch(job_id: str):
        batch_or_404(job_id)
        bulk.finish(job_id)
        return store.job(job_id)

    @app.get('/api/batches/{job_id}/download')
    def download_batch(job_id: str):
        batch_or_404(job_id)
        rows = store.all('SELECT photo_id,status,output_id,error FROM style_items WHERE job_id=? ORDER BY position', (job_id,))
        if not any(row['status']=='done' and row['output_id'] for row in rows):
            raise HTTPException(409, 'Chưa có ảnh hoàn tất để tải.')
        descriptor, name = tempfile.mkstemp(suffix='.zip', dir=settings.data_dir/'exports')
        import os
        os.close(descriptor)
        path = Path(name)
        try:
            # PNG already compressed. ZIP_STORED avoids compressing it again; RAM stays bounded.
            with file_lock, zipfile.ZipFile(path, 'w', zipfile.ZIP_STORED, allowZip64=True) as archive:
                exported = 0
                for index, row in enumerate(rows):
                    output = settings.data_dir/'outputs'/f'{row["output_id"]}.png'
                    in_library=bool(store.one('SELECT id FROM active_photos WHERE id=?',(row['photo_id'],)))
                    if in_library and row['status']=='done' and row['output_id'] and valid_output(store,settings.data_dir,row['output_id']):
                        ensure_space(settings,output.stat().st_size+65536)
                        archive.write(output, f'{index+1:05d}-{row["photo_id"][:8]}.png')
                        row['included'] = True
                        exported += 1
                    else:
                        row['included'] = False
                        if row['status']=='done':
                            row['error'] = 'Ảnh đang ở Thùng rác. Khôi phục ảnh để tải.' if not in_library else 'File kết quả thiếu hoặc hỏng. Tiếp tục/thử lại lô để khôi phục.'
                if not exported:
                    raise HTTPException(409,'Không còn file kết quả hợp lệ. Bấm tiếp tục/thử lại lô để tạo lại.')
                archive.writestr('report.json', json.dumps(rows, ensure_ascii=False, indent=2))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return FileResponse(path, media_type='application/zip', filename=f'LumaNest-batch-{job_id[:8]}.zip', background=BackgroundTask(path.unlink, missing_ok=True))

    @app.get('/api/jobs/{job_id}')
    def job(job_id: str):
        result = store.job(job_id)
        if not result:
            raise HTTPException(404, 'Không tìm thấy tác vụ.')
        return result

    @app.get('/api/jobs')
    def jobs():
        return [store.job(row['id']) for row in store.all("SELECT id FROM jobs ORDER BY CASE WHEN status IN ('queued','running') THEN 0 ELSE 1 END,created DESC LIMIT 30")]

    @app.get('/api/outputs')
    def outputs(album_id: str | None = None, limit: int = 50, offset: int = 0):
        if not 1<=limit<=100 or offset<0:
            raise HTTPException(422,'Phân trang không hợp lệ.')
        if album_id:
            album_or_404(album_id)
        return store.all('SELECT o.id,o.photo_id,o.style,o.created,d.title,p.name,p.album_id,a.profile,a.width,a.height,a.bytes FROM outputs o JOIN active_photos p ON p.id=o.photo_id LEFT JOIN output_details d ON d.output_id=o.id LEFT JOIN output_assets a ON a.output_id=o.id WHERE (? IS NULL OR p.album_id=?) ORDER BY o.created DESC,o.id LIMIT ? OFFSET ?', (album_id,album_id,limit,offset))

    @app.get('/api/outputs/{output_id}/image')
    def output_image(output_id: str, download: bool = False):
        if not store.one('SELECT o.id FROM outputs o JOIN active_photos p ON p.id=o.photo_id WHERE o.id=?', (output_id,)):
            raise HTTPException(404, 'Không tìm thấy ảnh kết quả.')
        if not valid_output(store,settings.data_dir,output_id):
            raise HTTPException(404,'File kết quả thiếu hoặc hỏng. Tạo lại tác phẩm hoặc thử lại lô ảnh.')
        return FileResponse(settings.data_dir / 'outputs' / f'{output_id}.png', media_type='image/png', filename=f'LumaNest-{output_id[:8]}.png' if download else None)

    @app.post('/api/export')
    def export(payload: ExportInput):
        descriptor, name = tempfile.mkstemp(suffix='.zip',dir=settings.data_dir/'exports')
        import os
        os.close(descriptor)
        target = Path(name)
        total,manifest = 0,[]
        try:
            with file_lock, zipfile.ZipFile(target,'w',zipfile.ZIP_STORED,allowZip64=True) as archive:
                for photo_id in dict.fromkeys(payload.photo_ids):
                    photo = photo_or_404(photo_id)
                    path,extension,mime,exact = source_file(photo_id)
                    total += path.stat().st_size
                    ensure_space(settings,path.stat().st_size+65536)
                    if total > 2*1024*1024*1024:
                        raise HTTPException(413,'Gói tải vượt 2 GB. Chọn ít ảnh hơn.')
                    archive_name = f'{photo_id}.{extension}'
                    archive.write(path,archive_name)
                    manifest.append({'id':photo_id,'name':photo['name'],'file':archive_name,'byte_original':exact})
                archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return FileResponse(target,media_type='application/zip',filename='LumaNest.zip',background=BackgroundTask(target.unlink,missing_ok=True))

    def expire_exports():
        for token,item in list(export_tickets.items()):
            if item['expires']<time.time():
                try:
                    item['path'].unlink(missing_ok=True)
                    del export_tickets[token]
                except PermissionError:
                    pass  # A download can still have the file open on Windows.

    def invalidate_exports(photo_ids):
        identities=set(photo_ids);failures=0
        with file_lock:
            for token,item in list(export_tickets.items()):
                if identities.intersection(item.get('photo_ids',identities)):
                    item['expires']=0
                    try:
                        item['path'].unlink(missing_ok=True)
                        del export_tickets[token]
                    except OSError:
                        failures+=1
        return failures

    @app.post('/api/exports',status_code=201)
    def prepare_export(payload: ExportInput):
        with file_lock:
            expire_exports()
            if len(export_tickets)>=4:
                raise HTTPException(429,'Đã chuẩn bị 4 gói tải. Dùng các gói hiện có hoặc đợi chúng hết hạn.')
            response = export(payload)
            token = uid()
            path = settings.data_dir/'exports'/f'download-{token}.zip'
            Path(response.path).replace(path)
            export_tickets[token]={'path':path,'expires':time.time()+3600,'photo_ids':set(payload.photo_ids)}
            return {'download_url':f'/api/exports/{token}','bytes':path.stat().st_size,'expires_in_seconds':3600}

    @app.get('/api/exports/{token}')
    def prepared_export(token: str):
        with file_lock:
            expire_exports()
            item=export_tickets.get(token)
            if not item or item['expires']<time.time() or not item['path'].is_file():
                raise HTTPException(404,'Gói tải đã hết hạn hoặc ứng dụng đã khởi động lại. Chuẩn bị lại gói tải từ thư viện.')
            return FileResponse(item['path'],media_type='application/zip',filename='LumaNest.zip')

    static = Path(__file__).parent / 'static'
    app.mount('/static', StaticFiles(directory=static), name='static')

    @app.get('/', include_in_schema=False)
    def home():
        return FileResponse(static / 'index.html')

    return app


app = create_app()
