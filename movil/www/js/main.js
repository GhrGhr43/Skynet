// Arranque: escena 3D (si hay WebGL) + interfaz. Si la GPU falla, la interfaz funciona igual.
import { App } from './app.js';
import { modoConexion, onNoAutorizado } from './api.js';
import { abrirConectar, cerrarConectar, conectarAbierto, AVISO } from './conectar.js';

const MOVIL = matchMedia('(pointer: coarse)').matches;

function pickQuality() {
  const q = new URLSearchParams(location.search).get('calidad');
  let saved = null;
  try { saved = localStorage.getItem('skynet.calidad'); } catch { /* sin almacenamiento */ }
  const choice = q || saved || 'auto';
  if (choice !== 'auto') return choice;
  // Automática: según la GPU que reporta el navegador.
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    const ext = gl && gl.getExtension('WEBGL_debug_renderer_info');
    const name = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : '';
    if (/SwiftShader|llvmpipe|Software|Basic Render/i.test(name)) return 'baja';
    if (MOVIL) return /Adreno \(TM\) [7-9]\d\d|Mali-G7|Immortalis/i.test(name) ? 'media' : 'baja';
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
  const chip = document.getElementById('demoChip');
  if (modoConexion !== 'demo') chip?.remove();
  else chip?.addEventListener('click', () => abrirConectar());
  // Avisos que vienen de antes de recargar (al emparejar o cuando el PC retiró la llave).
  let aviso = null;
  try { aviso = sessionStorage.getItem(AVISO); sessionStorage.removeItem(AVISO); } catch { /* sin almacenamiento */ }
  if (aviso === 'conectado') window.app.toast('Conectado a tu PC');
  if (aviso === 'noautorizado') abrirConectar({ aviso: 'Este móvil ya no está autorizado en tu PC. Vuelve a emparejarlo.' });
  if (enlacePendiente) { abrirConectar({ enlace: enlacePendiente }); enlacePendiente = null; }
  window.ready = true;
}

// Botón «atrás» de Android (lo llama la app nativa): cierra lo que haya abierto; si no hay nada, false.
// El PC rechazó la llave: se vuelve a demo (api.js ya la olvidó) y se pide emparejar de nuevo.
onNoAutorizado(() => {
  try { sessionStorage.setItem(AVISO, 'noautorizado'); } catch { /* sin almacenamiento */ }
  location.reload();
});

// Enlace skynet://emparejar que llega desde Android (QR leído con la cámara del sistema, por ejemplo).
let enlacePendiente = null;
window.skynetEnlace = (enlace) => {
  if (window.app) abrirConectar({ enlace });
  else enlacePendiente = enlace;
};

window.skynetAtras = () => {
  if (conectarAbierto()) { cerrarConectar(); return true; }
  const menu = document.getElementById('menu');
  if (menu && !menu.hidden) { window.app.closeMenu(); return true; }
  if (window.app.localConfirm) { window.app.localConfirm(false); return true; }
  if (window.app.panels.current) {
    if (window.app.panels.detail) { window.app.panels.detail = null; window.app.panels.render(); return true; }
    window.app.panels.close(); return true;
  }
  return false;
}

boot();
