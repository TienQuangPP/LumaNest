"""Bound request sizes before multipart/JSON parsing, including streamed bodies."""
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


class RequestSizeGuard:
    def __init__(self, app, upload_limit=128*1024*1024, json_limit=1024*1024):
        self.app, self.upload_limit, self.json_limit = app, upload_limit, json_limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in {'POST','PUT','PATCH'}:
            return await self.app(scope,receive,send)
        headers = dict(scope['headers'])
        limit = self.upload_limit if b'multipart/form-data' in headers.get(b'content-type',b'') else self.json_limit
        try:
            length = int(headers.get(b'content-length', b'0'))
            if length < 0:
                raise ValueError()
        except ValueError:
            return await JSONResponse({'detail':'Kích thước yêu cầu không hợp lệ.'},status_code=400)(scope,receive,send)
        if length > limit:
            return await JSONResponse({'detail':'Yêu cầu quá lớn. Chia ảnh thành nhóm nhỏ hơn.'},status_code=413)(scope,receive,send)
        consumed = 0

        async def bounded_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get('body',b''))
            if consumed > limit:
                raise HTTPException(413,'Yêu cầu quá lớn. Chia ảnh thành nhóm nhỏ hơn.')
            return message

        return await self.app(scope,bounded_receive,send)
