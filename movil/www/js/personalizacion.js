// Configuración del motor del agente (harness Pi), servidores MCP y memoria aprobada.
// Formulario con etiquetas encima, interruptores y controles segmentados: se lee de un vistazo.
import { esc } from './md.js';
import { api } from './api.js';
import { icon } from './icons.js';

const CACHE = [['f16', 'FP16', 'Calidad máxima'], ['q8_0', 'Q8', '½ memoria'], ['q4_0', 'Q4', '¼ memoria']];
const NATIVAS = [['read', 'Leer'], ['bash', 'Terminal'], ['edit', 'Editar'], ['write', 'Escribir']];

// Una fila con texto a la izquierda y un interruptor (checkbox real con aspecto de switch) a la derecha.
const sw = (attrs, on, title, sub = '') => `<label class="sw-row"><span class="grow"><span class="sw-t">${title}</span>${sub ? `<span class="sw-s">${sub}</span>` : ''}</span>
  <input type="checkbox" class="switch" ${attrs} ${on ? 'checked' : ''}></label>`;

// Lo que distingue a cada servidor: la URL, o el ejecutable (sin su ruta) con sus argumentos.
function mcpDetalle(m, completo = false) {
  if (m.url) return m.url;
  const cmd = completo ? m.command : String(m.command || '').split(/[\\/]/).pop();
  return [cmd, ...(Array.isArray(m.args) ? m.args : [])].filter(Boolean).join(' ');
}

export function opcionesHtml(o) {
  if (!o) return '';
  const harness = o.harnesses?.[o.harness] || {};
  const cache = o.cache_kv || 'f16';
  let html = `<div class="section-k" data-section="motor" style="margin-top:4px">Motor del agente</div>
  <div class="card form" id="motorForm">
    <label class="field"><span class="field-k">Harness</span>
      <select class="select" id="harnessSelect">${Object.entries(o.harnesses || {}).map(([id, h]) => `<option value="${esc(id)}" ${o.harness === id ? 'selected' : ''}>${esc(h.nombre || id)}</option>`).join('')}</select>
      <span class="field-note">${esc(harness.nombre || o.harness || 'Pi')} conserva sus herramientas, conversación y compactación. Otros motores necesitan un adaptador compatible.</span></label>

    <div class="field"><span class="field-k">Herramientas originales</span>
      <div class="chips">${NATIVAS.map(([t, label]) => `<label class="chip"><input type="checkbox" data-nativa="${t}" ${o.herramientas?.includes(t) ? 'checked' : ''}><span>${icon('check')}<b>${t}</b> ${label}</span></label>`).join('')}</div></div>

    <div class="form-sep"></div>
    <div class="field-k form-k">Modelo local</div>
    <div class="form-grid">
      <label class="field"><span class="field-k">Contexto</span>
        <span class="input-unit"><input class="input" id="contextoNative" type="number" min="2048" max="262144" step="1024" value="${esc(o.contexto)}"><span>tokens</span></span></label>
      <label class="field"><span class="field-k">Salida máxima</span>
        <span class="input-unit"><input class="input" id="salidaNative" type="number" min="256" max="131072" step="256" value="${esc(o.salida_max_tokens || 32768)}"><span>tokens</span></span></label>
    </div>
    <p class="field-note">La salida incluye razonamiento y código. Pi la limita a la mitad del contexto y reserva espacio para compactar. Se aplica en el siguiente mensaje.</p>

    <div class="field"><span class="field-k">Caché KV</span>
      <div class="seg" role="radiogroup" aria-label="Caché KV">${CACHE.map(([id, label, sub]) => `<label class="seg-i" title="${sub}"><input type="radio" name="cacheKv" value="${id}" ${cache === id ? 'checked' : ''}><span><b>${label}</b><small>${sub}</small></span></label>`).join('')}</div></div>
    <div class="sw-list">
      ${sw('data-opcion="mtp"', o.mtp, 'MTP', 'Acelera la generación cuando el modelo lo admite')}
      ${sw('data-opcion="vision_gpu"', o.vision_gpu, 'Imágenes en GPU', 'Apagado: la visión se procesa en la CPU')}
    </div>
    <p class="field-note">${icon('resume')} Contexto, caché, MTP y visión se aplican al reiniciar el motor local.</p>

    <div class="form-sep"></div>
    <div class="sw-list">
      ${sw('data-opcion="memoria_activa"', o.memoria_activa, 'Usar la memoria aprobada', 'Solo las entradas que hayas aprobado abajo')}
      ${sw('data-opcion="mcp_activo"', o.mcp_activo, 'Permitir herramientas MCP', 'Interruptor general; cada servidor se activa por separado')}
    </div>
    <div class="form-actions"><span class="form-dirty" id="motorDirty" hidden>Cambios sin guardar</span><span class="grow"></span>
      <button class="btn primary small" id="guardarNative" disabled>Guardar</button></div>
  </div>

  <div class="section-k" data-section="mcp">Servidores MCP</div>
  <div class="card">
    <p class="field-note" style="margin-top:0">Apagados no se conectan ni ofrecen herramientas. Búsqueda y navegador necesitan además Internet activado.</p>
    <div class="rows">`;
  const mcp = Object.entries(o.mcp || {});
  if (!mcp.length) html += '<div class="field-note">Ningún servidor configurado.</div>';
  for (const [id, m] of mcp) {
    html += `<div class="row">
      <span class="row-i">${icon(m.url ? 'globe' : 'terminal')}</span>
      <span class="grow"><span class="row-t">${esc(id)}</span><span class="row-s mono ellipsis" title="${esc(mcpDetalle(m, true))}">${esc(mcpDetalle(m) || 'Sin comando')}</span></span>
      <button class="icon-btn row-del" data-mcp-eliminar="${esc(id)}" aria-label="Eliminar ${esc(id)}" title="Eliminar">${icon('trash')}</button>
      <input type="checkbox" class="switch" data-mcp="${esc(id)}" ${m.enabled ? 'checked' : ''} aria-label="Activar ${esc(id)}">
    </div>`;
  }
  html += `</div>
    <details class="adv add-mcp"><summary>Añadir servidor MCP</summary>
      <form id="anadirMcp" class="form-grid">
        <label class="field span2"><span class="field-k">Nombre</span><input class="input" name="nombre" placeholder="mi-servidor" pattern="[A-Za-z0-9_\\-]+" required></label>
        <label class="field"><span class="field-k">Ejecutable (stdio)</span><input class="input mono" name="comando" placeholder="npx"></label>
        <label class="field"><span class="field-k">Argumentos (JSON)</span><input class="input mono" name="args" placeholder='["-y", "paquete"]'></label>
        <label class="field span2"><span class="field-k">o URL (HTTP)</span><input class="input mono" name="url" placeholder="http://127.0.0.1:3000/mcp"></label>
        <div class="span2 form-actions"><span class="field-note">Se añade apagado: actívalo cuando quieras usarlo.</span><span class="grow"></span><button class="btn small" type="submit">${icon('plus')} Añadir</button></div>
      </form>
    </details>
  </div>

  <div class="section-k" data-section="memoria">Memoria</div>
  <div class="card">
    <p class="field-note" style="margin-top:0">Una entrada por aprobación. Las pendientes no se usan.</p>
    <div class="rows">`;
  if (!(o.memoria || []).length) html += '<div class="field-note">Sin entradas todavía.</div>';
  for (const e of o.memoria || []) {
    html += `<div class="row mem-row"><div class="grow">
      <div class="row-t mem-t">${esc(e.texto)}</div>
      <div class="mem-actions"><span class="pill ${e.aprobada ? 's-hecha' : 's-pendiente'}">${e.aprobada ? 'Aprobada' : 'Pendiente'}</span><span class="grow"></span>
        ${e.aprobada ? '' : `<button class="btn small" data-memoria-aprobar="${e.id}">${icon('check')} Aprobar</button>`}
        <button class="icon-btn row-del" data-memoria-quitar="${e.id}" aria-label="${e.aprobada ? 'Eliminar' : 'Descartar'}" title="${e.aprobada ? 'Eliminar' : 'Descartar'}">${icon(e.aprobada ? 'trash' : 'x')}</button></div>
    </div></div>`;
  }
  html += `</div>
    <form id="anadirMemoria" class="inline-form"><input class="input" name="texto" maxlength="500" placeholder="Un hecho o preferencia que deba recordar" required>
      <button class="btn small" type="submit">${icon('plus')} Añadir</button></form>
  </div>

  <details class="adv"><summary>Más modelos y harnesses (JSON)</summary>
    <p class="field-note">Modelos: endpoint compatible con OpenAI. Harnesses: protocolo pi-rpc; no basta con indicar cualquier agente.</p>
    <label class="field"><span class="field-k">Modelos adicionales</span><textarea class="textarea mono" id="modelosNative" rows="5" spellcheck="false">${esc(JSON.stringify(o.modelos, null, 2))}</textarea>
      <span class="field-note">Ejemplo: {"otro":{"id":"modelo-servido","api_base":"http://127.0.0.1:1234/v1","privado":true,"contexto":16384}}</span></label>
    <label class="field"><span class="field-k">MCP (avanzado)</span><textarea class="textarea mono" id="mcpNative" rows="5" spellcheck="false">${esc(JSON.stringify(o.mcp, null, 2))}</textarea></label>
    <label class="field"><span class="field-k">Skills activas (rutas)</span><textarea class="textarea mono" id="skillsNative" rows="2" spellcheck="false">${esc(JSON.stringify(o.skills || []))}</textarea></label>
    <label class="field"><span class="field-k">Harnesses</span><textarea class="textarea mono" id="harnessesNative" rows="5" spellcheck="false">${esc(JSON.stringify(o.harnesses, null, 2))}</textarea></label>
    <div class="form-actions"><span class="grow"></span><button class="btn small" id="guardarCatalogos">Guardar catálogos</button></div>
  </details>`;
  return html;
}

// JSON escrito a mano: error legible en vez de «Unexpected token».
function parseJson(text, what, fallback) {
  const t = String(text ?? '').trim();
  if (!t) return fallback;
  try { return JSON.parse(t); } catch { throw new Error(`${what}: el JSON no es válido.`); }
}

export function enlazarOpciones(panel, o) {
  if (!o) return;
  const q = (s) => panel.body.querySelector(s);
  const run = async (f) => {
    try { await f(); panel.app.applySnap(await api.estado()); panel.render(true); } catch (e) { panel.app.toast(e.message, 'bad'); }
  };
  // «Guardar» se enciende solo cuando hay algo que guardar.
  const form = q('#motorForm');
  const dirty = () => { q('#guardarNative').disabled = false; q('#motorDirty').hidden = false; };
  form?.addEventListener('input', dirty);
  form?.addEventListener('change', dirty);
  q('#guardarNative')?.addEventListener('click', () => run(async () => {
    const body = {
      harness: q('#harnessSelect').value,
      contexto: Number(q('#contextoNative').value),
      salida_max_tokens: Number(q('#salidaNative').value),
      cache_kv: q('input[name="cacheKv"]:checked')?.value || 'f16',
      herramientas: [...panel.body.querySelectorAll('[data-nativa]:checked')].map((e) => e.dataset.nativa),
    };
    for (const e of panel.body.querySelectorAll('[data-opcion]')) body[e.dataset.opcion] = e.checked;
    await api.personalizacion(body);
    panel.app.toast('Opciones guardadas.');
  }));
  for (const e of panel.body.querySelectorAll('[data-mcp]')) {
    e.addEventListener('change', () => run(() => api.personalizacion({ mcp: { ...o.mcp, [e.dataset.mcp]: { ...o.mcp[e.dataset.mcp], enabled: e.checked } } })));
  }
  for (const e of panel.body.querySelectorAll('[data-mcp-eliminar]')) {
    e.addEventListener('click', async () => {
      const id = e.dataset.mcpEliminar;
      const ok = await panel.app.confirmDialog({ tipo: 'aviso', titulo: `¿Eliminar el servidor «${id}»?`, texto: 'Se quita de la configuración. Puedes volver a añadirlo cuando quieras.', boton: 'Eliminar' });
      if (!ok) return;
      run(() => { const mcp = { ...o.mcp }; delete mcp[id]; return api.personalizacion({ mcp }); });
    });
  }
  q('#anadirMcp')?.addEventListener('submit', (ev) => {
    ev.preventDefault();
    run(() => {
      const f = new FormData(ev.target);
      const id = String(f.get('nombre') || '').trim();
      const url = String(f.get('url') || '').trim();
      const comando = String(f.get('comando') || '').trim();
      if (!url && !comando) throw new Error('Indica un ejecutable o una URL.');
      if (o.mcp?.[id]) throw new Error(`Ya existe un servidor llamado «${id}».`);
      const args = parseJson(f.get('args'), 'Argumentos', []);
      if (!Array.isArray(args)) throw new Error('Los argumentos deben ser una lista JSON, por ejemplo ["-y", "paquete"].');
      const spec = url ? { url, enabled: false } : { command: comando, args, enabled: false };
      return api.personalizacion({ mcp: { ...o.mcp, [id]: spec } });
    });
  });
  q('#anadirMemoria')?.addEventListener('submit', (ev) => { ev.preventDefault(); run(() => api.memoria({ accion: 'proponer', texto: new FormData(ev.target).get('texto') })); });
  for (const e of panel.body.querySelectorAll('[data-memoria-aprobar]')) e.addEventListener('click', () => run(() => api.memoria({ accion: 'aprobar', id: e.dataset.memoriaAprobar })));
  for (const e of panel.body.querySelectorAll('[data-memoria-quitar]')) e.addEventListener('click', () => run(() => api.memoria({ accion: 'descartar', id: e.dataset.memoriaQuitar })));
  q('#guardarCatalogos')?.addEventListener('click', () => run(() => api.personalizacion({
    modelos: parseJson(q('#modelosNative').value, 'Modelos', {}),
    mcp: parseJson(q('#mcpNative').value, 'MCP', {}),
    skills: parseJson(q('#skillsNative').value, 'Skills', []),
    harnesses: parseJson(q('#harnessesNative').value, 'Harnesses', {}),
  })));
}
