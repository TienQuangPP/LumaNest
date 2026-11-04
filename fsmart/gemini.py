"""Gemini text input and reference image output; credentials stay in headers."""
import logging, re, time
import requests

DEFAULT_MODEL='gemini-3.5-flash-lite'
IMAGE_MODELS=('gemini-3.1-flash-lite-image','gemini-nano-banana-2.1','gemini-3.1-flash-image')
BASE_URL='https://generativelanguage.googleapis.com/v1beta/models/'
TRANSIENT={500,502,503,504}  # Google's "overloaded / try again" family
RETRY_DELAYS=(1.5,4.0)
log=logging.getLogger(__name__)


def normalize_key(value):
    """Unwrap a copied value or env assignment without changing the credential itself."""
    if not isinstance(value,str) or len(value)>8192:raise ValueError('Invalid credential input')
    text=value.strip().strip('\ufeff\u200b\u2060').strip()
    text=re.sub(r'^(?:(?:export|set)\s+|\$env:)?(?:GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*','',text,flags=re.IGNORECASE).strip()
    if len(text)>1 and (text[0],text[-1]) in [('"','"'),("'","'"),('`','`'),('“','”'),('‘','’')]:text=text[1:-1]
    return text.strip().strip('\ufeff\u200b\u2060').strip()

def generate(post,key,model,instructions,message,history,schema=None):
    from .chat import ChatUnavailable,redact
    if not key:raise ChatUnavailable('Chưa nhập Gemini API key. Mở Cài đặt trợ lý để kết nối hoặc chọn Qwen trên máy.',409)
    contents=[{'role':'model' if turn.role=='assistant' else 'user','parts':[{'text':redact(turn.content).replace(key,'[API key đã ẩn]')}]} for turn in history]
    contents.append({'role':'user','parts':[{'text':redact(message).replace(key,'[API key đã ẩn]')}]})
    config={'temperature':.6,'maxOutputTokens':2400}
    if schema is not None:config.update(responseMimeType='application/json',responseJsonSchema=schema)
    body={'systemInstruction':{'parts':[{'text':instructions}]},'contents':contents,'generationConfig':config}
    data=_request(post,key,model,body)
    try:
        candidate=data['candidates'][0]
        if candidate.get('finishReason')!='STOP':raise ValueError('Incomplete or blocked completion')
        text='\n'.join(part['text'] for part in candidate['content']['parts'] if isinstance(part.get('text'),str) and not part.get('thought')).strip()
        if not text:raise ValueError('Empty response')
        return redact(text).replace(key,'[API key đã ẩn]')[:7000]
    except (KeyError,IndexError,TypeError,AttributeError,ValueError):
        raise ChatUnavailable('Gemini chưa trả về câu trả lời đầy đủ hoặc đã chặn nội dung. Thử mô tả ngắn hơn.',502) from None


def _request(post,key,model,body,timeout=(5,60)):
    from .chat import ChatUnavailable
    if not key:raise ChatUnavailable('Chưa nhập Gemini API key. Mở Cài đặt trợ lý để kết nối hoặc chọn Qwen trên máy.',409)
    for attempt in range(len(RETRY_DELAYS)+1):
        try:
            response=post(BASE_URL+model+':generateContent',headers={'x-goog-api-key':key,'Content-Type':'application/json'},
                          json=body,timeout=timeout,allow_redirects=False)
        except requests.Timeout:
            log.warning('Gemini %s timed out after %ss',model,timeout[1])
            raise ChatUnavailable(f'Gemini không phản hồi trong {timeout[1]} giây (model {model} đang chậm hoặc quá tải). Thử lại sau hoặc chọn model khác.',504) from None
        except requests.RequestException as error:
            log.warning('Gemini %s connection failed: %s',model,type(error).__name__)
            raise ChatUnavailable('Không kết nối được Gemini. Kiểm tra Internet rồi thử lại.') from None
        if response.status_code not in TRANSIENT or attempt==len(RETRY_DELAYS):break
        log.warning('Gemini %s returned HTTP %s; retrying (%s/%s)',model,response.status_code,attempt+1,len(RETRY_DELAYS))
        time.sleep(RETRY_DELAYS[attempt])
    return _decode_response(response,key,model)


def _google_error(response,key=''):
    """Google's own error status, message and suggested retry delay, for the log and for picking a precise hint."""
    try:
        error=response.json().get('error',{})
        message=str(error.get('message',''))[:400]
        delay=next((d.get('retryDelay') for d in error.get('details',[]) if isinstance(d,dict) and d.get('retryDelay')),None)
        text=message.replace(key,'[key]') if key else message
        return str(error.get('status','')),text,delay
    except (ValueError,AttributeError,TypeError):
        return '','',None


def _decode_response(response,key='',model=''):
    from .chat import ChatUnavailable
    if response.status_code!=200:
        status,message,delay=_google_error(response,key)
        log.warning('Gemini %s returned HTTP %s %s: %s',model,response.status_code,status,message)
    if response.status_code in {401,403}:raise ChatUnavailable('Gemini từ chối key hoặc quyền truy cập. Kiểm tra key trong Google AI Studio.',502)
    if response.status_code==429:
        lowered=message.lower()
        if 'limit: 0' in lowered or 'free_tier' in lowered or 'billing' in lowered:
            raise ChatUnavailable(f'Tài khoản Google của bạn không có hạn mức miễn phí cho model {model or "này"} (mã 429). Model vẽ ảnh của Gemini cần bật thanh toán trong Google AI Studio; hoặc chọn nguồn VietAPI với model ảnh gpt-image-2.',429)
        wait=f' Google gợi ý chờ {delay}.' if delay else ''
        raise ChatUnavailable(f'Gemini báo hết lượt gọi cho model {model or "này"} (mã 429).{wait} Thử lại sau, đổi model khác, hoặc chọn nguồn khác.',429)
    if response.status_code in {400,404}:raise ChatUnavailable('Gemini không chấp nhận key hoặc model/cấu hình. Kiểm tra key, model và quyền truy cập của tài khoản.',502)
    if response.status_code==503:raise ChatUnavailable('Gemini đang quá tải (mã 503), đã tự thử lại 3 lần. Đợi một lát, đổi sang model Gemini khác trong Cài đặt trợ lý, hoặc chọn Qwen.',502)
    if response.status_code!=200:raise ChatUnavailable(f'Gemini chưa trả lời được (mã {response.status_code}), đã tự thử lại. Thử lại sau hoặc chọn Qwen.',502)
    try:
        data=response.json()
        if not isinstance(data,dict):raise ValueError('Invalid response')
        return data
    except (TypeError,ValueError):raise ChatUnavailable('Gemini trả dữ liệu chưa hợp lệ. Thử lại sau.',502) from None


def verify(get,key,model):
    """Authenticate a metadata request; never generate text/images or send chat history."""
    from .chat import ChatUnavailable
    if not key:raise ChatUnavailable('Chưa có key Gemini. Nhập key rồi bấm Lưu và kiểm tra.',409)
    try:
        response=get(BASE_URL+model,headers={'x-goog-api-key':key},timeout=(5,15),allow_redirects=False)
    except requests.RequestException:
        raise ChatUnavailable('Không kết nối được Google trong thời gian cho phép. Key vẫn ở trong RAM; kiểm tra Internet rồi thử lại.') from None
    data=_decode_response(response)
    methods=data.get('supportedGenerationMethods')
    if not isinstance(data.get('name'),str) or not data['name'].startswith('models/gemini-') or not isinstance(methods,list) or 'generateContent' not in methods:
        raise ChatUnavailable('Model này chưa hỗ trợ cách gọi chat của ứng dụng. Chọn model Gemini khác rồi thử lại.',502)


def generate_image(post,key,model,prompt):
    import base64,binascii
    from .chat import ChatUnavailable,redact
    from .images import decode_image
    if model not in IMAGE_MODELS:raise ChatUnavailable('Model ảnh Gemini chưa được hỗ trợ.',422)
    body={'contents':[{'role':'user','parts':[{'text':'Create a square abstract STYLE REFERENCE texture: palette, material and brushwork only. No faces, people, text, logos or recognizable subjects. Style: '+redact(prompt).replace(key,'[API key đã ẩn]')}]}],
          'generationConfig':{'responseModalities':['IMAGE']}}
    data=_request(post,key,model,body,timeout=(5,150))
    try:
        candidate=data['candidates'][0]
        if candidate.get('finishReason')!='STOP':raise ValueError('Incomplete image')
        inline=next(part['inlineData'] for part in candidate['content']['parts'] if part.get('inlineData') and not part.get('thought'))
        if inline['mimeType'] not in {'image/png','image/jpeg','image/webp'}:raise ValueError('Unexpected image type')
        encoded=inline['data']
        if not isinstance(encoded,str) or len(encoded)>16*1024*1024:raise ValueError('Oversized image')
        return decode_image(base64.b64decode(encoded,validate=True),4_194_304)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,StopIteration,binascii.Error):
        raise ChatUnavailable('Gemini chưa trả về ảnh phong cách hợp lệ. Thử lại sau.',502) from None


def edit_image(post,key,model,image,prompt):
    """Send one photo and an edit instruction to a Gemini image model; returns the repainted PIL image."""
    import base64,binascii,io
    from .chat import ChatUnavailable,redact
    from .images import decode_image
    if model not in IMAGE_MODELS:raise ChatUnavailable('Model ảnh Gemini chưa được hỗ trợ.',422)
    buffer=io.BytesIO();image.save(buffer,'JPEG',quality=92)
    body={'contents':[{'role':'user','parts':[{'inlineData':{'mimeType':'image/jpeg','data':base64.b64encode(buffer.getvalue()).decode()}},
                                              {'text':redact(prompt).replace(key,'[API key đã ẩn]')}]}],
          'generationConfig':{'responseModalities':['IMAGE']}}
    data=_request(post,key,model,body,timeout=(5,180))
    try:
        candidate=data['candidates'][0]
        if candidate.get('finishReason')!='STOP':raise ValueError('Incomplete image')
        inline=next(part['inlineData'] for part in candidate['content']['parts'] if part.get('inlineData') and not part.get('thought'))
        if inline['mimeType'] not in {'image/png','image/jpeg','image/webp'}:raise ValueError('Unexpected image type')
        encoded=inline['data']
        if not isinstance(encoded,str) or len(encoded)>24*1024*1024:raise ValueError('Oversized image')
        return decode_image(base64.b64decode(encoded,validate=True),16_777_216)
    except (ValueError,TypeError,KeyError,IndexError,AttributeError,StopIteration,binascii.Error):
        raise ChatUnavailable('Gemini chưa trả về ảnh đã vẽ lại (có thể bị chặn vì có người trong ảnh hoặc hết hạn mức). Thử ảnh khác hoặc model ảnh khác.',502) from None
