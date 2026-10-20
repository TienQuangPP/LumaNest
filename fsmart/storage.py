import shutil
from fastapi import HTTPException

RESERVE = 128*1024*1024


def ensure_space(settings, estimated_bytes):
    free=shutil.disk_usage(settings.data_dir).free
    needed=max(0,int(estimated_bytes))+RESERVE
    if free<needed:
        raise HTTPException(507,f'Không đủ dung lượng trống: còn {free/1024**2:.0f} MB, cần khoảng {needed/1024**2:.0f} MB gồm phần dự phòng. Chọn ít ảnh hơn, mức 512 px hoặc giải phóng ổ đĩa rồi thử lại.')
