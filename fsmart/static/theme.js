'use strict';
// Loaded without defer, before first paint, so the saved look never flashes (CSP forbids inline scripts).
// Three looks, cycled by the theme button: F Smart glass (default) → Aurora dark → Aurora light.
// data-theme stays dark/light so every Aurora rule and script keeps working; data-skin="glass" layers the F Smart look on top.
const themeStorageKey='fsm-theme';
const THEME_MODES=['glass','dark','light'];
const THEME_INFO={
  glass:{icon:'◐',name:'F Smart'},
  dark:{icon:'☾',name:'Aurora tối'},
  light:{icon:'☀',name:'Aurora sáng'},
};
function savedMode(){const v=localStorage.getItem(themeStorageKey);return THEME_MODES.includes(v)?v:'glass';}
function currentMode(){const root=document.documentElement;return root.dataset.skin==='glass'?'glass':(root.dataset.theme==='light'?'light':'dark');}
function currentTheme(){return document.documentElement.dataset.theme==='light'?'light':'dark';}
function setRootMode(mode){const root=document.documentElement;root.dataset.theme=mode==='light'?'light':'dark';root.dataset.skin=mode==='glass'?'glass':'aurora';}
function nextMode(mode){return THEME_MODES[(THEME_MODES.indexOf(mode)+1)%THEME_MODES.length];}
function applyTheme(mode){
  if(!THEME_MODES.includes(mode))mode='dark';
  setRootMode(mode);
  const button=document.getElementById('theme-toggle');
  if(button){
    const info=THEME_INFO[mode],next=THEME_INFO[nextMode(mode)];
    button.setAttribute('aria-pressed',String(mode!=='light'));
    button.dataset.mode=mode;
    button.textContent=info.icon;
    const label=`Giao diện: ${info.name}. Bấm để chuyển sang ${next.name}`;
    button.title=label;button.setAttribute('aria-label',label);
  }
  const meta=document.querySelector('meta[name="theme-color"]'),bg=getComputedStyle(document.documentElement).getPropertyValue('--bg').trim();
  if(meta&&bg)meta.content=bg;
  document.dispatchEvent(new CustomEvent('fsm:skin',{detail:{mode}}));
}
function toggleTheme(){const mode=nextMode(currentMode());localStorage.setItem(themeStorageKey,mode);applyTheme(mode);}
setRootMode(savedMode());
document.addEventListener('DOMContentLoaded',()=>{document.getElementById('theme-toggle').onclick=toggleTheme;applyTheme(currentMode());});
