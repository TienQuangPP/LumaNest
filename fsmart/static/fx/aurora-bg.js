/**
 * LumaNest Aurora v3 — Living Luminous WebGL Atmosphere
 * Fine Artistry, visionOS spatial refraction & adaptive performance.
 * Deferred initialization (post-load / idle) keeps DOMContentLoaded < 300ms.
 */
(() => {
  'use strict';

  // Check user preferences
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const saveData = Boolean(navigator.connection && navigator.connection.saveData);

  if (prefersReducedMotion || saveData) {
    return; // Preserve CSS gradient fallback
  }

  function initWebGL() {
    const canvas = document.createElement('canvas');
    canvas.id = 'aurora-canvas';
    canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;z-index:-3;pointer-events:none;opacity:0;transition:opacity 1s cubic-bezier(0.16, 1, 0.3, 1);';
    document.body.prepend(canvas);

    const gl = canvas.getContext('webgl', { alpha: true, depth: false, antialias: false, powerPreference: 'low-power' }) ||
               canvas.getContext('experimental-webgl');

    if (!gl) {
      canvas.remove();
      return;
    }

    const vsSource = `
      attribute vec2 aPos;
      varying vec2 vUv;
      void main() {
        vUv = aPos * 0.5 + 0.5;
        gl_Position = vec4(aPos, 0.0, 1.0);
      }
    `;

    const fsSource = `
      precision mediump float;
      varying vec2 vUv;
      uniform float uTime;
      uniform vec2 uResolution;
      uniform vec2 uMouse;
      uniform vec3 uC1;
      uniform vec3 uC2;
      uniform vec3 uC3;
      uniform vec3 uC4;
      uniform float uTheme; // 0.0 = dark, 1.0 = light

      // Simplex noise approximation
      vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
      vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
      vec3 permute(vec3 x) { return mod289(((x*34.0)+1.0)*x); }

      float snoise(vec2 v) {
        const vec4 C = vec4(0.211324865405187, 0.366025403784439, -0.577350269189626, 0.024390243902439);
        vec2 i  = floor(v + dot(v, C.yy));
        vec2 x0 = v -   i + dot(i, C.xx);
        vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
        vec4 x12 = x0.xyxy + C.xxzz;
        x12.xy -= i1;
        i = mod289(i);
        vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
        vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy), dot(x12.zw,x12.zw)), 0.0);
        m = m*m; m = m*m;
        vec3 x = 2.0 * fract(p * C.www) - 1.0;
        vec3 h = abs(x) - 0.5;
        vec3 ox = floor(x + 0.5);
        vec3 a0 = x - ox;
        m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
        vec3 g;
        g.x  = a0.x  * x0.x  + h.x  * x0.y;
        g.yz = a0.yz * x12.xz + h.yz * x12.yw;
        return 130.0 * dot(m, g);
      }

      void main() {
        vec2 uv = gl_FragCoord.xy / uResolution.xy;
        vec2 aspect = vec2(uResolution.x / uResolution.y, 1.0);
        vec2 p = (uv - 0.5) * aspect;

        // Subtle mouse interaction
        vec2 mouseShift = (uMouse - 0.5) * 0.12;
        p += mouseShift;

        float t = uTime * 0.06;
        
        // Multi-layer aurora fluid noise
        float n1 = snoise(p * 0.85 + vec2(t * 0.55, t * 0.35));
        float n2 = snoise(p * 1.5 - vec2(t * 0.4, t * 0.75) + vec2(n1 * 0.35));
        float n3 = snoise(p * 2.2 + vec2(n2 * 0.35, t * 0.25));

        // Color blending
        float w1 = smoothstep(-0.6, 0.8, n1);
        float w2 = smoothstep(-0.4, 0.9, n2);
        float w3 = smoothstep(-0.5, 0.7, n3);

        vec3 col = mix(uC1, uC2, w1);
        col = mix(col, uC3, w2 * 0.75);
        col = mix(col, uC4, w3 * 0.55);

        // Radial vignette & softness
        float dist = length(uv - 0.5);
        float alpha = smoothstep(1.2, 0.1, dist);

        if (uTheme > 0.5) {
          // Light mode: airy, ethereal luminosity
          gl_FragColor = vec4(col, alpha * 0.22);
        } else {
          // Dark mode: deep celestial twilight — muted & dark in main content area so text contrast is pristine
          float contentScrim = smoothstep(0.15, 0.75, length((uv - vec2(0.5, 0.65)) * aspect));
          float darkAlpha = alpha * 0.16 * (0.2 + 0.8 * contentScrim);
          gl_FragColor = vec4(col, darkAlpha);
        }
      }
    `;

    function createShader(type, src) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
        gl.deleteShader(s);
        return null;
      }
      return s;
    }

    const vs = createShader(gl.VERTEX_SHADER, vsSource);
    const fs = createShader(gl.FRAGMENT_SHADER, fsSource);
    if (!vs || !fs) {
      canvas.remove();
      return;
    }

    const prog = gl.createProgram();
    gl.attachShader(prog, vs);
    gl.attachShader(prog, fs);
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) {
      canvas.remove();
      return;
    }

    gl.useProgram(prog);

    // Buffer quad
    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([
      -1, -1,
       3, -1,
      -1,  3
    ]), gl.STATIC_DRAW);

    const aPos = gl.getAttribLocation(prog, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const uTimeLoc = gl.getUniformLocation(prog, 'uTime');
    const uResLoc = gl.getUniformLocation(prog, 'uResolution');
    const uMouseLoc = gl.getUniformLocation(prog, 'uMouse');
    const uC1Loc = gl.getUniformLocation(prog, 'uC1');
    const uC2Loc = gl.getUniformLocation(prog, 'uC2');
    const uC3Loc = gl.getUniformLocation(prog, 'uC3');
    const uC4Loc = gl.getUniformLocation(prog, 'uC4');
    const uThemeLoc = gl.getUniformLocation(prog, 'uTheme');

    // Colors state - muted 45% in dark mode to preserve high contrast for text
    const darkPalette = [
      [0.24, 0.12, 0.46],
      [0.34, 0.11, 0.38],
      [0.01, 0.26, 0.32],
      [0.38, 0.22, 0.04]
    ];
    const lightPalette = [
      [0.65, 0.45, 0.95],
      [0.92, 0.45, 0.75],
      [0.25, 0.75, 0.88],
      [0.95, 0.72, 0.35]
    ];

    let currentPalette = darkPalette.map(c => [...c]);
    let targetPalette = darkPalette.map(c => [...c]);

    let mouseX = 0.5, mouseY = 0.5;
    let targetMouseX = 0.5, targetMouseY = 0.5;
    let lastActive = performance.now();
    let lastFrameTime = performance.now();
    let lowFpsCount = 0;
    let rafId = null;
    let idleTimer = null;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      const w = Math.round(window.innerWidth * dpr);
      const h = Math.round(window.innerHeight * dpr);
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
    }

    window.addEventListener('resize', resize, { passive: true });
    resize();

    function wake() {
      lastActive = performance.now();
      lastFrameTime = performance.now();
      lowFpsCount = 0;
      if (idleTimer) {
        clearTimeout(idleTimer);
        idleTimer = null;
      }
      if (!rafId && !document.hidden) {
        rafId = requestAnimationFrame(loop);
      }
    }

    window.addEventListener('pointermove', (e) => {
      targetMouseX = e.clientX / window.innerWidth;
      targetMouseY = 1.0 - (e.clientY / window.innerHeight);
      wake();
    }, { passive: true });

    window.addEventListener('scroll', wake, { passive: true });
    document.addEventListener('fsm:page', wake);

    function updatePalette(theme) {
      const base = theme === 'light' ? lightPalette : darkPalette;
      targetPalette = base.map(c => [...c]);
    }

    const observer = new MutationObserver(() => {
      const theme = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
      updatePalette(theme);
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    updatePalette(document.documentElement.dataset.theme);

    // Fade in canvas smoothly
    requestAnimationFrame(() => {
      canvas.style.opacity = '1';
    });

    function loop(now) {
      if (document.hidden) {
        rafId = null;
        return;
      }

      const idleDuration = now - lastActive;
      const frameDelta = now - lastFrameTime;
      lastFrameTime = now;

      // Only evaluate FPS drops during active user interaction
      if (idleDuration <= 3000) {
        if (frameDelta > 45) { // < 22 fps during active interaction
          lowFpsCount++;
          if (lowFpsCount > 80) { // ~2 seconds continuous low performance
            canvas.style.opacity = '0';
            setTimeout(() => {
              canvas.remove();
              gl.getExtension('WEBGL_lose_context')?.loseContext();
            }, 800);
            return;
          }
        } else {
          lowFpsCount = Math.max(0, lowFpsCount - 1);
        }
      } else {
        lowFpsCount = 0; // Never count FPS drops during idle
      }

      // Smooth lerp updates
      mouseX += (targetMouseX - mouseX) * 0.05;
      mouseY += (targetMouseY - mouseY) * 0.05;

      for (let i = 0; i < 4; i++) {
        for (let j = 0; j < 3; j++) {
          currentPalette[i][j] += (targetPalette[i][j] - currentPalette[i][j]) * 0.03;
        }
      }

      const isLight = document.documentElement.dataset.theme === 'light' ? 1.0 : 0.0;

      gl.useProgram(prog);
      gl.uniform1f(uTimeLoc, now * 0.001);
      gl.uniform2f(uResLoc, canvas.width, canvas.height);
      gl.uniform2f(uMouseLoc, mouseX, mouseY);
      gl.uniform3fv(uC1Loc, currentPalette[0]);
      gl.uniform3fv(uC2Loc, currentPalette[1]);
      gl.uniform3fv(uC3Loc, currentPalette[2]);
      gl.uniform3fv(uC4Loc, currentPalette[3]);
      gl.uniform1f(uThemeLoc, isLight);

      gl.drawArrays(gl.TRIANGLES, 0, 3);

      if (idleDuration > 3000) {
        // Conserve CPU/GPU: sleep ~40ms before next rAF (drops wakeups from 60/s to ~25/s)
        idleTimer = setTimeout(() => {
          idleTimer = null;
          if (!document.hidden && !rafId) {
            rafId = requestAnimationFrame(loop);
          }
        }, 40);
        rafId = null;
      } else {
        rafId = requestAnimationFrame(loop);
      }
    }

    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        if (idleTimer) {
          clearTimeout(idleTimer);
          idleTimer = null;
        }
        if (rafId) {
          cancelAnimationFrame(rafId);
          rafId = null;
        }
      } else {
        wake();
      }
    });

    rafId = requestAnimationFrame(loop);

    // Custom event for photos: extract ambient colors
    window.addEventListener('fsm:ambient-photo', (e) => {
      const colors = e.detail;
      const isDark = document.documentElement.dataset.theme !== 'light';
      const factor = isDark ? 0.45 : 1.0;
      if (Array.isArray(colors) && colors.length >= 3) {
        for (let i = 0; i < Math.min(colors.length, 4); i++) {
          targetPalette[i] = [colors[i][0] * factor, colors[i][1] * factor, colors[i][2] * factor];
        }
      }
    });
  }

  // Defer initialization to after page load / idle so DOMContentLoaded is ultra fast
  const startInit = () => {
    if ('requestIdleCallback' in window) {
      requestIdleCallback(initWebGL, { timeout: 1200 });
    } else {
      setTimeout(initWebGL, 200);
    }
  };

  if (document.readyState === 'complete') {
    startInit();
  } else {
    window.addEventListener('load', startInit, { once: true });
  }
})();
