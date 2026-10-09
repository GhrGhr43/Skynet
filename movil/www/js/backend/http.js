import { ApiError } from './error.js';
// Cliente del servidor de Skynet en tu PC: JSON por HTTP y eventos en vivo por SSE.
// En remoto (por Tailscale) cada petición lleva `Authorization: Bearer <llave>`; por eso el stream
// se lee con fetch y no con EventSource, que no admite cabeceras.

export const NO_LLEGO = 'No llego a tu PC. ¿Tienes Tailscale activado en el móvil y Skynet abierto en el PC?';
const REINTENTO_MS = 2500;
const SILENCIO_MS = 45000;  // el servidor manda «: ping» cada 15 s; sin nada en 45 s, la conexión está muerta
const LIMITE_MS = 20000;

let BASE = '';
let LLAVE = '';
let alRechazar = null;
let rechazado = false;

export function setBase(url) { BASE = String(url || '').replace(/\/+$/, ''); }
export function setLlave(llave) { LLAVE = String(llave || ''); }
// `fn(datos)` se llama una sola vez cuando el PC contesta 401 (llave revocada o que ya no vale).
export function onNoAutorizado(fn) { alRechazar = fn; }

function noAutorizado(data) {
  if (rechazado) return;
  rechazado = true;
  try { alRechazar && alRechazar(data); } catch (e) { console.error(e); }
}

function cabeceras(extra) {
  const h = { Accept: 'application/json', ...extra };
  if (LLAVE) h.Authorization = `Bearer ${LLAVE}`;
  return h;
}

async function request(method, url, body) {
  const opts = { method, headers: cabeceras(), cache: 'no-store' };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), LIMITE_MS);
  opts.signal = ctrl.signal;
  let res;
  try {
    res = await fetch(BASE + url, opts);
  } catch {
    throw new ApiError(NO_LLEGO, 0);
  } finally {
    clearTimeout(t);
  }
  let data = null;
  try { data = await res.json(); } catch { /* respuesta vacía */ }
  if (res.status === 401) {
    noAutorizado(data);
    throw new ApiError('Este móvil ya no está autorizado. Vuelve a emparejarlo.', 401, data);
  }
  if (!res.ok) throw new ApiError((data && data.error) || `Error ${res.status}`, res.status, data);
  return data;
}

export const api = {
  estado: () => request('GET', '/api/estado'),
  mensaje: (texto) => request('POST', '/api/mensaje', { texto }),
  responder: (id, respuesta) => request('POST', '/api/responder', { id, respuesta }),
  cancelar: () => request('POST', '/api/cancelar', {}),
  ajustes: (cambios) => request('POST', '/api/ajustes', cambios),
  repo: (datos) => request('POST', '/api/repos', datos),
  motor: (nombre, encender) => request('POST', '/api/motor', { nombre, encender }),
  tareas: (n = 40) => request('GET', `/api/tareas?n=${n}`),
  tarea: (id) => request('GET', `/api/tareas/${id}`),
  accion: (id, accion, body = {}) => request('POST', `/api/tareas/${id}/${accion}`, body),
  largo: (datos) => request('POST', '/api/largo', datos),
  log: (tarea, n = 150) => request('GET', `/api/log?n=${n}${tarea ? `&tarea=${tarea}` : ''}`),
  doctor: () => request('GET', '/api/doctor'),
};

// Quién soy para el PC: {dispositivo: {id, nombre}, remoto: true}.
export const yo = () => request('GET', '/api/yo');

// Lee un cuerpo SSE por trozos y llama a `emitir(tipo, datos)` por cada evento completo.
// Formato: líneas «campo: valor»; una línea vacía cierra el evento; «:» al principio es un comentario.
function lectorSSE(emitir) {
  let buf = '';
  let tipo = '';
  let datos = [];
  return (texto) => {
    buf += texto;
    let i;
    while ((i = buf.indexOf('\n')) >= 0) {
      let linea = buf.slice(0, i);
      buf = buf.slice(i + 1);
      if (linea.endsWith('\r')) linea = linea.slice(0, -1);
      if (linea === '') {
        if (datos.length) emitir(tipo || 'message', datos.join('\n'));
        tipo = '';
        datos = [];
        continue;
      }
      if (linea[0] === ':') continue;
      const p = linea.indexOf(':');
      const campo = p < 0 ? linea : linea.slice(0, p);
      let valor = p < 0 ? '' : linea.slice(p + 1);
      if (valor[0] === ' ') valor = valor.slice(1);
      if (campo === 'event') tipo = valor;
      else if (campo === 'data') datos.push(valor);
    }
  };
}

// Conexión en vivo. Cada (re)conexión empieza con «hola» (foto del estado) seguida de la conversación
// reciente marcada como replay. Si se corta, se reintenta cada 2,5 s; si el PC dice 401, se para.
export function connect({ onHello, onMessage, onStatus }) {
  let parado = false;
  let reintento = null;
  let vigia = null;
  let ctrl = null;

  const caer = () => {
    clearTimeout(vigia);
    if (parado) return;
    onStatus(false);
    clearTimeout(reintento);
    reintento = setTimeout(abrir, REINTENTO_MS);
  };

  const vigilar = () => {
    clearTimeout(vigia);
    vigia = setTimeout(() => ctrl && ctrl.abort(), SILENCIO_MS);
  };

  const emitir = (tipo, datos) => {
    let m;
    try { m = JSON.parse(datos); } catch (err) { console.error('evento ilegible', err); return; }
    if (tipo === 'hola') { onStatus(true); onHello(m); } else if (tipo === 'message') onMessage(m);
  };

  async function abrir() {
    if (parado) return;
    ctrl = new AbortController();
    let res;
    try {
      vigilar();
      res = await fetch(BASE + '/api/stream', {
        headers: cabeceras({ Accept: 'text/event-stream' }), cache: 'no-store', signal: ctrl.signal,
      });
    } catch {
      caer();
      return;
    }
    if (res.status === 401) {
      clearTimeout(vigia);
      let data = null;
      try { data = await res.json(); } catch { /* sin cuerpo */ }
      onStatus(false);
      noAutorizado(data);
      return;
    }
    if (!res.ok || !res.body) { caer(); return; }
    const leer = lectorSSE((tipo, datos) => { try { emitir(tipo, datos); } catch (e) { console.error(e); } });
    const dec = new TextDecoder();
    const reader = res.body.getReader();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        ultimo = Date.now();
        vigilar();
        leer(dec.decode(value, { stream: true }));
      }
    } catch { /* cortada o abortada */ }
    caer();
  }

  // Al volver de segundo plano: si el stream lleva más de 20 s sin ni un «ping», se reabre ya.
  let ultimo = Date.now();
  const visibilidad = () => {
    if (!document.hidden && !parado && ctrl && Date.now() - ultimo > 20000) ctrl.abort();
  };
  document.addEventListener('visibilitychange', visibilidad);

  abrir();
  return () => {
    parado = true;
    clearTimeout(reintento);
    clearTimeout(vigia);
    document.removeEventListener('visibilitychange', visibilidad);
    ctrl && ctrl.abort();
  };
}
