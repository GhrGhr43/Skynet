// Cliente del servidor local de Skynet: JSON por HTTP y eventos en vivo por SSE.
export class ApiError extends Error {
  constructor(message, status, data = null) {
    super(message);
    this.status = status;
    this.data = data;  // p. ej. {confirmar: {...}} cuando el servidor pide una confirmación (409)
  }
}

async function request(method, url, body) {
  const opts = { method, headers: { Accept: 'application/json' } };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(url, opts);
  } catch {
    throw new ApiError('No hay conexión con Skynet. ¿Sigue abierta la ventana de «skynet web»?', 0);
  }
  let data = null;
  try { data = await res.json(); } catch { /* respuesta vacía */ }
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
  modelosLocales: () => request('GET', '/api/modelos-locales'),
  elegirLocal: (nombre) => request('POST', '/api/modelo-local', { nombre }),
  motor: (nombre, encender) => request('POST', '/api/motor', { nombre, encender }),
  tareas: (n = 40) => request('GET', `/api/tareas?n=${n}`),
  tarea: (id) => request('GET', `/api/tareas/${id}`),
  accion: (id, accion, body = {}) => request('POST', `/api/tareas/${id}/${accion}`, body),
  largo: (datos) => request('POST', '/api/largo', datos),
  log: (tarea, n = 150) => request('GET', `/api/log?n=${n}${tarea ? `&tarea=${tarea}` : ''}`),
  doctor: () => request('GET', '/api/doctor'),
  // Móviles vinculados (solo desde el PC).
  dispositivos: () => request('GET', '/api/dispositivos'),
  emparejarDispositivo: (nombre) => request('POST', '/api/dispositivos/emparejar', nombre ? { nombre } : {}),
  revocarDispositivo: (id) => request('POST', `/api/dispositivos/${encodeURIComponent(id)}/revocar`, {}),
};

// Conexión en vivo. EventSource reconecta solo; cada reconexión empieza con "hola" (foto del
// estado) seguida de la conversación reciente marcada como replay.
export function connect({ onHello, onMessage, onStatus }) {
  let es = null;
  let retry = null;
  const open = () => {
    es = new EventSource('/api/stream');
    es.addEventListener('hola', (e) => { onStatus(true); onHello(JSON.parse(e.data)); });
    es.onmessage = (e) => {
      try { onMessage(JSON.parse(e.data)); } catch (err) { console.error('evento ilegible', err); }
    };
    es.onerror = () => {
      onStatus(false);
      // Si el navegador da la conexión por perdida (servidor cerrado), se reintenta a mano.
      if (es.readyState === EventSource.CLOSED) {
        clearTimeout(retry);
        retry = setTimeout(open, 2500);
      }
    };
  };
  open();
  return () => { clearTimeout(retry); es && es.close(); };
}
