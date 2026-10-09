// Punto único de acceso al servidor. La interfaz solo importa `api` y `connect` de aquí.
// Modo «demo»: datos de prueba dentro de la app, sin conexión.
// Modo «pc»: Skynet en tu PC (`skynet web` publicado con `tailscale serve`), por HTTP + SSE con llave.
import * as demo from './backend/demo.js';
import * as http from './backend/http.js';
import { ApiError } from './backend/error.js';
export { ApiError };

const KEY = 'skynet.conexion';
export const NOMBRE_POR_DEFECTO = 'Móvil de Daniel';

// {modo: 'demo'|'pc', url, llave, dispositivo: {id, nombre}|null}
export function conexion() {
  let c = {};
  try { c = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch { /* sin almacenamiento */ }
  return { modo: 'demo', url: '', llave: '', dispositivo: null, ...c };
}
export function guardarConexion(c) {
  try { localStorage.setItem(KEY, JSON.stringify(c)); } catch { /* sin almacenamiento */ }
}
// Olvida la llave y vuelve a demo. Se recuerda el nombre del móvil para el próximo emparejado.
export function olvidarConexion() {
  const c = conexion();
  guardarConexion({ modo: 'demo', url: '', llave: '', dispositivo: null, nombre: c.dispositivo?.nombre || c.nombre || '' });
}

const cfg = conexion();
const usarPC = cfg.modo === 'pc' && !!cfg.url && !!cfg.llave;
const backend = usarPC ? http : demo;

// Lo que hace la app cuando el PC rechaza la llave (lo registra main.js).
let alRechazo = null;
export function onNoAutorizado(fn) { alRechazo = fn; }

if (usarPC) {
  http.setBase(cfg.url);
  http.setLlave(cfg.llave);
  http.onNoAutorizado((data) => {
    olvidarConexion();
    if (alRechazo) alRechazo(data);
  });
}

export const modoConexion = usarPC ? 'pc' : 'demo';
export const api = backend.api;
export const connect = backend.connect;

// «Probar»: pregunta al PC quién es este móvil y cuánto tarda en contestar.
export async function probarConexion() {
  if (!usarPC) throw new ApiError('No estás conectado a tu PC.', 0);
  const t0 = performance.now();
  const d = await http.yo();
  return { ...d, ms: Math.round(performance.now() - t0) };
}

// --- emparejar ---------------------------------------------------------------------
// Acepta `skynet://emparejar?u=<url codificada>&c=<código>` (con espacios o saltos de línea en
// medio, como queda al copiar), cualquier texto con esa misma query (`…?u=…&c=…`), o la dirección
// del PC seguida del código: `https://pc.tail1234.ts.net ABCD-1234`.
export function leerEnlace(texto) {
  const raw = String(texto || '').trim();
  if (!raw) return null;
  const junto = raw.replace(/\s+/g, '');
  let u = '', c = '';
  const q = junto.indexOf('?');
  const query = q >= 0 ? junto.slice(q + 1) : /^[uc]=/i.test(junto) ? junto : '';
  if (query) {
    try {
      const p = new URLSearchParams(query.split('#')[0]);
      u = p.get('u') || '';
      c = p.get('c') || '';
    } catch { /* query rota */ }
  }
  if (!(u && c)) {
    const m = raw.match(/(https?:\/\/[^\s?#]+)\s+([A-Za-z0-9][A-Za-z0-9_-]{3,})\s*$/);
    if (m) { u = m[1]; c = m[2]; }
  }
  if (!u || !c) return null;
  let url;
  try { url = new URL(u); } catch { return null; }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
  return { url: (url.origin + url.pathname).replace(/\/+$/, ''), host: url.host, codigo: c.trim() };
}

const MSG_CODIGO = 'El código ha caducado o ya se usó. Genera otro en el PC.';

export async function emparejar(enlaceOTexto, nombre) {
  const e = leerEnlace(enlaceOTexto);
  if (!e) throw new ApiError('Ese enlace no vale. Escanea el QR o pega el enlace que empieza por skynet://', 400);
  nombre = String(nombre || '').trim().slice(0, 60) || NOMBRE_POR_DEFECTO;
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), 15000);
  let res;
  try {
    res = await fetch(e.url + '/api/emparejar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({ codigo: e.codigo, nombre }),
      cache: 'no-store',
      signal: ctrl.signal,
    });
  } catch {
    throw new ApiError(http.NO_LLEGO, 0);
  } finally {
    clearTimeout(t);
  }
  let data = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  if (res.status === 403) {
    // 403 casi siempre es el código; si el servidor explica otra cosa (Funnel, origen...), se enseña eso.
    const err = data && data.error ? String(data.error) : '';
    throw new ApiError(!err || /c[oó]digo|caduc|usad|expir/i.test(err) ? MSG_CODIGO : err, 403, data);
  }
  if (!res.ok || !data || !data.llave) {
    throw new ApiError((data && data.error) || `Tu PC respondió con un error (${res.status}).`, res.status, data);
  }
  const c = { modo: 'pc', url: e.url, llave: String(data.llave), dispositivo: data.dispositivo || { id: '', nombre } };
  guardarConexion(c);
  return c;
}
