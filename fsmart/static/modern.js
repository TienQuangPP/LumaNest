'use strict';
// Static markup only; all photo names, notes and server messages use textContent.
const discoveryPanel=el('section','discovery-panel');
discoveryPanel.setAttribute('aria-labelledby','discovery-title');
discoveryPanel.innerHTML=`<div class="discovery-heading"><div><p class="eyebrow">TÌM THEO ĐIỀU BẠN NHỚ</p><h2 id="discovery-title">Tìm ảnh bằng mô tả</h2></div><span class="local-chip">◉ AI cục bộ</span></div><form id="discovery-form"><label class="chat-sr-only" for="discovery-query">Mô tả ảnh cần tìm</label><input id="discovery-query" maxlength="300" placeholder="Ví dụ: ảnh tập thể sinh viên…" required autocomplete="off"><button id="discovery-submit" class="button primary">⌕ Tìm bằng AI</button></form><div class="discovery-bottom"><p id="discovery-status" role="status">Đang kiểm tra chỉ mục AI…</p><button id="discovery-index" class="text-button" type="button">Cập nhật AI ↗</button></div>`;
$('page-library').insertBefore(discoveryPanel,$('page-library').querySelector('.section-top'));
const filters=el('div','library-filters');
filters.innerHTML=`<label class="metadata-search">Tên, nhãn hoặc ghi chú<input id="library-query" type="search" maxlength="300" placeholder="Tìm trong bộ ảnh…" autocomplete="off"></label><button id="favorite-filter" class="button outline" aria-pressed="false">☆ Yêu thích</button><label>Khung ảnh<select id="orientation-filter"><option value="all">Tất cả</option><option value="portrait">Ảnh dọc</option><option value="landscape">Ảnh ngang</option></select></label><label>Khuôn mặt<select id="faces-filter"><option value="0">Tất cả</option><option value="1">Có người</option><option value="2">Từ 2 khuôn mặt</option><option value="5">Từ 5 khuôn mặt</option></select></label><label>Sắp xếp<select id="library-sort"><option value="newest">Mới nhất</option><option value="oldest">Cũ nhất</option><option value="name">Tên ảnh</option></select></label><button id="clear-library-filters" class="text-button">Đặt lại</button>`;
$('gallery').before(filters);
const selectionFavorite=el('button','button outline','☆ Yêu thích ảnh đã chọn');selectionFavorite.id='selection-favorite';
$('selection-delete').before(selectionFavorite);
selectionFavorite.onclick=()=>busy(selectionFavorite,'Đang lưu…',async()=>{
  if(!state.selectedIds.size)throw new Error('Chọn ảnh trước khi đánh dấu yêu thích.');
  const favorite=!favoritesOnly,response=await api('/api/library/favorites',jsonRequest({photo_ids:[...state.selectedIds],favorite}));
  await refreshPhotos();toast(`Đã ${favorite?'đánh dấu':'bỏ đánh dấu'} ${response.updated} ảnh yêu thích.`);
});

let discoveryQuery=null,filterTimer,favoritesOnly=false,discoveryLimit=24;
const oldUpdateSelection=updateSelection;updateSelection=function(){oldUpdateSelection();document.querySelector('#page-library .selection-bar').classList.toggle('has-selection',!!state.selectedIds.size);selectionFavorite.disabled=!state.selectedIds.size;selectionFavorite.textContent=favoritesOnly?'☆ Bỏ yêu thích ảnh đã chọn':'☆ Yêu thích ảnh đã chọn';};updateSelection();
const oldPhotoCard=photoCard;
photoCard=function(photo,mode='gallery'){
  const card=oldPhotoCard(photo,mode);if(mode!=='gallery')return card;
  const imageButton=card.querySelector('.image-button');imageButton.setAttribute('aria-label',`Xem ảnh ${photo.name}`);imageButton.onclick=()=>openLightbox(photo.id);
  const star=el('button',`favorite-star${photo.favorite?' is-favorite':''}`,photo.favorite?'★':'☆');star.setAttribute('aria-label',`Yêu thích ${photo.name}`);star.setAttribute('aria-pressed',String(!!photo.favorite));
  star.onclick=async()=>{star.disabled=true;try{await toggleFavorite(photo,star);if(favoritesOnly)await refreshPhotos();}catch(error){toast(error.message,true);}finally{star.disabled=false;}};card.append(star);
  const edit=el('button','photo-create','Sáng tạo ↗');edit.onclick=()=>selectPhoto(photo);card.querySelector('.photo-info').append(edit);
  if(photo.tags?.length){const labels=el('div','photo-tags');photo.tags.slice(0,3).forEach(tag=>labels.append(el('span','',tag)));card.append(labels);}
  return card;
};
async function toggleFavorite(photo,button){
  const result=await api(`/api/photos/${photo.id}/metadata`,{...jsonRequest({favorite:!photo.favorite}),method:'PATCH'});
  Object.assign(photo,result);for(const item of state.photos)if(item.id===photo.id)Object.assign(item,result);
  if(button){button.textContent=photo.favorite?'★':'☆';button.classList.toggle('is-favorite',photo.favorite);button.setAttribute('aria-pressed',String(photo.favorite));}
  if(lightboxPhoto?.id===photo.id){lightboxPhoto={...lightboxPhoto,favorite:result.favorite,version:result.version};updateLightboxStar();}
  return result;
}
refreshPhotos=async function(append=false){
  const album=currentAlbum(),version=++photosRequestVersion;
  if(!album){state.photos=[];$('gallery').replaceChildren();$('gallery-empty').classList.remove('hidden');$('load-more').classList.add('hidden');return;}
  let result;
  if(discoveryQuery){
    if(append)discoveryLimit=Math.min(100,discoveryLimit+24);
    result=await api('/api/discovery/search',jsonRequest({album_id:album.id,...discoveryQuery,limit:discoveryLimit}));
    if(version!==photosRequestVersion||album.id!==state.album)return;
    result.total=Math.max(0,Math.min(100,result.coverage.indexed-(discoveryQuery.photo_id?1:0)));
    $('album-meta').textContent=`${result.items.length} ảnh gần nhất · ${result.elapsed}s`;
    $('album-title').textContent=discoveryQuery.photo_id?'Ảnh có nội dung tương tự':'Kết quả theo mô tả';
  }else{
    const params=new URLSearchParams({album_id:album.id,q:$('library-query').value,favorite:favoritesOnly,orientation:$('orientation-filter').value,min_faces:$('faces-filter').value,sort:$('library-sort').value,limit:100,offset:append?state.photos.length:0});
    result=await api(`/api/library?${params}`);
    if(version!==photosRequestVersion||album.id!==state.album)return;
    $('album-title').textContent=favoritesOnly?'Ảnh yêu thích':'Ảnh trong bộ';$('album-meta').textContent=`${result.total} / ${album.photo_count} ảnh`;
  }
  state.photos=append&&!discoveryQuery?[...state.photos,...result.items]:result.items;
  $('gallery').replaceChildren(...state.photos.map(photo=>photoCard(photo)));
  $('gallery-empty').classList.toggle('hidden',!!state.photos.length);
  $('gallery-empty').querySelector('h3').textContent=album.photo_count?'Không có ảnh phù hợp':'Chỗ dành cho những kỷ niệm';
  $('gallery-empty').querySelector('p').textContent=album.photo_count?'Thử mô tả khác hoặc đặt lại bộ lọc.':'Thêm ảnh để bắt đầu bộ sưu tập của bạn.';
  $('empty-create').textContent='＋ Thêm ảnh vào bộ';
  $('load-more').classList.toggle('hidden',state.photos.length>=result.total);
  const selected=state.selected?.id||'';$('studio-photo').replaceChildren(el('option','','Chọn ảnh'));
  for(const photo of state.photos){const option=el('option','',photo.name);option.value=photo.id;$('studio-photo').append(option);}
  if(state.selected&&!state.photos.some(photo=>photo.id===selected)){const option=el('option','',state.selected.name);option.value=selected;$('studio-photo').append(option);}
  $('studio-photo').value=selected;syncPhotoPickers();updateCollectionContext();
};
function filterChanged(){discoveryQuery=null;updateSelection();refreshPhotos().catch(error=>toast(error.message,true));}
$('library-query').oninput=()=>{clearTimeout(filterTimer);filterTimer=setTimeout(filterChanged,220);};
['orientation-filter','faces-filter','library-sort'].forEach(id=>$(id).onchange=filterChanged);
$('favorite-filter').onclick=()=>{favoritesOnly=!favoritesOnly;$('favorite-filter').setAttribute('aria-pressed',String(favoritesOnly));filterChanged();};
function clearLibraryFilters(){favoritesOnly=false;discoveryQuery=null;discoveryLimit=24;$('favorite-filter').setAttribute('aria-pressed','false');$('library-query').value='';$('orientation-filter').value='all';$('faces-filter').value='0';$('library-sort').value='newest';}
$('clear-library-filters').onclick=()=>{clearLibraryFilters();filterChanged();};
document.addEventListener('fsm:collection',()=>{clearTimeout(filterTimer);clearLibraryFilters();$('discovery-query').value='';});
async function refreshDiscovery(){
  if(!state.album)return;
  const album=state.album,data=await api(`/api/discovery/status?album_id=${album}`);if(album!==state.album)return;
  $('discovery-status').textContent=data.busy?(data.job?.message||'AI đang xử lý…'):(data.installed?`${data.indexed}/${data.total} ảnh sẵn sàng`:'Chưa tải model tìm ảnh.');
  $('discovery-index').disabled=data.busy||!data.installed;$('discovery-submit').disabled=data.busy||!data.installed||!data.indexed;
}
$('discovery-index').onclick=()=>busy($('discovery-index'),'Đang cập nhật…',async()=>{const album=state.album;const job=await api('/api/discovery/index',jsonRequest({album_id:album}));try{toast((await watchJob(job.job_id)).message);}finally{await refreshDiscovery();}});
$('discovery-form').onsubmit=event=>{event.preventDefault();busy($('discovery-submit'),'Đang tìm…',async()=>{clearLibraryFilters();discoveryQuery={text:$('discovery-query').value};try{await refreshPhotos();$('album-title').scrollIntoView({behavior:'smooth',block:'start'});}catch(error){discoveryQuery=null;throw error;}});};
document.addEventListener('fsm:page',()=>{if(state.page==='library')refreshDiscovery().catch(error=>toast(error.message,true));});
setInterval(()=>{if(state.page==='library')refreshDiscovery().catch(()=>{});},5000);

const lightbox=el('dialog','lightbox');lightbox.id='lightbox';lightbox.setAttribute('aria-labelledby','lightbox-name');
lightbox.innerHTML=`<div class="lightbox-toolbar"><span id="lightbox-position"></span><button id="lightbox-close" class="icon-button" aria-label="Đóng xem ảnh">×</button></div><div class="lightbox-layout"><div class="lightbox-image-stage"><button id="lightbox-prev" class="lightbox-arrow" aria-label="Ảnh trước">‹</button><img id="lightbox-image" alt="Ảnh đang xem"><button id="lightbox-next" class="lightbox-arrow next" aria-label="Ảnh tiếp theo">›</button></div><aside class="lightbox-inspector"><p class="eyebrow">KHOẢNH KHẮC CỦA BẠN</p><h2 id="lightbox-name"></h2><p id="lightbox-detail"></p><button id="lightbox-favorite" class="button outline" aria-pressed="false">☆ Yêu thích</button><form id="metadata-form"><label for="photo-tags">Nhãn ảnh</label><input id="photo-tags" maxlength="850" placeholder="Các nhãn cách nhau bằng dấu phẩy"><label for="photo-notes">Ghi chú</label><textarea id="photo-notes" maxlength="2000" rows="4" placeholder="Điều bạn muốn nhớ về bức ảnh…"></textarea><button id="save-metadata" class="button primary full">Lưu thông tin</button><p id="metadata-state" role="status"></p></form><div class="lightbox-actions"><button id="lightbox-create" class="button outline">✳ Sáng tạo ảnh này</button><button id="lightbox-similar" class="button outline">◎ Tìm ảnh tương tự</button><a id="lightbox-download" class="button subtle" download>↓ Tải ảnh nguồn</a></div><details class="helper"><summary>Phím tắt</summary><p>← → chuyển ảnh · F yêu thích · E sáng tạo · Esc đóng</p></details></aside></div>`;
document.body.append(lightbox);
let lightboxPhoto=null,lightboxVersion=0,metadataDirty=false;
function updateLightboxStar(){const active=!!lightboxPhoto?.favorite;$('lightbox-favorite').textContent=active?'★ Đã yêu thích':'☆ Yêu thích';$('lightbox-favorite').setAttribute('aria-pressed',String(active));}
function canLeaveMetadata(){return !metadataDirty||window.confirm('Thông tin chưa lưu. Bỏ thay đổi và tiếp tục?');}
async function openLightbox(id){
  if(lightbox.open&&!canLeaveMetadata())return;
  const version=++lightboxVersion;metadataDirty=false;lightboxPhoto=null;
  if(!lightbox.open)lightbox.showModal();$('metadata-form').inert=true;$('lightbox-favorite').disabled=true;$('lightbox-create').disabled=true;$('lightbox-similar').disabled=true;
  $('lightbox-name').textContent='Đang mở ảnh…';$('lightbox-image').removeAttribute('src');$('metadata-state').textContent='';
  try{
    const photo=await api(`/api/photos/${id}/metadata`);if(version!==lightboxVersion||!lightbox.open)return;
    lightboxPhoto=photo;const index=state.photos.findIndex(item=>item.id===id);
    $('lightbox-name').textContent=photo.name;$('lightbox-image').src=`/api/photos/${id}/image`;$('lightbox-image').alt=photo.name;
    $('lightbox-position').textContent=index>=0?`${index+1} / ${state.photos.length} ảnh đang hiển thị`:'';
    $('lightbox-detail').textContent=`${photo.width} × ${photo.height} px · ${photo.face_count} khuôn mặt`;
    $('photo-tags').value=photo.tags.join(', ');$('photo-notes').value=photo.notes;
    $('lightbox-download').href=`/api/photos/${id}/original`;updateLightboxStar();
    $('metadata-form').inert=false;$('lightbox-favorite').disabled=false;$('lightbox-create').disabled=false;$('lightbox-similar').disabled=false;
    $('lightbox-prev').disabled=index<=0;$('lightbox-next').disabled=index<0||index>=state.photos.length-1;
  }catch(error){$('lightbox-name').textContent='Chưa mở được ảnh';toast(error.message,true);}
}
function closeLightbox(){if(canLeaveMetadata()){++lightboxVersion;lightbox.close();}}
$('lightbox-close').onclick=closeLightbox;lightbox.addEventListener('cancel',event=>{event.preventDefault();closeLightbox();});
function stepPhoto(step){const index=state.photos.findIndex(photo=>photo.id===lightboxPhoto?.id);const next=state.photos[index+step];if(next)openLightbox(next.id);}
$('lightbox-prev').onclick=()=>stepPhoto(-1);$('lightbox-next').onclick=()=>stepPhoto(1);
['photo-tags','photo-notes'].forEach(id=>$(id).oninput=()=>{metadataDirty=true;$('metadata-state').textContent='Có thay đổi chưa lưu';});
$('metadata-form').onsubmit=event=>{event.preventDefault();busy($('save-metadata'),'Đang lưu…',async()=>{
  const photo=lightboxPhoto,version=lightboxVersion;
  const result=await api(`/api/photos/${photo.id}/metadata`,{...jsonRequest({tags:$('photo-tags').value.split(',').map(x=>x.trim()).filter(Boolean),notes:$('photo-notes').value,expected_version:photo.version}),method:'PATCH'});
  if(version===lightboxVersion){lightboxPhoto=result;metadataDirty=false;$('metadata-state').textContent='Đã lưu vào thư viện';}
  await refreshPhotos();
});};
$('lightbox-favorite').onclick=async()=>{const button=$('lightbox-favorite');button.disabled=true;try{await toggleFavorite(lightboxPhoto);updateLightboxStar();await refreshPhotos();}catch(error){toast(error.message,true);}finally{button.disabled=false;}};
$('lightbox-create').onclick=()=>{if(!lightboxPhoto||!canLeaveMetadata())return;const photo=lightboxPhoto;metadataDirty=false;lightbox.close();selectPhoto(photo);};
$('lightbox-similar').onclick=()=>busy($('lightbox-similar'),'Đang tìm…',async()=>{
  if(!canLeaveMetadata())return;clearLibraryFilters();discoveryQuery={photo_id:lightboxPhoto.id};
  try{await refreshPhotos();metadataDirty=false;lightbox.close();navigate('library');$('album-title').scrollIntoView({block:'start'});}catch(error){discoveryQuery=null;throw error;}
});
lightbox.addEventListener('keydown',event=>{if(event.target.closest('input,textarea,select'))return;if(event.key==='ArrowLeft'){event.preventDefault();stepPhoto(-1);}if(event.key==='ArrowRight'){event.preventDefault();stepPhoto(1);}if(event.key.toLowerCase()==='f')$('lightbox-favorite').click();if(event.key.toLowerCase()==='e')$('lightbox-create').click();});

const colourLab=el('section','panel colour-lab');colourLab.setAttribute('aria-labelledby','colour-title');
colourLab.innerHTML=`<div class="colour-copy"><p class="eyebrow">THỬ MÀU TRONG TÍCH TẮC</p><h2 id="colour-title">Thêm một lớp cảm xúc.</h2></div><div><label for="colour-source">Áp dụng lên</label><select id="colour-source"><option value="original">Ảnh gốc</option><option value="output">Tác phẩm đang xem</option></select><div id="colour-presets" class="colour-presets"></div><label for="colour-strength">Độ đậm màu <output id="colour-value">80%</output></label><input id="colour-strength" type="range" min="0" max="1" step="0.05" value="0.8"><div class="colour-actions"><button id="preview-colour" class="button outline">Xem trước màu</button><button id="save-colour" class="button primary" title="Lưu PNG tối đa 2048 px">Lưu phiên bản màu</button></div><p id="colour-status" class="helper" role="status"></p></div>`;
$('batch-section').before(colourLab);
let colourLook='cinema',colourTimer,colourController,colourObjectURL,colourSourceOutput=null,colourPreviewActive=false;
let studioPreviewEpoch=0,studioPreviewAbort=null;
function invalidateStudioPreview(){studioPreviewEpoch++;studioPreviewAbort?.abort();colourController?.abort();clearTimeout(colourTimer);}
const oldResetStudio=resetStudio;resetStudio=function(){invalidateStudioPreview();oldResetStudio();colourSourceOutput=null;colourPreviewActive=false;if($('colour-source'))$('colour-source').value='original';};
const oldShowOutput=showOutput;showOutput=function(image,download){invalidateStudioPreview();oldShowOutput(image,download);$('after-label').textContent='Sau sáng tạo';colourSourceOutput=image.match(/^\/api\/outputs\/([0-9a-f]{32})\/image/)?.[1]||null;colourPreviewActive=false;};
function colourPayload(){if(!state.selected)throw new Error('Chọn ảnh trước khi thử màu.');const source=$('colour-source').value==='output'?colourSourceOutput:null;if($('colour-source').value==='output'&&!source)throw new Error('Chưa có tác phẩm đang xem. Tạo hoặc mở một tác phẩm trước.');return {photo_id:state.selected.id,look:colourLook,strength:Number($('colour-strength').value),source_output:source};}
async function previewColour(){
  const payload=colourPayload(),photoId=payload.photo_id;invalidateStudioPreview();const epoch=studioPreviewEpoch,controller=new AbortController();colourController=controller;
  const params=new URLSearchParams({look:payload.look,strength:payload.strength});if(payload.source_output)params.set('source_output',payload.source_output);
  const response=await fetch(`/api/photos/${photoId}/look-preview?${params}`,{signal:controller.signal});if(!response.ok){const data=await response.json();throw new Error(data.detail||'Không xem trước được màu.');}
  const blob=await response.blob();if(state.selected?.id!==photoId||controller.signal.aborted||epoch!==studioPreviewEpoch)return;
  if(colourObjectURL)URL.revokeObjectURL(colourObjectURL);colourObjectURL=URL.createObjectURL(blob);
  oldShowOutput(colourObjectURL,'');$('download-art').classList.add('hidden');$('after-label').textContent='Xem trước màu';colourPreviewActive=true;
  $('colour-status').textContent='Bản xem trước · 640 px';
}
function scheduleColour(){clearTimeout(colourTimer);colourTimer=setTimeout(()=>{if(state.selected)previewColour().catch(error=>{if(error.name!=='AbortError')toast(error.message,true);});},160);}
[['original','Nguyên bản'],['cinema','Cinema'],['portra','Soft film'],['noir','Noir'],['cool','Nordic'],['sunset','Golden hour']].forEach(([id,name])=>{const button=el('button',`colour-swatch swatch-${id}`,name);button.setAttribute('aria-pressed',String(id===colourLook));button.onclick=()=>{colourLook=id;document.querySelectorAll('.colour-swatch').forEach(node=>node.setAttribute('aria-pressed',String(node===button)));scheduleColour();};$('colour-presets').append(button);});
$('colour-strength').oninput=()=>{$('colour-value').textContent=`${Math.round(Number($('colour-strength').value)*100)}%`;scheduleColour();};
$('colour-source').onchange=scheduleColour;
$('preview-colour').onclick=()=>busy($('preview-colour'),'Đang xem…',previewColour);
$('save-colour').onclick=()=>busy($('save-colour'),'Đang lưu…',async()=>{const payload=colourPayload(),result=await api('/api/looks',jsonRequest(payload));if(state.selected?.id===payload.photo_id){showOutput(result.image_url,result.download_url);$('after-label').textContent=result.style_label;$('colour-status').textContent='Đã lưu phiên bản màu.';}await refreshOutputs();toast('Đã lưu phiên bản màu.');});

const palette=el('dialog','command-palette');palette.id='command-palette';palette.setAttribute('aria-labelledby','command-title');
palette.innerHTML=`<h2 id="command-title">Bạn muốn làm gì?</h2><label class="chat-sr-only" for="command-query">Tìm thao tác</label><input id="command-query" placeholder="Tìm ảnh, tạo bộ, sáng tạo…" autocomplete="off"><div id="command-results"></div><button id="command-close" class="text-button">Đóng · Esc</button>`;document.body.append(palette);
const commandButton=el('button','command-launcher','⌕ Thao tác · Ctrl K');commandButton.setAttribute('aria-label','Mở tìm thao tác');document.querySelector('.topbar-right').prepend(commandButton);
const commands=[['▦ Mở thư viện ảnh',()=>navigate('collections')],['＋ Tạo bộ ảnh',()=>showAlbumDialog()],['⌕ Tìm ảnh bằng mô tả',()=>{navigate('library');$('discovery-query').focus();}],['☆ Xem ảnh yêu thích',()=>{navigate('library');clearLibraryFilters();favoritesOnly=true;$('favorite-filter').setAttribute('aria-pressed','true');filterChanged();}],['✳ Mở phòng sáng tạo',()=>navigate('studio')],['⌕ Tìm khuôn mặt',()=>navigate('search')],['◎ Kiểm tra hệ thống',()=>navigate('system')]];
function renderCommands(){const q=$('command-query').value.toLocaleLowerCase('vi');$('command-results').replaceChildren();for(const [name,action] of commands.filter(([name])=>name.toLocaleLowerCase('vi').includes(q))){const button=el('button','command-option',name);button.onclick=()=>{palette.close();action();};$('command-results').append(button);}}
function openCommands(){if(document.querySelector('dialog[open]'))return;palette.showModal();$('command-query').value='';renderCommands();$('command-query').focus();}
commandButton.onclick=openCommands;$('command-close').onclick=()=>palette.close();$('command-query').oninput=renderCommands;
$('command-query').onkeydown=event=>{if(event.key==='ArrowDown'){event.preventDefault();$('command-results').querySelector('button')?.focus();}if(event.key==='Enter'){$('command-results').querySelector('button')?.click();}};
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='k'){event.preventDefault();openCommands();}});
