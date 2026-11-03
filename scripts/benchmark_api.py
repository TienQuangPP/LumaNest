"""End-to-end speed of every LumaNest feature against a fresh server (cold model loads included).

Needs requirements-dev.txt (httpx) and the model weights (FSM_WEIGHTS_DIR, default ./weights). Starts its own
server on port 8767 with an empty data folder under .cache/, so the user's library is never touched, and writes
artifacts/performance/api-bench-<date>.json. Windows only (memory is read through PowerShell).
"""
import io, json, os, shutil, statistics, subprocess, sys, time, uuid
from pathlib import Path

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
PORT = 8767
BASE = f'http://127.0.0.1:{PORT}'
DATA = ROOT / '.cache' / 'bench-runtime'
OUT = ROOT / 'artifacts' / 'performance' / f'api-bench-{time.strftime("%Y-%m-%d")}.json'
WEIGHTS = os.environ.get('FSM_WEIGHTS_DIR', str(ROOT / 'weights'))
report = {'stages': {}, 'memory_mb': {}, 'errors': {}}


def photo(seed, w=4000, h=3000):
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    base = np.stack([(x / w) * 200 + 30 * np.sin(y / 90 + seed), (y / h) * 180 + 40 * np.cos(x / 120),
                     120 + 80 * np.sin((x + y) / 300 + seed)], -1)
    im = Image.fromarray(np.clip(base + rng.normal(0, 12, base.shape), 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(im)
    for _ in range(12):
        cx, cy, r = rng.integers(0, w), rng.integers(0, h), rng.integers(80, 500)
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(int(v) for v in rng.integers(0, 255, 3)))
    buf = io.BytesIO()
    im.filter(ImageFilter.GaussianBlur(1.2)).save(buf, 'JPEG', quality=90)
    return buf.getvalue()


def memory(pid):
    """Working set of the server process plus its children (the local chat worker runs as a child)."""
    ps = ("$ids=@(%d)+@(Get-CimInstance Win32_Process -Filter 'ParentProcessId=%d' | ForEach-Object ProcessId);"
          "$t=0;foreach($i in $ids){$p=Get-Process -Id $i -ErrorAction SilentlyContinue;if($p){$t+=$p.WorkingSet64}};$t") % (pid, pid)
    out = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True).stdout.strip()
    return round(int(out or 0) / 2**20)


def timed(fn, *a, **k):
    start = time.perf_counter()
    value = fn(*a, **k)
    return time.perf_counter() - start, value


def stage(name):
    def wrap(fn):
        try:
            result = fn()
            report['stages'][name] = result
            print(name, json.dumps(result, ensure_ascii=False), flush=True)
        except Exception as exc:  # keep measuring the other features
            report['errors'][name] = f'{type(exc).__name__}: {exc}'
            print(name, 'ERROR', exc, flush=True)
        return fn
    return wrap


def wait_job(client, job_id, limit=900):
    start = time.perf_counter()
    while time.perf_counter() - start < limit:
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in ('done', 'error', 'cancelled'):
            return time.perf_counter() - start, job
        time.sleep(0.25)
    raise TimeoutError(job_id)


def ok(response):
    if response.status_code >= 400:
        raise RuntimeError(f'{response.status_code} {response.text[:200]}')
    return response


shutil.rmtree(DATA, ignore_errors=True)
env = {**os.environ, 'FSM_DATA_DIR': str(DATA), 'FSM_WEIGHTS_DIR': WEIGHTS}
started = time.perf_counter()
(ROOT / '.cache').mkdir(exist_ok=True)
server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'fsmart.app:app', '--port', str(PORT)], env=env, cwd=ROOT,
                          stdout=open(ROOT / '.cache' / 'bench-server.log', 'w'), stderr=subprocess.STDOUT)
client = httpx.Client(base_url=BASE, timeout=900)
try:
    while True:
        try:
            if client.get('/').status_code == 200:
                break
        except httpx.TransportError:
            time.sleep(0.2)
    report['stages']['server_start_seconds'] = round(time.perf_counter() - started, 2)
    report['memory_mb']['after_start'] = memory(server.pid)
    print('server up', report['stages']['server_start_seconds'], flush=True)

    images = [photo(seed) for seed in range(10)]
    album = ok(client.post('/api/albums', json={'name': 'Benchmark'})).json()['id']
    ctx = {}

    @stage('upload_and_face_index')
    def _():
        files = [('files', (f'bench{i}.jpg', data, 'image/jpeg')) for i, data in enumerate(images)]
        upload_s, response = timed(client.post, f'/api/albums/{album}/photos', files=files)
        result = ok(response).json()
        index_s, job = wait_job(client, result['job_id'])
        ctx['photos'] = [p['id'] for p in client.get(f'/api/albums/{album}/photos?limit=100').json()]
        return {'photos': len(images), 'megapixels_each': 12, 'mb_total': round(sum(map(len, images)) / 2**20, 1),
                'upload_seconds': round(upload_s, 2), 'face_index_seconds': round(index_s, 2),
                'face_index_seconds_per_photo': round(index_s / len(images), 2), 'job': job['message']}
    report['memory_mb']['after_face_index'] = memory(server.pid)

    @stage('library_api')
    def _():
        lists = [timed(client.get, f'/api/library?album_id={album}&limit=100')[0] for _ in range(20)]
        thumbs = [timed(client.get, f'/api/photos/{pid}/image?thumbnail=true') for pid in ctx['photos']]
        full = client.get(f'/api/photos/{ctx["photos"][0]}/image')
        return {'library_list_ms_median': round(statistics.median(lists) * 1000, 1),
                'thumbnail_ms_median': round(statistics.median(t for t, _ in thumbs) * 1000, 1),
                'thumbnail_kb': round(len(thumbs[0][1].content) / 1024), 'display_image_kb': round(len(full.content) / 1024)}

    @stage('semantic_index_and_search')
    def _():
        index_s, job = wait_job(client, ok(client.post('/api/discovery/index', json={'album_id': album})).json()['job_id'])
        cold, _ = timed(client.post, '/api/discovery/search', json={'album_id': album, 'text': 'hoàng hôn trên biển'})
        warm = [timed(client.post, '/api/discovery/search', json={'album_id': album, 'text': f'ảnh số {i}'})[0] for i in range(10)]
        similar = [timed(client.post, '/api/discovery/search', json={'album_id': album, 'photo_id': ctx['photos'][0]})[0] for _ in range(5)]
        return {'index_seconds_10_photos_incl_model_load': round(index_s, 2), 'text_search_first_seconds': round(cold, 2),
                'text_search_ms_median': round(statistics.median(warm) * 1000, 1),
                'similar_search_ms_median': round(statistics.median(similar) * 1000, 1), 'job': job['message']}
    report['memory_mb']['after_semantic'] = memory(server.pid)

    @stage('style_preview')
    def _():
        pid = ctx['photos'][1]
        cold, _ = timed(lambda: ok(client.get(f'/api/photos/{pid}/style-preview?style=mosaic&strength=0.8')))
        warm = {s: round(timed(lambda: ok(client.get(f'/api/photos/{pid}/style-preview?style={s}&strength=0.7')))[0], 2)
                for s in ['candy', 'mosaic', 'rain_princess', 'udnie']}
        return {'first_seconds_incl_model_load': round(cold, 2), 'warm_seconds_by_style': warm}

    @stage('stylize_12mp')
    def _():
        out = {}
        for i, profile in enumerate(['fast', 'balanced', 'quality']):
            form = {'photo_id': ctx['photos'][2], 'style_id': 'udnie', 'strength': str(0.61 + i / 100), 'steps': '150', 'profile': profile}
            wall, job = wait_job(client, ok(client.post('/api/stylize', data=form, headers={'Idempotency-Key': uuid.uuid4().hex})).json()['job_id'])
            res = job.get('result') or {}
            out[profile] = {'wall_seconds': round(wall, 2), 'server_seconds': res.get('seconds'), 'cached': res.get('cached')}
        return out
    report['memory_mb']['after_style'] = memory(server.pid)

    @stage('batch_style_10_photos_fast')
    def _():
        payload = {'album_id': album, 'photo_ids': ctx['photos'], 'style': 'candy', 'strength': 0.66, 'profile': 'fast'}
        wall, job = wait_job(client, ok(client.post('/api/stylize/batch', json=payload)).json()['job_id'])
        return {'seconds': round(wall, 2), 'photos_per_second': round(len(ctx['photos']) / wall, 2), 'job': job['message']}

    @stage('colour_look')
    def _():
        pid = ctx['photos'][3]
        previews = [timed(lambda look=look: ok(client.get(f'/api/photos/{pid}/look-preview?look={look}&strength=0.8')))[0]
                    for look in ['cinema', 'portra', 'noir', 'cool', 'sunset']]
        save, _ = timed(lambda: ok(client.post('/api/looks', json={'photo_id': pid, 'look': 'noir', 'strength': 0.8})))
        return {'preview_first_seconds': round(previews[0], 2), 'preview_ms_median': round(statistics.median(previews[1:]) * 1000),
                'save_2048px_seconds': round(save, 2)}

    @stage('subject_sam2')
    def _():
        pid = ctx['photos'][4]
        cold, first = timed(lambda: ok(client.post('/api/subjects/segment', json={'photo_id': pid, 'points': [{'x': .5, 'y': .5, 'label': 1}]})))
        warm, second = timed(lambda: ok(client.post('/api/subjects/segment', json={'photo_id': pid, 'points': [{'x': .3, 'y': .4, 'label': 1}]})))
        mask = second.json()['masks'][0]['id']
        render, _ = timed(lambda: ok(client.post('/api/subjects/render', json={'mask_id': mask, 'effect': 'blur'})))
        return {'segment_first_seconds': round(cold, 2), 'segment_warm_seconds': round(warm, 2),
                'masks': len(second.json()['masks']), 'render_blur_seconds': round(render, 2)}
    report['memory_mb']['after_sam'] = memory(server.pid)

    @stage('face_query_no_face_12mp')
    def _():
        t, r = timed(client.post, '/api/query', files=[('file', ('q.jpg', images[5], 'image/jpeg'))])
        return {'seconds': round(t, 2), 'status': r.status_code}

    @stage('assistant_qwen')
    def _():
        status = client.get('/api/chat/status').json()
        questions = ['Làm sao để tìm ảnh theo khuôn mặt?', 'Nên chọn phong cách nào cho ảnh phong cảnh?', 'Ảnh của tôi có bị gửi ra ngoài không?']
        runs = []
        for q in questions:
            t, r = timed(lambda q=q: ok(client.post('/api/chat', json={'message': q, 'history': [], 'page': 'library', 'mode': 'support'})))
            reply = r.json().get('reply') or r.json().get('message') or ''
            runs.append({'seconds': round(t, 2), 'chars': len(reply)})
        return {'provider': status.get('selected') or status.get('provider'), 'runs': runs,
                'chars_per_second_warm': round(sum(r['chars'] for r in runs[1:]) / sum(r['seconds'] for r in runs[1:]), 1)}
    report['memory_mb']['after_chat'] = memory(server.pid)

    @stage('export_zip')
    def _():
        t, r = timed(lambda: ok(client.post('/api/exports', json={'photo_ids': ctx['photos']})))
        dl, z = timed(client.get, r.json()['download_url'])
        return {'prepare_seconds': round(t, 2), 'download_seconds': round(dl, 2), 'zip_mb': round(len(z.content) / 2**20, 1)}

    @stage('system_verify')
    def _():
        t, r = timed(lambda: ok(client.post('/api/system/verify')))
        return {'seconds': round(t, 2), 'summary': r.json().get('summary')}
finally:
    client.close()
    server.terminate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print('wrote', OUT, flush=True)
