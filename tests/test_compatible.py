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


def test_van_gogh_with_an_api_source_is_painted_by_that_api_not_locally(tmp_path):
    from test_style_chat import StyleModels, upload, wait_job, png
    artwork = {'reply': 'Dùng tranh Van Gogh.', 'title': 'Van Gogh', 'engine': 'artwork', 'preset': 'candy',
               'strength': .7, 'steps': 50, 'reference_prompt': 'met:436535'}  # what a planner may still answer
    fake = Fake([chat_reply(json.dumps(artwork)), response({'data': [{'b64_json': base64.b64encode(png('green')).decode()}]})])
    s = service(fake); configure(s, image_model='gpt-image-2', image_mode='edit')
    app = create_app(Settings(data_dir=tmp_path / 'runtime', weights_dir=tmp_path / 'weights'), StyleModels(), s)
    with TestClient(app) as client:
        photo = upload(client)
        plan = client.post('/api/chat', json={'message': 'tạo phong cách vangogh', 'mode': 'style', 'provider': 'compatible'}).json()['style_plan']
        assert plan['direct'] and plan['engine'] == 'reference' and plan['api_label'] == 'VietAPI' and plan['image_model'] == 'gpt-image-2'
        assert 'MODEL API' in fake.calls[0][1]['json']['messages'][0]['content']
        job = wait_job(client, client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': plan['id']}).json()['job_id'])
        assert job['status'] == 'done' and job['result']['provider'] == 'VietAPI' and job['result']['model'] == 'gpt-image-2'
        url, kw = fake.calls[1]
        assert url == BASE + '/images/edits' and kw['data']['model'] == 'gpt-image-2' and 'van Gogh' in kw['data']['prompt']
        assert client.app.state.models.calls == []


def test_api_plan_without_an_image_model_asks_for_one_instead_of_running_locally(tmp_path):
    from test_style_chat import StyleModels, upload, REFERENCE
    fake = Fake([chat_reply(json.dumps(REFERENCE))])
    s = service(fake); configure(s)  # chat model only
    app = create_app(Settings(data_dir=tmp_path / 'runtime', weights_dir=tmp_path / 'weights'), StyleModels(), s)
    with TestClient(app) as client:
        photo = upload(client)
        plan = client.post('/api/chat', json={'message': 'màu nước', 'mode': 'style', 'provider': 'compatible'}).json()['style_plan']
        refused = client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': plan['id']})
        assert refused.status_code == 409 and 'model tạo ảnh' in refused.json()['detail'] and not client.app.state.models.calls


def limited(message, retry=None):
    r = response({'error': {'message': message, 'type': 'rate_limit_error'}}, 429)
    if retry is not None:
        r.headers['Retry-After'] = str(retry)
    return r


def test_short_rate_limits_wait_and_retry_then_succeed(monkeypatch):
    waits = []
    monkeypatch.setattr(compatible.time, 'sleep', waits.append)
    fake = Fake([limited('Rate limit reached: 3 RPM', retry=2), limited('Rate limit reached: 3 RPM'), chat_reply('xong')])
    s = service(fake); configure(s)
    assert s.reply(ChatInput(message='hi', provider='compatible'))['reply'] == 'xong'
    assert waits == [2.0, compatible.RATE_RETRIES[1]] and len(fake.calls) == 3


def test_quota_429_is_not_retried_and_shows_the_provider_reason(monkeypatch):
    monkeypatch.setattr(compatible.time, 'sleep', lambda s: None)
    fake = Fake([limited(f'Insufficient balance for gpt-image-2, need 0.3 credit (key {KEY})')])
    s = service(fake); configure(s)
    with pytest.raises(ChatUnavailable) as caught:
        s.reply(ChatInput(message='hi', provider='compatible'))
    text = str(caught.value)
    assert len(fake.calls) == 1 and 'hết hạn mức hoặc số dư' in text and 'Insufficient balance' in text and KEY not in text


def test_persistent_or_long_rate_limits_are_reported_with_the_reason(monkeypatch):
    waits = []
    monkeypatch.setattr(compatible.time, 'sleep', waits.append)
    fake = Fake([limited('Too many requests')] * 3)
    s = service(fake); configure(s)
    with pytest.raises(ChatUnavailable) as caught:
        s.reply(ChatInput(message='hi', provider='compatible'))
    assert len(fake.calls) == 3 and 'đã tự chờ và thử lại' in str(caught.value) and 'Too many requests' in str(caught.value)
    fake.posts = [limited('Slow down', retry=120)]
    with pytest.raises(ChatUnavailable):
        s.reply(ChatInput(message='hi', provider='compatible'))
    assert len(fake.calls) == 4  # a 2-minute Retry-After is reported, not slept through


def test_vietapi_redraws_the_whole_scene_from_a_vision_description(tmp_path):
    """VietAPI has no /images/edits: its vision chat model describes the photo, gpt-image paints it; nothing local."""
    from test_style_chat import StyleModels, upload, wait_job, png
    recipe = {'reply': 'Vẽ lại kiểu Van Gogh.', 'title': 'Van Gogh', 'engine': 'reference', 'preset': 'candy',
              'strength': .7, 'steps': 50, 'reference_prompt': 'Van Gogh swirling impasto, cobalt and gold'}
    scene = 'Four young people stand in a row on a stage holding paper signs, purple lights behind them, smiling at the camera.'
    fake = Fake([chat_reply(json.dumps(recipe)),
                 response({'choices': [{'message': {'content': 'I cannot see images.'}}]}),  # chat model without vision
                 chat_reply(scene),                                                          # vision fallback
                 response({'data': [{'b64_json': base64.b64encode(png('green')).decode()}]})],
                models=('glm-5.2', 'claude-sonnet-5.5', 'gpt-image-2', 'gpt-image-2.5'))
    s = service(fake)
    with pytest.raises(ChatUnavailable) as caught:  # a chat model in the image slot is refused up front
        s.configure_compatible(CompatibleConfigInput(base_url='https://api.vietapi.tech/v1', api_key=KEY, model='glm-5.2', image_model='glm-5.2', label='VietAPI'))
    assert 'không phải model vẽ ảnh' in str(caught.value) and 'gpt-image-2' in str(caught.value)
    state = s.configure_compatible(CompatibleConfigInput(base_url='https://api.vietapi.tech/v1', api_key=KEY, model='glm-5.2', image_model='gpt-image-2', label='VietAPI'))
    assert state['compatible_image_mode'] == 'redraw'
    app = create_app(Settings(data_dir=tmp_path / 'runtime', weights_dir=tmp_path / 'weights'), StyleModels(), s)
    with TestClient(app) as client:
        photo = upload(client)
        plan = client.post('/api/chat', json={'message': 'phong cách van gogh', 'mode': 'style', 'provider': 'compatible'}).json()['style_plan']
        job = wait_job(client, client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': plan['id']}).json()['job_id'])
        assert job['status'] == 'done' and job['result']['provider'] == 'VietAPI', job
        urls = [c[0] for c in fake.calls]
        assert urls == ['https://api.vietapi.tech/v1/chat/completions'] * 3 + ['https://api.vietapi.tech/v1/images/generations']
        first, second = fake.calls[1][1]['json'], fake.calls[2][1]['json']
        assert first['model'] == 'glm-5.2' and second['model'] == 'claude-sonnet-5.5'
        assert second['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/jpeg;base64,')
        body = fake.calls[3][1]['json']
        assert body['model'] == 'gpt-image-2' and scene in body['prompt'] and 'Van Gogh' in body['prompt'] and body['size'] in {'1536x1024', '1024x1536', '1024x1024'}
        assert client.app.state.models.calls == [] and '/images/edits' not in ' '.join(urls)
