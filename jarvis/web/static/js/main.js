// Arranque: escena 3D (si hay WebGL) + interfaz. Si la GPU falla, la interfaz funciona igual.
import { App } from './app.js';

function pickQuality() {
  const q = new URLSearchParams(location.search).get('calidad');
  let saved = null;
  try { saved = localStorage.getItem('jarvis.calidad'); } catch { /* sin almacenamiento */ }
  const choice = q || saved || 'auto';
  if (choice !== 'auto') return choice;
  // Automática: según la GPU que reporta el navegador.
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
    const name = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : '';
    if (/SwiftShader|llvmpipe|Software|Basic Render/i.test(name)) return 'baja';
    if (/RTX|RX\s?[6-9]\d{3}|Radeon RX [6-9]|Arc A7|Apple M[2-9]/i.test(name)) return 'ultra';
    if (/Intel|Iris|UHD|Mali|Adreno/i.test(name)) return 'media';
  } catch { /* nada */ }
  return 'alta';
}

async function boot() {
  let engine = null;
  try {
    const { Engine } = await import('./scene/engine.js');
    engine = new Engine(document.getElementById('gl'), { quality: pickQuality() });
    window.engine = engine;
    if (new URLSearchParams(location.search).has('fps')) {
      const tag = document.createElement('div');
      tag.style.cssText = 'position:fixed;left:12px;bottom:8px;z-index:99;font:11px monospace;color:#888';
      document.body.appendChild(tag);
      engine.onFps = (f, pr) => { tag.textContent = `${f.toFixed(0)} fps · pr ${pr} · ${engine.quality}`; };
    }
  } catch (e) {
    console.warn('Sin escena 3D:', e);
    document.body.classList.add('no-webgl');
  }
  window.app = new App(engine);
  window.ready = true;
}

boot();
