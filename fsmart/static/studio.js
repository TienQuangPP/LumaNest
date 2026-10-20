'use strict';
// One studio, three tools. Preview responses are accepted only for the latest intent.
const studioPanel=document.querySelector('.controls-panel');
const sharedStudioNodes=[studioPanel.querySelector('.panel-title'),studioPanel.querySelector('label[for="studio-photo"]'),$('studio-photo')];
const artPane=el('div','studio-tool-pane');artPane.id='studio-tool-art';
for(const child of [...studioPanel.children])if(!sharedStudioNodes.includes(child))artPane.append(child);
studioPanel.querySelector('h3').textContent='Công cụ sáng tạo';
const toolTabs=el('div','studio-tool-tabs');toolTabs.setAttribute('role','tablist');toolTabs.setAttribute('aria-label','Công cụ sáng tạo');
const colourPane=el('div','studio-tool-pane hidden');colourPane.id='studio-tool-colour';
colourPane.append(colourLab.lastElementChild);colourLab.remove();
const subjectPane=el('div','studio-tool-pane hidden');subjectPane.id='studio-tool-subject';
subjectPane.innerHTML=`<p class="helper">Bấm lên người hoặc vật trong ảnh. Thêm điểm bỏ để loại vùng chọn thừa.</p><div class="subject-point-modes"><label><input type="radio" name="subject-point" value="1" checked> + Chọn</label><label><input type="radio" name="subject-point" value="0"> − Bỏ</label><button id="subject-undo" class="text-button">Hoàn tác điểm</button></div><div class="subject-actions"><button id="subject-segment" class="button primary">Tách vùng chọn</button><button id="subject-reset" class="button outline">Chọn lại</button></div><div id="subject-masks" class="subject-masks" aria-label="Các vùng chọn gợi ý"></div><label class="field-label" for="subject-effect">Hiệu ứng</label><select id="subject-effect"><option value="cutout">PNG nền trong suốt</option><option value="colorpop">Giữ màu chủ thể</option><option value="blur">Làm mờ nền</option><option value="art-background">Giữ chủ thể · nền nghệ thuật</option></select><button id="subject-save" class="button primary full" disabled>Lưu phiên bản chủ thể</button><button id="subject-edit" class="text-button hidden">Chỉnh vùng chọn ↗</button><p id="subject-status" class="helper" role="status">Chọn ảnh để bắt đầu.</p>`;
studioPanel.append(toolTabs,artPane,colourPane,subjectPane);
const previewStatus=el('p','studio-preview-status');previewStatus.id='studio-preview-status';previewStatus.setAttribute('role','status');
document.querySelector('.canvas-top').after(previewStatus);
const subjectStage=el('div','subject-stage hidden');
subjectStage.innerHTML=`<div id="subject-media" class="subject-media" role="button" tabindex="0" aria-label="Chọn điểm trên chủ thể; Enter chọn điểm giữa ảnh"><img id="subject-image" alt="Ảnh để chọn chủ thể"><img id="subject-overlay" class="subject-overlay hidden" alt="Vùng được chọn"><div id="subject-dots" class="subject-dots"></div></div>`;
$('comparison').after(subjectStage);
let studioTool='art',stylePreviewTimer,stylePreviewURL,subjectVersion=0,subjectPoints=[],subjectMasks=[],subjectMask=null,subjectWorking=false;
function syncCompactWorkspace(){document.body.classList.toggle('studio-active',state.page==='studio');}
document.addEventListener('fsm:page',syncCompactWorkspace);syncCompactWorkspace();
function setStudioTool(tool,focus=false){
  studioTool=tool;invalidateStudioPreview();
  ['art','colour','subject'].forEach(id=>{const active=id===tool;const tab=$('studio-tab-'+id);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;$('studio-tool-'+id).classList.toggle('hidden',!active);if(active&&focus)tab.focus();});
  showSubjectStage(tool==='subject'&&!!state.selected);
  if(tool==='subject')previewStatus.textContent='Chọn vùng cần giữ bằng điểm trên ảnh.';
  if(tool==='colour')previewStatus.textContent='Chọn một bảng màu để xem trước.';
  if(tool==='art'&&state.selected)scheduleStylePreview();
}
['art','colour','subject'].forEach((id,index)=>{
  const tab=el('button','', ['Nghệ thuật','Màu ảnh','Chủ thể'][index]);tab.id='studio-tab-'+id;tab.type='button';tab.setAttribute('role','tab');tab.setAttribute('aria-controls','studio-tool-'+id);tab.setAttribute('aria-selected',String(!index));tab.tabIndex=index?-1:0;
  tab.onclick=()=>setStudioTool(id);tab.onkeydown=event=>{const ids=['art','colour','subject'];if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();setStudioTool(ids[event.key==='Home'?0:event.key==='End'?2:(index+(event.key==='ArrowRight'?1:2))%3],true);};
  toolTabs.append(tab);const pane=$('studio-tool-'+id);pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby',tab.id);
});
function hidePreviewResult(){ $('after-wrap').classList.add('hidden');$('compare-control').classList.add('hidden');$('after-label').classList.add('hidden');$('download-art').classList.add('hidden'); }
function scheduleStylePreview(){
  clearTimeout(stylePreviewTimer);invalidateStudioPreview();
  if(studioTool!=='art'||!state.selected)return;
  hidePreviewResult();colourSourceOutput=null;
  if(state.style==='custom'){previewStatus.textContent='Chọn ảnh phong cách rồi tạo tác phẩm để xem kết quả.';return;}
  previewStatus.textContent='Đang chuẩn bị mẫu vừa chọn…';
  stylePreviewTimer=setTimeout(()=>previewStyle().catch(error=>{if(error.name!=='AbortError')previewStatus.textContent=error.message;}),240);
}
async function previewStyle(){
  const photo=state.selected?.id,style=state.style,epoch=studioPreviewEpoch;if(!photo||style==='custom'||studioTool!=='art')return;
  const controller=new AbortController();studioPreviewAbort=controller;
  const query=new URLSearchParams({style,strength:$('strength').value});let response;
  for(let attempt=0;attempt<12;attempt++){
    if(controller.signal.aborted||epoch!==studioPreviewEpoch)return;
    response=await fetch(`/api/photos/${photo}/style-preview?${query}`,{signal:controller.signal});
    if(response.status!==429)break;
    await new Promise(resolve=>setTimeout(resolve,500));
  }
  if(!response.ok){const data=await response.json();throw new Error(data.detail||'Không xem trước được phong cách.');}
  const blob=await response.blob();if(controller.signal.aborted||epoch!==studioPreviewEpoch||state.selected?.id!==photo||state.style!==style)return;
  if(stylePreviewURL)URL.revokeObjectURL(stylePreviewURL);stylePreviewURL=URL.createObjectURL(blob);
  oldShowOutput(stylePreviewURL,'');$('download-art').classList.add('hidden');
  const name=state.styles.find(item=>item.id===style)?.name||style;$('after-label').textContent='Xem trước · '+name;
  previewStatus.textContent=`${name} · xem trước 512 px. Bấm Tạo ảnh nghệ thuật để lưu.`;
}
document.addEventListener('fsm:style-picked',()=>{if(studioTool!=='art')setStudioTool('art');else scheduleStylePreview();});
const compactResetStudio=resetStudio;resetStudio=function(){
  compactResetStudio();subjectVersion++;subjectPoints=[];subjectMasks=[];subjectMask=null;subjectWorking=false;
  $('subject-masks').replaceChildren();$('subject-overlay').classList.add('hidden');$('subject-dots').replaceChildren();$('subject-save').disabled=true;$('subject-segment').disabled=false;
  previewStatus.textContent='';$('subject-status').textContent=state.selected?'Bấm điểm trên chủ thể cần giữ.':'Chọn ảnh để bắt đầu.';
  $('subject-edit').classList.add('hidden');if(state.selected)$('subject-image').src=`/api/photos/${state.selected.id}/image`;
  showSubjectStage(studioTool==='subject'&&!!state.selected);if(studioTool==='art')scheduleStylePreview();
};
const compactShowOutput=showOutput;showOutput=function(image,download){compactShowOutput(image,download);clearTimeout(stylePreviewTimer);previewStatus.textContent='Phiên bản đã lưu';showSubjectStage(false);if(studioTool==='subject')$('subject-edit').classList.remove('hidden');};
function showSubjectStage(active){subjectStage.classList.toggle('hidden',!active);$('comparison').classList.toggle('hidden',active);if(active){$('compare-control').classList.add('hidden');$('download-art').classList.add('hidden');}}
function drawSubjectPoints(){
  $('subject-dots').replaceChildren(...subjectPoints.map(point=>{const dot=el('span',`subject-dot ${point.label?'positive':'negative'}`,point.label?'+':'−');dot.style.left=point.x*100+'%';dot.style.top=point.y*100+'%';return dot;}));
  subjectMask=null;$('subject-overlay').classList.add('hidden');$('subject-save').disabled=true;$('subject-masks').replaceChildren();
  $('subject-status').textContent=`${subjectPoints.length}/12 điểm · Bấm Tách vùng chọn để cập nhật.`;
}
function addSubjectPoint(x,y){if(subjectWorking||!state.selected)return;if(subjectPoints.length>=12){toast('Tối đa 12 điểm. Hoàn tác hoặc chọn lại.',true);return;}subjectPoints.push({x:Math.max(0,Math.min(1,x)),y:Math.max(0,Math.min(1,y)),label:Number(document.querySelector('[name="subject-point"]:checked').value)});drawSubjectPoints();}
$('subject-media').onclick=event=>{const rect=$('subject-image').getBoundingClientRect();if(rect.width&&rect.height)addSubjectPoint((event.clientX-rect.left)/rect.width,(event.clientY-rect.top)/rect.height);};
$('subject-media').onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();addSubjectPoint(.5,.5);}};
$('subject-undo').onclick=()=>{if(subjectWorking)return;subjectPoints.pop();drawSubjectPoints();};
$('subject-reset').onclick=()=>{if(subjectWorking)return;subjectVersion++;subjectPoints=[];drawSubjectPoints();showSubjectStage(!!state.selected);};
$('subject-edit').onclick=()=>showSubjectStage(!!state.selected);
function chooseSubjectMask(mask){subjectMask=mask;$('subject-overlay').src=mask.image_url;$('subject-overlay').classList.remove('hidden');$('subject-save').disabled=false;for(const button of $('subject-masks').children)button.setAttribute('aria-pressed',String(button.dataset.mask===mask.id));}
$('subject-segment').onclick=()=>busy($('subject-segment'),'Đang tách…',async()=>{
  if(!state.selected||!subjectPoints.some(point=>point.label))throw new Error('Chọn ít nhất một điểm + trên chủ thể.');
  const photo=state.selected.id,version=subjectVersion;subjectWorking=true;
  try{const result=await api('/api/subjects/segment',jsonRequest({photo_id:photo,points:subjectPoints}));if(version!==subjectVersion||state.selected?.id!==photo)return;
    subjectMasks=result.masks;$('subject-masks').replaceChildren(...subjectMasks.map((mask,index)=>{const button=el('button','subject-mask');button.dataset.mask=mask.id;button.setAttribute('aria-label',`Vùng chọn ${index+1}`);const image=el('img');image.src=mask.image_url;image.alt='';image.style.backgroundImage=`url(/api/photos/${photo}/image?thumbnail=true)`;button.append(image,el('span','',`Vùng ${index+1}`));button.onclick=()=>chooseSubjectMask(mask);return button;}));
    chooseSubjectMask(subjectMasks[0]);$('subject-status').textContent=`Chọn vùng phù hợp nhất · ${result.seconds}s${result.cached?' · dùng lại vùng đã lưu':''}`;
  }finally{if(version===subjectVersion)subjectWorking=false;}
});
$('subject-save').onclick=()=>busy($('subject-save'),'Đang lưu…',async()=>{
  if(!subjectMask||!state.selected)throw new Error('Tách và chọn một vùng trước.');
  const photo=state.selected.id,effect=$('subject-effect').value;
  if(effect==='art-background'&&!colourSourceOutput)throw new Error('Tạo hoặc mở tác phẩm nghệ thuật trước, rồi chọn chủ thể.');
  const result=await api('/api/subjects/render',jsonRequest({mask_id:subjectMask.id,effect,source_output:effect==='art-background'?colourSourceOutput:null}));
  if(state.selected?.id===photo){showOutput(result.image_url,result.download_url);$('after-label').textContent=result.title;}
  await refreshOutputs();toast('Đã lưu phiên bản chủ thể.');
});
// Keep batch progress and saved versions close, without extending the working canvas.
for(const [id,title] of [['batch-section','Hàng đợi xử lý'],['output-history','Các phiên bản đã lưu']]){
  const node=$(id),details=el('details','studio-fold'),summary=el('summary','',title);node.before(details);details.append(summary);
  if(id==='batch-section'){details.append(node);node.querySelector('.section-top').remove();}
  else{const heading=details.previousElementSibling;heading?.classList.contains('section-top')&&heading.remove();details.append(node,$('output-more'),$('output-empty'));}
  if(id==='batch-section')new MutationObserver(()=>{if($('batch-list').children.length)details.open=true;}).observe($('batch-list'),{childList:true});
}
