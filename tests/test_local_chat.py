import json
from types import SimpleNamespace
import pytest
from fsmart.chat import ChatService,ChatInput,ChatTurn,ChatUnavailable
from fsmart.local_chat import LocalChat,REPO,REVISION

class FakeLocal:
    def __init__(self,text='Mở bộ ảnh → Thùng rác → chọn ảnh → Khôi phục.'):self.text=text;self.calls=[]
    def installed(self):return True
    def generate(self,*args,**kwargs):self.calls.append((args,kwargs));return {'text':self.text,'seconds':.3}

def test_model_support_and_status_without_external_api():
    engine=FakeLocal();service=ChatService(api_key='',local_engine=engine,post=lambda *a,**k:pytest.fail('External API'))
    assert service.status()['provider']=='local-model' and service.status()['local_ready']
    assert not service.status()['configured']
    result=service.reply(ChatInput(message='Lỡ xóa ảnh rồi?'))
    assert result['provider']=='local-model' and result['model']=='Qwen3-1.7B' and engine.calls
    service.clear();assert service.status()['provider']=='local-model'

def test_model_recipes_validate_and_keep_unknown_styles_explicit():
    engine=FakeLocal(json.dumps({'preset':'rain_princess','strength':.6,'title':'Gam ấm','reply':'Thử cọ dày 60%.'}))
    service=ChatService(api_key='',local_engine=engine)
    result=service.reply(ChatInput(message='Gam ấm',mode='style'))
    assert result['provider']=='local-model' and result['style_plan']['strength']==.6
    engine.text='{"preset":"../../anything","strength":9}'
    bad=service.reply(ChatInput(message='Mosaic 70%',mode='style'))
    assert bad['provider']=='local' and bad['style_plan']['preset']=='mosaic'
    count=len(engine.calls)
    novel=service.reply(ChatInput(message='Màu nước pastel',mode='style'))
    assert novel['style_plan']['requires_api_key'] and len(engine.calls)==count+1
    assert novel['provider']=='local-model'

def test_local_transport_redacts_keys_bounds_history_and_never_uses_proxy(tmp_path):
    engine=LocalChat(tmp_path);engine.installed=lambda:True;engine._load=lambda:None
    assert not engine.http.trust_env
    engine.url='http://127.0.0.1:12345';captured={}
    def post(url,**kwargs):
        captured.update(url=url,**kwargs)
        return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'choices':[{'message':{'content':'Đã hiểu.'},'finish_reason':'stop'}]})
    engine.http.post=post
    engine.generate('System',[ChatTurn(role='user',content='old')]*7,'sk-'+('a'*28))
    assert captured['url'].startswith('http://127.0.0.1:') and not captured['allow_redirects']
    assert len(captured['json']['messages'])==6 and 'sk-' not in str(captured['json']['messages'])
    assert captured['json']['chat_template_kwargs']=={'enable_thinking':False}
    engine._busy.acquire()
    with pytest.raises(ChatUnavailable) as caught:engine.generate('System',[],'Hi')
    assert caught.value.status_code==429
    engine._busy.release()

def test_untrusted_manifest_fails_before_execution(tmp_path,monkeypatch):
    (tmp_path/'provenance.json').write_text(json.dumps({'repo':REPO,'revision':'untrusted','release':'b11669'}),'utf-8')
    engine=LocalChat(tmp_path)
    monkeypatch.setattr('subprocess.Popen',lambda *a,**k:pytest.fail('Unverified executable'))
    with pytest.raises(ValueError):engine._load()

@pytest.mark.parametrize('message,expected',[('Thêm nhãn ảnh và ghi chú thế nào?','Lưu thông tin'),('Chọn chủ thể thế nào?','Tách vùng chọn'),('Tôi lỡ xóa ảnh, có khôi phục được không?','Thùng rác')])
def test_vietnamese_guide_topics_do_not_confuse_diacritics(message,expected):
    service=ChatService(api_key='')
    assert expected in service.reply(ChatInput(message=message))['reply']
