"""Scoped documentation CSP: allow the documented CDN and exact inline boot code."""
import base64
import hashlib
import re

from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html


def documentation(kind, title):
    if kind=='swagger':
        response=get_swagger_ui_html(openapi_url='/openapi.json',title=title,
                                     oauth2_redirect_url='/docs/oauth2-redirect')
    elif kind=='redoc':
        response=get_redoc_html(openapi_url='/openapi.json',title=title,with_google_fonts=False)
    else:
        response=get_swagger_ui_oauth2_redirect_html()
    hashes=[]
    for inline in re.findall(rb'<script>(.*?)</script>',response.body,re.S):
        digest=base64.b64encode(hashlib.sha256(inline).digest()).decode('ascii')
        hashes.append(f"'sha256-{digest}'")
    response.headers['Content-Security-Policy']=(
        "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net "+' '.join(hashes)+
        "; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; connect-src 'self'; "
        "base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
    return response
