function clearStyleRecipe() {
  state.activeRecipe = null;
  $('strength').disabled = false;
  $('style-steps').disabled = false;
  $('ai-style-active').classList.add('hidden');
}

function applyStyleRecipe(plan) {
  state.activeRecipe = plan;
  state.style = ['reference','artwork'].includes(plan.engine) ? 'custom' : plan.preset;
  $('strength').value = plan.strength;
  $('strength-value').textContent = `${Math.round(plan.strength*100)}%`;
  $('style-steps').value = plan.steps;
  $('strength').disabled = true;
  $('style-steps').disabled = true;
  document.querySelectorAll('.style-option').forEach(button => button.classList.toggle('selected', plan.engine === 'preset' && button.dataset.style === plan.preset));
  $('custom-style').classList.add('hidden');
  $('ai-style-active').textContent = `Phong cách từ chat: ${plan.title}. Mô tả tiếp trong chat để chỉnh đề xuất, hoặc chọn preset khác bên dưới để chỉnh thủ công.`;
  $('ai-style-active').classList.remove('hidden');
}

async function createFromStyleRecipe(plan, photo) {
  if (state.styleGenerating) throw new Error('Đang tạo một tác phẩm. Chờ tác vụ hiện tại hoàn tất.');
  state.styleGenerating = true;
  $('run-style').disabled = true;
  try {
    selectPhoto(photo);
    applyStyleRecipe(plan);
    const job = await api('/api/stylize/from-chat', jsonRequest({photo_id: photo.id, plan_id: plan.id, profile: $('speed-profile').value}));
    const done = await watchJob(job.job_id);
    if (state.selected?.id === photo.id) showOutput(done.result.image_url, done.result.download_url);
    await refreshOutputs();
    toast('Đã tạo ảnh theo phong cách từ chat.');
    return done.result;
  } finally {
    state.styleGenerating = false;
    $('run-style').disabled = !state.selected;
  }
}

$('describe-style').onclick = () => document.dispatchEvent(new CustomEvent('fsm:describe-style'));
