/* Query selection is the search trigger. No second, hidden step below a tall preview. */
let faceSearchTimer, faceSearchController, faceSearchVersion = 0, queryUploadVersion = 0, lastFaceSearchSignature = '';

function showSearchState(kind, detail = '') {
  const messages = {
    idle: ['Bắt đầu bằng một khuôn mặt', 'Chọn ảnh tham chiếu. App sẽ tự tìm ảnh có khuôn mặt đã chọn.'],
    detecting: ['Đang đọc ảnh tham chiếu…', 'Đang phát hiện khuôn mặt. Kết quả sẽ được tìm tự động sau bước này.'],
    loading: ['Đang tìm trong album…', 'Đang so sánh khuôn mặt đã chọn với các ảnh đã lập chỉ mục.'],
    error: ['Chưa tìm kiếm được', detail],
    empty: ['Chưa có ảnh vượt ngưỡng', detail || 'Thử một ảnh tham chiếu rõ hơn hoặc kiểm tra album đã xử lý xong.'],
    noalbum: ['Chưa chọn album', 'Tạo album và thêm ảnh trong Thư viện ảnh trước khi tìm.']
  };
  const [title, description] = messages[kind] || messages.idle;
  state.results = [];
  $('search-results').replaceChildren();
  $('download-results').classList.add('hidden');
  $('search-empty').classList.remove('hidden');
  $('search-empty').classList.toggle('is-error', kind === 'error');
  $('search-empty').querySelector('h3').textContent = title;
  $('search-empty').querySelector('p').textContent = description;
  $('search-meta').textContent = title;
  document.querySelector('.search-results-panel').setAttribute('aria-busy', String(['loading', 'detecting'].includes(kind)));
  $('search-notice').classList.add('hidden');
}

function selectFace(index, search = true) {
  state.face = index;
  document.querySelectorAll('.face-choice,.face-overlay').forEach(node => node.classList.toggle('active', Number(node.dataset.index) === index));
  if (state.query) localStorage.setItem('fsm-query-face', String(index));
  if (search && state.query) scheduleFaceSearch();
}

function renderQuery(query, face = 0) {
  state.query = query;
  localStorage.setItem('fsm-query-id', query.id);
  $('query-image').src = `/api/query/${query.id}/image`;
  $('query-preview').classList.remove('hidden');
  $('face-choices').replaceChildren();
  $('face-boxes').replaceChildren();
  for (const item of query.faces) {
    const box = el('button', 'face-overlay');
    const [x1, y1, x2, y2] = item.bbox;
    Object.assign(box.style, {left: `${100*x1/query.width}%`, top: `${100*y1/query.height}%`, width: `${100*(x2-x1)/query.width}%`, height: `${100*(y2-y1)/query.height}%`});
    box.dataset.index = item.index;
    box.append(el('span', '', String(item.index+1)));
    box.setAttribute('aria-label', `Chọn khuôn mặt ${item.index+1}`);
    box.onclick = () => selectFace(item.index);
    $('face-boxes').append(box);
    const choice = el('button', 'face-choice', `Khuôn mặt ${item.index+1}`);
    choice.dataset.index = item.index;
    choice.onclick = () => selectFace(item.index);
    $('face-choices').append(choice);
  }
  selectFace(Number.isInteger(face) ? Math.max(0, Math.min(face, query.faces.length-1)) : 0, false);
  $('run-search').disabled = false;
  $('face-hint').textContent = `${query.faces.length} khuôn mặt · Chọn mặt cần tìm.`;
}

function renderResults(result) {
  state.results = result.results;
  const counts = result.album_status || {};
  document.querySelector('.search-results-panel').setAttribute('aria-busy', 'false');
  $('search-empty').classList.remove('is-error');
  $('search-results').replaceChildren(...state.results.map(photo => {
    const card = photoCard(photo, 'result');
    const imageButton = card.querySelector('.image-button');
    imageButton.classList.add('search-result-image');
    const [x1, y1, x2, y2] = photo.bbox;
    const box = el('span', 'result-face-box');
    // Use a whole-image preview so the face box stays correct on landscape and portrait photos.
    Object.assign(box.style, {left: `${100*x1/photo.width}%`, top: `${100*y1/photo.height}%`, width: `${100*(x2-x1)/photo.width}%`, height: `${100*(y2-y1)/photo.height}%`});
    imageButton.append(box);
    return card;
  }));
  $('search-empty').classList.toggle('hidden', state.results.length > 0);
  $('download-results').classList.toggle('hidden', !state.results.length);
  $('search-meta').textContent = `${state.results.length}/${counts.indexed ?? counts.total ?? '?'} ảnh vượt ngưỡng ${result.threshold.toFixed(2)} · ${currentAlbum()?.name || 'album'}`;
  if (!state.results.length) {
    $('search-empty').querySelector('h3').textContent = counts.processing ? 'Album đang được xử lý' : 'Chưa có ảnh vượt ngưỡng';
    $('search-empty').querySelector('p').textContent = counts.processing ? 'App sẽ tự cập nhật khi có thêm ảnh xử lý xong.' : 'Đã tìm với khuôn mặt đang chọn. Thử ảnh rõ hơn hoặc điều chỉnh ngưỡng; hạ ngưỡng có thể tăng kết quả sai.';
  }
  const notes = [];
  if (counts.processing) notes.push(`${counts.processing} ảnh đang xử lý. Kết quả sẽ tự cập nhật.`);
  if (counts.failed) notes.push(`${counts.failed} ảnh lỗi xử lý. Kiểm tra trong Thư viện ảnh.`);
  if (counts.outdated) notes.push(`${counts.outdated} ảnh cần lập chỉ mục lại do phiên bản model thay đổi.`);
  $('search-notice').textContent = notes.join(' ');
  $('search-notice').classList.toggle('hidden', !notes.length);
}

function scheduleFaceSearch(delay = 0) {
  clearTimeout(faceSearchTimer);
  faceSearchTimer = setTimeout(runFaceSearch, delay);
}

async function runFaceSearch() {
  clearTimeout(faceSearchTimer);
  const version = ++faceSearchVersion;
  faceSearchController?.abort();
  if (!state.query || !state.album) {
    $('run-search').disabled = true;
    $('run-search').textContent = 'Tìm ảnh của tôi ↗';
    showSearchState(state.album ? 'idle' : 'noalbum');
    return;
  }
  const controller = faceSearchController = new AbortController();
  const payload = {album_id: state.album, query_id: state.query.id, face_index: state.face, threshold: Number($('threshold').value), top_k: 30};
  const signature = JSON.stringify(payload);
  $('run-search').disabled = true;
  $('run-search').textContent = 'Đang tìm…';
  if (signature !== lastFaceSearchSignature) showSearchState('loading');
  try {
    const result = await api('/api/search', {...jsonRequest(payload), signal: controller.signal});
    if (version !== faceSearchVersion || payload.album_id !== state.album || payload.query_id !== state.query?.id || payload.face_index !== state.face || payload.threshold !== Number($('threshold').value)) return;
    lastFaceSearchSignature = signature;
    renderResults(result);
    if (result.album_status?.processing) scheduleFaceSearch(1800);
  } catch (error) {
    if (version === faceSearchVersion && error.name !== 'AbortError') showSearchState('error', error.message);
  } finally {
    if (version === faceSearchVersion) {
      $('run-search').disabled = !state.query;
      $('run-search').textContent = 'Tìm ảnh của tôi ↗';
    }
  }
}

async function restoreFaceSearch() {
  let query;
  const id = localStorage.getItem('fsm-query-id');
  try {
    if (id) {
      try { query = await api(`/api/query/${encodeURIComponent(id)}`); }
      catch { localStorage.removeItem('fsm-query-id'); }
    }
    if (!query) query = await api('/api/query/latest');
    if (query && !query.model_current) query = await api(`/api/query/${query.id}/refresh`, {method: 'POST'});
    if (query) renderQuery(query, Number(localStorage.getItem('fsm-query-face') || 0));
    const savedPage = localStorage.getItem('fsm-page') || 'collections';
    navigate(['collections','library','search','studio','trash','system'].includes(savedPage)?savedPage:'collections');
    if (query) await runFaceSearch();
  } catch (error) {
    $('face-hint').textContent = error.message;
    showSearchState('error', error.message);
  }
}

$('query-file').onchange = async () => {
  const file = $('query-file').files[0];
  if (!file) return;
  const upload = ++queryUploadVersion;
  ++faceSearchVersion;
  faceSearchController?.abort();
  clearTimeout(faceSearchTimer);
  state.query = null;
  $('run-search').disabled = true;
  $('face-choices').replaceChildren();
  $('face-boxes').replaceChildren();
  $('query-preview').classList.add('hidden');
  showSearchState('detecting');
  try {
    const form = new FormData();
    form.append('file', file);
    const query = await api('/api/query', {method: 'POST', body: form});
    if (upload !== queryUploadVersion) return;
    renderQuery(query);
    await runFaceSearch();
  } catch (error) {
    if (upload === queryUploadVersion) {
      $('face-hint').textContent = error.message;
      showSearchState('error', error.message);
    }
  }
};
$('run-search').onclick = runFaceSearch;
$('threshold').oninput = () => {
  $('threshold-value').textContent = Number($('threshold').value).toFixed(2);
  if (state.query) scheduleFaceSearch(250);
};

