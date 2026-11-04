"""OpenAI-compatible chat/image APIs (VietAPI, OpenRouter, DeepSeek, Claude's compatibility endpoint, OpenAI itself…).

The user supplies a base URL, a key and any model name. Keys stay in RAM and in the Authorization header only;
provider error bodies are never reflected because they can echo the request or the key.
"""
import base64, binascii, ipaddress, json, logging, re, time
from urllib.parse import urlsplit

import requests

MODEL_PATTERN = r'^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,127}$'
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


def _send(method, url, key, *, label, timeout, **kwargs):
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            response = method(url, headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'},
                              timeout=timeout, allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise _unavailable(f'Không kết nối được {label}. Kiểm tra Internet và Base URL rồi thử lại.', 503) from None
        if response.status_code not in TRANSIENT or attempt == len(RETRY_DELAYS):
            break
        log.warning('%s returned HTTP %s; retrying (%s/%s)', label, response.status_code, attempt + 1, len(RETRY_DELAYS))
        time.sleep(RETRY_DELAYS[attempt])
    code = response.status_code
    if code != 200:
        log.warning('%s returned HTTP %s', label, code)
    if code in {401, 403}:
        raise _unavailable(f'{label} từ chối API key (mã {code}). Kiểm tra key và số dư tài khoản.')
    if code == 402:
        raise _unavailable(f'{label} báo hết số dư hoặc credit (mã 402). Nạp thêm rồi thử lại.')
    if code == 429:
        raise _unavailable(f'{label} báo giới hạn lượt gọi (mã 429). Thử lại sau một lát.', 429)
    if code in {400, 404, 422}:
        raise _unavailable(f'{label} không nhận model hoặc yêu cầu này (mã {code}). Kiểm tra tên model và Base URL.')
    if 300 <= code < 400:
        raise _unavailable(f'{label} chuyển hướng sang địa chỉ khác (mã {code}). Dùng đúng Base URL của API, thường kết thúc bằng /v1.')
    if code != 200:
        raise _unavailable(f'{label} chưa trả lời được (mã {code}), đã tự thử lại. Thử lại sau hoặc chọn nguồn khác.')
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


def generate_image(post, get, base_url, key, model, prompt, label='API'):
    from .images import decode_image
    body = {'model': model, 'prompt': prompt, 'n': 1, 'size': '1024x1024'}
    data = _send(post, base_url + '/images/generations', key, label=label, timeout=(5, 180), json=body)
    try:
        item = data['data'][0]
        if isinstance(item.get('b64_json'), str):
            if len(item['b64_json']) > 16 * 1024 * 1024:
                raise ValueError('Oversized image')
            raw = base64.b64decode(item['b64_json'], validate=True)
        else:
            url = item['url']
            if not isinstance(url, str) or urlsplit(url).scheme != 'https':
                raise ValueError('Unexpected image URL')
            response = get(url, timeout=(5, 60), allow_redirects=False, stream=True)
            if response.status_code != 200:
                raise ValueError('Image download failed')
            raw = response.raw.read(12 * 1024 * 1024 + 1, decode_content=True)
            if len(raw) > 12 * 1024 * 1024:
                raise ValueError('Oversized image')
        return decode_image(raw, 4_194_304)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, binascii.Error, requests.RequestException):
        raise _unavailable(f'{label} chưa trả về ảnh phong cách hợp lệ. Kiểm tra model ảnh rồi thử lại.') from None
