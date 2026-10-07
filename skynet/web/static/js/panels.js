// Paneles laterales: todo lo que antes eran comandos (/tareas, /largo, /log, /modelo, /repo,
// /privado, /doctor, /ayuda) como pantallas que se entienden sin saberse nada.
import { api } from './api.js';
import { md, esc } from './md.js';
import { icon, paintIcons } from './icons.js';
import { QUALITY } from './scene/engine.js';

const $ = (s, r = document) => r.querySelector(s);

const TITLES = {
  tareas: 'Tareas',
  largo: 'Tarea larga',
  registro: 'Registro y consumo',
  ajustes: 'Modelos y repos',
  diagnostico: 'Diagnóstico',
  ayuda: 'Qué puede hacer Skynet',
};

const STATUS_TEXT = {
  pendiente: 'pendiente', en_curso: 'en curso', esperando_permiso: 'esperando permiso',
  hecha: 'hecha', fallida: 'fallida', pausada: 'pausada',
};

const AGENT_TEXT = { chat: 'conversación', skynet: 'programador', scheduler: 'tarea larga', 'agente-godot': 'agente-godot' };

function ago(ts) {
  if (!ts) return '';
  const s = (Date.now() - new Date(ts).getTime()) / 1000;
  if (s < 60) return 'hace un momento';
  if (s < 3600) return `hace ${Math.round(s / 60)} min`;
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`;
  return new Date(ts).toLocaleDateString('es-ES', { day: 'numeric', month: 'short' });
}

function clock(ts) {
  try { return new Date(ts).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' }); } catch { return ''; }
}

function pill(status, live) {
  return `<span class="pill s-${esc(status)} ${live ? 'live' : ''}">${esc(STATUS_TEXT[status] || status)}${live ? ' · trabajando' : ''}</span>`;
}

const fmt = (n) => Number(n || 0).toLocaleString('es-ES');
const eur = (n) => `${Number(n || 0).toLocaleString('es-ES', { minimumFractionDigits: 2, maximumFractionDigits: 4 })} €`;

export class Panels {
  constructor(app) {
    this.app = app;
    this.current = null;
    this.detail = null;
    this.timer = null;
    this.body = $('#panelBody');
  }

  toggle(name) {
    if (name === 'conversacion') {
      this.close();
      document.body.classList.toggle('convo-hidden');
      const hidden = document.body.classList.contains('convo-hidden');
      document.body.classList.toggle('has-convo', !hidden && this.app.convo.children.length > 0);
      if (!hidden && !this.app.convo.children.length) this.app.toast('Aún no hay conversación. Escribe abajo para empezar.');
      this.app.updateFocus();
      this.markRail();
      return;
    }
    if (this.current === name && !this.detail) this.close();
    else this.open(name);
  }

  open(name, opts = {}) {
    this.current = name;
    this.detail = opts.detail ?? null;
    $('#panelTitle').textContent = TITLES[name] || '';
    const panel = $('#panel');
    panel.classList.add('open');
    panel.setAttribute('aria-hidden', 'false');
    document.body.classList.add('has-panel');
    this.markRail();
    this.app.updateFocus();
    clearInterval(this.timer);
    this.render();
    if (name === 'tareas' || name === 'registro') this.timer = setInterval(() => this.render(true), 4000);
  }

  close() {
    this.current = null;
    this.detail = null;
    clearInterval(this.timer);
    const panel = $('#panel');
    panel.classList.remove('open');
    panel.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('has-panel');
    this.markRail();
    this.app.updateFocus();
  }

  markRail() {
    for (const b of document.querySelectorAll('.rail-btn')) {
      const p = b.dataset.panel;
      b.classList.toggle('active', p === this.current || (p === 'conversacion' && !this.current && document.body.classList.contains('has-convo')));
    }
  }

  refresh() {
    if (this.current) this.render(true);
  }

  onSnap() {
    if (this.current === 'ajustes') this.render(true);
  }

  onDiag(checks) {
    if (this.current === 'diagnostico') this.paintDiag(checks);
  }

  async render(silent = false) {
    const name = this.current;
    const body = this.body;
    if (!silent) body.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    try {
      if (name === 'tareas') await (this.detail ? this.renderTask(this.detail, silent) : this.renderTasks());
      else if (name === 'largo') this.renderLong();
      else if (name === 'registro') await this.renderLog(silent);
      else if (name === 'ajustes') this.renderSettings();
      else if (name === 'diagnostico') this.renderDiag();
      else if (name === 'ayuda') this.renderHelp();
    } catch (e) {
      if (!silent) body.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
    paintIcons(body);
  }

  // Mantiene el scroll y el foco al refrescar en caliente.
  paint(html) {
    const top = this.body.scrollTop;
    const active = document.activeElement && this.body.contains(document.activeElement) ? document.activeElement.id : null;
    this.body.innerHTML = html;
    this.body.scrollTop = top;
    if (active) document.getElementById(active)?.focus();
  }

  // --- tareas -------------------------------------------------------------
  async renderTasks() {
    const tasks = await api.tareas(40);
    if (this.current !== 'tareas' || this.detail) return;
    const pend = this.app.snap?.pendiente;
    let html = '<p class="lead">Todo lo que le has pedido queda guardado. Las tareas a medias se pueden continuar aunque hayas cerrado Skynet.</p>';
    if (!tasks.length) html += '<div class="empty">Aún no hay tareas. Pídele algo a Skynet abajo.</div>';
    for (const t of tasks) {
      const isPend = pend && pend.id === t.id;
      html += `<div class="card clickable ${isPend ? 'selected' : ''}" data-task="${t.id}">
        <div class="card-row"><div class="grow card-title ellipsis">${esc(t.title)}</div>${pill(t.status, t.vivo)}</div>
        <div class="card-sub">#${t.id} · ${esc(AGENT_TEXT[t.agent] || t.agent)}${t.repo ? ` · ${esc(t.repo)}` : ''}${t.larga ? ` · ${t.iters_done} iteraciones` : ''} · ${ago(t.updated_at)}${isPend ? ' · <b>la retoma «continuar»</b>' : ''}</div>
      </div>`;
    }
    this.paint(html);
    for (const c of this.body.querySelectorAll('[data-task]')) c.addEventListener('click', () => { this.detail = +c.dataset.task; this.render(); });
  }

  async renderTask(id, silent) {
    const d = await api.tarea(id);
    if (this.current !== 'tareas' || this.detail !== id) return;
    const t = d.tarea;
    const done = t.status === 'hecha' || t.status === 'fallida';
    const busy = this.app.busy;
    const c = d.consumo || {};
    let html = `<button class="btn small" id="taskBack">${icon('chev')} Todas las tareas</button>
      <div class="section-k">Tarea #${t.id}</div>
      <div class="card">
        <div class="card-row"><div class="grow card-title">${esc(t.title)}</div>${pill(t.status, t.vivo)}</div>
        <div class="card-sub">${esc(AGENT_TEXT[t.agent] || t.agent)}${t.repo ? ` · repo ${esc(t.repo)}` : ''} · creada ${ago(t.created_at)}${t.max_hours ? ` · límite ${t.max_hours} h` : ''}</div>
        ${t.goal !== t.title ? `<div class="card-text">${esc(t.goal)}</div>` : ''}
        ${t.result_summary ? `<div class="section-k" style="margin:14px 0 6px">Resultado</div><div class="md" style="font-size:13px">${md(t.result_summary.slice(0, 1500))}</div>` : ''}
        <div class="btn-row">
          ${!done && !t.vivo ? `<button class="btn primary small" id="tContinue" ${busy ? 'disabled' : ''}>${icon('resume')} Continuar</button>` : ''}
          ${done ? `<button class="btn small" id="tContinue" ${busy ? 'disabled' : ''}>${icon('resume')} Retomar igualmente</button>` : ''}
          ${t.larga && !done ? `<button class="btn warn small" id="tStop">${icon('pause')} Parar</button>` : ''}
          ${!done ? `<button class="btn danger small" id="tDrop">${icon('trash')} Descartar</button>` : ''}
          <button class="btn small" id="tLog">${icon('log')} Ver su registro</button>
        </div>
      </div>
      <div class="section-k">Consumo</div>
      <div class="stats">
        <div class="stat"><div class="stat-v">${fmt(c.llamadas)}</div><div class="stat-k">llamadas al modelo</div></div>
        <div class="stat"><div class="stat-v">${eur(c.cost_eur)}</div><div class="stat-k">coste</div></div>
        <div class="stat"><div class="stat-v">${fmt(c.tokens_in)}</div><div class="stat-k">tokens de entrada</div></div>
        <div class="stat"><div class="stat-v">${fmt(c.tokens_out)}</div><div class="stat-k">tokens de salida</div></div>
      </div>`;
    if (d.pasos?.length) {
      html += '<div class="section-k">Pasos</div><div class="evlist">';
      for (const s of d.pasos.slice(-25).reverse()) {
        const good = ['completado', 'ok', 'avance'].includes(s.status);
        const bad = ['error', 'revertida', 'interrumpido', 'limite_turnos'].includes(s.status);
        html += `<div class="ev"><span class="ev-t">${clock(s.started_at)}</span><span class="ev-i ${good ? 'ok' : bad ? 'bad' : ''}">${icon(good ? 'check' : bad ? 'x' : 'dot')}</span>
          <div class="ev-main"><div class="ev-title">${s.n}. ${esc(s.kind)} · ${esc(s.status)}${s.commit_sha ? ` · <span class="mono">${esc(s.commit_sha.slice(0, 8))}</span>` : ''}</div>
          ${s.output_summary ? `<div class="ev-meta">${esc(s.output_summary.slice(0, 220))}</div>` : ''}
          ${s.verifier_result ? `<div class="ev-sub">${esc(s.verifier_result)}</div>` : ''}</div></div>`;
      }
      html += '</div>';
    }
    if (d.progreso) html += `<div class="section-k">PROGRESO.md del repo</div><div class="card progress-md"><div class="md">${md(d.progreso)}</div></div>`;
    this.paint(html);
    $('#taskBack').addEventListener('click', () => { this.detail = null; this.render(); });
    $('#tContinue')?.addEventListener('click', () => { this.app.resumeTask(t.id); this.close(); });
    $('#tStop')?.addEventListener('click', () => this.taskAction(t.id, 'parar'));
    $('#tDrop')?.addEventListener('click', () => this.taskAction(t.id, 'descartar'));
    $('#tLog').addEventListener('click', () => { this.logTask = t.id; this.open('registro'); });
  }

  async taskAction(id, action) {
    try {
      await api.accion(id, action);
      this.app.toast(action === 'parar' ? `Parada pedida: la tarea ${id} se detiene al acabar la iteración en curso.` : `Tarea ${id} descartada.`);
      this.render(true);
      this.app.poll();
    } catch (e) { this.app.toast(e.message, 'bad'); }
  }

  // --- tarea larga ----------------------------------------------------------
  renderLong() {
    const s = this.app.snap || {};
    const repos = s.repos || [];
    const maxH = s.limites?.max_horas || 8;
    if (!repos.length) {
      this.paint('<p class="lead">Para lanzar una tarea larga necesitas al menos un repo autorizado en <span class="mono">config/repos.toml</span>.</p>');
      return;
    }
    const cur = s.repo || repos[0].nombre;
    const opts = repos.map((r) => `<option value="${esc(r.nombre)}" ${r.nombre === cur ? 'selected' : ''}>${esc(r.nombre)}</option>`).join('');
    this.paint(`
      <p class="lead">Skynet trabaja solo durante horas, en pasos pequeños que un verificador comprueba. Puedes cerrar esta ventana: sigue en segundo plano.</p>
      <label class="field"><span class="field-k">Repo</span><select class="select" id="lRepo">${opts}</select></label>
      <label class="field"><span class="field-k">Objetivo</span><textarea class="textarea" id="lGoal" placeholder="Ej.: haz que pasen todos los tests"></textarea></label>
      <label class="field"><span class="field-k">Duración máxima</span>
        <div class="range-row"><input type="range" id="lHours" min="0.5" max="${maxH}" step="0.5" value="1"><output id="lHoursV">1 h</output></div></label>
      <div class="section-k">Qué va a pasar</div>
      <ol class="steps-list" id="lExplain"></ol>
      <div class="btn-row"><button class="btn primary" id="lGo">${icon('play')} Revisar y lanzar</button></div>
      <p class="note">Antes de empezar te pedirá confirmación. Las acciones que necesiten permiso se deniegan solas durante la tarea, porque no estarás delante.</p>`);
    const explain = () => {
      const r = repos.find((x) => x.nombre === $('#lRepo').value) || repos[0];
      const h = $('#lHours').value;
      $('#lHoursV').textContent = `${String(h).replace('.', ',')} h`;
      $('#lExplain').innerHTML = r.agente === 'agente-godot'
        ? `<li>Lanza <b>agente-godot</b> (noche.ps1) sobre el juego de <b>${esc(r.nombre)}</b>.</li><li>Skynet lo vigila sin gastar modelo.</li><li>Se para al cumplir el plan o a las ${esc(h)} h.</li>`
        : `<li>Guarda un punto de partida con git en <b>${esc(r.nombre)}</b>.</li>
           <li>Cada iteración: el modelo local da un paso y el verificador <span class="mono">${esc(r.verificador || 'ninguno')}</span> lo comprueba.</li>
           <li>Si avanza o no empeora, hace commit; si empeora, lo deshace y apunta el error.</li>
           <li>Escribe el avance en <span class="mono">PROGRESO.md</span>. Para a las ${esc(String(h).replace('.', ','))} h, al cumplirse el objetivo, o si se atasca.</li>`;
    };
    $('#lRepo').addEventListener('change', explain);
    $('#lHours').addEventListener('input', explain);
    explain();
    $('#lGo').addEventListener('click', async () => {
      const objetivo = $('#lGoal').value.trim();
      if (!objetivo) { $('#lGoal').focus(); this.app.toast('Escribe el objetivo de la tarea.'); return; }
      try {
        await api.largo({ repo: $('#lRepo').value, horas: +$('#lHours').value, objetivo });
        this.close();
      } catch (e) { this.app.toast(e.message, 'bad'); }
    });
  }

  // --- registro -----------------------------------------------------------
  async renderLog(silent) {
    const taskId = this.logTask || null;
    const d = await api.log(taskId, 150);
    if (this.current !== 'registro') return;
    const t = d.total || {}, m = d.mes || {};
    const ICON = { llm: 'brain', tool: 'cpu', route: 'route', verifier: 'shield', commit: 'git', rollback: 'resume', permission: 'key', task: 'tasks', error: 'warn' };
    const TYPE = { llm: 'Modelo', tool: 'Herramienta', route: 'Router', verifier: 'Verificador', commit: 'Commit', rollback: 'Rollback', permission: 'Permiso', task: 'Tarea', error: 'Error' };
    let html = `<p class="lead">Cada llamada al modelo, herramienta, permiso y verificación queda anotada en la base de datos local.</p>
      <div class="card-row" style="gap:8px">
        <input class="input" id="logTask" inputmode="numeric" placeholder="Filtrar por tarea #" value="${taskId || ''}" style="max-width:170px">
        ${taskId ? '<button class="btn small" id="logAll">Ver todo</button>' : ''}
      </div>
      <div class="section-k">${taskId ? `Tarea ${taskId}` : 'Total'}</div>
      <div class="stats">
        <div class="stat"><div class="stat-v">${fmt(t.llamadas)}</div><div class="stat-k">llamadas al modelo</div></div>
        <div class="stat"><div class="stat-v">${eur(t.cost_eur)}</div><div class="stat-k">coste</div></div>
        <div class="stat"><div class="stat-v">${fmt(t.tokens_in)}</div><div class="stat-k">tokens de entrada</div></div>
        <div class="stat"><div class="stat-v">${fmt(t.tokens_out)}</div><div class="stat-k">tokens de salida</div></div>
      </div>
      ${taskId ? '' : `<p class="note">Este mes: <b>${fmt(m.llamadas)}</b> llamadas · <b>${fmt((m.tokens_in || 0) + (m.tokens_out || 0))}</b> tokens · <b>${eur(m.cost_eur)}</b>${this.app.snap ? ` · presupuesto cloud ${eur(this.app.snap.presupuesto_eur)}/mes` : ''}</p>`}
      <div class="section-k">Últimos eventos</div><div class="evlist">`;
    const evs = (d.eventos || []).slice().reverse();
    if (!evs.length) html += '<div class="empty">Sin eventos todavía.</div>';
    for (const e of evs) {
      const dec = e.decision || '';
      const bad = ['denegado', 'fallida', 'bloqueado', 'error'].includes(dec) || e.type === 'error' || (e.type === 'verifier' && e.detail && e.detail.ok === false);
      const ok = (e.type === 'verifier' && e.detail?.ok) || dec === 'hecha';
      const title = e.type === 'tool' ? (e.tool || '') : e.type === 'llm' ? String(e.model || '').split('/').pop() : (TYPE[e.type] || e.type);
      const meta = [];
      if (e.task_id) meta.push(`#${e.task_id}`);
      if (e.permission_level) meta.push(e.permission_level);
      if (dec) meta.push(dec);
      if (e.tokens_in || e.tokens_out) meta.push(`${fmt(e.tokens_in)} + ${fmt(e.tokens_out)} tok`);
      if (e.cost_eur) meta.push(eur(e.cost_eur));
      html += `<div class="ev"><span class="ev-t">${clock(e.ts)}</span><span class="ev-i ${bad ? 'bad' : ok ? 'ok' : ''}">${icon(ICON[e.type] || 'dot')}</span>
        <div class="ev-main"><div class="ev-title">${esc(TYPE[e.type] || e.type)}${e.type === 'tool' || e.type === 'llm' ? ` · <span class="mono">${esc(title)}</span>` : ''}</div>
        ${e.descripcion ? `<div class="ev-sub" title="${esc(e.descripcion)}">${esc(e.descripcion)}</div>` : ''}
        <div class="ev-meta">${esc(meta.join(' · '))}</div></div></div>`;
    }
    html += '</div>';
    this.paint(html);
    const inp = $('#logTask');
    inp.addEventListener('change', () => { const v = parseInt(inp.value, 10); this.logTask = Number.isFinite(v) ? v : null; this.render(); });
    $('#logAll')?.addEventListener('click', () => { this.logTask = null; this.render(); });
  }

  // --- ajustes ---------------------------------------------------------------
  async setRepo(name) {
    try { this.app.applySnap(await api.ajustes({ repo: name || 'ninguno' })); } catch (e) { this.app.toast(e.message, 'bad'); }
  }

  async setModel(name) {
    try { this.app.applySnap(await api.ajustes({ modelo: name })); } catch (e) { this.app.toast(e.message, 'bad'); }
  }

  renderSettings() {
    const s = this.app.snap;
    if (!s) return;
    const quality = localStorage.getItem('skynet.calidad') || 'auto';
    let html = '<div class="section-k" style="margin-top:4px">Dónde trabaja</div>';
    html += `<div class="card clickable ${!s.repo ? 'selected' : ''}" data-repo="">
      <div class="card-row">${icon('chat')}<div class="grow"><div class="card-title">Sin repo</div><div class="card-sub">Solo conversación: Skynet no toca archivos.</div></div></div></div>`;
    for (const r of s.repos || []) {
      html += `<div class="card clickable ${s.repo === r.nombre ? 'selected' : ''}" data-repo="${esc(r.nombre)}">
        <div class="card-row">${icon('repo')}<div class="grow"><div class="card-title">${esc(r.nombre)}</div>
        <div class="card-sub mono ellipsis" title="${esc(r.ruta)}">${esc(r.ruta)}</div>
        <div class="card-sub">verificador: <span class="mono">${esc(r.verificador || '—')}</span> · ${esc(r.agente)}${r.privacidad === 'alta' ? ' · privado' : ''}${r.existe ? '' : ' · <span style="color:var(--bad)">la carpeta no existe</span>'}</div></div></div></div>`;
    }
    html += '<p class="note">Los repos autorizados se añaden en <span class="mono">config/repos.toml</span>. Fuera de ellos Skynet no lee ni escribe nada.</p>';

    html += '<div class="section-k">Modelo</div>';
    html += `<div class="card clickable ${s.modelo === 'auto' ? 'selected' : ''}" data-model="auto">
      <div class="card-row">${icon('route')}<div class="grow"><div class="card-title">Automático</div><div class="card-sub">El router elige según la tarea (privacidad, coste, razonamiento).</div></div></div></div>`;
    const motores = Object.fromEntries((s.motores || []).map((e) => [e.nombre, e]));
    for (const m of s.modelos || []) {
      const tags = [m.privado ? 'en tu PC' : 'en la nube', m.gratis ? 'gratis' : `${m.coste[0]} $ / ${m.coste[1]} $ por M tokens`];
      const e = motores[m.nombre];
      const sw = e ? `<button class="toggle" data-engine="${esc(m.nombre)}" role="switch" aria-checked="${e.encendido}"
        aria-label="${e.encendido ? 'Apagar' : 'Encender'} ${esc(m.nombre)}" ${e.ocupado ? 'disabled' : ''}
        title="${e.ocupado ? 'Un momento…' : e.encendido ? 'Encendido: clic para apagar' : 'Apagado: clic para encender (apaga el otro motor local)'}"></button>` : '';
      html += `<div class="card clickable ${s.modelo === m.nombre ? 'selected' : ''}" data-model="${esc(m.nombre)}">
        <div class="card-row">${icon(m.privado ? 'cpu' : 'cloud')}<div class="grow"><div class="card-title">${esc(m.nombre)} <span class="card-sub mono">${esc(m.litellm.split('/').slice(1).join('/'))}</span></div>
        <div class="card-sub">${esc(tags.join(' · '))}</div>
        ${e?.ocupado ? '<div class="card-sub" style="color:var(--warn)">Cambiando… cargar el modelo tarda hasta unos minutos.</div>'
          : m.disponible ? '' : e ? '<div class="card-sub" style="color:var(--warn)">Apagado. Enciéndelo con el interruptor.</div>'
          : `<div class="card-sub" style="color:var(--warn)">No disponible: ${esc(m.motivo)}. Si lo eliges, Skynet usará el local.</div>`}</div>${sw}</div></div>`;
    }
    html += `<div class="card" style="margin-top:14px"><div class="card-row">${icon('lock')}<div class="grow"><div class="card-title">Privacidad alta</div>
      <div class="card-sub">Fuerza el modelo local: nada sale de tu PC.</div></div>
      <button class="toggle" id="privToggle" role="switch" aria-checked="${s.privado}" aria-label="Privacidad alta"></button></div></div>`;
    if (s.reglas?.length) {
      html += '<div class="section-k">Cómo decide el router</div><div class="card">';
      s.reglas.forEach((r, i) => {
        const cond = Object.entries(r.si || {}).map(([k, v]) => `${k} = ${v}`).join(', ') || 'en cualquier otro caso';
        html += `<div class="card-sub" style="margin-top:${i ? 8 : 0}px">${i + 1}. Si <span class="mono">${esc(cond)}</span> → <b style="color:var(--fg)">${esc(r.usar)}</b>${r.motivo ? ` · ${esc(r.motivo)}` : ''}</div>`;
      });
      html += '</div>';
    }
    const notif = 'Notification' in window ? Notification.permission : 'unsupported';
    html += `<div class="section-k">Interfaz</div><div class="card"><div class="card-row">${icon('warn')}<div class="grow"><div class="card-title">Avisos de Windows</div>
      <div class="card-sub">${notif === 'granted' ? 'Activados: si Skynet necesita tu confirmación con la pestaña en segundo plano, te avisa.'
        : notif === 'denied' ? 'Bloqueados en el navegador. Actívalos desde el candado de la barra de direcciones.'
        : notif === 'unsupported' ? 'Este navegador no los admite.' : 'Te avisa cuando Skynet necesita tu confirmación y estás en otra ventana.'}</div></div>
      ${notif === 'default' ? '<button class="btn small" id="notifBtn">Activar</button>' : ''}</div></div>`;
    html += `<div class="field-k" style="margin-top:14px">Calidad visual</div>
      <label class="field" style="margin-top:0"><select class="select" id="quality">
        ${['auto', ...Object.keys(QUALITY)].map((q) => `<option value="${q}" ${q === quality ? 'selected' : ''}>${q === 'auto' ? 'Automática' : `${q[0].toUpperCase()}${q.slice(1)} · ${(QUALITY[q] ** 2).toLocaleString('es-ES')} partículas`}</option>`).join('')}
      </select></label>
      <p class="note">Ultra está pensada para GPUs potentes (tu RX 9070 XT va sobrada). Se aplica al recargar.</p>`;
    this.paint(html);
    for (const c of this.body.querySelectorAll('[data-repo]')) c.addEventListener('click', () => this.setRepo(c.dataset.repo || null));
    for (const c of this.body.querySelectorAll('[data-model]')) c.addEventListener('click', () => this.setModel(c.dataset.model));
    for (const b of this.body.querySelectorAll('[data-engine]')) b.addEventListener('click', async (ev) => {
      ev.stopPropagation();  // el interruptor no selecciona la tarjeta
      b.disabled = true;
      try { this.app.applySnap(await api.motor(b.dataset.engine, b.getAttribute('aria-checked') !== 'true')); }
      catch (e) { this.app.toast(e.message, 'bad'); b.disabled = false; }
    });
    $('#privToggle').addEventListener('click', () => this.app.setPrivate(!s.privado));
    $('#notifBtn')?.addEventListener('click', async () => { await Notification.requestPermission(); this.render(true); });
    $('#quality').addEventListener('change', (e) => {
      try { localStorage.setItem('skynet.calidad', e.target.value); } catch { /* sin almacenamiento */ }
      location.reload();
    });
  }

  // --- diagnóstico ---------------------------------------------------------
  renderDiag() {
    this.paint(`<p class="lead">Comprueba la configuración, la base de datos, git, LM Studio, los modelos en la nube y los servidores MCP de cada repo.</p>
      <div class="btn-row" style="margin-top:0"><button class="btn primary" id="dRun">${icon('pulse')} Comprobar ahora</button></div>
      <div class="checks" id="dOut"></div>`);
    $('#dRun').addEventListener('click', () => this.runDiag());
    this.runDiag();
  }

  async runDiag() {
    const out = $('#dOut');
    if (!out) return;
    out.innerHTML = '<div class="skeleton" style="margin-top:16px"></div><div class="skeleton"></div>';
    $('#dRun').disabled = true;
    try {
      const d = await api.doctor();
      this.paintDiag(d.checks || []);
    } catch (e) {
      out.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    } finally {
      const b = $('#dRun');
      if (b) b.disabled = false;
    }
  }

  paintDiag(checks) {
    const out = $('#dOut');
    if (!out) return;
    const bad = checks.filter((c) => c.estado === 'mal').length;
    out.innerHTML = `<div class="section-k">${bad ? `${bad} problema${bad > 1 ? 's' : ''}` : 'Todo en orden'}</div>` + checks.map((c) => `
      <div class="check"><span class="check-i ${c.estado}">${icon(c.estado === 'ok' ? 'check' : c.estado === 'mal' ? 'x' : 'dot')}</span>
      <div class="grow"><div>${esc(c.nombre)}${c.estado === 'off' ? ' <span class="pill plain">apagado</span>' : ''}</div><div class="check-d">${esc(c.detalle || '')}</div></div></div>`).join('');
  }

  // --- ayuda -----------------------------------------------------------------
  renderHelp() {
    const s = this.app.snap || {};
    const caps = [
      ['chat', 'Pídeselo con tus palabras', 'Escribe abajo lo que quieres, como a una persona. Con un repo elegido, Skynet lee, edita y prueba el código; sin repo, solo conversa.', 'Probar', () => this.app.fill(s.repo ? 'Explícame qué hace este repo y qué falta por hacer' : '¿Qué puedes hacer por mí?')],
      ['shield', 'Te pregunta antes de lo arriesgado', 'Leer y editar dentro del repo es automático. Ejecutar comandos fuera de la lista blanca, acciones privilegiadas o borrar siempre te piden permiso en un diálogo.', null, null],
      ['check', 'No se da la razón a sí mismo', 'Al terminar, un verificador objetivo (por ejemplo, los tests del repo) decide si la tarea queda hecha o fallida.', null, null],
      ['resume', 'Continúa donde lo dejó', 'Si cierras Skynet, lo detienes o falla, la tarea queda pausada. Pulsa «Continuar» (o escribe «continúa») y la retoma.', 'Ver tareas', () => this.open('tareas')],
      ['orbit', 'Trabaja solo durante horas', 'Las tareas largas avanzan en pasos verificados con commits y PROGRESO.md, con el modelo local. Cada una aparece como una luz en órbita alrededor de la nebulosa.', 'Lanzar una', () => this.open('largo')],
      ['route', 'Elige el modelo por ti', 'Local (Qwen en LM Studio, privado y gratis), Gemini Flash (gratis) o Anthropic. El router decide según privacidad y coste, o lo eliges tú.', 'Modelos', () => this.open('ajustes')],
      ['log', 'Todo queda registrado', 'Herramientas usadas, permisos, modelo, tokens y coste de cada tarea.', 'Ver registro', () => this.open('registro')],
    ];
    let html = '<p class="lead">La nebulosa del centro es Skynet: su color te dice qué está haciendo.</p>';
    html += `<div class="card"><div class="shortcuts">
      <span class="pill plain" style="color:#86a8ff">blanco azulado</span><span>en espera</span>
      <span class="pill plain" style="color:#3a9dff">azul</span><span>pensando</span>
      <span class="pill plain" style="color:#9b78ff">violeta</span><span>usando herramientas</span>
      <span class="pill plain" style="color:#2fe3bd">turquesa</span><span>verificando</span>
      <span class="pill plain" style="color:#ffa63d">ámbar</span><span>te necesita</span>
      <span class="pill plain" style="color:#5bffaa">verde</span><span>hecho</span>
      <span class="pill plain" style="color:#ff4558">rojo</span><span>algo falló</span>
    </div></div>`;
    caps.forEach(([ico, title, text, btn], i) => {
      html += `<div class="card cap" style="margin-top:10px"><span class="cap-i">${icon(ico)}</span><div><div class="card-title">${esc(title)}</div><div class="card-text">${esc(text)}</div>${btn ? `<button class="btn small" data-cap="${i}">${esc(btn)}</button>` : ''}</div></div>`;
    });
    html += `<div class="section-k">Atajos</div><div class="card"><div class="shortcuts">
      <span><kbd>Ctrl</kbd> <kbd>K</kbd></span><span>todas las acciones, buscando por nombre</span>
      <span><kbd>/</kbd></span><span>escribir a Skynet</span>
      <span><kbd>Esc</kbd></span><span>cerrar panel · detener lo que hace</span>
      <span><kbd>S</kbd> <kbd>N</kbd> <kbd>T</kbd></span><span>sí, no o sí a toda la tarea en un permiso</span>
    </div></div>
    <div class="section-k">Comandos de texto (opcionales)</div>
    <div class="card"><pre class="mono" style="margin:0;white-space:pre-wrap;color:var(--fg3)">${esc(s.ayuda || '')}</pre></div>`;
    this.paint(html);
    for (const b of this.body.querySelectorAll('[data-cap]')) b.addEventListener('click', () => caps[+b.dataset.cap][4]());
  }
}
