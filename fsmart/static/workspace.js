'use strict';
let outputOffset=0;
let outputsRequestVersion=0;
let thresholdInitialized=false;
const baseRefreshHealth=refreshHealth;
refreshHealth=async function(){const threshold=$('threshold').value;await baseRefreshHealth();if(thresholdInitialized)$('threshold').value=threshold;else{const saved=Number(localStorage.getItem('fsm-threshold'));if(saved>=.1&&saved<=.9)$('threshold').value=String(saved);thresholdInitialized=true;}$('threshold-value').textContent=Number($('threshold').value).toFixed(2);};
$('threshold').addEventListener('input',()=>localStorage.setItem('fsm-threshold',$('threshold').value));
$('speed-profile').value=['fast','balanced','quality'].includes(localStorage.getItem('fsm-speed-profile'))?localStorage.getItem('fsm-speed-profile'):'fast';
$('speed-profile').onchange=()=>localStorage.setItem('fsm-speed-profile',$('speed-profile').value);
function updateSelection(){
  const count=state.selectedIds.size;
  $('selection-count').textContent=`${count} ảnh đã chọn`;
  $('selection-create').disabled=!count;
  $('selection-download').disabled=!count;
  $('selection-clear').disabled=!count;
  $('selection-move').disabled=!count;
  $('selection-delete').disabled=!count;
  $('run-selection-batch').classList.toggle('hidden',!count);
  $('run-selection-batch').textContent=`✳ Tạo style ${count} ảnh đã chọn`;
  document.querySelectorAll('.photo-select input').forEach(input=>{input.checked=state.selectedIds.has(input.dataset.photo);});
}
function addSelectionControls(){
  for(const card of document.querySelectorAll('#gallery .photo-card')){
    if(card.querySelector('.photo-select'))continue;
    const photo=state.photos.find(p=>p.id===card.dataset.photo);
    if(!photo)continue;
    const label=el('label','photo-select'), input=el('input');input.type='checkbox';input.dataset.photo=photo.id;
    input.setAttribute('aria-label',`Chọn xử lý lô: ${photo.name}`);input.checked=state.selectedIds.has(photo.id);
    input.onchange=()=>{if(input.checked)state.selectedIds.add(photo.id);else state.selectedIds.delete(photo.id);updateSelection();};
    label.append(input,el('span','','Chọn'));card.prepend(label);
  }
  updateSelection();
}
const galleryObserver=new MutationObserver(addSelectionControls);
galleryObserver.observe($('gallery'),{childList:true});
$('selection-visible').onclick=()=>{state.photos.forEach(p=>state.selectedIds.add(p.id));updateSelection();};
$('selection-clear').onclick=()=>{state.selectedIds.clear();updateSelection();};
$('selection-create').onclick=()=>{const photo=state.photos.find(p=>state.selectedIds.has(p.id));if(photo)selectPhoto(photo);else navigate('studio');};
$('rename-album').onclick=()=>{if(!state.album)return toast('Tạo album trước.',true);showAlbumDialog(state.album);};
$('album-form').onsubmit=async event=>{event.preventDefault();await busy(event.submitter,'Đang lưu…',async()=>{const edit=state.editingAlbum;const request=jsonRequest({name:$('album-name').value});if(edit)request.method='PATCH';const album=await api(edit?`/api/albums/${edit}`:'/api/albums',request);$('album-dialog').close();$('album-form').reset();if(edit){await refreshAlbums();await refreshPhotos();}else await chooseAlbum(album.id);toast(edit?'Đã đổi tên bộ ảnh.':'Đã tạo bộ ảnh. Bấm Thêm ảnh để lưu ảnh vào bộ này.');});};
async function downloadSources(ids){
  const created=await api('/api/exports',jsonRequest({photo_ids:ids}));
  const link=el('a');link.href=created.download_url;link.download='LumaNest.zip';document.body.append(link);link.click();link.remove();
  toast('Gói tải đã sẵn sàng. Ảnh nhập mới giữ nguyên file upload; ảnh cũ có ghi rõ trong manifest.');
}
$('selection-download').onclick=()=>busy($('selection-download'),'Đang đóng gói…',()=>downloadSources([...state.selectedIds]));
$('download-results').onclick=()=>busy($('download-results'),'Đang đóng gói…',()=>downloadSources(state.results.map(p=>p.id)));

$('photo-files').onchange=async()=>{
  const files=[...$('photo-files').files],albumId=state.album;if(!files.length||!albumId)return;
  if(state.uploading)return toast('Đang tải một nhóm ảnh. Chờ quá trình tải xong.',true);
  state.uploading=true;
  await busy($('add-photos'),'Đang tải…',async()=>{
    const groups=[];let group=[],bytes=0,accepted=0,duplicates=0,failed=0;
    for(const file of files){if(file.size>20*1024*1024){failed++;continue;}if(group.length>=12||bytes+file.size>96*1024*1024){groups.push(group);group=[];bytes=0;}group.push(file);bytes+=file.size;}if(group.length)groups.push(group);
    $('upload-state').classList.remove('hidden');
    try{
      for(let index=0;index<groups.length;index++){
        $('upload-state').textContent=`Đang tải nhóm ${index+1}/${groups.length}… Nhận diện tiếp tục chạy nền.`;
        const form=new FormData();groups[index].forEach(file=>form.append('files',file));
        const result=await api(`/api/albums/${albumId}/photos`,{method:'POST',body:form});accepted+=result.accepted;duplicates+=result.duplicates;failed+=result.errors.length;
        if(result.errors.length)toast(result.errors.slice(0,3).map(e=>`${e.name}: ${e.message}`).join('; '),true);
        await refreshAlbums();await refreshPhotos();
      }
      toast(`Đã nhận ${accepted} ảnh · ${duplicates} ảnh trùng · ${failed} lỗi. Theo dõi lập chỉ mục trong Hệ thống.`,!!failed);
      refreshTasks();
    }finally{$('upload-state').classList.add('hidden');await refreshAlbums();await refreshPhotos();}
  });state.uploading=false;$('photo-files').value='';
};

// Stable snapshot: a late result may never replace the preview of another photo.
$('run-style').onclick=()=>busy($('run-style'),'Đang sáng tạo…',async()=>{
  if(!state.selected)throw new Error('Chọn ảnh trước khi tạo tác phẩm.');
  if(state.styleGenerating)throw new Error('Đang tạo ảnh. Có thể dùng chế độ theo lô cho nhiều ảnh.');
  const photo={...state.selected};if(state.activeRecipe)return createFromStyleRecipe(state.activeRecipe,photo);
  state.styleGenerating=true;
  try{
    const form=new FormData();form.append('photo_id',photo.id);form.append('style_id',state.style);form.append('strength',$('strength').value);form.append('steps',$('style-steps').value);form.append('profile',$('speed-profile').value);
    if(state.style==='custom'){if(!$('style-file').files[0])throw new Error('Chọn một ảnh phong cách.');form.append('style_image',$('style-file').files[0]);}
    const job=await api('/api/stylize',{method:'POST',body:form,headers:{'Idempotency-Key':crypto.randomUUID()}});
    const done=await watchJob(job.job_id);if(state.selected?.id===photo.id)showOutput(done.result.image_url,done.result.download_url);
    await refreshOutputs();await refreshHealth();toast(`Đã tạo ảnh trong ${done.result.seconds} giây${done.result.cached?' · dùng lại kết quả đã lưu':''}.`);
  }finally{state.styleGenerating=false;}
});

refreshOutputs=async function(append=false){
  const album=state.album,version=++outputsRequestVersion;if(!append)outputOffset=0;
  const rows=await api(`/api/outputs?limit=50&offset=${outputOffset}${album?'&album_id='+encodeURIComponent(album):''}`);
  if(album!==state.album||version!==outputsRequestVersion)return;
  if(!append)$('output-history').replaceChildren();
  for(const output of rows){const card=el('article','photo-card'),button=el('button','image-button'),image=el('img');image.src=`/api/outputs/${output.id}/image`;image.alt=`${output.name} - ${output.style}`;image.loading='lazy';button.append(image);button.onclick=()=>{selectPhoto({id:output.photo_id,name:output.name});showOutput(`/api/outputs/${output.id}/image`,`/api/outputs/${output.id}/image?download=true`);};const info=el('div','photo-info');info.append(el('p','',output.title||state.styles.find(s=>s.id===output.style)?.name||output.style));if(output.width)info.append(el('small','output-size',`${output.width} × ${output.height} px`));card.append(button,info);$('output-history').append(card);}
  outputOffset+=rows.length;$('output-empty').classList.toggle('hidden',!!$('output-history').children.length);$('output-more').classList.toggle('hidden',rows.length<50);
};
$('output-more').onclick=()=>busy($('output-more'),'Đang tải…',()=>refreshOutputs(true));

// Reconnect independent jobs without making a page reload lose all progress.
let tasksTimer,taskBusy=false,lastJobsSignature='',lastIndexSignature='';
async function refreshTasks(){
  if(taskBusy)return;taskBusy=true;clearTimeout(tasksTimer);
  try{
    const jobs=await api('/api/jobs');
    const signature=jobs.map(j=>`${j.id}:${j.status}:${j.progress}`).join('|');
    const active=jobs.filter(j=>['queued','running'].includes(j.status));
    $('task-summary').textContent=active.length?`${active.length} tác vụ đang chờ hoặc xử lý`:'Không có tác vụ đang chạy';
    if(signature!==lastJobsSignature){
      const previous=lastJobsSignature;lastJobsSignature=signature;
      $('task-list').replaceChildren(...jobs.slice(0,12).map(job=>{
        const row=el('article',`task-row task-${job.status}`);
        const names={index:'Lập chỉ mục khuôn mặt',stylize:'Tạo ảnh', 'bulk-style':'Style theo lô'};
        const statuses={queued:'Đang chờ',running:'Đang xử lý',done:'Hoàn tất',error:'Có lỗi',cancelled:'Đã dừng'};
        row.append(el('b','',`${names[job.kind]||job.kind} · ${statuses[job.status]||job.status}`),el('p','',formatJobMessage(job.message)));
        const progress=el('progress');progress.max=1;progress.value=job.progress;row.append(progress);return row;
      }));
      const indexSignature=jobs.filter(j=>j.kind==='index').map(j=>`${j.id}:${j.status}:${j.progress}`).join('|');
      if(previous && lastIndexSignature!==indexSignature){await refreshAlbums();await refreshPhotos();}
      lastIndexSignature=indexSignature;
    }
    tasksTimer=setTimeout(refreshTasks,active.length?1800:8000);
    $('tasks-offline').classList.add('hidden');
  }catch(error){$('tasks-offline').classList.remove('hidden');tasksTimer=setTimeout(refreshTasks,4000);}
  finally{taskBusy=false;}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refreshTasks();});
refreshTasks();
addSelectionControls();
