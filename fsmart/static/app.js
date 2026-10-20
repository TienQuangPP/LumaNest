'use strict';
const $ = id => document.getElementById(id);
const state = {albums: [], album: localStorage.getItem('fsm-album'), photos: [], extraPhotos:new Map(),query: null, face: 0, results: [], selected: null, selectedIds:new Set(),trashSelectedIds:new Set(), style: 'mosaic', styles: [], page: 'collections', total: 0};
let albumSelectionVersion=0,photosRequestVersion=0,albumsRequestVersion=0,navigationVersion=0;
let toastTimer, reconnectTimer;
let connectionFailed = false;
function toast(message, error = false) { $('toast').textContent = message; $('toast').className = `toast${error ? ' error' : ''}`; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.add('hidden'), 6500); }
async function api(url, options = {}) { const response = await fetch(url, options); if (!response.ok) { let data; try {data = await response.json();} catch {data = {};} const detail = Array.isArray(data.detail) ? data.detail.map(x => x.msg).join('; ') : data.detail; throw new Error(detail || `Yêu cầu thất bại (${response.status})`); } return response.json(); }
function jsonRequest(body) { return {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}; }
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function updateCollectionContext(){
  const album=currentAlbum();
  $('collection-title').textContent=album?.name || 'Bộ ảnh';
  $('collection-meta').textContent=album?`${album.photo_count} ảnh · ${album.indexed_count} ảnh đã xử lý`:'';
  $('search-collection-label').textContent=album?.name || '';
  const names={library:'Ảnh',search:'Tìm khuôn mặt',studio:'Sáng tạo',trash:'Thùng rác'};
  const label=names[state.page]&&album?`Thư viện ảnh / ${album.name} / ${names[state.page]}`:state.page==='system'?'Hệ thống':'Thư viện ảnh';
  $('breadcrumb').textContent=label;
}
function navigate(page){
  ++navigationVersion;
  if(!['collections','library','search','studio','trash','system'].includes(page))page='collections';
  if(['library','search','studio','trash'].includes(page)&&!currentAlbum())page='collections';
  state.page=page;localStorage.setItem('fsm-page',page);
  document.querySelectorAll('.page').forEach(node=>node.classList.toggle('active',node.id===`page-${page}`));
  $('collection-workspace').classList.toggle('hidden',!['library','search','studio','trash'].includes(page));
  document.querySelectorAll('.nav-item').forEach(node=>node.classList.toggle('active',node.dataset.page===(page==='system'?'system':'collections')));
  document.querySelectorAll('.collection-tabs [role="tab"]').forEach(node=>{const active=node.dataset.page===page;node.setAttribute('aria-selected',String(active));node.tabIndex=active?0:-1;});
  updateCollectionContext();window.scrollTo({top:0,behavior:'instant'});
  document.dispatchEvent(new CustomEvent('fsm:page',{detail:page}));
}
document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => navigate(button.dataset.page)));
async function busy(button, label, operation) { const old = button.textContent; button.disabled = true; button.textContent = label; try { return await operation(); } catch (error) {toast(error.message, true);} finally {button.disabled = button.id==='run-style' && (!state.selected||!!state.styleGenerating); button.textContent = old;} }
const jobViews=new Map();
function formatJobMessage(message){return message.replace(/^Đang tối ưu ảnh (\d+)\/(\d+)$/,'Bước tối ưu $1/$2 · 1 ảnh');}
function renderJobViews(){const views=[...jobViews.values()];$('job-panel').classList.toggle('hidden',!views.length);if(views.length){const view=views[views.length-1];$('job-message').textContent=`${views.length>1?views.length+' tác vụ · ':''}${formatJobMessage(view.message)}`;$('job-progress').value=view.progress;}}
async function watchJob(jobId){
  if(jobViews.has(jobId))return jobViews.get(jobId).promise;
  const view={message:'Đang chờ xử lý',progress:0,promise:null};jobViews.set(jobId,view);renderJobViews();
  view.promise=(async()=>{
    let disconnected=0;
    try{for(let i=0;i<2400;i++){
      let job;
      try{job=await api(`/api/jobs/${jobId}`);disconnected=0;}
      catch(error){if(++disconnected>12)throw new Error('Chưa kết nối lại được. Tiến độ vẫn lưu trên server; mở Hệ thống để kiểm tra.');view.message='Mất kết nối, đang thử lại…';renderJobViews();await new Promise(resolve=>setTimeout(resolve,2500));continue;}
      view.message=job.message;view.progress=job.progress;renderJobViews();
      if(job.status==='error')throw new Error(job.message);
      if(job.status==='done'||job.status==='cancelled')return job;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }throw new Error('Tác vụ vẫn đang chạy. Mở Hệ thống để theo dõi.');}
    finally{jobViews.delete(jobId);renderJobViews();}
  })();return view.promise;
}
async function refreshHealth() { const health = await api('/api/health'); if ($('runtime-hint')) $('runtime-hint').textContent = health.style_backend && health.style_backend !== 'chưa nạp' ? `Đang dùng ${health.style_backend}. Kích thước tính theo cạnh dài; VGG19 dùng 512 px và chạy chậm hơn.` : (health.openvino_installed ? 'Đã cài OpenVINO CPU · Lần đầu mỗi preset cần chuẩn bị model. VGG19 chạy chậm hơn.' : 'Preset chạy PyTorch. Cài requirements-cpu.txt để bật OpenVINO CPU.'); $('connection').className = `connection ${health.face_ready && health.presets_ready ? 'ready' : 'warning'}`; $('connection').replaceChildren(el('i'), document.createTextNode(health.face_ready && health.presets_ready ? 'Model sẵn sàng' : 'Cần tải trọng số')); $('threshold').value = health.threshold; $('threshold-value').textContent = Number(health.threshold).toFixed(2); $('calibration-note').textContent = health.threshold_calibrated ? 'Ngưỡng đã được hiệu chỉnh với model hiện tại.' : 'Ngưỡng thử nghiệm. Điểm tương đồng không phải xác suất nhận diện.'; }
function currentAlbum() {return state.albums.find(x => x.id === state.album);}
async function refreshAlbums(){
  const version=++albumsRequestVersion,albums=await api('/api/albums');if(version!==albumsRequestVersion)return;
  state.albums=albums;if(!albums.some(album=>album.id===state.album))state.album=albums[0]?.id || null;
  $('album-list').replaceChildren();$('collection-switcher').replaceChildren();
  for(const album of albums){
    const button=el('button',`album-item${album.id===state.album?' active':''}`);
    button.append(el('span','',`▧ ${album.name}`),el('small','',album.photo_count));
    button.onclick=()=>chooseAlbum(album.id).catch(error=>toast(error.message,true));$('album-list').append(button);
    const option=el('option','',album.name);option.value=album.id;$('collection-switcher').append(option);
  }
  $('collection-switcher').value=state.album || '';localStorage.setItem('fsm-album',state.album || '');
  renderCollections();updateCollectionContext();
}
async function chooseAlbum(id,tab='library'){
  const version=++albumSelectionVersion,navigationAtStart=navigationVersion;
  ++photosRequestVersion;++outputsRequestVersion;++trashRequestVersion;
  state.album=id;state.selected=null;state.photos=[];state.extraPhotos.clear();state.trashSelectedIds.clear();state.selectedIds.clear();updateSelection();resetStudio();
  for(const [select] of photoPickerBindings)select.value='';
  $('studio-photo').value='';syncPhotoPickers();$('gallery').replaceChildren();$('output-history').replaceChildren();$('batch-list').replaceChildren();$('trash-gallery').replaceChildren();
  ++faceSearchVersion;faceSearchController?.abort();clearTimeout(faceSearchTimer);lastFaceSearchSignature='';showSearchState(state.query?'loading':'idle');
  document.dispatchEvent(new CustomEvent('fsm:collection',{detail:id}));
  await refreshAlbums();if(version!==albumSelectionVersion)return;
  if(navigationAtStart===navigationVersion)navigate(tab);
  await Promise.all([refreshPhotos(),refreshOutputs(),refreshBatches(),refreshTrash()]);
  if(version!==albumSelectionVersion)return;
  if(state.query)scheduleFaceSearch();else showSearchState('idle');
}
function photoCard(photo,mode='gallery'){
  const card=el('article','photo-card');card.dataset.photo=photo.id;
  const button=el('button','image-button');button.setAttribute('aria-label',`Chọn ảnh ${photo.name}`);
  const image=el('img');image.src=`/api/photos/${photo.id}/image?thumbnail=true`;image.alt=photo.name;image.loading='lazy';button.append(image);button.onclick=()=>selectPhoto(photo);
  if(mode==='result')button.append(el('span','photo-badge',`Tương đồng ${photo.similarity.toFixed(3)}`));
  const info=el('div','photo-info');info.append(el('p','',photo.name));
  if(mode==='gallery'){
    const status=photo.status==='ready'?`${photo.face_count} khuôn mặt`:photo.status==='error'?'Lỗi xử lý':'Đang xử lý';
    const small=el('small',photo.status==='error'?'photo-error':'',status);if(photo.error)small.title=photo.error;info.append(small);
    const remove=el('button','delete-photo','⌫');remove.setAttribute('aria-label',`Xóa ảnh ${photo.name}`);remove.title='Chuyển ảnh vào thùng rác';remove.disabled=photo.status==='queued';remove.onclick=()=>requestTrash([photo.id]);info.append(remove);
  }else info.append(el('small','','Sáng tạo ↗'));
  card.append(button,info);return card;
}
async function refreshPhotos(append=false){
  const album=currentAlbum(),version=++photosRequestVersion;
  $('album-title').textContent='Ảnh trong bộ';$('album-meta').textContent=album?`${album.photo_count} ảnh · ${album.indexed_count} ảnh đã xử lý`:'Tạo bộ ảnh đầu tiên để bắt đầu.';
  if(!album){state.photos=[];$('gallery').replaceChildren();$('gallery-empty').classList.remove('hidden');$('load-more').classList.add('hidden');return;}
  const photos=await api(`/api/albums/${album.id}/photos?limit=100&offset=${append?state.photos.length:0}`);
  if(album.id!==state.album||version!==photosRequestVersion)return;
  state.photos=append?[...state.photos,...photos]:photos;
  $('gallery').replaceChildren(...state.photos.map(photo=>{const card=photoCard(photo);card.dataset.photo=photo.id;return card;}));
  $('gallery-empty').classList.toggle('hidden',state.photos.length>0);$('empty-create').textContent='＋ Thêm ảnh vào bộ';
  $('load-more').classList.toggle('hidden',state.photos.length>=album.photo_count);
  const selected=state.selected?.id || '';$('studio-photo').replaceChildren(el('option','','Chọn ảnh'));
  for(const photo of state.photos){const option=el('option','',photo.name);option.value=photo.id;$('studio-photo').append(option);}
  if(state.selected&&!state.photos.some(photo=>photo.id===selected)){const option=el('option','',state.selected.name);option.value=selected;$('studio-photo').append(option);}
  $('studio-photo').value=selected;updateCollectionContext();
}
function showAlbumDialog(editId=null){state.editingAlbum=typeof editId==='string'?editId:null;$('album-dialog-title').textContent=state.editingAlbum?'Đổi tên bộ ảnh':'Tạo bộ ảnh mới';$('album-name').value=state.editingAlbum?currentAlbum()?.name || '':'';$('album-dialog').showModal();$('album-name').focus();}
$('new-album').onclick = showAlbumDialog;
$('new-album-mobile').onclick = showAlbumDialog;
$('close-dialog').onclick = () => $('album-dialog').close();
$('album-form').onsubmit = async event => {event.preventDefault(); await busy(event.submitter, 'Đang lưu...', async () => {const request=jsonRequest({name:$('album-name').value});if(state.editingAlbum)request.method='PATCH';const album=await api(state.editingAlbum?`/api/albums/${state.editingAlbum}`:'/api/albums',request);if(!state.editingAlbum){state.album=album.id;state.selectedIds.clear();updateSelection();} $('album-dialog').close();$('album-form').reset();await refreshAlbums();await refreshPhotos();toast('Đã lưu tên album.');});};
function uploadAction() {if (!state.album) return showAlbumDialog(); $('photo-files').click();}
['add-photos', 'empty-create'].forEach(id => $(id).onclick = uploadAction);
$('photo-files').onchange = async () => {
  const files = [...$('photo-files').files], albumId = state.album;
  if (!files.length || !albumId) return;
  await busy($('add-photos'), 'Đang tải...', async () => {
    const jobs = []; let accepted = 0, duplicates = 0, failed = 0;
    $('upload-state').classList.remove('hidden');
    try {
      // Bounded multipart requests: thousands of selected files never enter one request.
      for (let start = 0; start < files.length; start += 12) {
        const form = new FormData(); files.slice(start,start+12).forEach(file => form.append('files', file));
        $('upload-state').textContent = `Đang tải ${start+1}–${Math.min(start+12,files.length)}/${files.length} ảnh…`;
        const result = await api(`/api/albums/${albumId}/photos`, {method:'POST', body:form});
        accepted += result.accepted; duplicates += result.duplicates; failed += result.errors.length;
        if (result.job_id) jobs.push(result.job_id);
        await refreshAlbums(); await refreshPhotos();
      }
      $('upload-state').textContent = `Đã nhận ${accepted} ảnh · bỏ qua ${duplicates} ảnh trùng · ${failed} lỗi. Đang lập chỉ mục khuôn mặt…`;
      for (const job of jobs) {try {await watchJob(job);} catch (error) {toast(error.message, true);}}
      toast(`Đã tải và xử lý ${accepted} ảnh · ${duplicates} ảnh trùng · ${failed} lỗi.`);
    } finally {
      $('upload-state').classList.add('hidden'); await refreshAlbums(); await refreshPhotos();
    }
  });
  $('photo-files').value = '';
};
$('load-more').onclick = async () => {try {await refreshPhotos(true);} catch (error) {toast(error.message, true);}};
$('reindex').onclick = () => busy($('reindex'), 'Đang xử lý...', async () => {if (!state.album) throw new Error('Tạo album trước khi lập chỉ mục.'); const job = await api(`/api/albums/${state.album}/reindex`, jsonRequest({scope:$('reindex-scope').value})); try {toast((await watchJob(job.job_id)).message);} finally {await refreshAlbums(); await refreshPhotos();}});
$('download-results').onclick = () => busy($('download-results'),'Đang đóng gói...',async () => {const response = await fetch('/api/export',jsonRequest({photo_ids:state.results.map(x=>x.id)})); if (!response.ok) {const data=await response.json(); throw new Error(data.detail || 'Không tạo được gói tải.');} const url=URL.createObjectURL(await response.blob()); const a=el('a'); a.href=url;a.download='LumaNest.zip';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
function resetStudio() {$('canvas-placeholder').classList.toggle('hidden',!!state.selected); $('before-image').classList.toggle('hidden',!state.selected); $('after-wrap').classList.add('hidden'); $('compare-control').classList.add('hidden'); $('before-label').classList.add('hidden'); $('after-label').classList.add('hidden'); $('download-art').classList.add('hidden'); $('studio-photo-name').textContent=state.selected?.name || 'Chọn một bức ảnh để bắt đầu'; $('run-style').disabled=!state.selected || !!state.styleGenerating; if(state.selected) $('before-image').src=`/api/photos/${state.selected.id}/image`;syncPhotoPickers();}
function selectPhoto(photo) {state.selected=photo; $('studio-photo').value=photo.id; resetStudio();navigate('studio');}
function findPhotoById(id){return state.photos.find(photo=>photo.id===id)||state.extraPhotos.get(id);}
$('studio-photo').onchange=()=>{state.selected=findPhotoById($('studio-photo').value)||null;resetStudio();};
async function loadStyles(){state.styles=await api('/api/styles');$('style-grid').replaceChildren();for(const style of state.styles){const button=el('button',`style-option${style.id===state.style?' selected':''}`);button.dataset.style=style.id;button.title=style.description;button.append(el('span',`style-swatch swatch-${style.id}`,style.id==='custom'?'＋':undefined),el('span','',style.name));button.onclick=()=>{clearStyleRecipe();state.style=style.id;document.querySelectorAll('.style-option').forEach(x=>x.classList.toggle('selected',x.dataset.style===style.id));$('custom-style').classList.toggle('hidden',style.id!=='custom');document.dispatchEvent(new CustomEvent('fsm:style-picked'));};$('style-grid').append(button);}}
$('strength').oninput=()=>{$('strength-value').textContent=`${Math.round(Number($('strength').value)*100)}%`;document.dispatchEvent(new CustomEvent('fsm:style-picked'));};
$('compare-slider').oninput=()=>$('after-wrap').style.clipPath=`inset(0 0 0 ${Number($('compare-slider').value)}%)`;
$('run-style').onclick=()=>busy($('run-style'),'Đang sáng tạo...',async()=>{if(!state.selected)throw new Error('Chọn ảnh trước khi tạo tác phẩm.');const photo={...state.selected};if(state.activeRecipe)return createFromStyleRecipe(state.activeRecipe,photo);const form=new FormData();form.append('photo_id',photo.id);form.append('style_id',state.style);form.append('strength',$('strength').value);form.append('steps',$('style-steps').value);form.append('profile',$('speed-profile').value);if(state.style==='custom'){if(!$('style-file').files[0])throw new Error('Chọn một ảnh phong cách.');form.append('style_image',$('style-file').files[0]);}const job=await api('/api/stylize',{method:'POST',body:form,headers:{'Idempotency-Key':crypto.randomUUID()}});const done=await watchJob(job.job_id);if(state.selected?.id===photo.id)showOutput(done.result.image_url,done.result.download_url);await refreshOutputs();toast(`Đã tạo ảnh trong ${done.result.seconds ?? '?'} giây${done.result.cached ? ' · dùng lại kết quả đã lưu' : ''}.`);await refreshHealth();});
function showOutput(image,download){$('after-image').src=image;$('after-wrap').classList.remove('hidden');$('compare-control').classList.remove('hidden');$('before-label').classList.remove('hidden');$('after-label').classList.remove('hidden');$('download-art').classList.remove('hidden');$('download-art').href=download;$('compare-slider').value=50;$('after-wrap').style.clipPath='inset(0 0 0 50%)';}
async function refreshOutputs(){const outputs=await api('/api/outputs');$('output-history').replaceChildren();$('output-empty').classList.toggle('hidden',outputs.length>0);for(const output of outputs){const card=el('article','photo-card');const button=el('button','image-button');const img=el('img');img.src=`/api/outputs/${output.id}/image`;img.alt=`${output.name} - ${output.style}`;img.loading='lazy';button.append(img);button.onclick=()=>{selectPhoto({id:output.photo_id,name:output.name});showOutput(`/api/outputs/${output.id}/image`,`/api/outputs/${output.id}/image?download=true`);};const info=el('div','photo-info');info.append(el('p','',output.title || state.styles.find(x=>x.id===output.style)?.name || output.style));card.append(button,info);$('output-history').append(card);}}
async function start(){clearTimeout(reconnectTimer);try{await refreshHealth();await refreshAlbums();await refreshPhotos();await loadStyles();await refreshOutputs();await restoreFaceSearch();connectionFailed=false;}catch(error){$('connection').className='connection warning';$('connection').replaceChildren(el('i'),document.createTextNode('Đang kết nối lại'));if(!connectionFailed)toast('Chưa kết nối được ứng dụng. Trang sẽ tự thử lại khi server khởi động xong.',true);connectionFailed=true;reconnectTimer=setTimeout(start,3000);}}
