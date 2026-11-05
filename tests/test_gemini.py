import base64,json
import pytest,requests
from fastapi.testclient import TestClient
from fsmart.app import create_app
from fsmart.chat import ChatService,ChatInput,ChatProviderInput,ChatUnavailable,GeminiConfigInput
from fsmart.config import Settings
from fsmart.style_plans import local_recipe,StyleRecipe,is_style_request
from test_style_chat import StyleModels,upload,wait_job,png,REFERENCE

KEY='AIza'+'g'*35  # fake: all provider traffic is intercepted

def response(text=None,*,data=None,status=200):
    r=requests.Response();r.status_code=status
    r._content=json.dumps(data if data is not None else {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':text}]}}]}).encode()
    return r

def configure(service):service.configure_gemini(GeminiConfigInput(api_key=KEY))


@pytest.mark.parametrize('parts',[
    [{'text':'no image'}],
    [{'inlineData':{'mimeType':'image/png','data':'invalid base64!'}}],
    [{'inlineData':{'mimeType':'image/png','data':base64.b64encode(b'not an image').decode()}}],
    [{'inlineData':{'mimeType':'image/svg+xml','data':'PHN2Zy8+'}}],
    [{'inlineData':{'mimeType':'image/png','data':None}}],
    [None],
])
def test_invalid_image_responses_are_sanitized(parts):
    from fsmart.gemini import generate_image
    post=lambda *a,**k:response(data={'candidates':[{'finishReason':'STOP','content':{'parts':parts}}]})
    with pytest.raises(ChatUnavailable) as caught:generate_image(post,KEY,'gemini-3.1-flash-lite-image','watercolor')
    assert caught.value.status_code==502 and KEY not in str(caught.value)


def test_network_failure_releases_chat_capacity():
    calls=[]
    def post(*args,**options):
        calls.append(1)
        if len(calls)<3:raise requests.Timeout(KEY)
        return response('Thử lại được.')
    service=ChatService(api_key='',post=post);configure(service)
    for _ in range(2):
        with pytest.raises(ChatUnavailable) as caught:service.reply(ChatInput(message='Xin chào'))
        assert KEY not in str(caught.value)
    assert service.reply(ChatInput(message='Xin chào'))['reply']=='Thử lại được.'


def test_artwork_checksum_rejects_replaced_file(tmp_path):
    from fsmart.artworks import ARTWORK,reference
    settings=Settings(data_dir=tmp_path/'runtime',weights_dir=tmp_path/'weights')
    path=settings.weights_dir/'artworks'/ARTWORK['filename'];path.parent.mkdir(parents=True)
    path.write_bytes(png('red'))
    with pytest.raises(ChatUnavailable):reference(settings)

def test_switch_is_explicit_and_missing_key_does_not_fall_back_or_contact_google():
    s=ChatService(api_key='',post=lambda *a,**k:pytest.fail('Unconfigured API contacted'))
    s.select_provider(ChatProviderInput(provider='gemini'))
    assert s.status()['selection']=='gemini' and not s.status()['configured']
    with pytest.raises(ChatUnavailable) as caught:s.reply(ChatInput(message='Hướng dẫn tìm ảnh'))
    assert caught.value.status_code==409
    # A local tab remains local even if another tab changed the preferred provider.
    assert s.reply(ChatInput(message='Tìm khuôn mặt thế nào?',provider='qwen'))['provider']=='local'
    configure(s);s.select_provider(ChatProviderInput(provider='qwen'))
    assert s.status()['gemini_configured'] and not s.status()['configured']
    s.clear_gemini();assert not s.status()['gemini_configured']

def test_google_receives_only_redacted_text_in_header_authenticated_request():
    calls=[]
    def post(url,**options):calls.append((url,options));return response('Mở thư viện. '+KEY)
    s=ChatService(api_key='',post=post);configure(s)
    result=s.reply(ChatInput(message='Hỏi '+KEY,history=[{'role':'assistant','content':'Cũ '+KEY}]))
    assert result['provider']=='gemini' and KEY not in result['reply']
    url,options=calls[0]
    assert url=='https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent'
    assert options['headers']['x-goog-api-key']==KEY and KEY not in url
    assert not options['allow_redirects'] and 'tools' not in options['json']
    assert KEY not in json.dumps(options['json'])
    assert options['json']['contents'][0]['role']=='model'
    assert all(set(part)=={'text'} for item in options['json']['contents'] for part in item['parts'])

@pytest.mark.parametrize('status',[400,401,403,404,429,500,302])
def test_google_errors_never_reflect_provider_body(status):
    s=ChatService(api_key='',post=lambda *a,**k:response(data={'error':KEY},status=status));configure(s)
    with pytest.raises(ChatUnavailable) as caught:s.reply(ChatInput(message='Xin chào'))
    assert KEY not in str(caught.value) and caught.value.status_code==(429 if status==429 else 502)

@pytest.mark.parametrize('data',[{}, {'candidates':[]},{'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'partial'}]}}]}, {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':'private reasoning','thought':True}]}}]}])
def test_google_incomplete_and_thinking_only_answers_are_errors(data):
    s=ChatService(api_key='',post=lambda *a,**k:response(data=data));configure(s)
    with pytest.raises(ChatUnavailable):s.reply(ChatInput(message='Xin chào'))

def test_google_schema_is_validated_and_image_job_stays_with_google(tmp_path):
    calls=[]
    def post(url,**options):
        calls.append((url,options))
        if options['json']['generationConfig'].get('responseMimeType')=='application/json':return response(json.dumps(REFERENCE))
        return response(data={'candidates':[{'finishReason':'STOP','content':{'parts':[{'inlineData':{'mimeType':'image/png','data':base64.b64encode(png('blue')).decode()}}]}}]})
    s=ChatService(api_key='',post=post);configure(s)
    app=create_app(Settings(data_dir=tmp_path/'runtime',weights_dir=tmp_path/'weights'),StyleModels(),s)
    with TestClient(app) as client:
        photo=upload(client)
        plan=client.post('/api/chat',json={'message':'Màu nước pastel','mode':'style','provider':'gemini'}).json()
        assert plan['provider']=='gemini' and plan['style_plan']['api_provider']=='gemini'
        assert plan['style_plan']['direct'] and plan['style_plan']['image_model']=='gemini-3.1-flash-lite-image'
        assert calls[0][1]['json']['generationConfig']['responseJsonSchema']['additionalProperties'] is False
        assert 'MODEL API' in calls[0][1]['json']['systemInstruction']['parts'][0]['text']
        s.select_provider(ChatProviderInput(provider='qwen'))  # the plan keeps the provider it was made with
        job=client.post('/api/stylize/from-chat',json={'photo_id':photo,'plan_id':plan['style_plan']['id']})
        done=wait_job(client,job.json()['job_id'])
        assert job.status_code==202 and done['status']=='done' and done['result']['profile']=='api' and done['result']['provider']=='Gemini'
        # Google's image model receives the photo itself and repaints it; no local VGG19 or style reference file.
        assert len(calls)==2 and 'gemini-3.1-flash-lite-image:generateContent' in calls[1][0]
        parts=calls[1][1]['json']['contents'][0]['parts']
        assert parts[0]['inlineData']['mimeType']=='image/jpeg' and 'Repaint this exact photo' in parts[1]['text']
        assert photo not in json.dumps(calls) and KEY not in json.dumps([c[1]['json'] for c in calls])
        assert not list((tmp_path/'runtime/styles').iterdir())

def test_invalid_google_recipe_rejected_and_no_key_written_to_disk(tmp_path):
    s=ChatService(api_key='',post=lambda *a,**k:response('{"engine":"shell"}'))
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime',weights_dir=tmp_path/'weights'),StyleModels(),s)) as c:
        saved=c.post('/api/chat/gemini/config',json={'api_key':KEY});assert saved.status_code==200 and KEY not in saved.text
        assert c.post('/api/chat',json={'message':'Mosaic','mode':'style','provider':'gemini'}).status_code==502
        for data in [{'api_key':KEY,'model':'https://evil.example'},{'api_key':KEY+'\r\ninject'},{'api_key':KEY,'extra_url':'http://evil'}]:
            r=c.post('/api/chat/gemini/config',json=data);assert r.status_code==422 and KEY not in r.text
        assert c.post('/api/chat/provider',json={'provider':'other'}).status_code==422
        assert c.post('/api/chat/gemini/config',json={'api_key':KEY},headers={'Origin':'https://evil.example'}).status_code==403
        assert not any(KEY.encode() in p.read_bytes() for p in tmp_path.rglob('*') if p.is_file())
        assert c.delete('/api/chat/gemini/config').json()['selection']=='qwen'

@pytest.mark.parametrize('name',['vangot','van got','Van Gogh','vangogh','Van-Gogh','VANGOG'])
def test_van_gogh_aliases_use_real_local_reference_without_api(name):
    assert is_style_request('phong cách tranh của '+name)
    recipe=local_recipe('phong cách '+name+' 60%')
    assert recipe.engine=='artwork' and recipe.reference_prompt=='met:436535' and recipe.strength==.6
    assert 'không cần API' in recipe.reply

def test_curated_reference_preserved_and_recipe_recorded(tmp_path,monkeypatch):
    from PIL import Image
    monkeypatch.setattr('fsmart.artworks.reference',lambda settings:Image.new('RGB',(32,32),'orange'))
    s=ChatService(api_key='',post=lambda *a,**k:pytest.fail('Van Gogh must run offline'))
    with TestClient(create_app(Settings(data_dir=tmp_path/'runtime',weights_dir=tmp_path/'weights'),StyleModels(),s)) as c:
        photo=upload(c);source=c.get(f'/api/photos/{photo}/image').content
        plan=c.post('/api/chat',json={'message':'phong cách tranh của vangot','mode':'style'}).json()['style_plan']
        assert plan['engine']=='artwork' and not plan['requires_api_key'] and plan['source_url'].startswith('https://www.metmuseum.org/')
        assert c.get(plan['reference_image_url']).status_code==200
        job=c.post('/api/stylize/from-chat',json={'photo_id':photo,'plan_id':plan['id']})
        done=wait_job(c,job.json()['job_id']);assert done['status']=='done'
        assert c.get(f'/api/photos/{photo}/image').content==source
        recipe=json.loads(c.app.state.store.one('SELECT metadata FROM output_assets WHERE output_id=?',(done['result']['output_id'],))['metadata'])
        assert recipe['reference']['id']=='met:436535' and recipe['strength']==.65
        assert not list((tmp_path/'runtime/styles').iterdir())
        follow=c.post('/api/chat',json={'message':'nhạt hơn','mode':'style','history':[{'role':'user','content':'vangot'}]}).json()
        assert follow['style_plan']['engine']=='artwork' and follow['style_plan']['strength']==.5
    with pytest.raises(ValueError):StyleRecipe(engine='artwork',preset='candy',strength=.6,steps=50,title='Bad',reply='Bad',reference_prompt='../../outside')


def test_transient_gemini_errors_are_retried(monkeypatch):
    import fsmart.gemini as gemini
    monkeypatch.setattr(gemini,'RETRY_DELAYS',(0,0))
    replies=[response(status=503),response(status=500),response('Xin chào')]
    calls=[]
    def post(*a,**k):calls.append(a[0]);return replies.pop(0)
    assert gemini.generate(post,KEY,'gemini-3.8-flash','sys','hi',[])=='Xin chào' and len(calls)==3


@pytest.mark.parametrize('status,needle',[(503,'quá tải (mã 503)'),(504,'mã 504')])
def test_persistent_gemini_overload_names_the_status(monkeypatch,status,needle):
    import fsmart.gemini as gemini
    monkeypatch.setattr(gemini,'RETRY_DELAYS',(0,0))
    calls=[]
    def post(*a,**k):calls.append(1);return response(status=status)
    with pytest.raises(ChatUnavailable) as caught:gemini.generate(post,KEY,'gemini-3.8-flash','sys','hi',[])
    assert needle in str(caught.value) and caught.value.status_code==502 and len(calls)==3 and KEY not in str(caught.value)


def test_client_errors_are_not_retried(monkeypatch):
    import fsmart.gemini as gemini
    monkeypatch.setattr(gemini,'RETRY_DELAYS',(0,0))
    calls=[]
    def post(*a,**k):calls.append(1);return response(status=400)
    with pytest.raises(ChatUnavailable):gemini.generate(post,KEY,'gemini-3.8-flash','sys','hi',[])
    assert len(calls)==1


def test_free_tier_image_quota_and_timeouts_get_precise_messages(monkeypatch):
    import fsmart.gemini as gemini
    from PIL import Image
    quota={'error':{'code':429,'status':'RESOURCE_EXHAUSTED','message':f'Quota exceeded for metric generate_content_free_tier_requests, limit: 0, model: gemini-3.1-flash-lite-image {KEY}'}}
    with pytest.raises(ChatUnavailable) as caught:
        gemini.edit_image(lambda *a,**k:response(data=quota,status=429),KEY,'gemini-3.1-flash-lite-image',Image.new('RGB',(8,8)),'paint')
    assert 'không có hạn mức miễn phí' in str(caught.value) and 'gpt-image-2' in str(caught.value) and KEY not in str(caught.value)
    busy={'error':{'code':429,'status':'RESOURCE_EXHAUSTED','message':'Resource exhausted','details':[{'@type':'type.googleapis.com/google.rpc.RetryInfo','retryDelay':'37s'}]}}
    with pytest.raises(ChatUnavailable) as caught:gemini.generate(lambda *a,**k:response(data=busy,status=429),KEY,'gemini-3.8-flash','sys','hi',[])
    assert 'chờ 37s' in str(caught.value) and caught.value.status_code==429
    def slow(*a,**k):raise requests.Timeout()
    with pytest.raises(ChatUnavailable) as caught:gemini.generate(slow,KEY,'gemini-3.8-flash','sys','hi',[])
    assert 'không phản hồi trong 60 giây' in str(caught.value) and caught.value.status_code==504


def test_short_google_rate_limit_is_waited_out(monkeypatch):
    import fsmart.gemini as gemini
    waits=[]
    monkeypatch.setattr(gemini.time,'sleep',waits.append)
    busy={'error':{'code':429,'status':'RESOURCE_EXHAUSTED','message':'Resource exhausted','details':[{'retryDelay':'3s'}]}}
    replies=[response(data=busy,status=429),response('ok')]
    assert gemini.generate(lambda *a,**k:replies.pop(0),KEY,'gemini-3.5-flash-lite','sys','hi',[])=='ok' and waits==[3.0]
