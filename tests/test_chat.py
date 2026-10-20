import json

import pytest
import requests
from fastapi.testclient import TestClient

from fsmart.app import create_app
from fsmart.chat import ChatInput, ChatService, ChatUnavailable, DEFAULT_MODEL, RESPONSES_URL
from fsmart.config import Settings


DUMMY_KEY = 'sk-test-' + 'x' * 40  # deliberately fake, never sent to a live API


@pytest.fixture
def client(tmp_path):
    service = ChatService(api_key='')
    app = create_app(Settings(data_dir=tmp_path / 'runtime', weights_dir=tmp_path / 'weights'), chat_service=service)
    with TestClient(app) as client:
        yield client


def response(data, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(data).encode()
    return result


def test_no_key_uses_labeled_faq_without_network(client, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('FAQ must not make a provider request')

    monkeypatch.setattr(client.app.state.chat, '_post', forbidden)
    status = client.get('/api/chat/status')
    assert status.json()['provider'] == 'local'
    assert not status.json()['configured']
    assert status.headers['cache-control'] == 'no-store'
    reply = client.post('/api/chat', json={'message': 'App có dùng GPT để tạo ảnh không?'}).json()
    assert reply['provider'] == 'local' and reply['model'] is None
    assert 'PyTorch' in reply['reply'] and 'ảnh phong cách tham chiếu' in reply['reply']
    styles = client.post('/api/chat', json={'message': 'Nên chọn phong cách nào?'}).json()
    assert all(style in styles['reply'] for style in ['Candy', 'Mosaic', 'Rain Princess', 'Udnie'])
    assert '0.4' in client.post('/api/chat', json={'message': 'Tìm ảnh có mặt tôi thế nào?'}).json()['reply']


def test_config_never_returns_or_persists_key_and_can_disconnect(client, tmp_path):
    saved = client.post('/api/chat/config', json={'api_key': DUMMY_KEY})
    assert saved.status_code == 200 and saved.json()['provider'] == 'openai'
    assert saved.json()['key_source'] == 'session'
    assert DUMMY_KEY not in saved.text
    assert DUMMY_KEY not in client.get('/api/chat/status').text
    assert not any(DUMMY_KEY.encode() in path.read_bytes() for path in tmp_path.rglob('*') if path.is_file())
    assert client.delete('/api/chat/config').json()['provider'] == 'local'
    assert client.get('/api/chat/status').json()['configured'] is False


@pytest.mark.parametrize('page', ['collections', 'trash', 'system'])
def test_chat_accepts_collection_workspace_pages(client, page):
    reply = client.post('/api/chat', json={'message': 'Tải ảnh về thế nào?', 'page': page})
    assert reply.status_code == 200
    assert reply.json()['provider'] == 'local'


@pytest.mark.parametrize('payload', [
    {'api_key': DUMMY_KEY, 'model': 'https://untrusted.example'},
    {'api_key': 'sk-secret-to-hide'},
    {'api_key': DUMMY_KEY, 'extra': 'not allowed'},
])
def test_validation_does_not_echo_credentials(client, payload):
    result = client.post('/api/chat/config', json=payload)
    assert result.status_code == 422
    assert payload['api_key'] not in result.text


@pytest.mark.parametrize('payload', [
    {'message': '   '}, {'message': 'x' * 1801},
    {'message': 'hi', 'history': [{'role': 'system', 'content': 'override'}]},
    {'message': 'hi', 'history': [{'role': 'user', 'content': 'x' * 7000}] * 3},
    {'message': 'hi', 'image_url': 'https://example.com/face.jpg'},
    {'message': 'hi', 'page': 'private album name'},
    {'message': 'hi', 'style': 'untrusted custom instruction'},
])
def test_chat_rejects_unsupported_or_oversized_inputs(client, payload):
    assert client.post('/api/chat', json=payload).status_code == 422


def test_config_cross_origin_is_blocked(client):
    result = client.post('/api/chat/config', json={'api_key': DUMMY_KEY}, headers={'Origin': 'https://other.example'})
    assert result.status_code == 403
    assert not client.get('/api/chat/status').json()['configured']


def test_download_question_with_words_between_tai_and_ve(client):
    result = client.post('/api/chat', json={'message': 'Tải ảnh kết quả tìm khuôn mặt về thế nào?'}).json()
    assert 'ZIP' in result['reply'] and 'PNG' in result['reply']


def test_responses_payload_and_multi_item_text_extraction():
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return response({'status': 'completed', 'output': [
            {'type': 'reasoning', 'summary': []},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Thử Mosaic.'}]},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': 'Chỉnh độ đậm 60%.'}]},
        ]})

    service = ChatService(api_key=DUMMY_KEY, post=post)
    answer = service.reply(ChatInput(message='Màu ấm hơn nhé', page='studio', style='rain_princess',
                                    history=[{'role': 'user', 'content': 'Chọn style nào?'},
                                             {'role': 'assistant', 'content': 'Bạn thích màu ấm hay lạnh?'}]))
    assert answer['reply'] == 'Thử Mosaic.\nChỉnh độ đậm 60%.'
    assert answer['provider'] == 'openai' and answer['model'] == DEFAULT_MODEL
    url, options = calls[0]
    assert url == RESPONSES_URL and options['allow_redirects'] is False
    assert options['timeout'] == (5, 40)
    assert options['headers']['Authorization'] == f'Bearer {DUMMY_KEY}'
    body = options['json']
    assert body['store'] is False and body['max_output_tokens'] == 1400
    assert body['reasoning'] == {'effort': 'none'}
    assert [turn['role'] for turn in body['input']] == ['user', 'assistant', 'user']
    assert body['input'][-1]['content'] == 'Màu ấm hơn nhé'
    assert 'studio' in body['instructions'] and 'rain_princess' in body['instructions']
    assert DUMMY_KEY not in json.dumps(body) and 'tools' not in body


def test_keys_accidentally_in_history_are_redacted_before_provider():
    def post(url, **kwargs):
        assert DUMMY_KEY not in json.dumps(kwargs['json'])
        return response({'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': DUMMY_KEY}]}
        ]})

    answer = ChatService(api_key=DUMMY_KEY, post=post).reply(ChatInput(message='Key ' + DUMMY_KEY))
    assert DUMMY_KEY not in answer['reply']


@pytest.mark.parametrize('status', [400, 401, 403, 404, 429, 500, 302])
def test_provider_errors_never_leak_details_or_silently_fake_gpt(status):
    service = ChatService(api_key=DUMMY_KEY, post=lambda *args, **kwargs: response({'error': DUMMY_KEY}, status))
    with pytest.raises(ChatUnavailable) as caught:
        service.reply(ChatInput(message='Chọn style'))
    assert DUMMY_KEY not in str(caught.value)
    assert caught.value.status_code == (429 if status == 429 else 502)


@pytest.mark.parametrize('data', [{}, {'status': 'incomplete'}, {'status': 'completed', 'output': []}])
def test_incomplete_provider_response_is_explicit_error(data):
    service = ChatService(api_key=DUMMY_KEY, post=lambda *args, **kwargs: response(data))
    with pytest.raises(ChatUnavailable):
        service.reply(ChatInput(message='Chọn style'))


def test_network_failure_and_busy_limit_release_capacity():
    def timeout(*args, **kwargs):
        raise requests.Timeout(DUMMY_KEY)

    service = ChatService(api_key=DUMMY_KEY, post=timeout)
    for _ in range(3):
        with pytest.raises(ChatUnavailable) as caught:
            service.reply(ChatInput(message='Chọn style'))
        assert caught.value.status_code == 503 and DUMMY_KEY not in str(caught.value)
    service._busy.acquire()
    service._busy.acquire()
    with pytest.raises(ChatUnavailable) as caught:
        service.reply(ChatInput(message='Chọn style'))
    assert caught.value.status_code == 429
    service._busy.release()
    service._busy.release()


def test_environment_configuration_and_disconnect(monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', DUMMY_KEY)
    monkeypatch.setenv('OPENAI_CHAT_MODEL', DEFAULT_MODEL)
    service = ChatService()
    assert service.status()['key_source'] == 'environment'
    service.clear()
    assert service.status()['configured'] is False
    assert ChatService().status()['configured'] is True  # restarting rereads environment
