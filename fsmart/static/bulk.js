'use strict';
let bulkTimer;
let bulkRefresh = false;
let bulkRefreshQueued=false;
let bulkOutputSignature = '';
function renderBatch(job,order){
  let row=document.querySelector(`.batch-row[data-job="${job.id}"]`);
  if(!row){row=el('article','batch-row');row.dataset.job=job.id;const heading=el('div','batch-heading');heading.append(el('b'),el('small'));const progress=el('progress');progress.max=1;row.append(heading,el('p','batch-message'),progress,el('small','batch-stats muted'),el('div','batch-actions'));$('batch-list').append(row);}
  row.style.order=order;
  const detail=job.result, running=['queued','running'].includes(job.status),closed=!!detail?.context?.closed;
  const label={queued:'Đang chờ',running:'Đang xử lý',done:detail?.failed?'Hoàn tất có lỗi':'Hoàn tất',error:'Thất bại',cancelled:closed?'Đã kết thúc':'Tạm dừng'}[job.status]||job.status;
  row.classList.toggle('batch-error',job.status==='error'||!!detail?.failed);
  row.querySelector('.batch-heading b').textContent=`${label} · ${detail?.style||'Style cả album'}${detail?.context?.album_name?' · '+detail.context.album_name:''}`;
  row.querySelector('.batch-heading small').textContent=new Date(job.created).toLocaleString('vi-VN');
  row.querySelector('.batch-message').textContent=job.message;row.querySelector('progress').value=job.progress;
  row.querySelector('.batch-stats').textContent=detail?`${{fast:'512 px',balanced:'768 px',quality:'1024 px'}[detail.profile]||detail.profile} · ${detail.images_per_second?detail.images_per_second.toFixed(2)+' mục/giây':'Đang chuẩn bị'} · ${detail.cached||0} dùng lại`:'';
  const actionKey=`${running}:${closed}:${job.status}:${!!detail?.failed}:${!!detail?.download_url}`;
  if(row.dataset.actions===actionKey)return;
  row.dataset.actions=actionKey;const actions=row.querySelector('.batch-actions');actions.replaceChildren();
  if(running){const stop=el('button','button subtle','Tạm dừng sau ảnh hiện tại');stop.onclick=()=>busy(stop,'Đang dừng…',async()=>{await api(`/api/batches/${job.id}/cancel`,{method:'POST'});await refreshBatches();});actions.append(stop);}
  else if(!closed && (job.status!=='done'||detail?.failed)){const resume=el('button','button outline','Tiếp tục / thử lại ảnh lỗi');resume.onclick=()=>busy(resume,'Đang tiếp tục…',async()=>{await api(`/api/batches/${job.id}/resume`,{method:'POST'});await refreshBatches();});actions.append(resume);const finish=el('button','button subtle','Bỏ phần còn lại, kết thúc lô');finish.onclick=()=>busy(finish,'Đang kết thúc…',async()=>{await api(`/api/batches/${job.id}/finish`,{method:'POST'});await refreshBatches();});actions.append(finish);}
  if(detail?.download_url){const link=el('a','button outline','↓ Tải ZIP kết quả');link.href=detail.download_url;link.download='';actions.append(link);}
}
async function refreshBatches() {
  if (bulkRefresh){bulkRefreshQueued=true;return;}
  bulkRefresh = true;
  clearTimeout(bulkTimer);
  try {
    const albumId=state.album;
    const jobs=albumId?await api(`/api/batches?album_id=${encodeURIComponent(albumId)}`):[];
    if(albumId!==state.album)return;
    const ids=new Set(jobs.slice(0,8).map(job=>job.id));
    for(const node of $('batch-list').children)if(!ids.has(node.dataset.job))node.remove();
    $('batch-empty').classList.toggle('hidden', jobs.length > 0);
    jobs.slice(0,8).forEach(renderBatch);
    const active = jobs.some(x => ['queued','running'].includes(x.status));
    bulkTimer = setTimeout(refreshBatches, active ? 1000 : 5000);
    const signature = jobs.map(x => `${x.id}:${x.result?.completed || 0}`).join('|');
    if (signature !== bulkOutputSignature) {bulkOutputSignature = signature; await refreshOutputs();}
  } catch (error) {
    bulkTimer = setTimeout(refreshBatches, 5000);
  } finally {bulkRefresh=false;if(bulkRefreshQueued){bulkRefreshQueued=false;refreshBatches();}}
}
async function startStyleBatch(photoIds=null){
  if (!state.album || !currentAlbum()?.photo_count) throw new Error('Thêm ảnh vào album trước khi chạy lô.');
  const recipe = state.activeRecipe,album=currentAlbum();
  if (state.style === 'custom' || recipe?.engine === 'reference') throw new Error('Chạy nhanh cả album dùng một trong 4 preset. Phong cách ảnh mẫu/VGG19 vẫn tạo từng ảnh và cần nhiều thời gian hơn.');
  const result = await api('/api/stylize/batch', jsonRequest({album_id:album.id, photo_ids:photoIds, style:recipe?.preset || state.style, strength:recipe?.strength ?? Number($('strength').value), profile:$('speed-profile').value}));
  toast(`Đã xếp hàng ${result.total} ảnh trong bộ ${album.name}. Tiến độ được lưu sau từng ảnh.`);
  await refreshBatches();if(state.album===album.id&&state.page==='studio')$('batch-section').scrollIntoView({behavior:'smooth',block:'start'});
}
$('run-batch').onclick=()=>busy($('run-batch'),'Đang tạo lô…',()=>startStyleBatch());
$('run-selection-batch').onclick=()=>busy($('run-selection-batch'),'Đang tạo lô…',()=>startStyleBatch([...state.selectedIds]));
