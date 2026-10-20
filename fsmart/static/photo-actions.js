'use strict';
let trashRows=[],trashRequestVersion=0,photoDestruction=null,undoTrashIds=[];

function updateTrashSelection(){
  const count=state.trashSelectedIds.size;
  $('trash-selection-count').textContent=`${count} ảnh đã chọn`;
  $('trash-restore-selected').disabled=!count;$('trash-purge-selected').disabled=!count;
  document.querySelectorAll('#trash-gallery input[type="checkbox"]').forEach(input=>{input.checked=state.trashSelectedIds.has(input.dataset.photo);});
}

async function refreshTrash(append=false){
  const albumId=state.album,version=++trashRequestVersion;
  if(!albumId){trashRows=[];$('trash-gallery').replaceChildren();return;}
  const rows=await api(`/api/albums/${albumId}/trash?limit=100&offset=${append?trashRows.length:0}`);
  if(albumId!==state.album||version!==trashRequestVersion)return;
  trashRows=append?[...trashRows,...rows]:rows;
  $('trash-gallery').replaceChildren(...trashRows.map(photo=>{
    const card=el('article','photo-card trash-card'),image=el('img');image.src=`/api/trash/${photo.id}/thumbnail`;image.alt=photo.name;image.loading='lazy';
    const preview=el('div','trash-image');preview.append(image);
    const label=el('label','photo-select'),input=el('input');input.type='checkbox';input.dataset.photo=photo.id;input.setAttribute('aria-label',`Chọn trong thùng rác: ${photo.name}`);input.onchange=()=>{if(input.checked)state.trashSelectedIds.add(photo.id);else state.trashSelectedIds.delete(photo.id);updateTrashSelection();};label.append(input,el('span','','Chọn'));
    const info=el('div','trash-card-info');info.append(el('b','',photo.name),el('small','',`Đã xóa ${new Date(photo.deleted_at).toLocaleString('vi-VN')}`));
    const actions=el('div','trash-card-actions'),restore=el('button','button outline','Khôi phục'),purge=el('button','button subtle danger-text','Xóa vĩnh viễn');
    restore.onclick=()=>busy(restore,'Đang khôi phục…',()=>restorePhotos([photo.id]));purge.onclick=()=>requestPurge([photo.id]);actions.append(restore,purge);card.append(preview,label,info,actions);return card;
  }));
  $('trash-empty').classList.toggle('hidden',trashRows.length>0);$('trash-more').classList.toggle('hidden',rows.length<100);
  $('trash-summary').textContent=`${currentAlbum()?.trash_count || 0} ảnh trong Thùng rác của bộ này · khôi phục để dùng lại`;
  updateTrashSelection();
}

async function refreshPhotoViews(){
  await refreshAlbums();await Promise.all([refreshPhotos(),refreshOutputs(),refreshTrash()]);
  if(state.query)scheduleFaceSearch();
}

function openPhotoConfirmation(mode,ids){
  if(!ids.length)return;
  photoDestruction={mode,ids:[...ids],albumId:state.album};
  const permanent=mode==='purge';
  $('photo-confirm-title').textContent=permanent?`Xóa vĩnh viễn ${ids.length} ảnh?`:`Chuyển ${ids.length} ảnh vào Thùng rác?`;
  $('photo-confirm-description').textContent=permanent?'Xóa file nguồn, dữ liệu khuôn mặt và các tác phẩm đi kèm. Không thể khôi phục sau bước này.':'Ảnh và tác phẩm sẽ ẩn khỏi bộ ảnh, tìm kiếm và sáng tạo. File được giữ trong Thùng rác để bạn khôi phục; dung lượng chưa được giải phóng.';
  $('purge-acknowledge').checked=false;$('purge-acknowledge').required=permanent;$('purge-acknowledge-field').classList.toggle('hidden',!permanent);
  $('photo-confirm-submit').textContent=permanent?'Xóa vĩnh viễn':'Chuyển vào Thùng rác';$('photo-confirm-submit').disabled=permanent;
  $('photo-confirm-dialog').showModal();$('photo-confirm-cancel').focus();
}
function requestTrash(ids){openPhotoConfirmation('trash',ids);}
function requestPurge(ids){openPhotoConfirmation('purge',ids);}

async function restorePhotos(ids){
  const result=await api('/api/trash/restore',jsonRequest({photo_ids:ids}));
  for(const id of ids)state.trashSelectedIds.delete(id);
  if(ids.some(id=>undoTrashIds.includes(id))){undoTrashIds=[];$('trash-undo').classList.add('hidden');}
  await refreshPhotoViews();toast(`Đã khôi phục ${result.restored} ảnh cùng khuôn mặt và tác phẩm.`);
}

$('selection-delete').onclick=()=>requestTrash([...state.selectedIds]);
$('trash-select-visible').onclick=()=>{trashRows.forEach(photo=>state.trashSelectedIds.add(photo.id));updateTrashSelection();};
$('trash-clear-selection').onclick=()=>{state.trashSelectedIds.clear();updateTrashSelection();};
$('trash-restore-selected').onclick=()=>busy($('trash-restore-selected'),'Đang khôi phục…',()=>restorePhotos([...state.trashSelectedIds]));
$('trash-purge-selected').onclick=()=>requestPurge([...state.trashSelectedIds]);
$('trash-more').onclick=()=>busy($('trash-more'),'Đang tải…',()=>refreshTrash(true));
$('undo-trash-button').onclick=()=>busy($('undo-trash-button'),'Đang hoàn tác…',()=>restorePhotos(undoTrashIds));
$('dismiss-trash-undo').onclick=()=>$('trash-undo').classList.add('hidden');
$('purge-acknowledge').onchange=()=>{$('photo-confirm-submit').disabled=!$('purge-acknowledge').checked;};
$('photo-confirm-close').onclick=()=>$('photo-confirm-dialog').close();
$('photo-confirm-cancel').onclick=()=>$('photo-confirm-dialog').close();
$('photo-confirm-form').onsubmit=async event=>{
  event.preventDefault();const action=photoDestruction;if(!action)return;
  if(action.mode==='purge'&&!$('purge-acknowledge').checked)return;
  await busy($('photo-confirm-submit'),'Đang xử lý…',async()=>{
    const result=await api(action.mode==='purge'?'/api/trash/purge':`/api/albums/${action.albumId}/trash`,jsonRequest({photo_ids:action.ids}));
    $('photo-confirm-dialog').close();
    for(const id of action.ids){state.selectedIds.delete(id);state.trashSelectedIds.delete(id);state.extraPhotos.delete(id);}
    if(action.ids.includes(state.selected?.id)){state.selected=null;$('studio-photo').value='';resetStudio();}
    updateSelection();
    if(action.mode==='trash'){
      undoTrashIds=action.ids;$('trash-undo-message').textContent=`Đã chuyển ${result.trashed} ảnh vào Thùng rác.`;$('trash-undo').classList.remove('hidden');
    }else{
      undoTrashIds=undoTrashIds.filter(id=>!action.ids.includes(id));if(!undoTrashIds.length)$('trash-undo').classList.add('hidden');
      toast(result.file_cleanup_errors?`Đã xóa dữ liệu ảnh; còn ${result.file_cleanup_errors} file đang bị khóa trên ổ. Kiểm tra log sau khi đóng tải file.`:`Đã xóa vĩnh viễn ${result.purged} ảnh.`,!!result.file_cleanup_errors);
    }
    await refreshPhotoViews();
  });
};
document.addEventListener('fsm:page',event=>{if(event.detail==='trash')refreshTrash().catch(error=>toast(error.message,true));});
