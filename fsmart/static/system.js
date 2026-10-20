'use strict';
let systemRefreshing=false;
async function refreshSystem(){
  if(systemRefreshing)return;systemRefreshing=true;
  try{
    const info=await api('/api/system/status');
    const backend=info.models.style_backend==='chưa nạp'?(info.models.openvino_installed?'OpenVINO CPU đã cài · chờ nạp preset':'PyTorch · chờ nạp model'):info.models.style_backend;
    const data=[['Bộ xử lý',info.cpu],['Backend style',backend],['Dung lượng còn trống',`${info.disk_free_gb} GB`],['Thư viện',`${info.counts.photos} ảnh · ${info.counts.faces} khuôn mặt`],['Lập chỉ mục',`${info.counts.ready} sẵn sàng · ${info.counts.pending} đang chờ · ${info.counts.failed} lỗi`],['GPT',info.chat_configured?'Đã cấu hình key trong phiên':'Chưa cấu hình key · preset vẫn chạy cục bộ']];
    data[5]=['Trợ lý',info.chat?.provider==='local-model'?info.chat.model:info.chat_configured?'OpenAI đã cấu hình':'Hướng dẫn có sẵn'];
    data.push(['Chọn chủ thể',info.subject_model_installed?'Meta SAM 2.1 Tiny · trên máy':'Chưa tải model']);
    $('system-metrics').replaceChildren(...data.map(([label,value])=>{const card=el('div','system-metric');card.append(el('small','',label),el('b','',value));return card;}));
    $('system-connection').textContent=`Đã kết nối · ${new Date(info.checked_at).toLocaleTimeString('vi-VN')}`;
  }catch(error){$('system-connection').textContent=error.message;}
  finally{systemRefreshing=false;}
}
$('refresh-system').onclick=refreshSystem;
$('verify-system').onclick=()=>busy($('verify-system'),'Đang kiểm tra file và dữ liệu…',async()=>{
  const report=await api('/api/system/verify',{method:'POST'});
  $('verification-summary').textContent=report.passed?`Không phát hiện lỗi toàn vẹn trong các kiểm tra đã chạy · ${report.seconds} giây`:'Phát hiện dữ liệu cần xử lý. Xem từng mục bên dưới.';
  $('verification-summary').className=report.passed?'verification-ok':'verification-error';
  $('verification-checks').replaceChildren(...report.checks.map(check=>{const skipped=check.applicable===false;const row=el('li',skipped?'check-neutral':check.ok?'check-ok':'check-fail');row.append(el('b','',skipped?'CHƯA CÓ':check.ok?'ĐẠT':'LỖI'),document.createTextNode(` ${check.label}${check.checked_count!==undefined?` · ${check.checked_count} mục đã kiểm tra`:''}${check.count?` · ${check.count} lỗi`:''}`));return row;}));
  $('verification-warnings').replaceChildren(...report.warnings.map(text=>el('p','',text)));
  $('repair-thumbnails').disabled=!report.counts.missing_thumbnails;
  await refreshSystem();
});
$('repair-thumbnails').onclick=()=>busy($('repair-thumbnails'),'Đang khôi phục ảnh thu nhỏ…',async()=>{const result=await api('/api/system/repair-thumbnails',{method:'POST'});toast(`Đã khôi phục ${result.repaired} ảnh thu nhỏ · ${result.failed} lỗi.`);await refreshPhotos();});
document.addEventListener('fsm:page',event=>{if(event.detail==='system')refreshSystem();});
if(state.page==='system')refreshSystem();
