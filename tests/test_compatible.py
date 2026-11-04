import base64, io, json
import pytest, requests
from fastapi.testclient import TestClient
from PIL import Image
from fsmart.app import create_app
from fsmart.chat import ChatService, ChatInput, ChatUnavailable, CompatibleConfigInput
from fsmart.config import Settings
import fsmart.compatible as compatible

KEY = 'sk-viet-' + 'x' * 32  # fake: all provider traffic is intercepted
BASE = 'https://api.vietapi.example/v1'


def response(data=None, status=200):
    r = requests.Response(); r.status_code = status
    r._content = json.dumps(data if data is not None else {}).encode()
    return r


def chat_reply(text):
    return response({'choices': [{'message': {'role': 'assistant', 'content': text}, 'finish_reason': 'stop'}]})


class Fake:
    def __init__(self, posts=(), models=('claude-sonnet-5.5', 'gpt-6-sol', 'deepseek-v4-flash'), get_status=200):
        self.posts, self.calls, self.gets = list(posts), [], []
        self.models, self.get_status = models, get_status

    def post(self, url, **kw):
        self.calls.append((url, kw)); return self.posts.pop(0)

    def get(self, url, **kw):
        self.gets.append((url, kw))
        return response({'object': 'list', 'data': [{'id': m} for m in self.models]}, self.get_status)


def service(fake):
    return ChatService(api_key='', post=fake.post, get=fake.get, gemini_key='')


def configure(s, **extra):
    return s.configure_compatible(CompatibleConfigInput(base_url=BASE + '/', api_key=KEY, model='claude-sonnet-5.5', label='VietAPI', **extra))


def test_chat_through_an_openai_compatible_gateway():
    fake = Fake([chat_reply('<think>nội bộ</think>Chào bạn, chọn preset mosaic nhé.')])
    s = service(fake); state = configure(s)
    assert state['selection'] == 'compatible' and state['compatible_verified'] and KEY not in json.dumps(state)
    assert state['compatible_base_url'] == BASE and state['model'] == 'claude-sonnet-5.5'
    result = s.reply(ChatInput(message='Nên chọn style nào?', provider='compatible'))
    assert result['reply'] == 'Chào bạn, chọn preset mosaic nhé.' and result['provider'] == 'compatible'
    url, kw = fake.calls[0]
    assert url == BASE + '/chat/completions' and kw['headers']['Authorization'] == f'Bearer {KEY}'
    assert kw['allow_redirects'] is False and kw['json']['model'] == 'claude-sonnet-5.5'
    assert kw['json']['messages'][0]['role'] == 'system' and kw['json']['messages'][-1]['content'] == 'Nên chọn style nào?'
    assert fake.gets[0][0] == BASE + '/models'


def test_unknown_model_is_saved_but_marked_unverified_and_missing_models_endpoint_is_tolerated():
    s = service(Fake(models=('gpt-6-sol',)))
    assert not configure(s)['compatible_verified']
    s = service(Fake(get_status=404))
    state = configure(s)
    assert state['compatible_configured'] and not state['compatible_verified']


@pytest.mark.parametrize('status,needle', [(401, 'từ chối API key'), (402, 'hết số dư')])
def test_failed_model_listing_saves_but_explains(status, needle):
    s = service(Fake(get_status=status))
    state = configure(s)
    assert state['compatible_configured'] and not state['compatible_verified']
    assert needle in state['compatible_note'] and KEY not in json.dumps(state)


def test_transient_errors_retry_then_name_the_status(monkeypatch):
    monkeypatch.setattr(compatible, 'RETRY_DELAYS', (0, 0))
    fake = Fake([response(status=503), chat_reply('ok')])
    s = service(fake); configure(s)
    assert s.reply(ChatInput(message='hi', provider='compatible'))['reply'] == 'ok' and len(fake.calls) == 2
    fake.posts = [response(status=502)] * 3
    with pytest.raises(ChatUnavailable) as caught:
        s.reply(ChatInput(message='hi', provider='compatible'))
    assert 'mã 502' in str(caught.value) and 'VietAPI' in str(caught.value)


def test_style_plan_accepts_json_wrapped_in_prose():
    recipe = {'reply': 'Thử nét cọ xoáy kiểu Van Gogh.', 'title': 'Đêm đầy sao', 'engine': 'preset', 'preset': 'rain_princess',
              'strength': .6, 'steps': 50, 'reference_prompt': ''}
    fake = Fake([chat_reply('Đây là công thức:\n```json\n' + json.dumps(recipe, ensure_ascii=False) + '\n```')])
    s = service(fake); configure(s)
    plan = s.reply(ChatInput(message='tạo phong cách van gogh', mode='style', provider='compatible'))
    assert plan['style_plan']['preset'] == 'rain_princess' and plan['provider'] == 'compatible'
    assert 'JSON' in fake.calls[0][1]['json']['messages'][0]['content']


def test_reference_images_use_the_gateway_image_model():
    buf = io.BytesIO(); Image.new('RGB', (64, 64), '#7c3aed').save(buf, 'PNG')
    fake = Fake([response({'data': [{'b64_json': base64.b64encode(buf.getvalue()).decode()}]})])
    s = service(fake)
    configure(s)
    with pytest.raises(ChatUnavailable):
        s.require_image_key('compatible')
    configure(s, image_model='gpt-image-2')
    from fsmart.style_plans import StyleRecipe
    recipe = StyleRecipe(reply='r', title='t', engine='reference', preset='candy', strength=.6, steps=150, reference_prompt='xanh cobalt')
    image = s.generate_style_reference(recipe, 'compatible')
    assert image.size == (64, 64) and fake.calls[0][0] == BASE + '/images/generations' and fake.calls[0][1]['json']['model'] == 'gpt-image-2'


@pytest.mark.parametrize('url', ['http://api.vietapi.example/v1', 'https://user:pw@api.example/v1', 'https://api.example/v1?x=1', 'file:///c:/x'])
def test_unsafe_base_urls_are_rejected_without_echoing_the_key(tmp_path, url):
    app = create_app(Settings(data_dir=tmp_path), chat_service=service(Fake()))
    with TestClient(app) as c:
        r = c.post('/api/chat/compatible/config', json={'base_url': url, 'api_key': KEY, 'model': 'gpt-6-sol'})
        assert r.status_code == 422 and KEY not in r.text and 'Base URL' in r.json()['detail']


def test_routes_configure_list_and_clear(tmp_path):
    app = create_app(Settings(data_dir=tmp_path), chat_service=service(Fake()))
    with TestClient(app) as c:
        listed = c.post('/api/chat/compatible/models', json={'base_url': BASE, 'api_key': KEY})
        assert listed.status_code == 200 and 'claude-sonnet-5.5' in listed.json()['models'] and KEY not in listed.text
        saved = c.post('/api/chat/compatible/config', json={'base_url': BASE, 'api_key': KEY, 'model': 'gpt-6-sol', 'label': 'VietAPI'})
        assert saved.status_code == 200 and saved.json()['selection'] == 'compatible' and KEY not in saved.text
        again = c.post('/api/chat/compatible/models', json={'base_url': BASE})  # stored key is reused for the same URL
        assert again.status_code == 200
        assert c.post('/api/chat/compatible/config', json={'base_url': BASE, 'api_key': KEY, 'model': 'x'}, headers={'Origin': 'https://evil.example'}).status_code == 403
        cleared = c.delete('/api/chat/compatible/config').json()
        assert cleared['selection'] == 'qwen' and not cleared['compatible_configured']
