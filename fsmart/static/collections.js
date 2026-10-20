'use strict';

function collectionSearchKey(value){return value.toLocaleLowerCase('vi').normalize('NFD').replace(/\p{Diacritic}/gu,'').replace(/đ/g,'d');}
function renderCollections(){
  const term=collectionSearchKey($('collection-filter').value.trim());
  const visible=state.albums.filter(album=>collectionSearchKey(album.name).includes(term));
  const count=state.albums.reduce((sum,album)=>sum+album.photo_count,0);
  $('collections-summary').textContent=`${state.albums.length} bộ ảnh · ${count} ảnh${term?` · ${visible.length} bộ phù hợp`:''}`;
  $('collections-grid').replaceChildren(...visible.map(album=>{
    const card=el('button','collection-card');card.type='button';card.setAttribute('aria-label',`Mở bộ ảnh ${album.name}`);
    const cover=el('div','collection-cover');
    if(album.cover_photo_id){const image=el('img');image.src=`/api/photos/${album.cover_photo_id}/image?thumbnail=true`;image.alt='';image.loading='lazy';image.onerror=()=>{image.remove();cover.append(el('span','collection-cover-empty','▧'));};cover.append(image);}
    else cover.append(el('span','collection-cover-empty','▧'));
    cover.append(el('span','collection-photo-count',`${album.photo_count} ảnh`));
    const info=el('div','collection-card-info');info.append(el('h3','',album.name));
    info.append(el('p','',album.photo_count?`${album.indexed_count} ảnh đã xử lý · ${album.photo_count-album.indexed_count} chưa sẵn sàng`:'Bộ ảnh mới · thêm những tấm ảnh đầu tiên'));
    info.append(el('span','collection-card-open','Mở bộ ảnh ↗'));card.append(cover,info);
    card.onclick=()=>chooseAlbum(album.id).catch(error=>toast(error.message,true));return card;
  }));
  $('collections-empty').classList.toggle('hidden',visible.length>0);
  $('collections-empty-title').textContent=term?'Không tìm thấy bộ ảnh':'Tạo bộ ảnh đầu tiên';
  $('collections-empty-description').textContent=term?'Thử tên khác hoặc xóa bộ lọc để xem tất cả bộ ảnh.':'Mỗi bộ ảnh có thư viện, tìm khuôn mặt và tác phẩm riêng.';
  $('empty-collection').textContent=term?'Xóa bộ lọc':'＋ Tạo bộ ảnh mới';
  $('empty-collection').onclick=()=>{if(term){$('collection-filter').value='';renderCollections();}else showAlbumDialog();};
}

$('create-collection').onclick=()=>showAlbumDialog();
$('collection-filter').oninput=renderCollections;
$('all-collections').onclick=()=>navigate('collections');
$('rename-collection').onclick=()=>showAlbumDialog(state.album);
$('collection-switcher').onchange=()=>chooseAlbum($('collection-switcher').value,['library','search','studio','trash'].includes(state.page)?state.page:'library').catch(error=>toast(error.message,true));

const collectionTabs=[...document.querySelectorAll('.collection-tabs [role="tab"]')];
for(const tab of collectionTabs){
  tab.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    event.preventDefault();let index=collectionTabs.indexOf(tab);
    index=event.key==='Home'?0:event.key==='End'?collectionTabs.length-1:(index+(event.key==='ArrowRight'?1:-1)+collectionTabs.length)%collectionTabs.length;
    navigate(collectionTabs[index].dataset.page);collectionTabs[index].focus();
  });
}

let moveSelection=null,movingPhotos=false;
$('selection-move').onclick=()=>{
  if(!state.selectedIds.size||!state.album)return;
  moveSelection={albumId:state.album,ids:[...state.selectedIds]};
  $('move-summary').textContent=`Chuyển ${moveSelection.ids.length} ảnh từ bộ “${currentAlbum().name}”. File nguồn, khuôn mặt và tác phẩm đi cùng ảnh.`;
  $('move-destination').replaceChildren();
  const create=el('option','','＋ Tạo bộ ảnh mới');create.value='__new__';$('move-destination').append(create);
  for(const album of state.albums.filter(album=>album.id!==state.album)){
    const option=el('option','',`${album.name} · ${album.photo_count} ảnh`);option.value=album.id;$('move-destination').append(option);
  }
  $('move-new-name').value='';updateMoveDestination();$('move-dialog').showModal();$('move-new-name').focus();
};
function updateMoveDestination(){const creating=$('move-destination').value==='__new__';$('move-new-field').classList.toggle('hidden',!creating);$('move-new-name').required=creating;}
$('move-destination').onchange=updateMoveDestination;
$('close-move-dialog').onclick=()=>$('move-dialog').close();
$('cancel-move').onclick=()=>$('move-dialog').close();
$('move-form').onsubmit=async event=>{
  event.preventDefault();if(movingPhotos||!moveSelection)return;
  movingPhotos=true;
  try{await busy($('move-submit'),'Đang chuyển…',async()=>{
    const destination=$('move-destination').value;
    const payload={photo_ids:moveSelection.ids};
    if(destination==='__new__')payload.new_album_name=$('move-new-name').value;else payload.destination_album_id=destination;
    const result=await api(`/api/albums/${moveSelection.albumId}/move-photos`,jsonRequest(payload));
    $('move-dialog').close();state.selectedIds.clear();updateSelection();
    await chooseAlbum(result.destination_album_id);toast(`Đã chuyển ${result.moved} ảnh vào bộ đang mở.`);
  });}finally{movingPhotos=false;}
};

// Show the new collection overview once; later reloads restore the current tool.
if(localStorage.getItem('fsm-library-layout')!=='collections-v1'){
  localStorage.setItem('fsm-library-layout','collections-v1');localStorage.setItem('fsm-page','collections');
}
mountPhotoPicker($('studio-photo'));
start().then(()=>Promise.all([refreshBatches(),refreshTrash()]));
