// «Conectar con mi PC»: hoja a pantalla completa para emparejar el móvil con Skynet en el PC.
// Lee el QR con la cámara (BarcodeDetector si el móvil lo trae; si no, jsQR) o acepta el enlace pegado.
import { emparejar, leerEnlace, conexion, NOMBRE_POR_DEFECTO } from './api.js';
import { icon } from './icons.js';
import { esc } from './md.js';

const $ = (s) => document.getElementById(s);
const CADA_MS = 160;  // ~6 lecturas por segundo
export const AVISO = 'skynet.aviso';  // sessionStorage: qué contar tras recargar ('conectado' | 'noautorizado')

let el = null;
let abierto = false;
let ocupado = false;
let gen = 0;          // cada encendido de cámara tiene su número; uno viejo que vuelve tarde se descarta
let flujo = null;
let timer = null;
let detectar = null;
let reanudar = false; // la cámara estaba encendida al pasar a segundo plano
let capTimer = null;
let jsqr = null;

function construir() {
  if (el) return;
  el = document.createElement('aside');
  el.className = 'panel cx';
  el.id = 'conectar';
  el.setAttribute('role', 'dialog');
  el.setAttribute('aria-modal', 'true');
  el.setAttribute('aria-labelledby', 'cxTitle');
  el.setAttribute('aria-hidden', 'true');
  el.innerHTML = `
    <div class="panel-head">
      <h2 class="panel-title" id="cxTitle">Conectar con mi PC</h2>
      <button class="icon-btn" id="cxClose" aria-label="Cerrar">${icon('close')}</button>
    </div>
    <div class="panel-body cx-body">
      <div class="cx-aviso" id="cxAviso" role="alert" hidden></div>
      <div class="cx-cam" id="cxCam" data-estado="apagada">
        <video id="cxVideo" playsinline muted autoplay></video>
        <div class="cx-frame" aria-hidden="true"><span class="cx-scan"></span></div>
        <div class="cx-cam-msg" id="cxCamMsg"></div>
      </div>
      <div class="cx-cap" id="cxCap" aria-live="polite"></div>
      <label class="field"><span class="field-k">O pega el enlace</span>
        <input class="input mono" id="cxEnlace" placeholder="skynet://emparejar?u=…&amp;c=…" autocomplete="off"
          autocapitalize="off" autocorrect="off" spellcheck="false" inputmode="url" enterkeyhint="go"></label>
      <div class="cx-host" id="cxHost"></div>
      <label class="field"><span class="field-k">Nombre de este móvil</span>
        <input class="input" id="cxNombre" maxlength="60" autocomplete="off" enterkeyhint="go"></label>
      <button class="btn primary cx-go" id="cxGo" type="button">Conectar</button>
      <div class="cx-msg" id="cxMsg" role="alert"></div>
      <div class="section-k">Cómo</div>
      <ol class="steps-list">
        <li>Instala <b>Tailscale</b> en el PC y en el móvil con la misma cuenta.</li>
        <li>En Skynet del PC: <b>Configuración › Dispositivos › Añadir móvil</b>.</li>
        <li>Escanea el QR.</li>
      </ol>
    </div>`;
  document.body.appendChild(el);
  $('cxClose').addEventListener('click', cerrarConectar);
  $('cxGo').addEventListener('click', conectar);
  $('cxEnlace').addEventListener('input', () => { pintarHost(); mensaje(''); });
  for (const id of ['cxEnlace', 'cxNombre']) {
    $(id).addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); conectar(); } });
  }
  $('cxCamMsg').addEventListener('click', (e) => { if (e.target.closest('[data-cam]')) encenderCamara(); });
  window.addEventListener('keydown', (e) => { if (abierto && e.key === 'Escape') { e.stopPropagation(); cerrarConectar(); } }, true);
  document.addEventListener('visibilitychange', () => {
    if (!abierto) return;
    if (document.hidden) { reanudar = !!flujo; apagarCamara(); }
    else if (reanudar) { reanudar = false; encenderCamara(); }
  });
}

export function conectarAbierto() { return abierto; }

// opts.enlace: enlace que llega de fuera (deep link): se rellena y se espera a que pulses «Conectar».
// opts.aviso: texto destacado arriba (p. ej. cuando el PC ha retirado la llave).
export function abrirConectar(opts = {}) {
  construir();
  const c = conexion();
  if (!abierto) $('cxNombre').value = c.dispositivo?.nombre || c.nombre || NOMBRE_POR_DEFECTO;
  abierto = true;
  el.classList.add('open');
  el.setAttribute('aria-hidden', 'false');
  const av = $('cxAviso');
  av.textContent = opts.aviso || '';
  av.hidden = !opts.aviso;
  mensaje('');
  if (opts.enlace) {
    $('cxEnlace').value = String(opts.enlace).trim();
    apagarCamara();
    estadoCamara('apagada');
  } else if (!flujo) {
    encenderCamara();
  }
  pintarHost();
}

export function cerrarConectar() {
  if (!el || !abierto) return;
  abierto = false;
  reanudar = false;
  apagarCamara();
  el.classList.remove('open');
  el.setAttribute('aria-hidden', 'true');
  if (el.contains(document.activeElement)) document.activeElement.blur();
}

// --- cámara -----------------------------------------------------------------------
function estadoCamara(estado, texto = '', sub = '', boton = '') {
  const cam = $('cxCam');
  cam.dataset.estado = estado;
  const ico = { denegada: 'lock', sin: 'warn', leido: 'check', apagada: 'camera', inicio: '' }[estado];
  $('cxCamMsg').innerHTML = estado === 'viva' ? '' : `
    ${estado === 'inicio' ? '<span class="spinner"></span>' : ico ? icon(ico) : ''}
    ${texto ? `<div>${esc(texto)}</div>` : ''}${sub ? `<div class="sub">${esc(sub)}</div>` : ''}
    ${boton ? `<button class="btn small" type="button" data-cam>${esc(boton)}</button>` : ''}`;
  if (estado === 'apagada' && !texto) {
    $('cxCamMsg').innerHTML = `${icon('camera')}<button class="btn small" type="button" data-cam>Usar la cámara</button>`;
  }
  rotulo(estado === 'viva' ? 'Apunta al QR que enseña tu PC' : '');
}

function rotulo(texto, ms = 0) {
  clearTimeout(capTimer);
  $('cxCap').textContent = texto;
  if (ms) capTimer = setTimeout(() => { if ($('cxCam').dataset.estado === 'viva') rotulo('Apunta al QR que enseña tu PC'); }, ms);
}

async function encenderCamara() {
  apagarCamara();
  const yo = ++gen;
  estadoCamara('inicio', 'Abriendo la cámara…');
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    estadoCamara('sin', 'No puedo usar la cámara aquí.', 'Pega el enlace abajo.');
    return;
  }
  let s;
  try {
    s = await navigator.mediaDevices.getUserMedia({ audio: false, video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } } });
  } catch (e) {
    if (yo !== gen) return;
    const name = e && e.name;
    if (name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError') {
      estadoCamara('denegada', 'Sin permiso para la cámara.', 'Pega el enlace abajo, o permite la cámara y reintenta.', 'Reintentar');
    } else if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'DevicesNotFoundError') {
      estadoCamara('sin', 'No encuentro la cámara.', 'Pega el enlace abajo.', 'Reintentar');
    } else {
      estadoCamara('sin', 'La cámara no responde.', 'Pega el enlace abajo.', 'Reintentar');
    }
    return;
  }
  if (yo !== gen || !abierto) { soltar(s); return; }
  flujo = s;
  const video = $('cxVideo');
  video.srcObject = s;
  try { await video.play(); } catch { /* autoplay: el vídeo está silenciado, debería poder */ }
  if (yo !== gen) return;
  try { detectar = await crearDetector(video); } catch { detectar = null; }
  if (yo !== gen) return;
  if (!detectar) {
    apagarCamara();
    estadoCamara('sin', 'No puedo leer QR en este móvil.', 'Pega el enlace abajo.');
    return;
  }
  estadoCamara('viva');
  bucle(yo);
}

function soltar(s) {
  try { for (const t of s.getTracks()) t.stop(); } catch { /* ya parada */ }
}

function apagarCamara() {
  gen++;
  clearTimeout(timer);
  timer = null;
  if (flujo) soltar(flujo);
  flujo = null;
  const video = el && $('cxVideo');
  if (video) { try { video.pause(); } catch { /* nada */ } video.srcObject = null; }
}

function bucle(yo) {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if (yo !== gen) return;
    let valor = null;
    try { valor = await detectar(); } catch { /* fotograma no listo */ }
    if (yo !== gen) return;
    if (valor && leido(valor)) return;
    bucle(yo);
  }, CADA_MS);
}

function leido(valor) {
  if (!leerEnlace(valor)) { rotulo('Ese QR no es de Skynet.', 2200); return false; }
  try { navigator.vibrate && navigator.vibrate(30); } catch { /* sin vibración */ }
  apagarCamara();
  estadoCamara('leido', 'QR leído');
  $('cxEnlace').value = valor;
  pintarHost();
  conectar();
  return true;
}

function cargarJsQR() {
  if (window.jsQR) return Promise.resolve();
  if (!jsqr) {
    jsqr = new Promise((ok, mal) => {
      const s = document.createElement('script');
      s.src = 'vendor/jsqr/jsQR.js';
      s.onload = () => (window.jsQR ? ok() : mal(new Error('jsQR no cargó')));
      s.onerror = () => { jsqr = null; mal(new Error('jsQR no cargó')); };
      document.head.appendChild(s);
    });
  }
  return jsqr;
}

async function crearDetector(video) {
  if ('BarcodeDetector' in window) {
    try {
      const formatos = await window.BarcodeDetector.getSupportedFormats();
      if (formatos.includes('qr_code')) {
        const bd = new window.BarcodeDetector({ formats: ['qr_code'] });
        return async () => {
          if (video.readyState < 2) return null;
          const r = await bd.detect(video);
          return r.length ? r[0].rawValue : null;
        };
      }
    } catch { /* sin BarcodeDetector útil: jsQR */ }
  }
  await cargarJsQR();
  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  let invertido = false;
  return async () => {
    const w0 = video.videoWidth, h0 = video.videoHeight;
    if (!w0 || !h0 || video.readyState < 2) return null;
    const k = Math.min(1, 720 / Math.max(w0, h0));
    const w = Math.round(w0 * k), h = Math.round(h0 * k);
    if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
    ctx.drawImage(video, 0, 0, w, h);
    const img = ctx.getImageData(0, 0, w, h);
    // Un fotograma normal y el siguiente invertido: lee QR oscuros sobre claro y claros sobre oscuro.
    invertido = !invertido;
    const r = window.jsQR(img.data, w, h, { inversionAttempts: invertido ? 'onlyInvert' : 'dontInvert' });
    return r ? r.data : null;
  };
}

// --- emparejar ----------------------------------------------------------------------
function pintarHost() {
  const e = leerEnlace($('cxEnlace').value);
  $('cxHost').innerHTML = e ? `Tu PC: <b>${esc(e.host)}</b>` : '';
}

function mensaje(texto) {
  $('cxMsg').textContent = texto;
}

function ocupar(on, texto) {
  ocupado = on;
  const b = $('cxGo');
  b.disabled = on;
  b.innerHTML = on ? `<span class="spinner"></span>${esc(texto || 'Conectando…')}` : esc(texto || 'Conectar');
  $('cxEnlace').disabled = on;
  $('cxNombre').disabled = on;
}

async function conectar() {
  if (ocupado) return;
  const texto = $('cxEnlace').value;
  if (!texto.trim()) {
    mensaje('Escanea el QR o pega el enlace.');
    return;
  }
  if (!leerEnlace(texto)) {
    mensaje('Ese enlace no vale. Escanea el QR o pega el enlace que empieza por skynet://');
    return;
  }
  mensaje('');
  ocupar(true);
  try {
    await emparejar(texto, $('cxNombre').value);
  } catch (e) {
    ocupar(false);
    mensaje(e.message);
    if ($('cxCam').dataset.estado === 'leido') estadoCamara('leido', 'QR leído', '', 'Escanear otro');
    return;
  }
  apagarCamara();
  const b = $('cxGo');
  b.innerHTML = `${icon('check')}Conectado`;
  try { sessionStorage.setItem(AVISO, 'conectado'); } catch { /* sin almacenamiento */ }
  setTimeout(() => location.reload(), 500);
}
