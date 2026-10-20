'use strict';
const photoPickerBindings=new Map();
let photoPickerContext=null,photoPickerVersion=0,photoPickerTimer,photoPickerController;

function syncPhotoPickers(){
  for(const [select,binding] of photoPickerBindings){
    if(!select.isConnected){binding.observer.disconnect();photoPickerBindings.delete(select);continue;}
    const value=select.value,name=select.selectedOptions[0]?.textContent || 'Chọn ảnh có xem trước';
    binding.button.replaceChildren();
    if(value){const image=el('img');image.src=`/api/photos/${value}/image?thumbnail=true`;image.alt='';binding.button.append(image);}
    binding.button.append(el('span','',value?name:'Chọn ảnh có xem trước'),el('span','picker-chevron','⌄'));
    binding.button.disabled=select.disabled;
  }
}

function mountPhotoPicker(select){
  if(photoPickerBindings.has(select))return;
  const button=el('button','photo-picker-trigger');button.type='button';button.id=select.id+'-visual';
  button.setAttribute('role','combobox');button.setAttribute('aria-label','Chọn ảnh có xem trước');
  button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','photo-picker-modal');
  select.before(button);select.classList.add('hidden');select.hidden=true;select.tabIndex=-1;select.setAttribute('aria-hidden','true');
  const label=document.querySelector(`label[for="${select.id}"]`);if(label)label.htmlFor=button.id;
  const observer=new MutationObserver(syncPhotoPickers);observer.observe(select,{childList:true,attributes:true,attributeFilter:['disabled']});
  photoPickerBindings.set(select,{button,observer});button.onclick=()=>openPhotoPicker(select,button);select.addEventListener('change',syncPhotoPickers);syncPhotoPickers();
}

function previewPickerPhoto(photo){
  if(!photoPickerContext)return;
  photoPickerContext.preview=photo;
  const image=$('picker-preview-image');image.classList.toggle('hidden',!photo);
  $('picker-preview-placeholder').classList.toggle('hidden',!!photo);
  $('picker-preview-name').textContent=photo?.name || 'Rê chuột hoặc dùng phím mũi tên để xem ảnh';
  $('picker-preview-detail').textContent=photo?`${photo.width} × ${photo.height} px${photo.face_count!==undefined?' · '+photo.face_count+' khuôn mặt':''}`:'';
  $('picker-choose').disabled=!photo;
  if(photo)image.src=`/api/photos/${photo.id}/image?thumbnail=true`;
  document.querySelectorAll('#picker-results [role="option"]').forEach(node=>node.setAttribute('aria-selected',String(node.dataset.photo===photo?.id)));
}

function renderPickerRows(){
  const context=photoPickerContext;if(!context)return;
  $('picker-results').replaceChildren(...context.rows.map(photo=>{
    const row=el('button','picker-option');row.type='button';row.dataset.photo=photo.id;
    row.setAttribute('role','option');row.setAttribute('aria-selected',String(photo.id===context.preview?.id));
    const image=el('img');image.src=`/api/photos/${photo.id}/image?thumbnail=true`;image.alt='';image.loading='lazy';
    const info=el('span','picker-option-info');info.append(el('b','',photo.name),el('small','',`${photo.width} × ${photo.height} px`));row.append(image,info);
    row.onpointerenter=()=>previewPickerPhoto(photo);row.onfocus=()=>previewPickerPhoto(photo);row.onclick=()=>previewPickerPhoto(photo);row.ondblclick=commitPickerPhoto;
    return row;
  }));
  $('picker-empty').classList.toggle('hidden',context.rows.length>0);
  $('picker-more').classList.toggle('hidden',!context.more);
}

async function loadPickerPhotos(append=false){
  const context=photoPickerContext;if(!context)return;
  const version=++photoPickerVersion;photoPickerController?.abort();photoPickerController=new AbortController();
  const query=$('picker-search').value.trim();$('picker-status').textContent='Đang đọc danh sách ảnh…';$('picker-more').disabled=true;
  try{
    const rows=await api(`/api/albums/${context.albumId}/photos?limit=100&offset=${append?context.rows.length:0}&q=${encodeURIComponent(query)}`,{signal:photoPickerController.signal});
    if(version!==photoPickerVersion||context!==photoPickerContext)return;
    context.rows=append?[...context.rows,...rows]:rows;context.more=rows.length===100;
    for(const photo of rows)state.extraPhotos.set(photo.id,photo);
    renderPickerRows();
    const candidate=context.rows.find(photo=>photo.id===context.select.value)||(!append?context.rows[0]:context.preview);
    previewPickerPhoto(candidate||null);
    $('picker-status').textContent=`${context.rows.length} ảnh${context.more?' · còn ảnh để tải thêm':''} · rê chuột để xem, bấm Chọn ảnh này để dùng`;
  }catch(error){if(error.name!=='AbortError'&&context===photoPickerContext)$('picker-status').textContent=error.message;}
  finally{if(context===photoPickerContext)$('picker-more').disabled=false;}
}

function openPhotoPicker(select,button){
  const album=currentAlbum();if(!album)return toast('Mở một bộ ảnh trước khi chọn ảnh.',true);
  photoPickerContext={select,button,albumId:album.id,rows:[],preview:null,more:false};
  $('picker-scope').textContent=`Bộ ảnh: ${album.name}`;$('picker-search').value='';$('picker-results').replaceChildren();
  $('picker-more').classList.add('hidden');$('picker-empty').classList.add('hidden');previewPickerPhoto(null);
  button.setAttribute('aria-expanded','true');$('photo-picker-modal').showModal();$('picker-search').focus();loadPickerPhotos();
}

function commitPickerPhoto(){
  const context=photoPickerContext,photo=context?.preview;if(!photo)return;
  if(context.albumId!==state.album||!context.select.isConnected){$('photo-picker-modal').close();return toast('Bộ ảnh đã thay đổi. Mở bảng chọn lại.',true);}
  if(![...context.select.options].some(option=>option.value===photo.id)){const option=el('option','',photo.name);option.value=photo.id;context.select.append(option);}
  state.extraPhotos.set(photo.id,photo);context.select.value=photo.id;
  context.select.dispatchEvent(new Event('change',{bubbles:true}));syncPhotoPickers();$('photo-picker-modal').close();
}

$('picker-choose').onclick=commitPickerPhoto;
$('picker-close').onclick=()=>$('photo-picker-modal').close();
$('picker-cancel').onclick=()=>$('photo-picker-modal').close();
$('picker-search').oninput=()=>{clearTimeout(photoPickerTimer);++photoPickerVersion;photoPickerController?.abort();previewPickerPhoto(null);$('picker-results').replaceChildren();photoPickerTimer=setTimeout(()=>loadPickerPhotos(),180);};
$('picker-more').onclick=()=>loadPickerPhotos(true);
$('picker-preview-image').onerror=()=>{$('picker-preview-detail').textContent='Không tải được ảnh xem trước. Kiểm tra kết nối hoặc toàn vẹn dữ liệu.';};
$('photo-picker-modal').addEventListener('close',()=>{
  clearTimeout(photoPickerTimer);++photoPickerVersion;photoPickerController?.abort();
  const context=photoPickerContext;photoPickerContext=null;
  if(context){context.button.setAttribute('aria-expanded','false');if(context.button.isConnected)context.button.focus();}
});
$('photo-picker-modal').addEventListener('keydown',event=>{
  if(!photoPickerContext)return;
  const rows=[...$('picker-results').children];
  if(['ArrowDown','ArrowUp'].includes(event.key)&&rows.length){event.preventDefault();const current=rows.indexOf(document.activeElement);const index=current<0?0:Math.max(0,Math.min(rows.length-1,current+(event.key==='ArrowDown'?1:-1)));rows[index].focus();}
  if(event.key==='Enter'&&event.target===$('picker-search')){event.preventDefault();commitPickerPhoto();}
});
