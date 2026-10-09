// Servidor de mentira para la app móvil sin conexión: mismas respuestas y eventos que `skynet web`
// (ver skynet/web/server.py), con datos de prueba. Nada sale del teléfono.
import { ApiError } from './error.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = () => new Date().toISOString();
const ago = (min) => new Date(Date.now() - min * 60000).toISOString();

const MODOS = [
  { clave: 'repo', nombre: 'Solo repo', descripcion: 'Lee, edita y ejecuta tests solo dentro del repo autorizado.', fuerte: false },
  { clave: 'lectura', nombre: 'Ver mi PC', descripcion: 'Además puede leer archivos de todo tu PC. No escribe ni ejecuta nada fuera del repo.', fuerte: false },
  { clave: 'editar', nombre: 'Ver y editar', descripcion: 'Además puede crear y editar archivos de tu usuario. No ejecuta programas.', fuerte: true },
  { clave: 'total', nombre: 'Control total', descripcion: 'Además ejecuta comandos y abre programas, por ejemplo Steam para instalar un juego.', fuerte: true },
];
const SIEMPRE = 'Siempre se pregunta, en cualquier modo: pedir administrador, tocar carpetas del sistema (Windows, Program Files, registro), borrar archivos y leer contraseñas, claves o cookies.';
const SIN_PREGUNTAR = 'Sin preguntar: no pide confirmación para nada (administrador, carpetas del sistema, borrar, secretos). Todo queda en el registro. Solo en Control total y nunca en tareas largas.';
const HELP = `continúa            retoma la última tarea a medias
/tareas             lista de tareas
/largo <h> <obj>    tarea larga verificada
/log [tarea]        registro y consumo
/modelo <nombre>    fija el modelo (auto, local, gemini, anthropic)
/razonamiento <n>   auto, rápido, equilibrado, pensar más
/doctor             diagnóstico`;

const state = {
  repo: 'skynet',
  modelo: 'auto',
  privado: false,
  razonamiento: 'auto',
  ocupado: false,
  etiqueta: null,
  repos: [
    { nombre: 'skynet', ruta: 'C:\\Skynet', verificador: 'pytest -q', agente: 'skynet', privacidad: 'normal', existe: true },
    { nombre: 'agente-godot', ruta: 'C:\\Users\\HACHO\\Documents\\agente-godot', verificador: 'godot --headless --check-only', agente: 'agente-godot', privacidad: 'normal', existe: true },
  ],
  modelos: [
    { nombre: 'local', litellm: 'openai/qwen3.8-27b-ud-iq3_xxs', privado: true, gratis: true, disponible: true, motivo: '', activado: true, modo: 'repo', sin_preguntar: false, coste: [0, 0] },
    { nombre: 'gemini', litellm: 'gemini/gemini-flash-latest', privado: false, gratis: true, disponible: false, motivo: 'desactivado (modelo en la nube)', activado: false, modo: 'repo', sin_preguntar: false, coste: [0, 0] },
    { nombre: 'anthropic', litellm: 'anthropic/claude-sonnet-5-5', privado: false, gratis: false, disponible: false, motivo: 'desactivado (modelo en la nube)', activado: false, modo: 'repo', sin_preguntar: false, coste: [3, 15] },
  ],
  motores: [{ nombre: 'local', encendido: true, ocupado: false }],
};

const tasks = [
  { id: 14, title: 'Añadir selector de razonamiento al chat', goal: 'Añadir selector de razonamiento al chat', agent: 'skynet', repo: 'skynet', status: 'hecha', created_at: ago(190), updated_at: ago(170), larga: false, iters_done: 0, max_hours: null,
    result_summary: 'Selector **Auto / Rápido / Equilibrado / Pensar más** junto al modelo, y comando `/razonamiento`. Tests: 42 pasan.' },
  { id: 15, title: 'Que pasen todos los tests del parser', goal: 'Haz que pasen todos los tests del parser de comandos', agent: 'scheduler', repo: 'skynet', status: 'en_curso', created_at: ago(95), updated_at: ago(3), larga: true, iters_done: 7, max_hours: 2, result_summary: null },
  { id: 16, title: 'Revisar el bucle de enemigos del nivel 2', goal: 'Revisar el bucle de enemigos del nivel 2 y arreglar el que no reaparece', agent: 'agente-godot', repo: 'agente-godot', status: 'pausada', created_at: ago(60), updated_at: ago(41), larga: false, iters_done: 0, max_hours: null, result_summary: null },
  { id: 13, title: '¿Qué modelos locales caben en mi GPU?', goal: '¿Qué modelos locales caben en mi GPU?', agent: 'chat', repo: null, status: 'hecha', created_at: ago(1500), updated_at: ago(1495), larga: false, iters_done: 0, max_hours: null,
    result_summary: 'Con 16 GB de VRAM: Qwen3.8-27B en IQ3_XXS con MTP (~45 tok/s) es el mejor equilibrio.' },
];
const vivo = (t) => t.larga && t.status === 'en_curso';
const taskDict = (t) => ({ ...t, vivo: vivo(t) });

const events = [
  { ts: ago(170), type: 'task', task_id: 14, decision: 'hecha', descripcion: 'Tarea 14 terminada' },
  { ts: ago(171), type: 'verifier', task_id: 14, detail: { ok: true }, descripcion: 'pytest -q · 42 pasan' },
  { ts: ago(172), type: 'llm', model: 'openai/qwen3.8-27b', task_id: 14, tokens_in: 6120, tokens_out: 940, cost_eur: 0, descripcion: 'Respuesta final' },
  { ts: ago(174), type: 'tool', tool: 'workspace.edit_file', task_id: 14, permission_level: 'WRITE', decision: 'permitido', descripcion: "edit_file(path='skynet/web/static/js/app.js')" },
  { ts: ago(176), type: 'route', task_id: 14, descripcion: 'local · privado y gratis' },
  { ts: ago(42), type: 'permission', task_id: 16, permission_level: 'EXECUTE', decision: 'denegado', descripcion: 'run_command(godot --headless) sin tu confirmación' },
  { ts: ago(5), type: 'commit', task_id: 15, descripcion: 'iteración 7: arregla el caso de comillas vacías' },
  { ts: ago(4), type: 'verifier', task_id: 15, detail: { ok: true }, descripcion: 'pytest tests/test_parser.py · 18/21' },
  { ts: ago(3), type: 'llm', model: 'openai/qwen3.8-27b', task_id: 15, tokens_in: 8200, tokens_out: 610, cost_eur: 0, descripcion: 'Iteración 8' },
];

function totals(taskId) {
  const evs = events.filter((e) => e.type === 'llm' && (!taskId || e.task_id === taskId));
  return {
    llamadas: evs.length * 7,
    tokens_in: evs.reduce((a, e) => a + (e.tokens_in || 0), 0) * 7,
    tokens_out: evs.reduce((a, e) => a + (e.tokens_out || 0), 0) * 7,
    cost_eur: 0,
  };
}

function efectivo() {
  if (state.modelo !== 'auto') return state.modelo;
  return 'local';
}

function snapshot() {
  const m = state.modelos.find((x) => x.nombre === efectivo()) || state.modelos[0];
  const pend = tasks.find((t) => t.status === 'pausada');
  return {
    version: '0.4-movil',
    repo: state.repo,
    modelo: state.modelo,
    privado: state.privado,
    razonamiento: state.razonamiento,
    ocupado: state.ocupado,
    etiqueta: state.etiqueta,
    preguntas: question ? [question] : [],
    repos: state.repos,
    modelos: state.modelos,
    motores: state.motores,
    reglas: [
      { si: { privacidad: 'alta' }, usar: 'local', motivo: 'Datos privados: solo el modelo local' },
      { si: { coding: true }, usar: 'local', motivo: 'Código en un repo: modelo local' },
      { si: {}, usar: 'gemini', motivo: 'Resto: Gemini Flash si está activado, si no local' },
    ],
    presupuesto_eur: 0,
    mes: totals(),
    pendiente: pend ? taskDict(pend) : null,
    largas_vivas: tasks.filter(vivo).map((t) => t.id),
    limites: { max_horas: 8 },
    ayuda: HELP,
    propuestas: 1,
    modos: MODOS,
    modo_actual: m.modo,
    sin_preguntar_actual: m.sin_preguntar,
    sin_preguntar_texto: SIN_PREGUNTAR,
    modelo_efectivo: m.nombre,
    siempre: SIEMPRE,
  };
}

// --- bus de eventos (lo que en el PC llega por SSE) ----------------------------
let seq = 0;
const history = [];
const listeners = new Set();
function publish(tipo, data = {}) {
  const m = { seq: ++seq, tipo, ...data };
  if (!['estado', 'tareas', 'ocupado'].includes(tipo)) history.push(m);
  for (const l of listeners) l.onMessage(m);
  return m;
}

// --- conversación simulada ------------------------------------------------------
let question = null;
let answerQ = null;
let run = 0;
let nextTask = 17;

function ask(payload) {
  question = { id: `q${seq + 1}`, ...payload };
  publish('pregunta', question);
  return new Promise((resolve) => { answerQ = resolve; });
}

function closeQ() {
  if (!question) return;
  const id = question.id;
  question = null;
  answerQ = null;
  publish('pregunta_cerrada', { id });
}

function setBusy(on, label = null) {
  state.ocupado = on;
  state.etiqueta = on ? label : null;
  publish('ocupado', { ocupado: on, etiqueta: state.etiqueta });
}

function reply(text) {
  const t = text.toLowerCase();
  if (/hola|qué puedes|que puedes/.test(t)) {
    return 'Hola, Daniel. Esta es la **app móvil en modo demo**: todavía no está conectada a tu PC, así que respondo con datos de prueba.\n\nCuando esté conectada podrás pedirme desde aquí lo mismo que en el PC:\n\n- Tareas de código en tus repos, con permisos y verificación.\n- Seguir una tarea larga y ver su progreso.\n- Revisar el registro, el consumo y los modelos.';
  }
  if (/test|prueba/.test(t)) {
    return 'He ejecutado los tests del repo **skynet**: `42 pasan, 0 fallan`.\n\nNo he cambiado ningún archivo.';
  }
  if (/repo|explica/.test(t)) {
    return '**skynet** es tu Personal Agent OS:\n\n1. `coordinator.py` recibe tus mensajes y decide modelo y herramientas.\n2. `gate.py` pide permiso para lo arriesgado.\n3. `store.py` guarda tareas y registro en SQLite.\n\nLo siguiente pendiente según `PROGRESO.md`: probar el adaptador de agente-godot en un juego real.';
  }
  return `Entendido: «${text.slice(0, 80)}».\n\nEn esta versión de prueba no hago nada de verdad; cuando la app se conecte a tu PC, esta petición la ejecutará Skynet allí con el modelo **${efectivo()}**.`;
}

async function simulate(text, myRun) {
  const alive = () => myRun === run;
  const id = nextTask++;
  const repo = state.repo;
  tasks.unshift({ id, title: text.slice(0, 70), goal: text, agent: repo ? 'skynet' : 'chat', repo, status: 'en_curso', created_at: now(), updated_at: now(), larga: false, iters_done: 0, max_hours: null, result_summary: null });
  const task = tasks[0];
  const ev = (kind, datos) => alive() && publish('evento', { kind, datos });
  const m = state.modelos.find((x) => x.nombre === efectivo());
  ev('route', { model: m.litellm, reason: repo ? 'código en repo · privado y gratis' : 'conversación · privado y gratis' });
  await sleep(500); ev('thinking', { turn: 1 }); await sleep(1300);
  if (!alive()) return;
  let tools = 0;
  const wantsRun = repo && /test|prueba|ejecuta|instala/i.test(text);
  if (repo) {
    ev('tool', { key: 'workspace.read_file', args: "path='README.md'" }); tools++; await sleep(700);
    ev('tool_result', { ok: true });
    ev('tool', { key: 'workspace.search', args: "pattern='TODO'" }); tools++; await sleep(800);
    ev('tool_result', { ok: true });
    if (!alive()) return;
  }
  let verified = null;
  if (wantsRun) {
    task.status = 'esperando_permiso';
    const cmd = 'pytest -q';
    ev('tool', { key: 'workspace.run_command', args: `command='${cmd}'` }); tools++;
    const r = await ask({ clase: 'permiso', tarea: id, herramienta: 'workspace.run_command', nivel: 'EXECUTE', args: `command='${cmd}'`, motivo: 'El comando no está en la lista blanca.', todas: true });
    closeQ();
    if (!alive()) return;
    task.status = 'en_curso';
    if (r === 'n') {
      ev('denied', { key: 'workspace.run_command', reason: 'Lo has denegado' });
    } else {
      await sleep(1200); ev('tool_result', { ok: true });
      ev('verifying', { command: cmd }); await sleep(1400);
      verified = 'OK';
    }
  }
  ev('thinking', { turn: 2 }); await sleep(1000);
  if (!alive()) return;
  const answer = reply(text);
  publish('respuesta', { texto: answer });
  task.status = 'hecha';
  task.updated_at = now();
  task.result_summary = answer.split('\n')[0];
  const tin = 1800 + Math.round(Math.random() * 3000), tout = 200 + Math.round(Math.random() * 500);
  events.push({ ts: now(), type: 'llm', model: m.litellm, task_id: id, tokens_in: tin, tokens_out: tout, cost_eur: 0, descripcion: 'Respuesta final' });
  publish('info', { texto: `${m.nombre} · ${tin}+${tout} tokens · 0 € · ${tools} herramientas · tarea ${id}: hecha${verified ? ` · verificador ${verified}` : ''}` });
  setBusy(false);
  publish('tareas', {});
}

function confirmErr(tipo, titulo, texto, boton) {
  return new ApiError(titulo, 409, { confirmar: { tipo, titulo, texto, boton } });
}

const DOCTOR = [
  { nombre: 'Configuración', estado: 'ok', detalle: 'config/skynet.toml' },
  { nombre: 'Base de datos', estado: 'ok', detalle: 'skynet.db · 17 tareas' },
  { nombre: 'Git', estado: 'ok', detalle: 'git 2.51' },
  { nombre: 'Modelo local', estado: 'ok', detalle: 'Qwen3.8-27B · llama-server :8090' },
  { nombre: 'Gemini', estado: 'off', detalle: 'Desactivado' },
  { nombre: 'Conexión con el PC', estado: 'mal', detalle: 'Modo demo: la app aún no se conecta a tu PC' },
];

export const api = {
  async estado() { return snapshot(); },
  async mensaje(texto) {
    texto = String(texto || '').trim();
    if (!texto) throw new ApiError('Mensaje vacío', 400);
    if (state.ocupado) throw new ApiError(`Skynet está trabajando en «${state.etiqueta}». Espera o pulsa Detener.`, 409);
    if (texto.startsWith('/')) {
      publish('usuario', { texto });
      if (/^\/doctor/i.test(texto)) publish('diagnostico', { checks: DOCTOR });
      else publish('info', { texto: 'Los comandos de texto llegarán cuando la app se conecte a tu PC.' });
      return { ok: true };
    }
    publish('usuario', { texto });
    setBusy(true, texto.split('\n')[0].slice(0, 70));
    simulate(texto, ++run);
    return { ok: true };
  },
  async responder(id, respuesta) {
    if (!question || question.id !== id || !answerQ) throw new ApiError('Esa pregunta ya no está abierta', 404);
    answerQ(respuesta);
    return { ok: true };
  },
  async cancelar() {
    if (!state.ocupado) return { ok: true, cancelado: false };
    run++;
    if (answerQ) answerQ('n');
    closeQ();
    const t = tasks.find((x) => x.status === 'en_curso' && !x.larga);
    if (t) t.status = 'pausada';
    publish('info', { texto: 'Detenido. La tarea queda pausada; «continuar» la retoma.' });
    setBusy(false);
    return { ok: true, cancelado: true };
  },
  async ajustes(b) {
    const byName = (n) => state.modelos.find((x) => x.nombre === n);
    const sp = b.sin_preguntar;
    if (sp?.activar && !b.confirmar) {
      return Promise.reject(confirmErr('aviso', `¿${sp.modelo} sin preguntar nada?`,
        `${sp.modelo} podrá hacer cualquier cosa en tu PC sin preguntarte: instalar o desinstalar programas, borrar archivos, tocar carpetas del sistema y leer contraseñas o claves.`, 'Sí, sin preguntar'));
    }
    if ('repo' in b) {
      state.repo = ['', 'ninguno', null].includes(b.repo) ? null : b.repo;
      publish('info', { texto: state.repo ? `Repo: ${state.repo}` : 'Sin repo: conversación sin herramientas.' });
    }
    if ('razonamiento' in b) state.razonamiento = b.razonamiento;
    if (b.nube) {
      const m = byName(b.nube.modelo);
      if (b.nube.activar && !m.activado && !b.confirmar) {
        throw confirmErr('nube', `¿Activar ${m.nombre}?`, `${m.nombre} funciona en la nube: tus mensajes y lo que Skynet lea para la tarea salen de tu PC.`, 'Activar');
      }
      m.activado = m.disponible = !!b.nube.activar;
      m.motivo = m.activado ? '' : 'desactivado (modelo en la nube)';
      if (!m.activado && state.modelo === m.nombre) state.modelo = 'local';
    }
    if (b.permiso) {
      const m = byName(b.permiso.modelo);
      const fuerte = MODOS.find((o) => o.clave === b.permiso.modo)?.fuerte;
      if (!m.privado && fuerte && !b.confirmar) {
        throw confirmErr('aviso', `Modo «${MODOS.find((o) => o.clave === b.permiso.modo).nombre}» en un modelo en la nube`,
          `${m.nombre} es un modelo en la nube: todo lo que lea de tu PC se envía a su proveedor.`, 'Entiendo, darle este modo');
      }
      m.modo = b.permiso.modo;
      if (m.modo !== 'total') m.sin_preguntar = false;
    }
    if (sp) byName(sp.modelo).sin_preguntar = !!sp.activar;
    if ('modelo' in b) {
      const m = byName(b.modelo);
      if (m && !m.activado) {
        if (!b.confirmar) throw confirmErr('nube', `¿Activar ${m.nombre}?`, `${m.nombre} funciona en la nube: tus mensajes y lo que Skynet lea para la tarea salen de tu PC.`, 'Activar');
        m.activado = m.disponible = true;
        m.motivo = '';
      }
      state.modelo = m ? m.nombre : 'auto';
      publish('info', { texto: `Modelo: ${state.modelo === 'auto' ? 'automático (router)' : state.modelo}` });
    }
    const snap = snapshot();
    publish('estado', snap);
    return snap;
  },
  async repo() { throw new ApiError('Para añadir repos, hazlo desde el PC (la app aún no está conectada).', 400); },
  async motor(nombre, encender) {
    const e = state.motores.find((x) => x.nombre === nombre);
    if (e) e.encendido = !!encender;
    publish('info', { texto: `Motor ${nombre} ${encender ? 'encendido' : 'apagado'} (demo).` });
    return snapshot();
  },
  async tareas(n = 40) { await sleep(150); return tasks.slice(0, n).map(taskDict); },
  async tarea(id) {
    await sleep(150);
    const t = tasks.find((x) => x.id === +id);
    if (!t) throw new ApiError('No existe esa tarea', 404);
    const pasos = t.larga
      ? Array.from({ length: t.iters_done }, (_, i) => ({ n: i + 1, kind: 'iteracion', status: i === 3 ? 'revertida' : 'avance', started_at: ago(95 - i * 12), output_summary: ['Lee el parser y los tests', 'Arregla escapes', 'Soporta comillas simples', 'Intenta reescribir el tokenizer', 'Vuelve al tokenizer anterior y ajusta', 'Arregla espacios finales', 'Arregla el caso de comillas vacías'][i], verifier_result: `pytest · ${12 + i}/21`, commit_sha: i === 3 ? null : `a${i}f3c9e21b` }))
      : [];
    return {
      tarea: taskDict(t), pasos,
      eventos: events.filter((e) => e.task_id === t.id),
      consumo: totals(t.id),
      progreso: t.larga ? '# PROGRESO\n\n**Objetivo:** que pasen todos los tests del parser.\n\n- 18 de 21 tests pasan.\n- Falta: comillas anidadas y `\\n` literal.' : null,
    };
  },
  async accion(id, accion) {
    const t = tasks.find((x) => x.id === +id);
    if (!t) throw new ApiError('No existe esa tarea', 404);
    if (accion === 'parar') { t.status = 'pausada'; publish('info', { texto: `Pedida la parada de la tarea ${t.id}.` }); }
    else if (accion === 'descartar') { t.status = 'fallida'; publish('info', { texto: `Tarea ${t.id} descartada.` }); }
    else if (accion === 'continuar') { t.status = 'hecha'; return api.mensaje(`continúa la tarea ${t.id}`); }
    publish('estado', snapshot());
    publish('tareas', {});
    return { ok: true };
  },
  async largo({ repo, horas, objetivo }) {
    const id = nextTask++;
    tasks.unshift({ id, title: objetivo.slice(0, 70), goal: objetivo, agent: 'scheduler', repo, status: 'en_curso', created_at: now(), updated_at: now(), larga: true, iters_done: 0, max_hours: horas, result_summary: null });
    publish('usuario', { texto: `Tarea larga (${horas} h) en ${repo}: ${objetivo}` });
    publish('info', { texto: `Tarea larga ${id} lanzada (demo). Aparece como una luz en órbita.` });
    publish('estado', snapshot());
    return { ok: true };
  },
  async log(tarea) {
    await sleep(150);
    return { eventos: events.filter((e) => !tarea || e.task_id === +tarea).slice(-150), total: totals(tarea), mes: totals() };
  },
  async doctor() { await sleep(600); return { checks: DOCTOR }; },
};

export function connect({ onHello, onMessage, onStatus }) {
  const l = { onMessage };
  setTimeout(() => {
    onStatus(true);
    onHello(snapshot());
    for (const m of history) onMessage({ ...m, replay: true });
    listeners.add(l);
  }, 250);
  return () => listeners.delete(l);
}
