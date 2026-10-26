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
let thresholdInitialized = false;
async function refreshHealth() { const threshold = $('threshold').value; const health = await api('/api/health'); if ($('runtime-hint')) $('runtime-hint').textContent = health.style_backend && health.style_backend !== 'chưa nạp' ? `Đang dùng ${health.style_backend}. Kích thước tính theo cạnh dài; VGG19 dùng 512 px và chạy chậm hơn.` : (health.openvino_installed ? 'Đã cài OpenVINO CPU · Lần đầu mỗi preset cần chuẩn bị model. VGG19 chạy chậm hơn.' : 'Preset chạy PyTorch. Cài requirements-cpu.txt để bật OpenVINO CPU.'); $('connection').className = `connection ${health.face_ready && health.presets_ready ? 'ready' : 'warning'}`; $('connection').replaceChildren(el('i'), document.createTextNode(health.face_ready && health.presets_ready ? 'Model sẵn sàng' : 'Cần tải trọng số')); $('threshold').value = health.threshold; $('threshold-value').textContent = Number(health.threshold).toFixed(2); $('calibration-note').textContent = health.threshold_calibrated ? 'Ngưỡng đã được hiệu chỉnh với model hiện tại.' : 'Ngưỡng thử nghiệm. Điểm tương đồng không phải xác suất nhận diện.'; if (thresholdInitialized) $('threshold').value = threshold; else {const saved = Number(localStorage.getItem('fsm-threshold')); if (saved >= .1 && saved <= .9) $('threshold').value = String(saved); thresholdInitialized = true;} $('threshold-value').textContent = Number($('threshold').value).toFixed(2); }
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
function showAlbumDialog(editId=null){state.editingAlbum=typeof editId==='string'?editId:null;$('album-dialog-title').textContent=state.editingAlbum?'Đổi tên bộ ảnh':'Tạo bộ ảnh mới';$('album-name').value=state.editingAlbum?currentAlbum()?.name || '':'';$('album-dialog').showModal();$('album-name').focus();}
$('new-album').onclick = showAlbumDialog;
$('new-album-mobile').onclick = showAlbumDialog;
$('close-dialog').onclick = () => $('album-dialog').close();
function uploadAction() {if (!state.album) return showAlbumDialog(); $('photo-files').click();}
['add-photos', 'empty-create'].forEach(id => $(id).onclick = uploadAction);
$('load-more').onclick = async () => {try {await refreshPhotos(true);} catch (error) {toast(error.message, true);}};
$('reindex').onclick = () => busy($('reindex'), 'Đang xử lý...', async () => {if (!state.album) throw new Error('Tạo album trước khi lập chỉ mục.'); const job = await api(`/api/albums/${state.album}/reindex`, jsonRequest({scope:$('reindex-scope').value})); try {toast((await watchJob(job.job_id)).message);} finally {await refreshAlbums(); await refreshPhotos();}});
function selectPhoto(photo) {state.selected=photo; $('studio-photo').value=photo.id; resetStudio();navigate('studio');}
function findPhotoById(id){return state.photos.find(photo=>photo.id===id)||state.extraPhotos.get(id);}
$('studio-photo').onchange=()=>{state.selected=findPhotoById($('studio-photo').value)||null;resetStudio();};
async function loadStyles(){state.styles=await api('/api/styles');$('style-grid').replaceChildren();for(const style of state.styles){const button=el('button',`style-option${style.id===state.style?' selected':''}`);button.dataset.style=style.id;button.title=style.description;button.append(el('span',`style-swatch swatch-${style.id}`,style.id==='custom'?'＋':undefined),el('span','',style.name));button.onclick=()=>{clearStyleRecipe();state.style=style.id;document.querySelectorAll('.style-option').forEach(x=>x.classList.toggle('selected',x.dataset.style===style.id));$('custom-style').classList.toggle('hidden',style.id!=='custom');document.dispatchEvent(new CustomEvent('fsm:style-picked'));};$('style-grid').append(button);}}
$('strength').oninput=()=>{$('strength-value').textContent=`${Math.round(Number($('strength').value)*100)}%`;document.dispatchEvent(new CustomEvent('fsm:style-picked'));};
$('compare-slider').oninput=()=>$('after-wrap').style.clipPath=`inset(0 0 0 ${Number($('compare-slider').value)}%)`;
// Base before/after view; studio previews use it directly, saved results go through showOutput (studio.js).
function showComparison(image,download){$('after-image').src=image;$('after-wrap').classList.remove('hidden');$('compare-control').classList.remove('hidden');$('before-label').classList.remove('hidden');$('after-label').classList.remove('hidden');$('download-art').classList.remove('hidden');$('download-art').href=download;$('compare-slider').value=50;$('after-wrap').style.clipPath='inset(0 0 0 50%)';}
async function start(){clearTimeout(reconnectTimer);try{await refreshHealth();await refreshAlbums();await refreshPhotos();await loadStyles();await refreshOutputs();await restoreFaceSearch();connectionFailed=false;}catch(error){$('connection').className='connection warning';$('connection').replaceChildren(el('i'),document.createTextNode('Đang kết nối lại'));if(!connectionFailed)toast('Chưa kết nối được ứng dụng. Trang sẽ tự thử lại khi server khởi động xong.',true);connectionFailed=true;reconnectTimer=setTimeout(start,3000);}}
