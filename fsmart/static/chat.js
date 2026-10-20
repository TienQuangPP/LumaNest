/* No credentials or conversation text in localStorage. GPT receives text only. */
(() => {
  const chat = {history: [], status: null, pending: false, opening: 0, mode: 'support', lastStylePrompt: ''};
  const suggestions = ['Nên chọn phong cách nào?', 'Tìm ảnh có mặt tôi thế nào?', 'App có dùng GPT để tạo ảnh không?'];
  const styleSuggestions = ['Màu ấm, nét cọ dày, giữ ảnh gốc khá rõ', 'Tranh ghép Mosaic, đậm 70%', 'Màu nước pastel xanh nhạt'];
  const welcome = 'Chào bạn! Mình giúp bạn tìm ảnh, chọn phong cách và dùng LumaNest. Bạn muốn bắt đầu từ đâu?';

  function normalizeGeminiKey(value) {
    let text=value.trim().replace(/^[\uFEFF\u200B\u2060]+|[\uFEFF\u200B\u2060]+$/g,'').trim();
    text=text.replace(/^(?:(?:export|set)\s+|\$env:)?(?:GEMINI_API_KEY|GOOGLE_API_KEY)\s*=\s*/i,'').trim();
    if(text.length>1&&['""',"''",'``','“”','‘’'].includes(text[0]+text.at(-1)))text=text.slice(1,-1);
    return text.trim().replace(/^[\uFEFF\u200B\u2060]+|[\uFEFF\u200B\u2060]+$/g,'').trim();
  }

  function scrollChat() {
    $('chat-messages').scrollTop = $('chat-messages').scrollHeight;
  }

  function message(role, text, label, extra = '') {
    const row = el('div', `chat-message ${role} ${extra}`);
    row.append(el('span', 'chat-message-label', label), el('div', 'chat-bubble', text));
    $('chat-messages').append(row);
    scrollChat();
    return row;
  }

  function renderStatus(status) {
    chat.status = status;
    const gpt = status.provider === 'openai';
    const localModel = status.provider === 'local-model';
    const gemini=status.provider==='gemini',selection=status.selection||(gpt?'openai':gemini?'gemini':'qwen');
    if(selection==='openai'&&!$('chat-source').querySelector('[value="openai"]')){const option=el('option','','OpenAI · đã cấu hình');option.value='openai';$('chat-source').append(option);}
    $('chat-source').value=selection;
    $('chat-provider').textContent = gpt ? `GPT · ${status.model}` : gemini ? `${status.model}${status.configured?'':' · cần key'}` : localModel ? status.model : 'Hướng dẫn có sẵn';
    $('chat-privacy').textContent = gpt
      ? 'Văn bản chat được gửi tới OpenAI. Ảnh không được gửi.'
      : gemini ? 'Gemini nhận văn bản chat qua Google · ảnh nguồn không được gửi.' : localModel ? 'Qwen chạy trên máy · không gửi hội thoại hay ảnh ra ngoài.' : 'Hướng dẫn có sẵn · không gửi dữ liệu ra ngoài.';
    $('chat-config-status').textContent = gpt
      ? `Đã cấu hình ${status.model}${status.key_source === 'environment' ? ' từ biến môi trường' : ' cho phiên chạy này'}. Key sẽ được kiểm tra khi gửi câu hỏi.`
      : localModel ? 'Chatbot Qwen sẵn sàng. Lượt đầu cần nạp model; có thể mất vài chục giây.' : 'Chưa bật GPT. Bạn vẫn dùng được phần hướng dẫn có sẵn.';
    $('chat-model').value = status.api_model || status.model;
    $('chat-image-model').value = status.image_model || 'gpt-image-1.5';
    $('chat-clear-key').disabled = chat.pending||!status.image_configured;
    for(const [id,value] of [['gemini-model',status.gemini_model],['gemini-image-model',status.gemini_image_model]])if(value){if(![...$(id).options].some(option=>option.value===value)){const option=el('option','',value);option.value=value;$(id).append(option);}$(id).value=value;}
    $('gemini-clear-key').disabled=chat.pending||!status.gemini_configured;
    $('gemini-config-status').textContent=status.gemini_verified?'Đã kết nối model chat Gemini. Hạn mức tạo ảnh được kiểm tra riêng khi tạo.':status.gemini_configured?'Đã lưu key trong RAM. Bấm Lưu và kiểm tra để thử kết nối.':'Nhập key rồi bấm Lưu và kiểm tra. Qwen dùng được ngay trên máy.';
    $('gemini-config-status').classList.remove('config-error');
  }

  async function refreshStatus() {
    renderStatus(await api('/api/chat/status'));
  }

  function resetChat() {
    if (chat.pending) return;
    chat.history = [];
    $('chat-messages').replaceChildren();
    chat.lastStylePrompt = '';
    message('assistant', chat.mode === 'style' ? 'Mô tả màu sắc, nét cọ hoặc chất liệu bạn muốn. Mình sẽ đưa đề xuất để bạn chọn ảnh và tạo tác phẩm. Ví dụ: “gam ấm, nét cọ dày, đậm 65%”.' : welcome, 'Trợ lý LumaNest');
    renderSuggestions(chat.mode === 'style' ? styleSuggestions : suggestions);
  }

  function renderSuggestions(items) {
    $('chat-suggestions').replaceChildren();
    for (const text of items) {
      const chip = el('button', 'chat-suggestion', text);
      chip.type = 'button';
      chip.disabled = chat.pending;
      chip.onclick = () => { $('chat-input').value = text; $('chat-form').requestSubmit(); };
      $('chat-suggestions').append(chip);
    }
  }

  function setPending(value) {
    chat.pending = value;
    $('chat-send').disabled = value;
    $('chat-new').disabled = value;
    $('chat-mode-support').disabled = value;
    $('chat-mode-style').disabled = value;
    $('chat-save-key').disabled = value;
    $('chat-clear-key').disabled = value || !chat.status?.image_configured;
    $('chat-source').disabled=value;$('gemini-save-key').disabled=value;$('gemini-clear-key').disabled=value||!chat.status?.gemini_configured;
    for(const id of ['gemini-key','gemini-model','gemini-image-model','chat-settings-done'])$(id).disabled=value;
    $('gemini-key-form').setAttribute('aria-busy',String(value));
    $('chat-form').setAttribute('aria-busy', String(value));
    $('chat-suggestions').querySelectorAll('button').forEach(button => button.disabled = value);
    $('chat-messages').querySelectorAll('.chat-plan-create,.chat-plan-photo').forEach(control => control.disabled = value);
  }

  function setMode(mode, internalUpdate = false) {
    if (chat.pending && !internalUpdate) return;
    chat.mode = mode;
    $('chat-mode-support').setAttribute('aria-pressed', String(mode === 'support'));
    $('chat-mode-style').setAttribute('aria-pressed', String(mode === 'style'));
    $('chat-input').placeholder = mode === 'style' ? 'Màu ấm, nét cọ dày, đậm 65%…' : 'Hỏi cách chọn style, tìm ảnh…';
    if (chat.status) renderStatus(chat.status);
    renderSuggestions(mode === 'style' ? styleSuggestions : suggestions);
    $('chat-input').focus();
  }

  function openSettings() {
    $('chat-settings').classList.remove('hidden');
    $('chat-panel').classList.add('settings-open');
    $('chat-settings-toggle').setAttribute('aria-expanded', 'true');
    if(chat.status?.selection==='openai'){$('openai-settings').open=true;$('chat-key').focus();}else $('gemini-key').focus();
  }

  function attachStylePlan(row, plan) {
    const card = el('div', 'chat-style-plan');
    card.append(el('small', 'chat-plan-eyebrow', 'ĐỀ XUẤT PHONG CÁCH'), el('strong', '', plan.title));
    const preset = state.styles.find(style => style.id === plan.preset)?.name || plan.preset;
    const route = plan.engine === 'reference' ? `${plan.api_provider==='gemini'?'Gemini':'OpenAI'} tạo ảnh tham chiếu → VGG19 · ${plan.steps} bước` : plan.engine==='artwork' ? `Tranh có sẵn → VGG19 · ${plan.steps} bước · trên máy` : `${preset} · chạy NST trên máy`;
    card.append(el('p', '', `${route}\nĐộ đậm ${Math.round(plan.strength*100)}%`));
    if (plan.engine === 'reference') card.append(el('p', 'chat-plan-cost', 'Dùng hạn mức API ảnh khi bấm tạo. Chỉ gửi mô tả; ảnh gốc ở trên máy.'));
    if(plan.engine==='artwork'){const image=el('img','chat-reference');image.src=plan.reference_image_url;image.alt='Tranh tham chiếu Van Gogh';card.append(image);const source=el('a','text-button','Tranh public domain · The Met ↗');source.href=plan.source_url;source.target='_blank';source.rel='noopener noreferrer';card.append(source);}
    const label = el('label', '', 'Ảnh để tạo tác phẩm');
    const select = el('select', 'chat-plan-photo');
    select.id = `chat-photo-${plan.id}`;
    label.htmlFor = select.id;
    const photos = [...new Map([state.selected, ...state.photos].filter(Boolean).map(photo => [photo.id, photo])).values()];
    const placeholder = el('option', '', 'Chọn ảnh trong album…');
    placeholder.value = '';
    select.append(placeholder);
    for (const photo of photos) {
      const option = el('option', '', photo.name);
      option.value = photo.id;
      select.append(option);
    }
    select.value = state.selected?.id || '';
    const imageKeyReady=()=>plan.api_provider==='gemini'?!!chat.status?.gemini_configured:!!chat.status?.image_configured;
    const button = el('button', 'button primary chat-plan-create', plan.requires_api_key && !imageKeyReady() ? `Kết nối ${plan.api_provider==='gemini'?'Gemini':'API ảnh'} để tạo mới` : 'Tạo ảnh theo mô tả');
    button.type = 'button';
    const status = el('p', 'chat-plan-status');
    status.setAttribute('role', 'status');
    button.onclick = async () => {
      if (chat.pending) return;
      if (plan.requires_api_key && !imageKeyReady()) { openSettings();if(plan.api_provider!=='gemini'){$('openai-settings').open=true;$('chat-key').focus();}return; }
      const photo = findPhotoById(select.value);
      if (!photo) { status.textContent = 'Chọn một ảnh trong danh sách trước. Nếu chưa có ảnh, thêm ảnh vào Thư viện.'; return; }
      setPending(true);
      status.textContent = plan.engine === 'reference' ? 'Đang tạo ảnh phong cách rồi chuyển style. Có thể mất vài phút.' : 'Đang tạo tác phẩm bằng model NST…';
      try {
        const result = await createFromStyleRecipe(plan, photo);
        status.textContent = 'Đã tạo xong. Xem trước/sau trong Phòng sáng tạo.';
        const preview = el('img', 'chat-plan-output');
        preview.alt = plan.title;
        preview.src = result.image_url;
        const download = el('a', 'chat-plan-download', '↓ Tải ảnh tác phẩm');
        download.href = result.download_url;
        download.download = '';
        card.append(preview, download);
        scrollChat();
      } catch (error) {
        status.textContent = error.message;
      } finally { setPending(false); }
    };
    card.append(label, select, button, status);
    if(plan.engine==='reference'){
      const upload=el('button','button outline chat-plan-upload','Tải ảnh phong cách · dùng trên máy');upload.type='button';upload.onclick=()=>{if(chat.pending)return;const photo=findPhotoById(select.value);if(photo)selectPhoto(photo);else navigate('studio');clearStyleRecipe();state.style='custom';document.querySelectorAll('.style-option').forEach(node=>node.classList.toggle('selected',node.dataset.style==='custom'));$('custom-style').classList.remove('hidden');document.dispatchEvent(new CustomEvent('fsm:style-picked'));setOpen(false);$('style-file').focus();$('style-file').scrollIntoView({block:'center'});};card.append(upload);
    }
    row.append(card);
    mountPhotoPicker(select);
    scrollChat();
  }

  async function setOpen(open) {
    const opening = ++chat.opening;
    $('chat-panel').classList.toggle('hidden', !open);
    document.body.classList.toggle('chat-open', open);
    $('chat-launcher').setAttribute('aria-expanded', String(open));
    if (!open) { $('chat-key').value = '';$('gemini-key').value=''; $('chat-launcher').focus(); return; }
    $('chat-input').focus();
    scrollChat();
    try { await refreshStatus(); }
    catch {
      if (opening === chat.opening) {
        $('chat-provider').textContent = 'Chưa kết nối được trợ lý';
        $('chat-privacy').textContent = 'Kiểm tra server đang chạy rồi mở lại trợ lý.';
      }
    }
  }

  $('chat-launcher').onclick = () => setOpen($('chat-panel').classList.contains('hidden'));
  $('chat-close').onclick = () => setOpen(false);
  $('chat-panel').addEventListener('keydown', event => {
    if (event.key === 'Escape') { event.stopPropagation(); setOpen(false); }
  });
  $('chat-settings-toggle').onclick = () => {
    const open = $('chat-settings').classList.contains('hidden');
    $('chat-settings').classList.toggle('hidden', !open);
    $('chat-panel').classList.toggle('settings-open', open);
    $('chat-settings-toggle').setAttribute('aria-expanded', String(open));
    if (open) {if(chat.status?.selection==='openai'){$('openai-settings').open=true;$('chat-key').focus();}else $('gemini-key').focus();}
    else { $('chat-key').value = '';$('gemini-key').value='';}
  };
  $('chat-new').onclick = resetChat;
  $('chat-mode-support').onclick = () => setMode('support');
  $('chat-mode-style').onclick = () => setMode('style');
  document.addEventListener('fsm:describe-style', () => {setMode('style'); setOpen(true);});
  $('chat-open-studio').onclick = () => { navigate('studio'); setOpen(false); };
  $('chat-input').addEventListener('keydown', event => {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!chat.pending) $('chat-form').requestSubmit();
    }
  });

  $('chat-form').onsubmit = async event => {
    event.preventDefault();
    const text = $('chat-input').value.trim();
    if (!text || chat.pending) return;
    if(chat.status?.selection==='gemini'&&!chat.status.configured){openSettings();$('gemini-config-status').textContent='Nhập Gemini API key trước khi gửi, hoặc chọn Qwen trên máy.';return;}
    if (/sk-[A-Za-z0-9_-]{16,}|AIza[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9._~+/=-]{16,}/.test(text)) {
      message('assistant', 'Bạn vừa nhập nội dung giống API key. Hãy dùng Cài đặt trợ lý, không gửi key trong hội thoại. Tin nhắn này chưa được gửi.', 'Bảo vệ API key', 'error');
      $('chat-input').value = '';
      return;
    }
    setPending(true);
    if (chat.mode === 'style') chat.lastStylePrompt = text;
    message('user', text, 'Bạn');
    $('chat-input').value = '';
    const pending = message('assistant', 'Đang trả lời…', 'Trợ lý LumaNest', 'pending');
    try {
      let history = chat.history.slice(-10);
      while (history.reduce((sum, turn) => sum + turn.content.length, 0) > 20000) history = history.slice(2);
      const result = await api('/api/chat', jsonRequest({message: text, history, page: state.page, style: state.style, mode: chat.mode, provider:chat.status?.selection||'qwen', strength: Number($('strength').value)}));
      pending.remove();
      const styleMode = result.mode === 'style' || chat.mode === 'style';
      if (styleMode) chat.lastStylePrompt = text;
      const row = message('assistant', result.reply, result.provider === 'openai' ? `GPT · ${result.model}` : result.provider==='gemini'?`Gemini · ${result.model}` : result.provider === 'local-model' ? `${result.model} · trên máy${result.seconds ? ' · '+result.seconds+'s' : ''}` : result.style_plan?.engine==='artwork'?'Tranh tham chiếu có sẵn' : styleMode ? 'Gợi ý có sẵn' : 'Hướng dẫn có sẵn');
      if (result.style_plan) attachStylePlan(row, result.style_plan);
      const summary = result.style_plan ? `\nĐề xuất: ${result.style_plan.title}; engine=${result.style_plan.engine}; preset=${result.style_plan.preset}; strength=${result.style_plan.strength}; steps=${result.style_plan.steps}.` : '';
      chat.history.push({role: 'user', content: text}, {role: 'assistant', content: result.reply + summary});
      chat.history = chat.history.slice(-10);
      renderSuggestions(result.suggestions || (chat.mode === 'style' ? styleSuggestions : suggestions));
      if (result.mode === 'style' && chat.mode !== 'style') {
        setMode('style', true);
      }
    } catch (error) {
      pending.remove();
      message('assistant', error.message, 'Chưa gửi được', 'error');
      $('chat-input').value = text;
    } finally {
      setPending(false);
      if (!$('chat-panel').classList.contains('hidden')) $('chat-input').focus();
    }
  };

  $('chat-key-form').onsubmit = async event => {
    event.preventDefault();
    if (chat.pending) return;
    $('chat-save-key').disabled = true;
    try {
      const result = await api('/api/chat/config', jsonRequest({api_key: $('chat-key').value.trim(), model: $('chat-model').value.trim(), image_model: $('chat-image-model').value}));
      $('chat-key').value = '';
      const draft = chat.mode === 'style' ? chat.lastStylePrompt : '';
      resetChat();
      renderStatus(result);
      $('chat-settings').classList.add('hidden');
      $('chat-panel').classList.remove('settings-open');
      $('chat-settings-toggle').setAttribute('aria-expanded', 'false');
      message('assistant', 'Đã cấu hình GPT. Từ câu hỏi tiếp theo, văn bản hội thoại sẽ được gửi tới OpenAI; ảnh trong thư viện không được gửi. Key sẽ được kiểm tra ở lần gọi đầu tiên.', 'Cài đặt GPT');
      if (draft) {$('chat-input').value = draft; chat.lastStylePrompt = draft;}
      $('chat-input').focus();
    } catch (error) {
      $('chat-key').value = '';
      $('chat-config-status').textContent = error.message;
    } finally { $('chat-save-key').disabled = false; }
  };

  $('chat-clear-key').onclick = async () => {
    if (chat.pending) return;
    $('chat-clear-key').disabled = true;
    try {
      renderStatus(await api('/api/chat/config', {method: 'DELETE'}));
      $('chat-key').value = '';
      resetChat();
    } catch (error) {
      $('chat-config-status').textContent = error.message;
      $('chat-clear-key').disabled = false;
    }
  };

  $('chat-source').onchange=async()=>{
    if(chat.pending)return;const source=$('chat-source').value;let result;setPending(true);
    try{result=await api('/api/chat/provider',jsonRequest({provider:source}));}
    catch(error){$('chat-source').value=chat.status?.selection||'qwen';message('assistant',error.message,'Chưa đổi được','error');}
    finally{setPending(false);}
    if(result){resetChat();renderStatus(result);$('chat-key').value='';$('gemini-key').value='';if(source==='gemini'&&!result.configured)openSettings();else{$('chat-settings').classList.add('hidden');$('chat-panel').classList.remove('settings-open');$('chat-settings-toggle').setAttribute('aria-expanded','false');}}
  };
  $('gemini-key-form').onsubmit=async event=>{
    event.preventDefault();if(chat.pending)return;
    const key=normalizeGeminiKey($('gemini-key').value),model=$('gemini-model').value,imageModel=$('gemini-image-model').value;
    const report=text=>{$('gemini-config-status').textContent=text;$('gemini-config-status').classList.add('config-error');};
    if(key&&!/^[A-Za-z0-9._~+/=-]{20,4096}$/.test(key)){report('Key có khoảng trắng ở giữa hoặc ký tự không hợp lệ. App hỗ trợ cả AIza… và AQ.…; dán nguyên key từ Google AI Studio.');$('gemini-key').focus();return;}
    if(!key&&!chat.status?.gemini_configured){report('Bạn chưa nhập Gemini API key. Dán key vào ô phía trên rồi bấm Lưu và kiểm tra.');$('gemini-key').focus();return;}
    if(!key&&(model!==chat.status.gemini_model||imageModel!==chat.status.gemini_image_model)){report('Bạn vừa đổi model. Nhập lại key để lưu cấu hình mới.');$('gemini-key').focus();return;}
    setPending(true);$('gemini-save-key').textContent='Đang kiểm tra…';$('gemini-config-status').textContent='Đang kiểm tra kết nối với Google. Không tạo ảnh hoặc gửi hội thoại.';$('gemini-config-status').classList.remove('config-error');let result;
    try{
      if(key){const saved=await api('/api/chat/gemini/config',jsonRequest({api_key:key,model,image_model:imageModel}));renderStatus(saved);}
      $('gemini-key').value='';$('gemini-config-status').textContent='Đã lưu key trong RAM. Đang kiểm tra kết nối Google…';
      result=await api('/api/chat/gemini/check',{method:'POST',signal:AbortSignal.timeout(22000)});
    }catch(error){report(error.name==='TimeoutError'?'Kiểm tra quá thời gian chờ. Key đã lưu trong RAM; bấm lại để thử kết nối.':error.message==='Not Found'?'Server chưa nạp bản cập nhật. Khởi động lại ứng dụng rồi nhập key trong ô này.':error.message);}
    finally{$('gemini-key').value='';setPending(false);$('gemini-save-key').textContent='Lưu và kiểm tra';}
    if(result){resetChat();renderStatus(result);$('chat-settings').classList.add('hidden');$('chat-panel').classList.remove('settings-open');$('chat-settings-toggle').setAttribute('aria-expanded','false');message('assistant','Đã kết nối model chat Gemini. Nhập câu hỏi hoặc mô tả phong cách rồi bấm ↑ để bắt đầu. Tạo ảnh là thao tác riêng sau khi chọn ảnh.','Kết nối thành công');$('chat-input').focus();}
  };
  $('gemini-key').addEventListener('input',()=>{if(chat.pending)return;$('gemini-config-status').classList.remove('config-error');$('gemini-config-status').textContent='Bấm Lưu và kiểm tra, hoặc nhấn Enter để kết nối Gemini.';});
  $('chat-settings-done').onclick=()=>{if(chat.pending)return;$('gemini-key').value='';$('chat-key').value='';$('chat-settings').classList.add('hidden');$('chat-panel').classList.remove('settings-open');$('chat-settings-toggle').setAttribute('aria-expanded','false');$('chat-input').focus();};
  $('gemini-clear-key').onclick=async()=>{if(chat.pending)return;setPending(true);let result;try{result=await api('/api/chat/gemini/config',{method:'DELETE'});}catch(error){$('gemini-config-status').textContent=error.message;}finally{setPending(false);}if(result){resetChat();renderStatus(result);$('gemini-key').value='';}};
  resetChat();
})();
