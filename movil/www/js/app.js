// Controlador de la interfaz: conversación, estados, diálogos, paleta y avisos.
// Los paneles (tareas, registro, ajustes...) viven en panels.js.
import { api, connect } from './api.js';
import { md, esc } from './md.js';
import { icon, paintIcons } from './icons.js';
import { STATES } from './scene/engine.js';
import { Panels } from './panels.js';

const $ = (s, r = document) => r.querySelector(s);

// Herramientas MCP en lenguaje humano.
const TOOL_WORDS = {
  'workspace.read_file': ['Leyendo', 'file'],
  'workspace.list_dir': ['Explorando', 'folder'],
  'workspace.search': ['Buscando', 'search'],
  'workspace.git_status': ['Revisando git', 'git'],
  'workspace.git_diff': ['Revisando cambios', 'git'],
  'workspace.git_log': ['Revisando historial', 'git'],
  'workspace.write_file': ['Escribiendo', 'edit'],
  'workspace.edit_file': ['Editando', 'edit'],
  'workspace.run_command': ['Ejecutando', 'terminal'],
  'workspace.delete_file': ['Borrando', 'trash'],
  'coding_agent.start_task': ['Lanzando agente-godot', 'play'],
  'coding_agent.stop_task': ['Parando agente-godot', 'pause'],
  'coding_agent.status': ['Consultando agente-godot', 'eye'],
  'coding_agent.history': ['Consultando historial de agente-godot', 'eye'],
};

export function toolWords(key, args = '') {
  const [verb, ico] = TOOL_WORDS[key] || [key, 'cpu'];
  const m = String(args).match(/(?:path|command|pattern|query|ruta)='((?:[^'\\]|\\.)*)'/);
  return { verb, ico, target: m ? m[1] : '' };
}

const LEVEL_TEXT = {
  EXECUTE: ['Quiere ejecutar un comando', 'El comando no está en la lista blanca.'],
  PRIVILEGED: ['Quiere hacer una acción privilegiada', ''],
  DESTRUCTIVE: ['Quiere hacer algo que no se puede deshacer', ''],
  WRITE: ['Quiere escribir un archivo', ''],
  READ: ['Quiere leer', ''],
};

const WHERE = { auto: 'Automático', local: 'Local', nube: 'Nube' };
const EFFORT = { auto: 'Auto', low: 'Rápido', medium: 'Equilibrado', high: 'Pensar más' };

const FOOT_RE = /^(.+?) · (\d+)\+(\d+) tokens · ([\d.,]+) € · (\d+) herramientas · tarea (\d+): (\w+)(?: · verificador (OK|FALLA))?$/;

export class App {
  constructor(engine) {
    this.engine = engine;
    this.snap = null;
    this.connected = false;
    this.busy = false;
    this.phase = 'pensando';
    this.question = null;
    this.turn = null;
    this.lastAnswer = null;
    this.replaying = false;
    this.convo = $('#convoInner');
    this.scroll = $('#convoScroll');
    this.input = $('#input');
    this.panels = new Panels(this);
    paintIcons();
    this.bind();
    this.setState();
    this.disconnect = connect({
      onHello: (s) => this.onHello(s),
      onMessage: (m) => this.onMessage(m),
      onStatus: (ok) => this.onConnection(ok),
    });
    setInterval(() => this.poll(), 5000);
  }

  // --- entrada ---------------------------------------------------------
  bind() {
    const form = $('#prompt');
    form.addEventListener('submit', (e) => { e.preventDefault(); this.send(); });
    this.input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); this.send(); }
    });
    this.input.addEventListener('input', () => {
      this.autosize();
      // La nebulosa "escucha": cada pulsación la estremece un poco.
      const now = performance.now();
      if (this.engine && now - (this.lastKeyPulse || 0) > 140) { this.lastKeyPulse = now; this.engine.pulse(0.12); }
    });
    $('#stopBtn').addEventListener('click', () => this.stop());
    $('#tabRepo').addEventListener('click', (e) => this.menuRepo(e.currentTarget));
    $('#tabWhere').addEventListener('click', (e) => this.menuWhere(e.currentTarget));
    $('#btnModel').addEventListener('click', (e) => this.menuModel(e.currentTarget));
    $('#btnEffort').addEventListener('click', (e) => this.menuEffort(e.currentTarget));
    $('#btnPerm').addEventListener('click', (e) => this.menuPerm(e.currentTarget));
    document.addEventListener('pointerdown', (e) => { if (!$('#menu').hidden && !e.target.closest('#menu, .tab, .mini')) this.closeMenu(); });
    $('#chipProp').addEventListener('click', () => this.send('/propuestas'));
    for (const b of document.querySelectorAll('[data-panel]')) {
      b.addEventListener('click', () => this.panels.toggle(b.dataset.panel));
    }
    $('#panelClose').addEventListener('click', () => this.panels.close());
    window.addEventListener('keydown', (e) => this.onKey(e));
    $('#palette').addEventListener('click', (e) => { if (e.target.id === 'palette') this.closePalette(); });
    $('#paletteInput').addEventListener('input', () => this.renderPalette());
    $('#paletteInput').addEventListener('keydown', (e) => this.paletteKey(e));
    window.addEventListener('resize', () => this.updateFocus());
    this.autosize();
  }

  autosize() {
    const el = this.input;
    el.style.height = 'auto';
    el.style.height = Math.min(180, el.scrollHeight) + 'px';
    $('#sendBtn').disabled = !el.value.trim();
  }

  onKey(e) {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '');
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); this.openPalette(); return; }
    if (!$('#menu').hidden && e.key === 'Escape') { e.preventDefault(); this.closeMenu(); return; }
    if (this.localConfirm) {
      const k = e.key.toLowerCase();
      if (k === 'escape' || k === 'n') { e.preventDefault(); this.localConfirm(false); }
      return;
    }
    if (e.key === 'Escape') {
      if (!$('#palette').hidden) return this.closePalette();
      if (this.question) return;
      if (this.panels.current) return this.panels.close();
      if (this.busy && !typing) return this.stop();
    }
    if (this.question && !typing && !e.ctrlKey && !e.metaKey && !e.altKey) {
      const k = e.key.toLowerCase();
      if (k === 's' || k === 'n' || (k === 't' && this.question.todas)) { e.preventDefault(); this.answer(k); }
      return;
    }
    if (!typing && e.key === '/' && $('#palette').hidden) { e.preventDefault(); this.input.focus(); }
  }

  async send(text) {
    const value = (text ?? this.input.value).trim();
    if (!value) return;
    if (this.busy) { this.toast(`Skynet está trabajando en «${this.snap?.etiqueta || 'algo'}». Espera o pulsa Detener.`); return; }
    if (text === undefined) { this.input.value = ''; this.autosize(); }
    try {
      await api.mensaje(value);
    } catch (e) {
      this.toast(e.message, 'bad');
      if (text === undefined) { this.input.value = value; this.autosize(); }
    }
  }

  fill(text) {
    this.input.value = text;
    this.autosize();
    this.input.focus();
    this.input.setSelectionRange(text.length, text.length);
  }

  async stop() {
    if (!this.busy) return;
    this.toast('Deteniendo…');
    try { await api.cancelar(); } catch (e) { this.toast(e.message, 'bad'); }
  }

  // Ajustes que el servidor puede pedir confirmar (activar un modelo en la nube, modo fuerte en la nube):
  // si responde 409 con «confirmar», se enseña el aviso y, si aceptas, se repite con confirmar: true.
  async ajustes(cambios) {
    try {
      this.applySnap(await api.ajustes(cambios));
      return true;
    } catch (e) {
      const c = e.data && e.data.confirmar;
      if (!c) { this.toast(e.message, 'bad'); return false; }
      if (!(await this.confirmDialog(c))) { this.toast('Sin cambios.'); this.applySnap(this.snap); return false; }
      try { this.applySnap(await api.ajustes({ ...cambios, confirmar: true })); return true; }
      catch (e2) { this.toast(e2.message, 'bad'); return false; }
    }
  }

  confirmDialog(c) {
    return new Promise((resolve) => {
      if (this.question) { resolve(false); return; }  // hay una pregunta de una tarea abierta: esa primero
      const card = $('#askCard');
      const done = (v) => { $('#ask').hidden = true; this.localConfirm = null; this.setState(); resolve(v); };
      card.innerHTML = `
        <div class="ask-level">${c.tipo === 'aviso' ? 'Aviso' : 'Modelo en la nube'}</div>
        <h3 class="ask-title" id="askTitle">${esc(c.titulo)}</h3>
        <div class="ask-warn">${esc(c.texto)}</div>
        <div class="ask-actions">
          <button class="btn" data-c="n">Cancelar <kbd>N</kbd></button>
          <button class="btn ${c.tipo === 'aviso' ? 'danger' : 'primary'}" data-c="s">${esc(c.boton || 'Confirmar')}</button>
        </div>`;
      this.localConfirm = done;
      for (const b of card.querySelectorAll('[data-c]')) b.addEventListener('click', () => done(b.dataset.c === 's'));
      $('#ask').hidden = false;
      setTimeout(() => card.querySelector('[data-c="n"]')?.focus(), 50);
    });
  }

  // --- compositor: pestañas (repo, dónde piensa) y modelo/razonamiento/permisos debajo --------
  where(s) {
    if (s.modelo === 'auto') return 'auto';
    const m = (s.modelos || []).find((x) => x.nombre === s.modelo);
    return m && !m.privado ? 'nube' : 'local';
  }

  renderComposer(s) {
    const chev = icon('chev').replace('<svg', '<svg class="chev"');
    const tr = $('#tabRepo');
    tr.innerHTML = `${icon('repo')}<span class="tab-v">${esc(s.repo || 'Sin repo')}</span>${chev}`;
    tr.classList.toggle('off', !s.repo);
    const w = this.where(s);
    const tw = $('#tabWhere');
    tw.innerHTML = `${icon(w === 'nube' ? 'cloud' : w === 'local' ? 'cpu' : 'route')}<span class="tab-v">${WHERE[w]}</span>${chev}`;
    tw.dataset.where = w;
    const model = s.modelo === 'auto' ? `Auto · ${s.modelo_efectivo || 'local'}` : s.modelo;
    $('#btnModel').innerHTML = `<span>${esc(model)}</span>${chev}`;
    $('#btnEffort').innerHTML = `<span>${EFFORT[s.razonamiento] || 'Auto'}</span>${chev}`;
    const mode = (s.modos || []).find((o) => o.clave === s.modo_actual);
    const bp = $('#btnPerm');
    const libre = s.modo_actual === 'total' && s.sin_preguntar_actual;
    bp.innerHTML = `${icon('shield')}<span>${esc(mode ? mode.nombre : 'Solo repo')}${libre ? ' · sin preguntar' : ''}</span>${chev}`;
    bp.dataset.level = libre ? 'libre' : (s.modo_actual || 'repo');
  }

  openMenu(anchor, sections, pick) {
    const menu = $('#menu');
    if (!menu.hidden && this.menuAnchor === anchor) { this.closeMenu(); return; }
    this.closeMenu();
    let html = '';
    sections.forEach((sec, i) => {
      if (i && sec.sep !== false) html += '<div class="menu-sep"></div>';
      if (sec.title) html += `<div class="menu-k">${esc(sec.title)}</div>`;
      for (const it of sec.items) {
        html += `<button type="button" class="menu-i ${it.on ? 'on' : ''}" data-v="${esc(it.value)}">${it.ico ? icon(it.ico) : ''}
          <span class="menu-t">${esc(it.label)}${it.sub ? `<span class="menu-s">${esc(it.sub)}</span>` : ''}${it.toggle ? `<span class="menu-tg" role="checkbox" tabindex="0"
            aria-checked="${it.toggle.on}" data-v="${esc(it.toggle.value)}" title="${esc(it.toggle.title || '')}"><span class="box">${icon('check')}</span>${esc(it.toggle.label)}</span>` : ''}</span>${icon('check').replace('<svg', '<svg class="menu-ok"')}</button>`;
      }
    });
    menu.innerHTML = html;
    menu.hidden = false;
    const r = anchor.getBoundingClientRect();
    const mw = menu.offsetWidth;
    menu.style.left = `${Math.max(12, Math.min(r.left, window.innerWidth - mw - 12))}px`;
    menu.style.bottom = `${window.innerHeight - r.top + 6}px`;
    menu.style.top = 'auto';
    this.menuAnchor = anchor;
    anchor.setAttribute('aria-expanded', 'true');
    for (const b of menu.querySelectorAll('.menu-i')) b.addEventListener('click', () => { this.closeMenu(); pick(b.dataset.v); });
    for (const t of menu.querySelectorAll('.menu-tg')) {
      const go = (e) => { e.preventDefault(); e.stopPropagation(); this.closeMenu(); pick(t.dataset.v); };
      t.addEventListener('click', go);
      t.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') go(e); });
    }
    menu.querySelector('.menu-i.on, .menu-i')?.focus();
  }

  closeMenu() {
    $('#menu').hidden = true;
    this.menuAnchor?.setAttribute('aria-expanded', 'false');
    this.menuAnchor = null;
  }

  menuRepo(anchor) {
    const s = this.snap || {};
    this.openMenu(anchor, [
      { items: [{ value: '', label: 'Sin repo', sub: 'Solo conversación', ico: 'chat', on: !s.repo },
        ...(s.repos || []).map((r) => ({ value: r.nombre, label: r.nombre, sub: r.ruta, ico: 'repo', on: s.repo === r.nombre }))] },
      { items: [{ value: '__nuevo__', label: 'Añadir repo…', ico: 'folder' }] },
    ], (v) => (v === '__nuevo__' ? this.panels.open('ajustes') : this.ajustes({ repo: v || 'ninguno' })));
  }

  menuWhere(anchor) {
    const s = this.snap || {};
    const w = this.where(s);
    this.openMenu(anchor, [{ items: [
      { value: 'auto', label: 'Automático', sub: 'Skynet elige según la tarea', ico: 'route', on: w === 'auto' },
      { value: 'local', label: 'Local', sub: 'En tu PC: nada sale de él', ico: 'cpu', on: w === 'local' },
      { value: 'nube', label: 'Nube', sub: 'Gemini, OmniRoute, Anthropic… (pide confirmación)', ico: 'cloud', on: w === 'nube' },
    ] }], (v) => {
      const ms = s.modelos || [];
      if (v === 'auto') return this.ajustes({ modelo: 'auto' });
      if (v === 'local') return this.ajustes({ modelo: (ms.find((m) => m.privado) || { nombre: 'local' }).nombre });
      const cloud = ms.find((m) => !m.privado && m.activado && m.disponible) || ms.find((m) => !m.privado && m.activado) || ms.find((m) => !m.privado);
      if (cloud) this.ajustes({ modelo: cloud.nombre });
    });
  }

  menuModel(anchor) {
    const s = this.snap || {};
    const ms = s.modelos || [];
    const item = (m) => ({ value: m.nombre, label: m.nombre, sub: m.litellm.split('/').slice(1).join('/') + (m.privado || m.activado ? '' : ' · pide confirmación'),
      ico: m.privado ? 'cpu' : 'cloud', on: s.modelo === m.nombre });
    this.openMenu(anchor, [
      { items: [{ value: 'auto', label: 'Automático', sub: 'Skynet elige', ico: 'route', on: s.modelo === 'auto' }] },
      { title: 'Local', items: ms.filter((m) => m.privado).map(item) },
      { title: 'Nube', items: ms.filter((m) => !m.privado).map(item) },
    ], (v) => this.ajustes({ modelo: v }));
  }

  menuEffort(anchor) {
    const s = this.snap || {};
    this.openMenu(anchor, [{ items: Object.entries(EFFORT).map(([v, label]) => ({ value: v, label, on: (s.razonamiento || 'auto') === v,
      sub: { auto: 'Lo normal de cada modelo', low: 'Responde antes', medium: '', high: 'Tarda más en lo difícil' }[v] })) }],
    (v) => this.ajustes({ razonamiento: v }));
  }

  menuPerm(anchor) {
    const s = this.snap || {};
    const modelo = s.modelo_efectivo;
    const libre = s.modo_actual === 'total' && !!s.sin_preguntar_actual;
    this.openMenu(anchor, [
      { title: `Permisos de ${modelo || 'local'}`, items: (s.modos || []).map((o) => ({ value: o.clave, label: o.nombre, sub: o.descripcion, on: o.clave === s.modo_actual,
        toggle: o.clave === 'total' ? { value: libre ? '__preguntar__' : '__libre__', on: libre, label: 'Sin preguntar', title: s.sin_preguntar_texto } : null })) },
    ], (v) => {
      if (v === '__libre__') return this.ajustes({ permiso: { modelo, modo: 'total' }, sin_preguntar: { modelo, activar: true } });
      if (v === '__preguntar__') return this.ajustes({ sin_preguntar: { modelo, activar: false } });
      return this.ajustes({ permiso: { modelo, modo: v } });
    });
  }

  async resumeTask(id) {
    try { await api.accion(id, 'continuar'); } catch (e) { this.toast(e.message, 'bad'); }
  }

  // --- servidor -> interfaz -------------------------------------------
  onConnection(ok) {
    if (ok === this.connected) return;
    this.connected = ok;
    if (!ok) this.toast('Se perdió la conexión con Skynet. Reintentando…', 'bad');
    this.setState();
  }

  onHello(snap) {
    // Cada conexión (o reconexión) reconstruye la conversación desde el servidor.
    this.convo.innerHTML = '';
    this.turn = null;
    this.lastAnswer = null;
    this.replaying = true;
    clearTimeout(this.replayEnd);
    this.replayEnd = setTimeout(() => { this.replaying = false; this.scrollDown(true); this.renderSuggestions(); }, 400);
    this.applySnap(snap);
    const q = (snap.preguntas || [])[0];
    if (q) this.openQuestion(q); else this.closeQuestion();
  }

  applySnap(s) {
    if (!s) return;
    this.snap = s;
    this.setBusy(!!s.ocupado);
    this.renderComposer(s);
    $('#chipProp').hidden = !s.propuestas;
    $('#chipPropV').textContent = String(s.propuestas || 0);
    this.engine?.setSatellites((s.largas_vivas || []).length);
    const badge = document.querySelector('.rail-btn[data-panel="tareas"]');
    badge.querySelector('.badge')?.remove();
    if ((s.largas_vivas || []).length || s.pendiente) badge.insertAdjacentHTML('beforeend', '<span class="badge"></span>');
    this.renderSuggestions();
    this.setState();
    this.panels.onSnap(s);
  }

  onMessage(m) {
    const live = !m.replay;
    switch (m.tipo) {
      case 'usuario': this.addUser(m.texto); break;
      case 'respuesta': this.addAnswer(m.texto, live); break;
      case 'info': this.addInfo(m.texto, live); break;
      case 'evento': this.addEvent(m.kind, m.datos || {}, live); break;
      case 'tabla': this.addPre(m.texto); break;
      case 'error': this.addError(m.texto, live); break;
      case 'diagnostico': this.addDiag(m.checks || []); this.panels.onDiag(m.checks || []); break;
      case 'pregunta': this.openQuestion(m); break;
      case 'pregunta_cerrada': if (this.question && this.question.id === m.id) this.closeQuestion(); break;
      case 'ocupado': this.setBusy(m.ocupado, m.etiqueta); break;
      case 'estado': this.applySnap(m); break;
      case 'tareas': this.panels.refresh(); this.poll(); break;
      default: break;
    }
  }

  setBusy(on, label) {
    const was = this.busy;
    this.busy = !!on;
    document.body.classList.toggle('busy', this.busy);
    if (this.snap && label !== undefined) this.snap.etiqueta = label;
    if (this.busy && !was) this.phase = 'pensando';
    if (!this.busy && was) this.finishTurn();
    this.renderSuggestions();
    this.setState();
  }

  // Estado visual = conexión > pregunta abierta > fase del trabajo > reposo.
  setState(detail) {
    let s = 'reposo';
    if (!this.connected) s = 'desconectado';
    else if (this.question) s = 'esperando';
    else if (this.busy) s = this.phase;
    this.engine?.setState(s);
    this.paintState(detail);
  }

  paintState(detail) {
    const name = this.engine ? this.engine.activeState : (this.question ? 'esperando' : this.busy ? this.phase : 'reposo');
    const S = STATES[name] || STATES.reposo;
    document.documentElement.style.setProperty('--accent', S.accent);
    document.documentElement.style.setProperty('--accent-soft', S.accent + '29');
    $('#statusLabel').textContent = S.label;
    let d = detail ?? this.statusDetail ?? '';
    if (!this.busy && !this.question) d = '';
    const longs = (this.snap?.largas_vivas || []).length;
    if (longs && name !== 'desconectado') d = [d, `${longs} tarea${longs > 1 ? 's' : ''} larga${longs > 1 ? 's' : ''} en marcha`].filter(Boolean).join(' · ');
    $('#statusDetail').textContent = d ? '· ' + d : '';
    $('#status').classList.toggle('busy', this.busy || !!this.question);
  }

  flash(name, secs) {
    if (!this.engine) return;
    this.engine.flashState(name, secs);
    this.paintState();
    clearTimeout(this.flashTimer);
    this.flashTimer = setTimeout(() => this.paintState(), secs * 1000 + 50);
  }

  // --- conversación ---------------------------------------------------
  showConvo() {
    if (!document.body.classList.contains('has-convo')) {
      document.body.classList.add('has-convo');
      this.updateFocus();
    }
    if ($('#suggest').children.length) this.renderSuggestions();
  }

  // Centra la nebulosa en el hueco que dejan panel y conversación.
  updateFocus() {
    if (!this.engine) return;
    const w = window.innerWidth;
    if (w < 860) return this.engine.setFocusShift(0);
    const css = getComputedStyle(document.documentElement);
    const convoW = document.body.classList.contains('has-convo') && !document.body.classList.contains('convo-hidden')
      ? Math.min(parseFloat(css.getPropertyValue('--convo-w')) || 470, w * 0.34) + 26 : 0;
    const panelW = this.panels.current ? (parseFloat(css.getPropertyValue('--panel-w')) || 410) + 84 : 70;
    this.engine.setFocusShift((panelW - convoW) / 2);
  }

  append(el) {
    const stick = this.scroll.scrollHeight - this.scroll.scrollTop - this.scroll.clientHeight < 120;
    this.convo.appendChild(el);
    if (this.replaying) el.style.animation = 'none';
    this.showConvo();
    if (stick || this.replaying) this.scrollDown();
    return el;
  }

  scrollDown(instant) {
    requestAnimationFrame(() => this.scroll.scrollTo({ top: this.scroll.scrollHeight, behavior: instant || this.replaying ? 'auto' : 'smooth' }));
  }

  node(html, cls) {
    const d = document.createElement('div');
    d.className = cls;
    d.innerHTML = html;
    return d;
  }

  addUser(text) {
    this.finishTurn();
    this.append(this.node(`<div class="msg-k">Tú</div><div class="bubble">${esc(text)}</div>`, 'msg msg-user'));
    this.newTurn();
  }

  newTurn() {
    const act = this.node(
      `<div class="activity-head">${icon('chev', 'chev')}<span class="act-title">Actividad</span></div><div class="act-lines"></div>`,
      'msg activity');
    act.querySelector('.activity-head').addEventListener('click', () => act.classList.toggle('collapsed'));
    act.hidden = true;
    this.append(act);
    this.turn = { act, lines: act.querySelector('.act-lines'), count: 0, running: null, thinking: null };
  }

  ensureTurn() {
    if (!this.turn) this.newTurn();
    return this.turn;
  }

  actLine(ico, html, cls = '') {
    const t = this.ensureTurn();
    t.act.hidden = false;
    if (t.thinking) { t.thinking.remove(); t.thinking = null; }
    const l = this.node(`<span class="act-i">${ico === 'spin' ? '<span class="spinner"></span>' : icon(ico)}</span><div class="grow">${html}</div>`, 'act ' + cls);
    if (this.replaying) l.style.animation = 'none';
    t.lines.appendChild(l);
    t.count++;
    t.act.querySelector('.act-title').textContent = `Actividad · ${t.count}`;
    if (!this.replaying) this.scrollDown();
    return l;
  }

  addEvent(kind, d, live) {
    const t = this.ensureTurn();
    if (kind === 'route') {
      const model = String(d.model || '').split('/').pop();
      this.actLine('route', `Modelo <b>${esc(model)}</b> <span class="act-args">${esc(d.reason || '')}</span>`);
      if (live) { this.phase = 'pensando'; this.setState('eligiendo modelo'); }
    } else if (kind === 'thinking') {
      if (!live) return;
      if (!t.thinking) {
        t.act.hidden = false;
        t.thinking = this.node(`<span class="act-i"><span class="spinner"></span></span><div class="grow act-say">Pensando${d.turn > 1 ? ` · turno ${d.turn}` : ''}…</div>`, 'act running');
        t.lines.appendChild(t.thinking);
      }
      this.phase = 'pensando';
      this.setState(d.turn > 1 ? `turno ${d.turn}` : '');
    } else if (kind === 'say') {
      this.actLine('sparkle', `<span class="act-say">${esc(String(d.text || '').slice(0, 400))}</span>`);
    } else if (kind === 'tool') {
      const w = toolWords(d.key, d.args);
      const line = this.actLine(live ? 'spin' : w.ico,
        `${esc(w.verb)} ${w.target ? `<b>${esc(w.target)}</b>` : ''}<div class="act-args">${esc(d.key)}(${esc(String(d.args || '').slice(0, 240))})</div>`,
        live ? 'running' : '');
      line.dataset.ico = w.ico;
      t.running = line;
      if (live) {
        this.phase = 'herramienta';
        this.setState(`${w.verb.toLowerCase()} ${w.target}`.trim());
        this.engine?.pulse(0.45);
      }
    } else if (kind === 'tool_result') {
      const line = t.running;
      if (line) {
        line.classList.remove('running');
        line.classList.add(d.ok ? 'ok' : 'bad');
        line.querySelector('.act-i').innerHTML = icon(d.ok ? (line.dataset.ico || 'check') : 'x');
        if (!d.ok && d.first_line) line.querySelector('.grow').insertAdjacentHTML('beforeend', `<div class="act-args">${esc(d.first_line)}</div>`);
        t.running = null;
      }
    } else if (kind === 'denied') {
      if (t.running) { t.running.remove(); t.running = null; t.count--; }
      this.actLine('x', `Denegado <b>${esc(d.key)}</b><div class="act-args">${esc(d.reason || '')}</div>`, 'bad');
      if (live) this.flash('error', 1.2);
    } else if (kind === 'verifying') {
      t.verify = this.actLine(live ? 'spin' : 'shield', `Verificando <span class="act-args">${esc(d.command || '')}</span>`, live ? 'running' : '');
      if (live) { this.phase = 'verificando'; this.setState(d.command || ''); }
    }
  }

  addAnswer(text, live) {
    const t = this.ensureTurn();
    if (t.thinking) { t.thinking.remove(); t.thinking = null; }
    if (t.count > 0) t.act.classList.add('collapsed');
    const el = this.node(`<div class="msg-k"><span class="k-dot"></span>Skynet</div><div class="bubble"><div class="md">${md(text)}</div></div>`, 'msg msg-skynet');
    this.append(el);
    this.lastAnswer = el;
    if (live) this.engine?.pulse(0.8);
  }

  addInfo(text, live) {
    const foot = String(text).match(FOOT_RE);
    if (foot && this.lastAnswer && !this.lastAnswer.querySelector('.meta')) {
      const [, model, tin, tout, cost, tools, id, status, ver] = foot;
      const bits = [
        esc(model), `${(+tin).toLocaleString('es-ES')} + ${(+tout).toLocaleString('es-ES')} tokens`, `${esc(cost)} €`,
        `${tools} herramienta${tools === '1' ? '' : 's'}`, `tarea ${id}: <span class="${status === 'hecha' ? 'ok' : status === 'fallida' ? 'bad' : ''}">${esc(status)}</span>`,
      ];
      if (ver) bits.push(`verificador <span class="${ver === 'OK' ? 'ok' : 'bad'}">${ver}</span>`);
      this.lastAnswer.querySelector('.bubble').insertAdjacentHTML('beforeend', `<div class="meta">${bits.map((b) => `<span>${b}</span>`).join('')}</div>`);
      const v = this.turn?.verify;
      if (v && ver) {
        v.classList.remove('running');
        v.classList.add(ver === 'OK' ? 'ok' : 'bad');
        v.querySelector('.act-i').innerHTML = icon(ver === 'OK' ? 'check' : 'x');
      }
      if (live) this.flash(status === 'hecha' ? 'exito' : status === 'fallida' ? 'error' : 'reposo', status === 'fallida' ? 2.2 : 2.4);
      return;
    }
    if (/^El verificador falla:/.test(text)) {
      // La salida de los tests, recogida en una tarjeta con la acción obvia: que lo arregle.
      const tail = String(text).replace(/^El verificador falla:\n?/, '').replace(/\n?Di «continúa».*$/s, '');
      const el = this.node(`<div class="fail"><div class="fail-k">${icon('x')}El verificador no pasa</div><pre>${esc(tail.trim())}</pre>
        <div class="btn-row" style="margin-top:10px"><button class="btn small">${icon('resume')} Pídele que lo arregle</button></div></div>`, 'msg');
      el.querySelector('button').addEventListener('click', () => this.send('continúa'));
      this.append(el);
      return;
    }
    if (/Di «continúa» para seguir/.test(text)) {
      const el = this.node(`${esc(text)}<div><button class="btn small">${icon('resume')} Continuar</button></div>`, 'msg msg-info warn');
      el.querySelector('button').addEventListener('click', () => this.send('continúa'));
      this.append(el);
      return;
    }
    const warn = /falla|no está|desconocido|no encuentro|no hay|cancelado|detenido/i.test(text);
    this.append(this.node(esc(text), 'msg msg-info' + (warn ? ' warn' : '')));
    if (live && /Detenido/.test(text)) this.flash('reposo', 1.2);
  }

  addPre(text) {
    this.append(this.node(`<div class="bubble"><pre>${esc(text)}</pre></div>`, 'msg msg-skynet msg-pre'));
  }

  addError(text, live) {
    this.append(this.node(`<div class="msg-k">Error</div><div class="bubble">${esc(text)}</div>`, 'msg msg-error'));
    if (live) this.flash('error', 2.5);
  }

  addDiag(checks) {
    const rows = checks.map((c) => `<div class="act ${c.estado === 'ok' ? 'ok' : c.estado === 'mal' ? 'bad' : ''}"><span class="act-i">${icon(c.estado === 'ok' ? 'check' : c.estado === 'mal' ? 'x' : 'dot')}</span><div class="grow">${esc(c.nombre)}<div class="act-args">${esc(c.detalle || '')}</div></div></div>`).join('');
    this.append(this.node(`<div class="msg-k"><span class="k-dot"></span>Diagnóstico</div><div class="bubble"><div class="act-lines">${rows}</div></div>`, 'msg msg-skynet'));
  }

  finishTurn() {
    const t = this.turn;
    if (!t) return;
    if (t.thinking) { t.thinking.remove(); t.thinking = null; }
    if (t.running) {
      t.running.classList.remove('running');
      t.running.querySelector('.act-i').innerHTML = icon(t.running.dataset.ico || 'dot');
      t.running = null;
    }
    if (t.verify && t.verify.classList.contains('running')) {
      t.verify.classList.remove('running');
      t.verify.querySelector('.act-i').innerHTML = icon('shield');
    }
    if (!t.count) t.act.remove();
  }

  // --- preguntas (permisos y confirmaciones) ----------------------------
  openQuestion(q) {
    if (this.localConfirm) this.localConfirm(false);  // la pregunta de la tarea tiene prioridad
    this.question = q;
    const card = $('#askCard');
    if (q.clase === 'permiso') {
      const [title, extra] = LEVEL_TEXT[q.nivel] || ['Pide permiso', ''];
      const w = toolWords(q.herramienta, q.args);
      card.innerHTML = `
        <div class="ask-level">${esc(q.nivel)} · tarea ${esc(q.tarea)}</div>
        <h3 class="ask-title" id="askTitle">${esc(title)}</h3>
        <div class="card-sub">${esc(w.verb)} ${w.target ? `<b>${esc(w.target)}</b>` : ''}</div>
        <div class="ask-tool">${esc(q.herramienta)}(${esc(q.args)})</div>
        <div class="ask-why">Motivo: ${esc(q.motivo || extra)}</div>
        <div class="ask-actions">
          <button class="btn danger" data-a="n">Denegar <kbd>N</kbd></button>
          ${q.todas ? '<button class="btn" data-a="t">Permitir en toda la tarea <kbd>T</kbd></button>' : ''}
          <button class="btn primary" data-a="s">Permitir <kbd>S</kbd></button>
        </div>`;
    } else {
      const lines = String(q.texto || '').split('\n');
      const ask = lines.pop();
      card.innerHTML = `
        <div class="ask-level">Confirmación</div>
        <h3 class="ask-title" id="askTitle">${esc(ask.replace(/\s*\[s\/n\]\s*$/i, '') || '¿Seguro?')}</h3>
        <div class="ask-text">${esc(lines.join('\n'))}</div>
        <div class="ask-actions">
          <button class="btn" data-a="n">Cancelar <kbd>N</kbd></button>
          <button class="btn primary" data-a="s">Sí, adelante <kbd>S</kbd></button>
        </div>`;
    }
    for (const b of card.querySelectorAll('[data-a]')) b.addEventListener('click', () => this.answer(b.dataset.a));
    $('#ask').hidden = false;
    setTimeout(() => card.querySelector('.btn.primary')?.focus(), 50);
    this.setState('te necesita');
    if (document.hidden && 'Notification' in window && Notification.permission === 'granted') {
      new Notification('Skynet necesita tu confirmación', { body: q.herramienta || q.texto || '' });
    }
  }

  closeQuestion() {
    this.question = null;
    $('#ask').hidden = true;
    this.setState();
  }

  async answer(value) {
    const q = this.question;
    if (!q) return;
    this.closeQuestion();
    try { await api.responder(q.id, value); } catch (e) { this.toast(e.message, 'bad'); }
  }

  // --- sugerencias ------------------------------------------------------
  renderSuggestions() {
    const s = this.snap;
    const box = $('#suggest');
    if (!s) { box.innerHTML = ''; this.sgKey = ''; return; }
    const items = [];
    const fresh = this.convo.children.length === 0;  // solo al principio, antes de la primera conversación
    if (!this.busy) {
      if (s.pendiente && !(s.pendiente.larga && s.pendiente.vivo)) {
        items.push({ ico: 'resume', text: `Continuar «${s.pendiente.title}»`, cls: 'accent', run: () => this.resumeTask(s.pendiente.id) });
      }
      if (!fresh) {
        // nada: las sugerencias solo salen al empezar
      } else if (s.repo) {
        items.push({ ico: 'sparkle', text: 'Revisa el repo y dime qué falta', run: () => this.fill('Revisa el estado del repo y dime qué falta o qué está roto') });
        items.push({ ico: 'orbit', text: 'Tarea larga…', run: () => this.panels.open('largo') });
      } else {
        items.push({ ico: 'repo', text: 'Elegir un repo para programar', run: () => this.panels.open('ajustes') });
      }
      if (fresh) items.push({ ico: 'spark', text: '¿Qué puedes hacer?', run: () => this.panels.open('ayuda') });
    }
    const key = items.slice(0, 4).map((it) => it.text).join('|');
    if (key === this.sgKey) return;  // el sondeo periódico no debe re-animar los chips
    this.sgKey = key;
    box.innerHTML = '';
    items.slice(0, 4).forEach((it, i) => {
      const b = document.createElement('button');
      b.type = 'button';
      b.className = 'sg ' + (it.cls || '');
      b.style.animationDelay = `${i * 50}ms`;
      b.innerHTML = `${icon(it.ico)}<span>${esc(it.text)}</span>`;
      b.addEventListener('click', it.run);
      box.appendChild(b);
    });
  }

  // --- paleta de acciones (Ctrl+K) ---------------------------------------
  actions() {
    const s = this.snap || {};
    const A = [];
    const g = (group, ico, text, run, desc = '') => A.push({ group, ico, text, run, desc });
    g('Hablar', 'chat', 'Escribir a Skynet', () => this.input.focus(), 'Enter');
    if (s.pendiente) g('Hablar', 'resume', `Continuar «${s.pendiente.title}»`, () => this.resumeTask(s.pendiente.id), `tarea ${s.pendiente.id}`);
    if (this.busy) g('Hablar', 'stop', 'Detener lo que está haciendo', () => this.stop(), 'Esc');
    g('Tareas', 'tasks', 'Ver tareas', () => this.panels.open('tareas'));
    g('Tareas', 'orbit', 'Lanzar una tarea larga', () => this.panels.open('largo'));
    g('Tareas', 'log', 'Registro: herramientas, modelos, tokens y coste', () => this.panels.open('registro'));
    for (const r of s.repos || []) g('Repo', 'repo', `Trabajar en ${r.nombre}`, () => this.panels.setRepo(r.nombre), r.nombre === s.repo ? 'actual' : '');
    g('Repo', 'chat', 'Sin repo (solo conversación)', () => this.panels.setRepo(null));
    g('Modelo', 'route', 'Modelo automático (router)', () => this.panels.setModel('auto'), s.modelo === 'auto' ? 'actual' : '');
    for (const m of s.modelos || []) g('Modelo', m.privado ? 'cpu' : 'cloud', `Usar ${m.nombre}`, () => this.panels.setModel(m.nombre), m.disponible ? (s.modelo === m.nombre ? 'actual' : '') : 'no disponible');
    g('Sistema', 'pulse', 'Diagnóstico de la instalación', () => this.panels.open('diagnostico'));
    g('Sistema', 'spark', 'Qué puede hacer Skynet', () => this.panels.open('ayuda'));
    g('Sistema', 'eye', document.body.classList.contains('convo-hidden') ? 'Mostrar la conversación' : 'Ocultar la conversación (ver la nebulosa)', () => this.panels.toggle('conversacion'));
    return A;
  }

  openPalette() {
    const p = $('#palette');
    p.hidden = false;
    const inp = $('#paletteInput');
    inp.value = '';
    this.palSel = 0;
    this.renderPalette();
    inp.focus();
  }

  closePalette() {
    $('#palette').hidden = true;
  }

  renderPalette() {
    const q = $('#paletteInput').value.trim().toLowerCase();
    const norm = (x) => x.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');
    const words = norm(q).split(/\s+/).filter(Boolean);
    this.palItems = this.actions().filter((a) => words.every((w) => norm(`${a.group} ${a.text} ${a.desc}`).includes(w)));
    this.palSel = Math.min(this.palSel || 0, Math.max(0, this.palItems.length - 1));
    const list = $('#paletteList');
    let html = '', last = '';
    this.palItems.forEach((a, i) => {
      if (a.group !== last) { html += `<div class="pal-group">${esc(a.group)}</div>`; last = a.group; }
      html += `<button class="pal-item ${i === this.palSel ? 'sel' : ''}" data-i="${i}" role="option">${icon(a.ico)}<span>${esc(a.text)}</span><span class="pal-d">${esc(a.desc)}</span></button>`;
    });
    list.innerHTML = html || '<div class="empty">Nada coincide. Escríbeselo a Skynet directamente.</div>';
    for (const b of list.querySelectorAll('.pal-item')) {
      b.addEventListener('click', () => this.runPalette(+b.dataset.i));
      b.addEventListener('mousemove', () => { if (this.palSel !== +b.dataset.i) { this.palSel = +b.dataset.i; this.renderPalette(); } });
    }
    list.querySelector('.sel')?.scrollIntoView({ block: 'nearest' });
  }

  paletteKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); this.palSel = Math.min(this.palItems.length - 1, this.palSel + 1); this.renderPalette(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.palSel = Math.max(0, this.palSel - 1); this.renderPalette(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      if (this.palItems.length) this.runPalette(this.palSel);
      else { const v = $('#paletteInput').value; this.closePalette(); this.fill(v); }
    } else if (e.key === 'Escape') { e.preventDefault(); this.closePalette(); }
  }

  runPalette(i) {
    const a = this.palItems[i];
    this.closePalette();
    a?.run();
  }

  // --- utilidades -----------------------------------------------------
  toast(text, cls = '') {
    const t = this.node(esc(text), 'toast ' + cls);
    $('#toasts').appendChild(t);
    setTimeout(() => { t.classList.add('out'); setTimeout(() => t.remove(), 400); }, 4200);
  }

  async poll() {
    if (!this.connected) return;
    try { this.applySnap(await api.estado()); } catch { /* la conexión SSE ya avisa */ }
  }
}
