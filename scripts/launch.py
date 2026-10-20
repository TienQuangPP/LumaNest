"""Run the local app and open the default browser once HTTP is ready."""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
import webbrowser
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def ready(url):
    try:
        with urllib.request.urlopen(f'{url}/api/health', timeout=1) as response:
            health = json.load(response)
        return health.get('status') == 'ok' and bool(health.get('face_model'))
    except (OSError, ValueError):
        return False


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--background', action='store_true',help='Run a detached local server and write logs to runtime/logs')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    url = f'http://127.0.0.1:{args.port}'
    print(f'LumaNest · {url}', flush=True)

    def open_page():
        if not args.no_browser:
            print('Đang mở trình duyệt mặc định...', flush=True)
            if not webbrowser.open(url, new=2):
                print(f'Mở trình duyệt và truy cập {url}', flush=True)

    if ready(url):
        print('Ứng dụng đang chạy.', flush=True)
        open_page()
        return

    if args.background:
        directory=ROOT/'runtime/logs'
        directory.mkdir(parents=True,exist_ok=True)
        options={'cwd':str(ROOT),'stdin':subprocess.DEVNULL,'close_fds':True}
        if sys.platform=='win32':
            options['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
            startup=subprocess.STARTUPINFO()
            startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow=0
            options['startupinfo']=startup
        else:
            options['start_new_session']=True
        with (directory/'server.log').open('a',encoding='utf-8') as stdout,(directory/'server-error.log').open('a',encoding='utf-8') as stderr:
            process=subprocess.Popen([sys.executable,'-u','-m','uvicorn','fsmart.app:app','--host','127.0.0.1','--port',str(args.port)],stdout=stdout,stderr=stderr,**options)
        for _ in range(120):
            if ready(url):
                print('Server chạy nền. Đóng terminal không tắt ứng dụng. Log: runtime/logs',flush=True)
                open_page()
                return
            if process.poll() is not None:
                raise SystemExit('Không khởi động được. Kiểm tra cổng và runtime/logs/server-error.log.')
            time.sleep(.5)
        raise SystemExit('Server chưa sẵn sàng sau 60 giây. Kiểm tra log trước khi chạy thêm tiến trình.')

    print('Đang khởi động. Giữ cửa sổ này mở khi sử dụng.', flush=True)
    stop = threading.Event()

    def wait_for_server():
        for _ in range(120):
            if stop.is_set():
                return
            if ready(url):
                open_page()
                return
            stop.wait(.5)

    threading.Thread(target=wait_for_server, daemon=True).start()
    try:
        import uvicorn
        uvicorn.run('fsmart.app:app', host='127.0.0.1', port=args.port, log_level='info')
    finally:
        stop.set()


if __name__ == '__main__':
    main()
