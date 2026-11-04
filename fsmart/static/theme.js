'use strict';
// Loaded without defer, before first paint, so a saved light theme never flashes dark (CSP forbids inline scripts).
const themeStorageKey='fsm-theme';
function currentTheme(){return document.documentElement.dataset.theme==='light'?'light':'dark';}
function applyTheme(theme){
  document.documentElement.dataset.theme=theme;
  const button=document.getElementById('theme-toggle');
  if(button){const dark=theme==='dark';button.setAttribute('aria-pressed',String(dark));button.textContent=dark?'☾':'☀';const label=dark?'Chuyển sang giao diện sáng':'Chuyển sang giao diện tối';button.title=label;button.setAttribute('aria-label',label);}
  const meta=document.querySelector('meta[name="theme-color"]'),bg=getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  if(meta&&bg)meta.content=bg;
}
function toggleTheme(){const theme=currentTheme()==='dark'?'light':'dark';localStorage.setItem(themeStorageKey,theme);applyTheme(theme);}
document.documentElement.dataset.theme=localStorage.getItem(themeStorageKey)==='light'?'light':'dark';
document.addEventListener('DOMContentLoaded',()=>{document.getElementById('theme-toggle').onclick=toggleTheme;applyTheme(currentTheme());});
