import base64
import io
import json
import time

import pytest
import requests
from fastapi.testclient import TestClient
from PIL import Image

from fsmart.app import create_app
from fsmart.chat import ChatInput, ChatService, ChatUnavailable, IMAGES_URL, RESPONSES_URL
from fsmart.config import Settings
from fsmart.style_plans import StylePlanCache, StyleRecipe


KEY = 'sk-test-' + 'z' * 40  # fake; tests never contact OpenAI
REFERENCE = {'reply': 'Tạo style màu nước xanh rồi chuyển bằng VGG19.', 'title': 'Màu nước xanh',
             'engine': 'reference', 'preset': 'candy', 'strength': .6, 'steps': 50,
             'reference_prompt': 'Soft blue watercolor washes and paper grain, abstract texture.'}


def png(color):
    buffer = io.BytesIO()
    Image.new('RGB', (64, 64), color).save(buffer, 'PNG')
    return buffer.getvalue()


def response(data, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


def structured(data):
    return response({'status': 'completed', 'output': [{'type': 'message', 'content': [
        {'type': 'output_text', 'text': json.dumps(data)}]}]})


class StyleModels:
    key = 'test-style:1'

    def __init__(self):
        self.calls = []
        self.custom_ready = True

    def status(self):
        return {'face_ready': True, 'presets_ready': True, 'custom_ready': self.custom_ready, 'device': 'cpu'}

    def analyze(self, image):
        return []

    def preset(self, image, style, strength, progress, profile='fast'):
        self.calls.append(('preset', style, strength))
        return Image.blend(image, Image.new('RGB', image.size, 'yellow'), strength)

    def custom(self, image, style, strength, steps, progress):
        self.calls.append(('custom', style.getpixel((0, 0)), strength, steps))
        return style.resize(image.size)


def client_for(tmp_path, service):
    return TestClient(create_app(Settings(data_dir=tmp_path/'runtime', weights_dir=tmp_path/'weights'), StyleModels(), service))


def wait_job(client, job_id):
    for _ in range(200):
        job = client.get(f'/api/jobs/{job_id}').json()
        if job['status'] in {'done', 'error'}:
            return job
        time.sleep(.01)
    pytest.fail('Style job did not finish')


def upload(client):
    album = client.post('/api/albums', json={'name': 'private album never sent to provider'}).json()['id']
    result = client.post(f'/api/albums/{album}/photos', files={'files': ('private-photo.png', png('red'), 'image/png')}).json()
    assert wait_job(client, result['job_id'])['status'] == 'done'
    return client.get(f'/api/albums/{album}/photos').json()[0]['id']


def test_local_description_creates_stylized_output_and_duplicate_click_reuses_job(tmp_path):
    service = ChatService(api_key='', post=lambda *a, **k: pytest.fail('Offline recipe contacted OpenAI'))
    with client_for(tmp_path, service) as client:
        photo = upload(client)
        original = client.get(f'/api/photos/{photo}/image').content
        plan = client.post('/api/chat', json={'mode': 'style', 'message': 'Gam ấm, nét cọ dày, đậm 65%'}).json()
        assert plan['provider'] == 'local' and 'cục bộ' in plan['reply']
        assert plan['style_plan']['engine'] == 'preset' and plan['style_plan']['preset'] == 'rain_princess'
        payload = {'photo_id': photo, 'plan_id': plan['style_plan']['id']}
        first = client.post('/api/stylize/from-chat', json=payload)
        assert first.status_code == 202
        job = wait_job(client, first.json()['job_id'])
        assert job['status'] == 'done'
        assert client.post('/api/stylize/from-chat', json=payload).json()['job_id'] == job['id']
        assert client.app.state.models.calls == [('preset', 'rain_princess', .65)]
        assert client.get(job['result']['image_url']).content.startswith(b'\x89PNG')
        assert client.get(f'/api/photos/{photo}/image').content == original
        assert len(client.get('/api/outputs').json()) == 1
        assert '65%' in client.get('/api/outputs').json()[0]['title']
        assert client.delete(f'/api/photos/{photo}').status_code == 200
        assert len(client.app.state.store.all('SELECT * FROM output_details')) == 1  # recoverable delete retains recipes
        assert client.get('/api/outputs').json() == []


def test_novel_style_without_key_is_not_silently_replaced_with_a_preset(tmp_path):
    with client_for(tmp_path, ChatService(api_key='')) as client:
        photo = upload(client)
        answer = client.post('/api/chat', json={'mode': 'style', 'message': 'Màu nước pastel xanh nhạt'}).json()
        plan = answer['style_plan']
        assert plan['engine'] == 'reference' and plan['requires_api_key']
        result = client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': plan['id']})
        assert result.status_code == 503
        assert not client.get('/api/outputs').json() and not client.app.state.models.calls
        assert client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': '0'*32}).status_code == 409
        assert client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': plan['id'], 'engine': 'injected'}).status_code == 422
        unsupported = client.post('/api/chat', json={'mode': 'style', 'message': 'Thay mặt và đổi nền ảnh'}).json()
        assert unsupported['style_plan'] is None


def test_structured_plan_and_generated_reference_pipeline_send_text_only(tmp_path):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if url == RESPONSES_URL:
            schema = kwargs['json']['text']['format']
            assert schema['type'] == 'json_schema' and schema['strict']
            assert schema['schema']['additionalProperties'] is False
            assert set(schema['schema']['required']) == set(REFERENCE)
            return structured(REFERENCE)
        assert url == IMAGES_URL
        body = kwargs['json']
        assert set(body) == {'model', 'n', 'size', 'quality', 'output_format', 'prompt'}
        assert body['model'] == 'gpt-image-1.5' and body['n'] == 1 and body['quality'] == 'low'
        assert kwargs['allow_redirects'] is False
        assert 'private-photo' not in json.dumps(body) and 'private album' not in json.dumps(body)
        assert KEY not in json.dumps(body)
        return response({'data': [{'b64_json': base64.b64encode(png('blue')).decode()}]})

    with client_for(tmp_path, ChatService(api_key=KEY, post=post)) as client:
        photo = upload(client)
        plan = client.post('/api/chat', json={'mode': 'style', 'message': 'Màu nước xanh nhạt'}).json()['style_plan']
        assert len(calls) == 1  # proposing does not spend an image generation
        job_id = client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': plan['id']}).json()['job_id']
        job = wait_job(client, job_id)
        assert job['status'] == 'done' and len(calls) == 2
        assert client.app.state.models.calls == [('custom', (0, 0, 255), .6, 50)]
        image = Image.open(io.BytesIO(client.get(job['result']['image_url']).content))
        assert image.getpixel((0, 0)) == (0, 0, 255)
        assert client.get('/api/outputs').json()[0]['title'] == REFERENCE['title']
        assert list((tmp_path/'runtime/styles').iterdir()) == []  # temporary reference is cleaned


def test_missing_vgg_is_rejected_before_image_api_spend(tmp_path):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        assert url == RESPONSES_URL
        return structured(REFERENCE)

    with client_for(tmp_path, ChatService(api_key=KEY, post=post)) as client:
        photo = upload(client)
        client.app.state.models.custom_ready = False
        plan = client.post('/api/chat', json={'mode': 'style', 'message': 'Màu nước xanh'}).json()['style_plan']
        assert client.post('/api/stylize/from-chat', json={'photo_id': photo, 'plan_id': plan['id']}).status_code == 503
        assert calls == [RESPONSES_URL] and not client.app.state.models.calls


@pytest.mark.parametrize('change', [{'strength': 2}, {'preset': 'shell_command'}, {'extra_url': 'https://untrusted.example'}, {'reference_prompt': ''}])
def test_invalid_provider_recipe_never_becomes_an_executable_plan(change):
    service = ChatService(api_key=KEY, post=lambda *a, **k: structured({**REFERENCE, **change}))
    with pytest.raises(ChatUnavailable) as caught:
        service.reply(ChatInput(mode='style', message='màu nước'))
    assert caught.value.status_code == 502
    assert not service.plans._items


def test_image_provider_error_releases_plan_for_explicit_retry(tmp_path):
    attempts = []

    def post(url, **kwargs):
        if url == RESPONSES_URL:
            return structured(REFERENCE)
        attempts.append(url)
        if len(attempts) == 1:
            return response({'error': KEY}, 429)
        return response({'data': [{'b64_json': base64.b64encode(png('blue')).decode()}]})

    with client_for(tmp_path, ChatService(api_key=KEY, post=post)) as client:
        photo = upload(client)
        plan = client.post('/api/chat', json={'mode': 'style', 'message': 'Màu nước xanh'}).json()['style_plan']
        payload = {'photo_id': photo, 'plan_id': plan['id']}
        first_id = client.post('/api/stylize/from-chat', json=payload).json()['job_id']
        failed = wait_job(client, first_id)
        assert failed['status'] == 'error' and KEY not in json.dumps(failed)
        second_id = client.post('/api/stylize/from-chat', json=payload).json()['job_id']
        assert second_id != first_id and wait_job(client, second_id)['status'] == 'done'
        assert len(attempts) == 2


@pytest.mark.parametrize('data', [{'data': [{'url': 'https://untrusted.example/image'}]}, {'data': [{'b64_json': 'invalid'}]}, {'data': []}])
def test_reference_data_must_be_a_valid_bounded_image_not_a_remote_url(data):
    service = ChatService(api_key=KEY, post=lambda url, **kwargs: response(data))
    with pytest.raises(ChatUnavailable):
        service.generate_style_reference(StyleRecipe(**REFERENCE))


def test_plan_cache_expiration_capacity_and_copy_isolation():
    clock = [0]
    cache = StylePlanCache(ttl=10, capacity=2, clock=lambda: clock[0])
    recipe = StyleRecipe(**REFERENCE)
    first = cache.add(recipe)
    copy = cache.get(first)
    copy.strength = .1
    assert cache.get(first).strength == .6
    second = cache.add(recipe)
    cache.add(recipe)
    with pytest.raises(KeyError):
        cache.get(first)
    clock[0] = 11
    with pytest.raises(KeyError):
        cache.get(second)


def test_style_request_in_regular_chat_returns_actionable_plan():
    result = ChatService(api_key='').reply(ChatInput(message='Tôi muốn tạo ảnh gam màu ấm, nét cọ dày'))
    assert result['mode'] == 'style' and result['style_plan']['preset'] == 'rain_princess'


def test_novel_style_refinement_does_not_turn_into_unrelated_preset():
    service = ChatService(api_key='')
    first = service.reply(ChatInput(mode='style', message='Màu nước pastel xanh'))
    second = service.reply(ChatInput(mode='style', message='Nhạt hơn', history=[
        {'role': 'user', 'content': 'Màu nước pastel xanh'}, {'role': 'assistant', 'content': first['reply']}
    ]))
    assert second['style_plan']['engine'] == 'reference'
    assert 'Màu nước pastel xanh' in service.get_style_plan(second['style_plan']['id']).reference_prompt
