// Paneles laterales: todo lo que antes eran comandos (/tareas, /largo, /log, /modelo, /repo,
// /privado, /doctor, /ayuda) como pantallas que se entienden sin saberse nada.
import { api, modoConexion, conexion, olvidarConexion, probarConexion } from './api.js';
import { abrirConectar } from './conectar.js';
import { md, esc } from './md.js';
import { icon, paintIcons } from './icons.js';
import { QUALITY } from './scene/engine.js';

const $ = (s, r = document) => r.querySelector(s);

const TITLES = {
  registro: 'Uso',
  ajustes: 'Configuración',
  diagnostico: 'Estado',
  aprendizaje: 'Lo que ha aprendido',
};

const STATUS_TEXT = {
  pendiente: 'pendiente', en_curso: 'en curso', esperando_permiso: 'esperando permiso',
  hecha: 'hecha', fallida: 'fallida', pausada: 'pausada',
};


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
    if (name === 'registro') this.timer = setInterval(() => this.render(true), 4000);
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
    for (const b of document.querySelectorAll('.rail-btn, .config-btn, .learn')) {
      const p = b.dataset.panel;
      b.classList.toggle('active', p === this.current || (p === 'conversacion' && !this.current && document.body.classList.contains('has-convo')));
    }
  }

  refresh() {
    if (this.current) this.render(true);
  }

  onSnap(s) {
    if (this.current === 'ajustes') this.render(true);
    if (this.current === 'aprendizaje' && s && s.propuestas !== this.learnCount) this.render(true);
  }

  onDiag(checks) {
    if (this.current === 'diagnostico') this.paintDiag(checks);
  }

  async render(silent = false) {
    const name = this.current;
    const body = this.body;
    if (!silent) body.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div>';
    try {
      if (name === 'registro') await this.renderLog(silent);
      else if (name === 'ajustes') this.renderSettings();
      else if (name === 'diagnostico') this.renderDiag();
      else if (name === 'aprendizaje') await this.renderLearn(silent);
    } catch (e) {
      if (!silent) body.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
    }
    paintIcons(body);
  }

  // Mantiene el scroll y el foco al refrescar en caliente.
  paint(html) {
    const top = this.body.scrollTop;
    const active = document.activeElement && this.body.contains(document.activeElement) ? document.activeElement.id : null;
    const open = [...this.body.querySelectorAll('details')].map((d) => d.open);
    this.body.innerHTML = html;
    this.body.querySelectorAll('details').forEach((d, i) => { if (open[i]) d.open = true; });
    this.body.scrollTop = top;
    if (active) document.getElementById(active)?.focus();
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
    return this.app.ajustes({ modelo: name });
  }

  renderSettings() {
    const s = this.app.snap;
    if (!s) return;
    const quality = localStorage.getItem('skynet.calidad') || 'auto';
    const motores = Object.fromEntries((s.motores || []).map((e) => [e.nombre, e]));
    const modos = (s.modos || []);

    const cx = conexion();
    const enPC = modoConexion === 'pc';
    let html = `<div class="section-k" style="margin-top:4px">Conexión con tu PC</div>
      <div class="card"><div class="card-row">${icon(enPC ? 'phone' : 'cpu')}<div class="grow">
        <div class="card-title">${enPC ? 'Conectado a tu PC' : 'Modo demo'}</div>
        <div class="card-sub ${enPC ? 'mono ellipsis' : ''}">${enPC ? `${esc(cx.url.replace(/^https?:\/\//, ''))} · ${esc(cx.dispositivo?.nombre || 'este móvil')}`
          : 'Datos de prueba. Conecta la app con Skynet de tu PC para manejarlo desde aquí.'}</div></div></div>
        <div class="btn-row">${enPC
          ? '<button class="btn small" id="cxProbar">Probar</button><button class="btn small danger" id="cxSalir">Desconectar</button>'
          : `<button class="btn primary small" id="cxAbrir">${icon('link')} Conectar con mi PC</button>`}</div></div>`;
    html += '<div class="section-k">Repos</div>';
    for (const r of s.repos || []) {
      html += `<div class="card clickable ${s.repo === r.nombre ? 'selected' : ''}" data-repo="${esc(r.nombre)}">
        <div class="card-row">${icon('repo')}<div class="grow"><div class="card-title">${esc(r.nombre)}</div>
        <div class="card-sub mono ellipsis" title="${esc(r.ruta)}">${esc(r.ruta)}${r.existe ? '' : ' · <span class="warn-text">no existe</span>'}</div></div></div></div>`;
    }
    if (!enPC) html += `<form class="add-repo" id="addRepo">
      <label class="field-k" for="repoNombre">Añadir repo</label>
      <input class="input" id="repoNombre" placeholder="Nombre, p. ej. mi-juego" autocomplete="off" required>
      <input class="input mono" id="repoRuta" placeholder="Carpeta, p. ej. C:\\Users\\HACHO\\Documents\\mi-juego" autocomplete="off" required>
      <input class="input" id="repoVerif" placeholder="Comando para comprobarlo (opcional), p. ej. npm test" autocomplete="off">
      <button class="btn primary" type="submit">Añadir</button>
    </form>`;

    html += '<div class="section-k">Modelos</div>';
    for (const m of s.modelos || []) {
      const e = motores[m.motor || m.nombre];
      const busy = !!e?.ocupado;
      const on = m.privado ? (e ? !!e.encendido : true) : !!(m.activado && (!e || e.encendido));
      let estado;
      if (busy) estado = 'Cambiando… puede tardar unos minutos';
      else if (m.privado) estado = e ? (e.encendido ? 'Encendido' : 'Apagado') : 'Listo';
      else if (!m.activado) estado = 'Desactivado · pide confirmación';
      else if (e && !e.encendido) estado = 'Activado · motor apagado';
      else if (!m.disponible) estado = `No disponible: ${m.motivo}`;
      else estado = 'Activo';
      const bad = !m.privado && m.activado && !m.disponible && !busy;
      html += `<div class="card model-row ${s.modelo === m.nombre ? 'selected' : ''}">
        <div class="card-row">${icon(m.privado ? 'cpu' : 'cloud')}<div class="grow">
          <div class="card-title">${esc(m.nombre)} <span class="card-sub mono">${esc(m.litellm.split('/').slice(1).join('/'))}</span></div>
          <div class="card-sub ${bad ? 'warn-text' : ''}">${esc(m.privado ? 'En tu PC' : 'Online')} · ${esc(estado)}</div>
        </div>
        <button class="toggle" data-model-toggle="${esc(m.nombre)}" role="switch" aria-checked="${on}" ${busy ? 'disabled' : ''}
          aria-label="${on ? 'Apagar' : 'Encender'} ${esc(m.nombre)}"></button></div>
        <div class="perm-row"><span class="perm-k">Permisos</span>
          <select class="select" data-perm="${esc(m.nombre)}" aria-label="Permisos de ${esc(m.nombre)}">
            ${modos.map((o) => `<option value="${esc(o.clave)}" ${o.clave === m.modo ? 'selected' : ''}>${esc(o.nombre)}</option>`).join('')}
          </select>${m.modo === 'total' ? `<span class="menu-tg" role="checkbox" tabindex="0" data-libre="${esc(m.nombre)}" aria-checked="${!!m.sin_preguntar}"
            title="${esc(s.sin_preguntar_texto || '')}"><span class="box">${icon('check')}</span>Sin preguntar</span>` : ''}</div></div>`;
    }

    html += '<details class="adv"><summary>Avanzado</summary>';
    html += '<div class="section-k" style="margin-top:12px">Cómo elige el modelo «Automático»</div><div class="card">';
    (s.reglas || []).forEach((r, i) => {
      const cond = Object.entries(r.si || {}).map(([k, v]) => `${k} = ${v}`).join(', ') || 'en cualquier otro caso';
      html += `<div class="card-sub" style="margin-top:${i ? 8 : 0}px">${i + 1}. ${esc(r.motivo || cond)} → <b style="color:var(--fg)">${esc(r.usar)}</b></div>`;
    });
    html += '<div class="card-sub" style="margin-top:8px">Un modelo online solo se usa si lo has activado.</div></div>';
    html += '<div class="section-k">Permisos</div><div class="card">';
    html += modos.map((o) => `<div class="card-sub" style="margin-top:6px"><b style="color:var(--fg)">${esc(o.nombre)}:</b> ${esc(o.descripcion)}</div>`).join('');
    html += `<div class="card-sub" style="margin-top:8px">${esc(s.siempre || '')}</div>`;
    html += `<div class="card-sub" style="margin-top:8px">${esc(s.sin_preguntar_texto || '')}</div></div>`;
    html += `<div class="section-k">Modelo local</div><div class="card"><select class="select" id="localSel" aria-label="Modelo local" disabled><option>Buscando modelos…</option></select>
      <div class="card-sub" id="localInfo" style="margin-top:8px">Los GGUF de la carpeta de modelos de LM Studio. Si el motor está encendido, se reinicia con el elegido.</div></div>`;
    const notif = 'Notification' in window ? Notification.permission : 'unsupported';
    html += `<div class="section-k">Interfaz</div><div class="card solo-pc"><div class="card-row">${icon('warn')}<div class="grow"><div class="card-title">Avisos de Windows</div>
      <div class="card-sub">${notif === 'granted' ? 'Activados.'
        : notif === 'denied' ? 'Bloqueados en el navegador.'
        : notif === 'unsupported' ? 'Este navegador no los admite.' : 'Te avisa cuando Skynet necesita tu confirmación.'}</div></div>
      ${notif === 'default' ? '<button class="btn small" id="notifBtn">Activar</button>' : ''}</div></div>`;
    html += `<div class="field-k" style="margin-top:14px">Calidad visual</div>
      <label class="field" style="margin-top:0"><select class="select" id="quality">
        ${['auto', ...Object.keys(QUALITY)].map((q) => `<option value="${q}" ${q === quality ? 'selected' : ''}>${q === 'auto' ? 'Automática' : `${q[0].toUpperCase()}${q.slice(1)} · ${(QUALITY[q] ** 2).toLocaleString('es-ES')} partículas`}</option>`).join('')}
      </select></label>`;
    html += '</details>';

    this.paint(html);
    for (const c of this.body.querySelectorAll('[data-repo]')) c.addEventListener('click', () => this.setRepo(c.dataset.repo || null));
    for (const c of this.body.querySelectorAll('[data-model]')) c.addEventListener('click', () => this.setModel(c.dataset.model));
    for (const sel of this.body.querySelectorAll('[data-perm]')) sel.addEventListener('change', async () => {
      const prev = (s.modelos || []).find((m) => m.nombre === sel.dataset.perm)?.modo || 'repo';
      if (!(await this.app.ajustes({ permiso: { modelo: sel.dataset.perm, modo: sel.value } }))) sel.value = prev;
    });
    for (const t of this.body.querySelectorAll('[data-libre]')) {
      const go = (e) => { e.preventDefault(); this.app.ajustes({ sin_preguntar: { modelo: t.dataset.libre, activar: t.getAttribute('aria-checked') !== 'true' } }); };
      t.addEventListener('click', go);
      t.addEventListener('keydown', (e) => { if (e.key === ' ' || e.key === 'Enter') go(e); });
    }
    for (const b of this.body.querySelectorAll('[data-model-toggle]')) b.addEventListener('click', () => this.toggleModel(b.dataset.modelToggle, b.getAttribute('aria-checked') !== 'true'));
    $('#cxAbrir')?.addEventListener('click', () => abrirConectar());
    $('#cxProbar')?.addEventListener('click', async () => {
      try { const d = await probarConexion(); this.app.toast(`Tu PC responde (${d.ms} ms) · ${d.dispositivo?.nombre || ''}`); }
      catch (e) { this.app.toast(e.message, 'bad'); }
    });
    $('#cxSalir')?.addEventListener('click', async () => {
      const ok = await this.app.confirmDialog({ tipo: 'aviso', titulo: '¿Desconectar de tu PC?', texto: 'La app vuelve al modo demo. Para volver a conectar tendrás que escanear otro QR.', boton: 'Desconectar' });
      if (ok) { olvidarConexion(); location.reload(); }
    });
    this.loadLocalModels();
    $('#repoRuta')?.addEventListener('input', (e) => {
      const nombre = $('#repoNombre');
      if (!nombre.value.trim()) nombre.value = e.target.value.trim().replace(/[\\/]+$/, '').split(/[\\/]/).pop().replace(/[^A-Za-z0-9_-]/g, '-').slice(0, 40);
    });
    $('#addRepo')?.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      try {
        this.app.applySnap(await api.repo({ nombre: $('#repoNombre').value.trim(), ruta: $('#repoRuta').value.trim(), verificador: $('#repoVerif').value.trim() }));
        this.app.toast('Repo añadido');
        this.render(true);
      } catch (e) { this.app.toast(e.message, 'bad'); }
    });
    $('#notifBtn')?.addEventListener('click', async () => { await Notification.requestPermission(); this.render(true); });
    $('#quality')?.addEventListener('change', (e) => {
      try { localStorage.setItem('skynet.calidad', e.target.value); } catch { /* sin almacenamiento */ }
      location.reload();
    });
  }

  async loadLocalModels() {
    const sel = this.body.querySelector('#localSel');
    if (!sel) return;
    try {
      const { modelos, actual } = await api.modelosLocales();
      if (!this.body.contains(sel)) return;
      const busy = (this.app.snap?.motores || []).some((e) => e.nombre === 'local' && e.ocupado);
      sel.innerHTML = modelos.length
        ? modelos.map((m) => `<option value="${esc(m.nombre)}" ${m.nombre === actual ? 'selected' : ''}>${esc(m.nombre)} · ${esc(m.detalle)}</option>`).join('')
        : '<option>No encuentro modelos GGUF</option>';
      sel.disabled = !modelos.length || busy;
      sel.addEventListener('change', async () => {
        sel.disabled = true;
        try { this.app.applySnap(await api.elegirLocal(sel.value)); } catch (e) { this.app.toast(e.message, 'bad'); }
        this.render(true);
      });
    } catch (e) { this.app.toast(e.message, 'bad'); }
  }

  // --- dispositivos: móviles vinculados por Tailscale ---------------------------
  // La lista se pide al abrir Configuración y tras cada acción; entre medias se pinta desde la caché
  // (Configuración se repinta con cada foto del estado y no debe parpadear).
  loadDevices() {
    if (this.dev.loading) return this.dev.loading;
    this.dev.loading = (async () => {
      try { this.dev.data = await api.dispositivos(); this.dev.error = null; } catch (e) { this.dev.error = e.message; }
      this.dev.loading = false;
      this.paintDevices();
    })();
    return this.dev.loading;
  }

  paintDevices() {
    const box = this.current === 'ajustes' ? $('#devBox') : null;
    if (!box) return;
    box.innerHTML = this.devicesHtml();
    paintIcons(box);
    this.bindDevices(box);
  }

  devicesHtml() {
    const d = this.dev.data;
    if (!d) {
      if (this.dev.error && !this.dev.loading) {
        return `<div class="card"><div class="card-sub warn-text">${esc(this.dev.error)}</div>
          <div class="btn-row"><button class="btn small" data-dev-retry>Reintentar</button></div></div>`;
      }
      return '<div class="skeleton"></div>';
    }
    const acc = d.acceso || {};
    const ts = acc.tailscale || {};
    const all = d.dispositivos || [];
    const vivos = all.filter((x) => !x.revocado);
    const quitados = all.filter((x) => x.revocado).slice(-3);
    let h = '';
    if (!vivos.length) h += '<div class="card dev-empty"><div class="card-sub">Ningún móvil vinculado.</div></div>';
    for (const x of [...vivos, ...quitados]) {
      h += `<div class="card dev-row ${x.revocado ? 'off' : ''}"><div class="card-row">${icon('phone')}
        <div class="grow"><div class="card-title ellipsis">${esc(x.nombre || 'Móvil')}</div>
        <div class="card-sub" ${x.ultimo_origen ? `title="Desde ${esc(x.ultimo_origen)}"` : ''}>${x.revocado ? 'Ya no tiene acceso' : esc(lastUse(x.ultimo_uso))}</div></div>
        ${x.revocado ? '<span class="pill plain">quitado</span>' : `<button class="btn small danger" data-dev-revoke="${esc(x.id)}" data-dev-name="${esc(x.nombre || 'Móvil')}">Quitar</button>`}
      </div></div>`;
    }
    if (!acc.url) {
      h += `<div class="card dev-access"><div class="card-row">${icon('shield')}<div class="grow">
          <div class="card-title">Para usarlo desde el móvil</div><div class="card-sub">${esc(ts.detalle || 'No se detecta Tailscale en este PC.')}</div></div></div>
        ${tsFlags(ts)}${ts.funnel ? FUNNEL_WARN : ''}${PAIR_STEPS}</div>`;
    }
    h += `<div class="btn-row"><button class="btn primary small" data-dev-add>${icon('plus')} Añadir móvil</button></div>`;
    if (acc.url) {
      h += `<div class="card dev-access"><div class="card-row">${icon('shield')}<div class="grow">
          <div class="card-title">Dirección privada del PC</div>
          <div class="card-sub mono ellipsis" title="${esc(ts.detalle || acc.url)}">${esc(acc.url)}</div></div></div>
        ${tsFlags(ts)}${ts.funnel ? FUNNEL_WARN : ''}</div>`;
    }
    return h;
  }

  bindDevices(root) {
    root.querySelector('[data-dev-add]')?.addEventListener('click', () => this.addDevice());
    root.querySelector('[data-dev-retry]')?.addEventListener('click', () => { this.loadDevices(); this.paintDevices(); });
    for (const b of root.querySelectorAll('[data-dev-revoke]')) b.addEventListener('click', () => this.revokeDevice(b.dataset.devRevoke, b.dataset.devName));
    for (const b of root.querySelectorAll('[data-copy]')) b.addEventListener('click', () => this.copy(b.dataset.copy, 'Comando copiado'));
  }

  async revokeDevice(id, nombre) {
    const ok = await this.app.confirmDialog({
      tipo: 'aviso', titulo: `¿Quitar «${nombre}»?`,
      texto: 'Ese móvil dejará de poder usar Skynet al momento. Para volver a usarlo tendrás que vincularlo otra vez.', boton: 'Quitar',
    });
    if (!ok) return;
    try {
      this.dev.data = await api.revocarDispositivo(id);
      this.paintDevices();
      this.app.toast(`«${nombre}» ya no tiene acceso.`);
    } catch (e) { this.app.toast(e.message, 'bad'); this.loadDevices(); }
  }

  async copy(text, msg) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const t = document.createElement('textarea');
      t.value = text;
      t.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(t);
      t.select();
      try { document.execCommand('copy'); } catch { /* nada */ }
      t.remove();
    }
    this.app.toast(msg);
  }

  // Diálogo «Añadir móvil»: pide un código, enseña el QR del enlace y espera a que el móvil
  // se vincule (mira la lista cada 3 s); al aparecer un dispositivo nuevo, pasa a «Conectado».
  async addDevice() {
    if (this.pair) this.stopPair();
    const p = { estado: 'cargando', timers: [] };
    this.pair = p;
    $('#pair').hidden = false;
    this.renderPair();
    try {
      const antes = await api.dispositivos();
      this.dev.data = antes; this.dev.error = null;
      this.paintDevices();
      p.known = new Set((antes.dispositivos || []).map((x) => x.id));
      const r = await api.emparejarDispositivo();
      if (this.pair !== p) return;
      p.r = r;
      p.acceso = antes.acceso || {};
      if (!r.enlace) { p.estado = 'sin-red'; this.renderPair(); return; }
      if (typeof window.qrcode !== 'function') throw new Error('No se pudo cargar el generador de QR. Usa «Copiar enlace».');
      p.qr = qrSvg(r.enlace);
      p.fin = Date.parse(r.expira);
      p.estado = 'qr';
      this.renderPair();
      p.timers.push(setInterval(() => this.tickPair(p), 1000));
      p.timers.push(setInterval(() => this.pollPair(p), 3000));
    } catch (e) {
      if (this.pair !== p) return;
      p.estado = 'error'; p.error = e.message;
      this.renderPair();
    }
  }

  tickPair(p) {
    if (this.pair !== p || p.estado !== 'qr') return;
    const left = Math.max(0, Math.ceil((p.fin - Date.now()) / 1000));
    const el = $('#pairLeft');
    if (el) el.textContent = `Caduca en ${Math.floor(left / 60)}:${String(left % 60).padStart(2, '0')}`;
    if (left <= 0) { this.stopPair(); p.estado = 'caducado'; this.renderPair(); }
  }

  async pollPair(p) {
    if (p.polling) return;
    p.polling = true;
    try {
      const d = await api.dispositivos();
      if (this.pair !== p || p.estado !== 'qr') return;
      this.dev.data = d;
      this.paintDevices();
      const nuevo = (d.dispositivos || []).find((x) => !x.revocado && !p.known.has(x.id));
      if (nuevo) {
        this.stopPair();
        p.estado = 'conectado'; p.nombre = nuevo.nombre || 'Móvil';
        this.renderPair();
        this.app.engine?.pulse?.(0.35);
      }
    } catch { /* sin conexión: se reintenta en 3 s */ } finally { p.polling = false; }
  }

  stopPair() {
    for (const t of this.pair?.timers || []) clearInterval(t);
    if (this.pair) this.pair.timers = [];
  }

  closePair() {
    if (!this.pair) return;
    this.stopPair();
    this.pair = null;
    $('#pair').hidden = true;
    $('#pairCard').innerHTML = '';
    this.loadDevices();
  }

  renderPair() {
    const p = this.pair;
    const card = $('#pairCard');
    if (!p) return;
    const close = (label = 'Cerrar', cls = '') => `<button class="btn ${cls}" data-p="close">${label}</button>`;
    let h = '<div class="ask-level">Añadir móvil</div>';
    if (p.estado === 'cargando') {
      h += `<h3 class="ask-title" id="pairTitle">Preparando el código…</h3><div class="qr-box"><div class="skeleton qr-skel"></div></div>
        <div class="ask-actions">${close()}</div>`;
    } else if (p.estado === 'qr' || p.estado === 'caducado') {
      const off = p.estado === 'caducado';
      h += `<h3 class="ask-title" id="pairTitle">Escanéalo con la app Skynet del móvil</h3>
        <div class="qr-box ${off ? 'off' : ''}">${p.qr}${off ? '<div class="qr-over">Caducado</div>' : ''}</div>
        <div class="pair-left" id="pairLeft">${off ? 'El código ya no vale' : ''}</div>
        <div class="ask-actions">
          ${off ? '' : `<button class="btn small" data-p="copy">${icon('copy')} Copiar enlace</button>`}
          <span class="grow"></span>
          ${close()}
          ${off ? `<button class="btn primary" data-p="again">${icon('resume')} Generar otro</button>` : ''}
        </div>`;
    } else if (p.estado === 'conectado') {
      h += `<div class="pair-ok">${icon('check')}</div>
        <h3 class="ask-title pair-center" id="pairTitle">Conectado: ${esc(p.nombre)}</h3>
        <div class="card-sub pair-center">Ya puedes usar Skynet desde el móvil.</div>
        <div class="ask-actions">${close('Listo', 'primary')}</div>`;
    } else if (p.estado === 'sin-red') {
      const ts = p.acceso.tailscale || {};
      h += `<h3 class="ask-title" id="pairTitle">Antes, prepara Tailscale</h3>
        <div class="card-sub">${esc(ts.detalle || 'No se detecta la dirección privada del PC.')}</div>
        ${tsFlags(ts)}${ts.funnel ? FUNNEL_WARN : ''}${PAIR_STEPS}
        <div class="ask-actions">${close()}<button class="btn primary" data-p="again">${icon('resume')} Comprobar de nuevo</button></div>`;
    } else {
      h += `<h3 class="ask-title" id="pairTitle">No se pudo preparar el código</h3>
        <div class="ask-warn">${esc(p.error || 'Error')}</div>
        <div class="ask-actions">${p.r?.enlace ? `<button class="btn small" data-p="copy">${icon('copy')} Copiar enlace</button><span class="grow"></span>` : ''}
          ${close()}<button class="btn primary" data-p="again">Reintentar</button></div>`;
    }
    card.innerHTML = h;
    this.tickPair(p);
    for (const b of card.querySelectorAll('[data-p]')) {
      b.addEventListener('click', () => {
        const a = b.dataset.p;
        if (a === 'close') this.closePair();
        else if (a === 'again') this.addDevice();
        else if (a === 'copy') this.copy(p.r.enlace, 'Enlace copiado');
      });
    }
    for (const b of card.querySelectorAll('[data-copy]')) b.addEventListener('click', () => this.copy(b.dataset.copy, 'Comando copiado'));
    setTimeout(() => card.querySelector('.btn.primary, [data-p="close"]')?.focus(), 50);
  }

  // Un solo interruptor por modelo. En los online, encender activa el modelo (con confirmación) y
  // arranca su motor si lo tiene (Hermes); apagar hace lo contrario.
  async toggleModel(name, on) {
    const s = this.app.snap;
    const m = s.modelos.find((x) => x.nombre === name);
    const e = (s.motores || []).find((x) => x.nombre === (m.motor || name));
    try {
      if (m.privado) {
        if (e) this.app.applySnap(await api.motor(name, on));
      } else if (on) {
        if (!m.activado && !(await this.app.ajustes({ nube: { modelo: name, activar: true } }))) return;
        if (e && !e.encendido) this.app.applySnap(await api.motor(name, true));
      } else {
        if (!(await this.app.ajustes({ nube: { modelo: name, activar: false } }))) return;
        if (e && e.encendido) this.app.applySnap(await api.motor(name, false));
      }
    } catch (err) { this.app.toast(err.message, 'bad'); }
    this.render(true);
  }

  // --- diagnóstico ---------------------------------------------------------
  renderDiag() {
    this.paint(`<p class="lead">Comprueba la configuración, la base de datos, git, el modelo local, los modelos en la nube y los servidores MCP de cada repo.</p>
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
  // Lo que Skynet propone recordar (skills y memoria): tarjetas con Aprobar / Descartar / Ver.
  async renderLearn(silent) {
    const { items } = await api.aprendizaje();
    this.learnCount = this.app.snap?.propuestas;
    if (!items.length) {
      this.paint(`<p class="lead">Nada pendiente.</p><div class="note">Cuando una tarea sale bien, Skynet puede proponer una skill
        (cómo hacer tareas parecidas) o algo que recordar. Lo verás aquí y nada se activa sin tu visto bueno.</div>`);
      return;
    }
    const open = new Set([...this.body.querySelectorAll('.learn-body:not([hidden])')].map((el) => el.dataset.id));
    const kind = { skill: 'Skill', memoria: 'Memoria' };
    this.paint(`<p class="lead">Skynet propone recordar esto. Nada se activa sin tu visto bueno.</p>` + items.map((it) => `
      <div class="card learn-card" data-id="${esc(it.id)}">
        <div class="card-title"><span class="learn-kind">${kind[it.tipo] || esc(it.tipo)}</span><span class="grow ellipsis">${esc(it.titulo)}</span></div>
        <div class="card-sub">${esc(it.descripcion)}</div>
        ${it.origen ? `<div class="card-sub" style="opacity:.7">${esc(it.origen)}</div>` : ''}
        <div class="learn-body md" data-id="${esc(it.id)}" ${open.has(it.id) ? '' : 'hidden'}>${md(it.texto || '')}</div>
        <div class="btn-row">
          <button class="btn small primary" data-a="aprobar">${icon('check')} Aprobar</button>
          <button class="btn small" data-a="descartar">${icon('x')} Descartar</button>
          <span class="grow"></span>
          <button class="btn small" data-a="ver">${icon('eye')} ${open.has(it.id) ? 'Ocultar' : 'Ver'}</button>
        </div>
      </div>`).join(''));
    for (const card of this.body.querySelectorAll('.learn-card')) {
      const id = card.dataset.id;
      for (const b of card.querySelectorAll('[data-a]')) {
        b.addEventListener('click', async () => {
          const a = b.dataset.a;
          if (a === 'ver') {
            const body = card.querySelector('.learn-body');
            body.hidden = !body.hidden;
            b.innerHTML = `${icon('eye')} ${body.hidden ? 'Ver' : 'Ocultar'}`;
            return;
          }
          for (const x of card.querySelectorAll('button')) x.disabled = true;
          try {
            await api.aprendizajeAccion(id, a);
            if (a === 'descartar') { card.style.opacity = '0.4'; }
          } catch (e) {
            this.app.toast(e.message, 'bad');
            for (const x of card.querySelectorAll('button')) x.disabled = false;
          }
        });
      }
    }
  }

}
