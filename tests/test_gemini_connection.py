import pytest,requests
from fastapi.testclient import TestClient
from fsmart.app import create_app
from fsmart.config import Settings
from fsmart.chat import ChatService,ChatUnavailable,GeminiConfigInput
from test_app import TestModels
from test_gemini import KEY,response

AUTH_KEY='AQ.Ab'+'test_only_'*9+'.part-_~+/=='

@pytest.mark.parametrize('raw',[AUTH_KEY,' '+AUTH_KEY+' ', '"'+AUTH_KEY+'"',"'"+AUTH_KEY+"'",'GEMINI_API_KEY="'+AUTH_KEY+'"',"$env:GOOGLE_API_KEY = '"+AUTH_KEY+"'",'\ufeff\u200b'+AUTH_KEY+'\u2060'])
def test_auth_key_normalization_and_header_transport_without_exposing_key(raw):
    from fsmart.chat import redact,ChatInput
    calls=[]
    def get(url,**options):
        assert options['headers']['x-goog-api-key']==AUTH_KEY and AUTH_KEY not in url
        calls.append(1);return metadata()
    def post(url,**options):
        assert AUTH_KEY not in str(options['json'])
        return response(AUTH_KEY)
    service=ChatService(api_key='',get=get,post=post)
    state=service.configure_gemini(GeminiConfigInput(api_key=raw))
    assert AUTH_KEY not in str(state) and service.check_gemini()['gemini_verified']
    result=service.reply(ChatInput(message='Hỏi '+AUTH_KEY))
    assert AUTH_KEY not in result['reply'] and AUTH_KEY not in redact('Key '+AUTH_KEY) and calls==[1]

@pytest.mark.parametrize('bad',[AUTH_KEY+'\r\nx-injected: bad',AUTH_KEY+' middle space','AQ.'+'x'*4094])
def test_auth_key_rejects_header_injection_and_excess_length(bad):
    service=ChatService(api_key='')
    with pytest.raises((ValueError,ChatUnavailable)):service.configure_gemini(GeminiConfigInput(api_key=bad))

def metadata():return response(data={'name':'models/gemini-3.5-flash-lite','supportedGenerationMethods':['generateContent']})

def test_check_uses_header_only_and_does_not_generate(tmp_path):
    calls=[]
    def get(url,**options):calls.append((url,options));return metadata()
    service=ChatService(api_key='',get=get,post=lambda *a,**k:pytest.fail('Connection check must not generate'))
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime'),TestModels(),service)) as c:
        assert c.post('/api/chat/gemini/check').status_code==409 and not calls
        c.post('/api/chat/gemini/config',json={'api_key':KEY})
        assert not service.status()['gemini_verified']
        checked=c.post('/api/chat/gemini/check')
        assert checked.status_code==200 and checked.json()['gemini_verified'] and KEY not in checked.text
        assert checked.headers['cache-control']=='no-store'
        url,options=calls[0]
        assert url=='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite'
        assert KEY not in url and options['headers']['x-goog-api-key']==KEY and not options['allow_redirects']
        assert 'json' not in options and 'params' not in options
        assert c.post('/api/chat/gemini/check',headers={'Origin':'https://evil.example'}).status_code==403
        c.delete('/api/chat/gemini/config');assert not service.status()['gemini_verified']

@pytest.mark.parametrize('status',[400,403,404,429])
def test_check_failure_is_explicit_sanitized_and_key_stays_in_ram(status):
    service=ChatService(api_key='',get=lambda *a,**k:response(data={'error':KEY},status=status))
    service.configure_gemini(GeminiConfigInput(api_key=KEY))
    with pytest.raises(ChatUnavailable) as caught:service.check_gemini()
    assert KEY not in str(caught.value)
    assert service.status()['gemini_configured'] and not service.status()['gemini_verified']

def test_changed_key_cannot_be_marked_verified_by_older_request():
    def get(*a,**k):service.clear_gemini();return metadata()
    service=ChatService(api_key='',get=get);service.configure_gemini(GeminiConfigInput(api_key=KEY))
    with pytest.raises(ChatUnavailable) as caught:service.check_gemini()
    assert caught.value.status_code==409 and not service.status()['gemini_verified']

def test_check_timeout_releases_capacity_and_preserves_key():
    def get(*a,**k):raise requests.Timeout(KEY)
    service=ChatService(api_key='',get=get);service.configure_gemini(GeminiConfigInput(api_key=KEY))
    for _ in range(3):
        with pytest.raises(ChatUnavailable) as caught:service.check_gemini()
        assert caught.value.status_code==503 and KEY not in str(caught.value)
    service._get=lambda *a,**k:metadata()
    assert service.check_gemini()['gemini_verified']
