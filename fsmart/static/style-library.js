/* Built-in public-domain style library: pick a painting, VGG19 applies it on this machine (no API, no credit). */
(() => {
  const library = {styles: [], group: 'all'};

  function selectLibraryStyle(item) {
    clearStyleRecipe();
    state.style = 'custom';
    state.libraryStyle = item.key;
    document.querySelectorAll('.style-option').forEach(button => button.classList.remove('selected'));
    document.querySelectorAll('.library-card').forEach(card => card.classList.toggle('selected', card.dataset.key === item.key));
    $('custom-style').classList.remove('hidden');
    $('style-file').value = '';
    $('style-library-picked').textContent = `Đang chọn: ${item.name} · ${item.date || ''}`.replace(/ · $/, '');
    $('style-library-picked').classList.remove('hidden');
    document.dispatchEvent(new CustomEvent('fsm:style-picked'));
  }

  function render() {
    const groups = ['all', ...new Set(library.styles.map(item => item.group))];
    $('style-library-groups').replaceChildren(...groups.map(group => {
      const chip = el('button', `library-chip${group === library.group ? ' active' : ''}`, group === 'all' ? `Tất cả · ${library.styles.length}` : group);
      chip.type = 'button';
      chip.setAttribute('aria-pressed', String(group === library.group));
      chip.onclick = () => { library.group = group; render(); };
      return chip;
    }));
    const shown = library.styles.filter(item => library.group === 'all' || item.group === library.group);
    $('style-library-grid').replaceChildren(...shown.map(item => {
      const card = el('button', `library-card${item.key === state.libraryStyle ? ' selected' : ''}`);
      card.type = 'button';
      card.dataset.key = item.key;
      card.disabled = !item.ready;
      card.title = `${item.title} — ${item.artist}${item.date ? ', ' + item.date : ''}\n${item.licence}`;
      const image = el('img');
      image.src = item.thumb_url; image.alt = item.name; image.loading = 'lazy'; image.decoding = 'async';
      card.append(image, el('span', 'library-card-name', item.name));
      card.onclick = () => selectLibraryStyle(item);
      return card;
    }));
  }

  async function loadLibrary() {
    try {
      const data = await api('/api/style-library');
      library.styles = data.styles;
      $('style-library-count').textContent = `${data.styles.filter(item => item.ready).length} tranh`;
      render();
    } catch (error) {
      $('style-library-count').textContent = 'chưa tải được';
    }
  }

  // Picking a preset or "Style của bạn" leaves the library.
  $('style-grid').addEventListener('click', () => {
    state.libraryStyle = null;
    document.querySelectorAll('.library-card').forEach(card => card.classList.remove('selected'));
    $('style-library-picked').classList.add('hidden');
  }, true);
  $('style-file').addEventListener('change', () => {
    if (!$('style-file').files[0]) return;
    state.libraryStyle = null;
    document.querySelectorAll('.library-card').forEach(card => card.classList.remove('selected'));
    $('style-library-picked').classList.add('hidden');
  });
  loadLibrary();
})();
