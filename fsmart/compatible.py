"""OpenAI-compatible chat/image APIs (VietAPI, OpenRouter, DeepSeek, Claude's compatibility endpoint, OpenAI itself…).

The user supplies a base URL, a key and any model name. Keys stay in RAM and in the Authorization header only;
provider error bodies are never reflected because they can echo the request or the key.
"""
import base64, binascii, ipaddress, json, logging, re, time
from urllib.parse import urlsplit

import requests

MODEL_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$'
QUOTA_WORDS = ('quota', 'insufficient', 'balance', 'credit', 'billing', 'limit: 0', 'số dư', '余额', '额度')
IMAGE_MODEL_PATTERN = re.compile(r'image|dall-?e|imagen|flux|banana|stable-?diffusion|sdxl|midjourney|seedream|recraft|ideogram', re.I)
VISION_FALLBACKS = ('claude-sonnet-5.5', 'claude-sonnet-5', 'gpt-6-sol', 'gpt-5.6-luna', 'gemini-4-argon', 'gpt-4o', 'claude-sonnet-4')
DESCRIBE_PROMPT = ('Describe this photo for a painter who must repaint the same scene without seeing it. In English, 120-180 words: '
                   'how many people and where they stand, poses, gestures, facial expressions, hair, clothing and colours, objects, '
                   'background, lighting, camera angle and composition. Do not name or guess who anyone is. Plain prose only.')
RATE_RETRIES = (5.0, 12.0)  # short rate-limit waits honoured automatically; longer ones are reported
MAX_RATE_WAIT = 20.0
TRANSIENT = {500, 502, 503, 504}
RETRY_DELAYS = (1.5, 4.0)
log = logging.getLogger(__name__)


def normalize_base_url(value):
    """https://host[/path] with no credentials, query or fragment; http only for this computer (Ollama, LM Studio)."""
    text = (value or '').strip().rstrip('/')
    for suffix in ('/chat/completions', '/completions', '/models'):
        if text.lower().endswith(suffix):
            text = text[:-len(suffix)].rstrip('/')
    parts = urlsplit(text)
    host = (parts.hostname or '').lower()
    if not host or parts.username or parts.password or parts.query or parts.fragment or len(text) > 300:
        raise ValueError('Base URL không hợp lệ.')
    local = host == 'localhost'
    try:
        local = local or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if parts.scheme != 'https' and not (parts.scheme == 'http' and local):
        raise ValueError('Base URL phải dùng https:// (http:// chỉ cho máy này).')
    return text


def _unavailable(message, status=502):
    from .chat import ChatUnavailable
    return ChatUnavailable(message, status)


def provider_detail(response, key=''):
    """The provider's own error message (OpenAI or plain JSON), masked and shortened for the user."""
    try:
        body = response.json()
        error = body.get('error', body) if isinstance(body, dict) else body
        if isinstance(error, dict):
            detail = error.get('message') or error.get('detail') or error.get('code') or ''
        else:
            detail = error
    except (ValueError, AttributeError, TypeError):
        detail = response.text[:200] if isinstance(getattr(response, 'text', None), str) else ''
    detail = ' '.join(str(detail).split())[:220]
    return detail.replace(key, '[key]') if key else detail


def retry_after(response):
    try:
        return float(response.headers.get('Retry-After', ''))
    except (TypeError, ValueError):
        return None


def _send(method, url, key, *, label, timeout, **kwargs):
    headers = {'Authorization': f'Bearer {key}'}
    if 'files' not in kwargs:  # multipart requests set their own boundary header
        headers['Content-Type'] = 'application/json'
    rate_waits = 0
    for attempt in range(len(RETRY_DELAYS) + len(RATE_RETRIES) + 1):
        try:
            response = method(url, headers=headers, timeout=timeout, allow_redirects=False, **kwargs)
        except requests.Timeout:
            log.warning('%s timed out after %ss', label, timeout[1])
            raise _unavailable(f'{label} không phản hồi trong {timeout[1]} giây. Model có thể đang quá tải; thử lại hoặc chọn model khác.', 504) from None
        except requests.RequestException as error:
            log.warning('%s connection failed: %s', label, type(error).__name__)
            raise _unavailable(f'Không kết nối được {label}. Kiểm tra Internet và Base URL rồi thử lại.', 503) from None
        if response.status_code == 429:
            detail = provider_detail(response, key)
            wait = retry_after(response)
            quota = any(word in detail.lower() for word in QUOTA_WORDS)
            if quota or rate_waits == len(RATE_RETRIES) or (wait is not None and wait > MAX_RATE_WAIT):
                break
            wait = RATE_RETRIES[rate_waits] if wait is None else max(wait, .5)
            log.warning('%s rate limited (429: %s); waiting %.1fs', label, detail, wait)
            rate_waits += 1
            time.sleep(wait)
            continue
        transient_tries = attempt - rate_waits
        if response.status_code not in TRANSIENT or transient_tries >= len(RETRY_DELAYS):
            break
        log.warning('%s returned HTTP %s; retrying (%s/%s)', label, response.status_code, transient_tries + 1, len(RETRY_DELAYS))
        time.sleep(RETRY_DELAYS[transient_tries])
    code = response.status_code
    detail = provider_detail(response, key) if code != 200 else ''
    if code != 200:
        log.warning('%s %s returned HTTP %s: %s', label, url.rsplit('/', 1)[-1], code, detail)
    said = f' Lý do từ {label}: “{detail}”.' if detail else ''
    if code in {401, 403}:
        raise _unavailable(f'{label} từ chối API key hoặc quyền dùng model (mã {code}).{said}')
    if code == 402:
        raise _unavailable(f'{label} báo hết số dư hoặc credit (mã 402).{said} Nạp thêm rồi thử lại.')
    if code == 429:
        if any(word in detail.lower() for word in QUOTA_WORDS):
            raise _unavailable(f'{label} báo hết hạn mức hoặc số dư cho model này (mã 429).{said} Nạp thêm credit hoặc chọn model khác.', 429)
        raise _unavailable(f'{label} vẫn giới hạn lượt gọi sau khi app đã tự chờ và thử lại (mã 429).{said} Đợi khoảng 1 phút hoặc chọn model khác.', 429)
    if code in {400, 404, 422}:
        raise _unavailable(f'{label} không nhận model hoặc yêu cầu này (mã {code}).{said} Kiểm tra tên model (model ảnh phải là loại tạo ảnh, ví dụ gpt-image-2) và Base URL.')
    if 300 <= code < 400:
        raise _unavailable(f'{label} chuyển hướng sang địa chỉ khác (mã {code}). Dùng đúng Base URL của API, thường kết thúc bằng /v1.')
    if code != 200:
        raise _unavailable(f'{label} chưa trả lời được (mã {code}), đã tự thử lại.{said} Thử lại sau hoặc chọn nguồn khác.')
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError('Invalid response')
        return data
    except (TypeError, ValueError):
        raise _unavailable(f'{label} trả dữ liệu không đúng chuẩn OpenAI. Kiểm tra Base URL (thường kết thúc bằng /v1).') from None


def list_models(get, base_url, key, label='API'):
    data = _send(get, base_url + '/models', key, label=label, timeout=(5, 20))
    items = data.get('data')
    if not isinstance(items, list):
        raise _unavailable(f'{label} không trả danh sách model theo chuẩn OpenAI. Nhập tên model bằng tay.')
    ids = [item.get('id') for item in items if isinstance(item, dict)]
    return sorted({model for model in ids if isinstance(model, str) and re.fullmatch(MODEL_PATTERN, model)})[:800]


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # some gateways return content parts
        return '\n'.join(part.get('text', '') for part in content if isinstance(part, dict) and part.get('type') in (None, 'text', 'output_text'))
    return ''


def chat(post, base_url, key, model, system, message, history, *, label='API', max_tokens=1400, temperature=.6):
    from .chat import redact
    messages = [{'role': 'system', 'content': system}]
    messages += [{'role': turn.role, 'content': redact(turn.content).replace(key, '[API key đã ẩn]')} for turn in history]
    messages.append({'role': 'user', 'content': redact(message).replace(key, '[API key đã ẩn]')})
    body = {'model': model, 'messages': messages, 'max_tokens': max_tokens, 'temperature': temperature, 'stream': False}
    data = _send(post, base_url + '/chat/completions', key, label=label, timeout=(5, 90), json=body)
    try:
        choice = data['choices'][0]
        text = _content_text(choice['message'].get('content'))
        # Reasoning models sometimes wrap their thinking in <think>…</think>; never show it.
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()
        if not text:
            raise ValueError('Empty response')
        return redact(text).replace(key, '[API key đã ẩn]')[:7000]
    except (KeyError, IndexError, TypeError, AttributeError, ValueError):
        raise _unavailable(f'{label} chưa trả về câu trả lời. Thử câu ngắn hơn hoặc model khác.') from None


def json_object(text):
    """The first JSON object in a reply that may wrap it in prose or ``` fences."""
    text = text.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
    start = text.find('{')
    if start < 0:
        raise ValueError('No JSON object')
    return json.JSONDecoder().raw_decode(text[start:])[0]


def is_image_model(name):
    return bool(IMAGE_MODEL_PATTERN.search(name or ''))


def size_for(image):
    """The gpt-image canvas closest to the photo's shape."""
    ratio = image.width / max(1, image.height)
    return '1536x1024' if ratio > 1.15 else '1024x1536' if ratio < .87 else '1024x1024'


def describe_image(post, base_url, key, model, image, label='API'):
    """A vision chat model's description of the photo (sent as a data URL, max 1024 px)."""
    import io
    preview = image.copy(); preview.thumbnail((1024, 1024))
    buffer = io.BytesIO(); preview.save(buffer, 'JPEG', quality=88)
    url = 'data:image/jpeg;base64,' + base64.b64encode(buffer.getvalue()).decode()
    body = {'model': model, 'max_tokens': 500, 'temperature': .2, 'stream': False,
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': DESCRIBE_PROMPT},
                                                      {'type': 'image_url', 'image_url': {'url': url}}]}]}
    data = _send(post, base_url + '/chat/completions', key, label=label, timeout=(5, 120), json=body)
    try:
        text = re.sub(r'<think>.*?</think>', '', _content_text(data['choices'][0]['message'].get('content')), flags=re.S).strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        text = ''
    if len(text) < 40 or re.search(r"(can't|cannot|unable to) (see|view|access)|no image", text, re.I):
        raise _unavailable(f'Model {model} của {label} không đọc được ảnh (có thể không hỗ trợ ảnh đầu vào).')
    return ' '.join(text.split())[:1500]


def generate_image(post, get, base_url, key, model, prompt, label='API', size='1024x1024'):
    from .images import decode_image
    body = {'model': model, 'prompt': prompt, 'n': 1, 'size': size}
    data = _send(post, base_url + '/images/generations', key, label=label, timeout=(5, 180), json=body)
    try:
        return decode_image(_image_bytes(get, data), 4_194_304)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, binascii.Error, requests.RequestException):
        raise _unavailable(f'{label} chưa trả về ảnh phong cách hợp lệ. Kiểm tra model ảnh rồi thử lại.') from None


def _image_bytes(get, data, limit=24 * 1024 * 1024):
    """The first image of an OpenAI-style images response, as b64_json or an https URL."""
    item = data['data'][0]
    if isinstance(item.get('b64_json'), str):
        if len(item['b64_json']) > limit * 4 // 3:
            raise ValueError('Oversized image')
        return base64.b64decode(item['b64_json'], validate=True)
    url = item['url']
    if not isinstance(url, str) or urlsplit(url).scheme != 'https':
        raise ValueError('Unexpected image URL')
    response = get(url, timeout=(5, 60), allow_redirects=False, stream=True)
    if response.status_code != 200:
        raise ValueError('Image download failed')
    raw = response.raw.read(limit + 1, decode_content=True)
    if len(raw) > limit:
        raise ValueError('Oversized image')
    return raw


def edit_image(post, get, base_url, key, model, image, prompt, label='API'):
    """POST /images/edits (gpt-image style) with one photo; returns the repainted PIL image."""
    import io
    from .images import decode_image
    buffer = io.BytesIO(); image.save(buffer, 'PNG')
    ratio = image.width / max(1, image.height)
    size = '1536x1024' if ratio > 1.15 else '1024x1536' if ratio < .87 else '1024x1024'
    data = _send(post, base_url + '/images/edits', key, label=label, timeout=(5, 240),
                 files={'image': ('photo.png', buffer.getvalue(), 'image/png')},
                 data={'model': model, 'prompt': prompt, 'n': '1', 'size': size})
    try:
        return decode_image(_image_bytes(get, data), 16_777_216)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, binascii.Error, requests.RequestException):
        raise _unavailable(f'{label} chưa trả về ảnh đã vẽ lại. Kiểm tra model ảnh có hỗ trợ sửa ảnh (images/edits) không.') from None
