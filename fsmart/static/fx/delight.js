'use strict';
/* LumaNest Aurora v3 · finishing touches.
   Consistent SVG icons for the remaining text glyphs, lightbox gestures (swipe, zoom, pan) and filmstrip,
   a favourite burst, a soft cursor glow, a collapsible sidebar. Classic script loaded after modern.js:
   it only adds behaviour around existing ids/classes and never changes API calls or data flow. */
(() => {
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');
  const SPRITE = '/static/icons/sprites.svg';
  const SVG_NS = 'http://www.w3.org/2000/svg';

  // 1. Icons ────────────────────────────────────────────────────────────────────────────
  // Scripts still write labels such as "☆ Yêu thích" or "Sáng tạo ↗". The glyph stays in the DOM inside a
  // hidden span (so code that saves and restores textContent keeps working) and an SVG icon is drawn instead.
  const GLYPHS = {'▦': 'grid', '◎': 'similar', '⌕': 'search', '✳': 'sparkles', '⌫': 'trash', '↗': 'arrow-up-right',
    '☆': 'star-outline', '★': 'star', '‹': 'chevron-left', '›': 'chevron-right', '×': 'close', '✕': 'close',
    '↓': 'download', '↑': 'upload', '＋': 'plus', '◐': 'contrast', '✓': 'check'};
  const GLYPH_RE = /[▦◎⌕✳⌫↗☆★‹›×✕↓↑＋◐✓]/;
  const HOST = 'button, a, label, summary, [role="tab"], .nav-item, .eyebrow, .library-chip, .command-option';
  const SKIP = 'svg, script, style, textarea, input, select, option, code, pre, #chat-messages, [contenteditable], .glyph-src';

  function makeIcon(name) {
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('class', 'icon glyph-icon');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    const use = document.createElementNS(SVG_NS, 'use');
    use.setAttribute('href', `${SPRITE}#icon-${name}`);
    svg.append(use);
    return svg;
  }

  function convertText(node) {
    const parent = node.parentElement;
    if (!parent || !parent.isConnected || !parent.closest(HOST) || parent.closest(SKIP)) return;
    const text = node.nodeValue;
    if (!GLYPH_RE.test(text)) return;
    const frag = document.createDocumentFragment();
    let buffer = '';
    for (const ch of text) {
      const name = GLYPHS[ch];
      if (!name) { buffer += ch; continue; }
      if (buffer) { frag.append(buffer); buffer = ''; }
      const src = document.createElement('span');
      src.className = 'glyph-src';
      src.textContent = ch;
      frag.append(makeIcon(name), src);
    }
    if (buffer) frag.append(buffer);
    node.replaceWith(frag);
  }

  function scan(root) {
    if (root.nodeType === Node.TEXT_NODE) { convertText(root); return; }
    if (root.nodeType !== Node.ELEMENT_NODE || root.closest?.(SKIP)) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT,
      {acceptNode: n => GLYPH_RE.test(n.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT});
    const found = [];
    while (walker.nextNode()) found.push(walker.currentNode);
    found.forEach(convertText);
  }

  let pending = new Set(), scheduled = false;
  function flush() {
    scheduled = false;
    const nodes = pending; pending = new Set();
    nodes.forEach(scan);
  }
  new MutationObserver(records => {
    for (const r of records) {
      if (r.type === 'characterData') pending.add(r.target);
      else r.addedNodes.forEach(n => pending.add(n));
    }
    if (!scheduled && pending.size) { scheduled = true; requestAnimationFrame(flush); }
  }).observe(document.body, {childList: true, subtree: true, characterData: true});
  scan(document.body);

  // 2. Lightbox: swipe, zoom and pan, filmstrip ──────────────────────────────────────────
  const lightbox = document.getElementById('lightbox');
  const image = document.getElementById('lightbox-image');
  const stage = image?.closest('.lightbox-image-stage');
  if (lightbox && image && stage) {
    let scale = 1, x = 0, y = 0;
    const apply = () => {
      image.style.transform = scale === 1 ? '' : `translate(${x}px, ${y}px) scale(${scale})`;
      image.classList.toggle('is-zoomed', scale > 1);
    };
    const reset = () => { scale = 1; x = 0; y = 0; apply(); };
    const zoomTo = next => {
      scale = Math.min(4, Math.max(1, next));
      if (scale === 1) { x = 0; y = 0; }
      apply();
    };
    new MutationObserver(reset).observe(image, {attributes: true, attributeFilter: ['src']});
    lightbox.addEventListener('close', reset);

    image.addEventListener('dblclick', event => { event.preventDefault(); zoomTo(scale > 1 ? 1 : 2); });
    stage.addEventListener('wheel', event => {
      if (!lightbox.open || !image.src) return;
      event.preventDefault();
      zoomTo(scale * (event.deltaY < 0 ? 1.15 : 1 / 1.15));
    }, {passive: false});
    lightbox.addEventListener('keydown', event => {
      if (event.target.closest('input, textarea')) return;
      if (event.key === '+' || event.key === '=') zoomTo(scale * 1.25);
      else if (event.key === '-') zoomTo(scale / 1.25);
      else if (event.key === '0') reset();
    });

    let start = null;
    image.addEventListener('pointerdown', event => {
      start = {px: event.clientX, py: event.clientY, x, y, id: event.pointerId, type: event.pointerType};
      if (scale > 1) image.setPointerCapture(event.pointerId);
    });
    image.addEventListener('pointermove', event => {
      if (!start || start.id !== event.pointerId || scale === 1) return;
      x = start.x + (event.clientX - start.px);
      y = start.y + (event.clientY - start.py);
      apply();
    });
    const end = event => {
      if (!start || start.id !== event.pointerId) return;
      const dx = event.clientX - start.px, dy = event.clientY - start.py;
      if (scale === 1 && start.type !== 'mouse' && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.4) {
        const button = document.getElementById(dx < 0 ? 'lightbox-next' : 'lightbox-prev');
        if (button && !button.disabled) button.click();
      }
      start = null;
    };
    image.addEventListener('pointerup', end);
    image.addEventListener('pointercancel', () => { start = null; });

    // Filmstrip of nearby photos in the open collection; click to jump.
    const strip = document.createElement('nav');
    strip.id = 'lightbox-filmstrip';
    strip.className = 'lightbox-filmstrip';
    strip.setAttribute('aria-label', 'Ảnh lân cận trong bộ');
    stage.append(strip);
    let shownIds = '';
    function renderStrip() {
      const photos = (typeof state !== 'undefined' && Array.isArray(state.photos)) ? state.photos : [];
      const current = photos.find(p => image.src.includes(`/api/photos/${p.id}/image`)) || null;
      if (!current || photos.length < 2) { strip.hidden = true; return; }
      strip.hidden = false;
      const index = photos.indexOf(current);
      const from = Math.max(0, index - 12), to = Math.min(photos.length, index + 13);
      const windowIds = photos.slice(from, to).map(p => p.id).join(',');
      if (windowIds !== shownIds) {
        shownIds = windowIds;
        strip.replaceChildren(...photos.slice(from, to).map(photo => {
          const button = document.createElement('button');
          button.type = 'button';
          button.className = 'filmstrip-item';
          button.dataset.photo = photo.id;
          button.setAttribute('aria-label', `Xem ${photo.name}`);
          const thumb = document.createElement('img');
          thumb.src = `/api/photos/${photo.id}/image?thumbnail=true`;
          thumb.alt = '';
          thumb.loading = 'lazy';
          thumb.decoding = 'async';
          button.append(thumb);
          button.addEventListener('click', () => { if (typeof openLightbox === 'function') openLightbox(photo.id); });
          return button;
        }));
      }
      for (const item of strip.children) {
        const active = item.dataset.photo === current.id;
        item.classList.toggle('active', active);
        if (active) item.setAttribute('aria-current', 'true'); else item.removeAttribute('aria-current');
        if (active) item.scrollIntoView({block: 'nearest', inline: 'center', behavior: reduceMotion.matches ? 'auto' : 'smooth'});
      }
    }
    new MutationObserver(() => requestAnimationFrame(renderStrip))
      .observe(image, {attributes: true, attributeFilter: ['src']});
  }

  // 3. Favourite burst ───────────────────────────────────────────────────────────────────
  document.addEventListener('click', event => {
    const star = event.target.closest('.favorite-star, #lightbox-favorite');
    if (!star || reduceMotion.matches || star.getAttribute('aria-pressed') === 'true') return;
    const rect = star.getBoundingClientRect();
    const burst = document.createElement('span');
    burst.className = 'fav-burst';
    burst.setAttribute('aria-hidden', 'true');
    burst.style.left = `${rect.left + rect.width / 2}px`;
    burst.style.top = `${rect.top + rect.height / 2}px`;
    for (let i = 0; i < 8; i++) {
      const dot = document.createElement('i');
      dot.style.setProperty('--a', `${i * 45}deg`);
      burst.append(dot);
    }
    document.body.append(burst);
    setTimeout(() => burst.remove(), 750);
  }, true);

  // 4. Cursor glow (desktop mouse only, off with reduced motion) ────────────────────────
  if (finePointer.matches && !reduceMotion.matches) {
    const glow = document.createElement('div');
    glow.className = 'cursor-glow';
    glow.setAttribute('aria-hidden', 'true');
    document.body.append(glow);
    let gx = 0, gy = 0, queued = false;
    document.addEventListener('pointermove', event => {
      if (event.pointerType !== 'mouse') return;
      gx = event.clientX; gy = event.clientY;
      if (!queued) {
        queued = true;
        requestAnimationFrame(() => {
          queued = false;
          glow.style.transform = `translate(${gx}px, ${gy}px)`;
          glow.classList.add('visible');
        });
      }
    }, {passive: true});
    document.documentElement.addEventListener('pointerleave', () => glow.classList.remove('visible'));
  }

  // 5. Collapsible sidebar (wide screens) ────────────────────────────────────────────────
  const sidebar = document.querySelector('.sidebar');
  const brand = sidebar?.querySelector('.brand');
  if (sidebar && brand) {
    const key = 'fsm-sidebar';
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'icon-button sidebar-toggle';
    const update = () => {
      const collapsed = document.documentElement.classList.contains('sidebar-collapsed');
      toggle.setAttribute('aria-pressed', String(collapsed));
      toggle.setAttribute('aria-label', collapsed ? 'Mở rộng thanh bên' : 'Thu gọn thanh bên');
      toggle.title = toggle.getAttribute('aria-label');
      toggle.replaceChildren(makeIcon(collapsed ? 'chevron-right' : 'chevron-left'));
    };
    if (localStorage.getItem(key) === 'collapsed') document.documentElement.classList.add('sidebar-collapsed');
    toggle.addEventListener('click', () => {
      const collapsed = document.documentElement.classList.toggle('sidebar-collapsed');
      localStorage.setItem(key, collapsed ? 'collapsed' : 'open');
      update();
    });
    brand.after(toggle);
    update();
  }
})();
