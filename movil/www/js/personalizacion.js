import {esc} from './md.js';
import {api} from './api.js';

export function opcionesHtml(o) {
  if (!o) return '';
  const check=(k,label)=>`<label class="card-sub"><input type="checkbox" data-opcion="${k}" ${o[k]?'checked':''}> ${label}</label><br>`;
  let html=`<div class="section-k">Motor del agente</div><div class="card">
    <label>Harness <select class="select" id="harnessSelect">${Object.entries(o.harnesses).map(([id,h])=>`<option value="${esc(id)}" ${o.harness===id?'selected':''}>${esc(h.nombre||id)}</option>`).join('')}</select></label>
    <div class="card-sub">Pi conserva sus herramientas, conversación y compactación. Otros motores necesitan un adaptador compatible.</div>
    <div class="section-k">Herramientas originales</div>${['read','bash','edit','write'].map(t=>`<label class="card-sub"><input type="checkbox" data-nativa="${t}" ${o.herramientas.includes(t)?'checked':''}> ${t}</label> `).join('')}
    <div class="section-k">Modelo local</div><label>Contexto (tokens) <input class="input" id="contextoNative" type="number" min="2048" max="262144" value="${o.contexto}"></label>
    <label>Salida máxima por respuesta (tokens) <input class="input" id="salidaNative" type="number" min="256" max="131072" value="${o.salida_max_tokens||32768}"></label>
    <p class="note">Incluye razonamiento y código. Pi limita la salida a la mitad del contexto y reserva espacio con su compactación. Se aplica al siguiente mensaje.</p>
    ${check('mtp','MTP: acelerar generación cuando el modelo lo admita')}${check('vision_gpu','Procesar imágenes en GPU (apagado: CPU)')}
    <label>Caché KV <select class="select" id="cacheNative">${[['f16','FP16'],['q8_0','Q8'],['q4_0','Q4']].map(([id,label])=>`<option value="${id}" ${(o.cache_kv||'f16')===id?'selected':''}>${label}</option>`).join('')}</select></label>
    <p class="note">Contexto, caché, MTP y visión se aplican al reiniciar el motor.</p>
    ${check('memoria_activa','Utilizar memoria aprobada')}${check('mcp_activo','Permitir herramientas MCP')}
    <button class="btn primary small" id="guardarNative">Guardar opciones</button></div>
    <div class="section-k">Servidores MCP</div><div class="card"><p class="note">Desactivados: no se conectan ni ofrecen herramientas. Activa solo los que quieras usar.</p>`;
  for(const [id,m] of Object.entries(o.mcp))html+=`<div class="card-row"><label class="grow"><input type="checkbox" data-mcp="${esc(id)}" ${m.enabled?'checked':''}> ${esc(id)}</label><button class="btn small" data-mcp-eliminar="${esc(id)}">Eliminar</button></div>`;
  html+=`<p class="note">Búsqueda y navegador requieren Internet activado. El resto se activa por separado.</p><form id="anadirMcp"><input class="input" name="nombre" placeholder="Nombre del MCP" required><input class="input" name="comando" placeholder="Ejecutable (stdio), por ejemplo npx"><input class="input" name="url" placeholder="URL (HTTP), si no usa un ejecutable"><input class="input" name="args" placeholder='Argumentos JSON, por ejemplo ["-y","paquete"]' value="[]"><button class="btn small" type="submit">Añadir desactivado</button></form></div>
    <div class="section-k">Memoria: una entrada por aprobación</div><div class="card">`;
  for(const e of o.memoria)html+=`<div class="card"><p>${esc(e.texto)}</p><span class="card-sub">${e.aprobada?'Aprobada':'Pendiente; no se utiliza'}</span>${e.aprobada?'':`<button class="btn small" data-memoria-aprobar="${e.id}">Aprobar esta entrada</button>`}<button class="btn small" data-memoria-quitar="${e.id}">${e.aprobada?'Eliminar':'Descartar'}</button></div>`;
  html+=`<form id="anadirMemoria"><input class="input" name="texto" maxlength="500" placeholder="Un hecho o preferencia" required><button class="btn small" type="submit">Añadir pendiente de aprobación</button></form></div>
    <details class="adv"><summary>Más modelos y harnesses</summary><p class="note">Modelos: endpoint compatible con OpenAI. Harnesses: protocolo pi-rpc; no basta con indicar cualquier agente.</p>
    <label>Modelos adicionales (JSON)<textarea class="input" id="modelosNative" rows="5">${esc(JSON.stringify(o.modelos,null,2))}</textarea></label>
    <p class="note">Ejemplo: {"otro":{"id":"modelo-servido","api_base":"http://127.0.0.1:1234/v1","privado":true,"contexto":16384}}</p>
    <label>Configuración avanzada de MCP (JSON)<textarea class="input" id="mcpNative" rows="5">${esc(JSON.stringify(o.mcp,null,2))}</textarea></label>
    <label>Skills activas (rutas JSON)<textarea class="input" id="skillsNative" rows="2">${esc(JSON.stringify(o.skills||[]))}</textarea></label><label>Harnesses (JSON)<textarea class="input" id="harnessesNative" rows="5">${esc(JSON.stringify(o.harnesses,null,2))}</textarea></label>
    <button class="btn small" id="guardarCatalogos">Guardar catálogos</button></details>`;
  return html;
}

export function enlazarOpciones(panel,o){
  if(!o)return;
  const q=s=>panel.body.querySelector(s);
  const run=async f=>{try{await f();panel.app.applySnap(await api.estado());panel.render(true);}catch(e){panel.app.toast(e.message,'bad');}};
  q('#guardarNative')?.addEventListener('click',()=>run(async()=>{
    const body={harness:q('#harnessSelect').value,contexto:Number(q('#contextoNative').value),salida_max_tokens:Number(q('#salidaNative').value),cache_kv:q('#cacheNative').value,herramientas:[...panel.body.querySelectorAll('[data-nativa]:checked')].map(e=>e.dataset.nativa)};
    for(const e of panel.body.querySelectorAll('[data-opcion]'))body[e.dataset.opcion]=e.checked;
    await api.personalizacion(body);
  }));
  for(const e of panel.body.querySelectorAll('[data-mcp]'))e.addEventListener('change',()=>run(()=>api.personalizacion({mcp:{...o.mcp,[e.dataset.mcp]:{...o.mcp[e.dataset.mcp],enabled:e.checked}}})));
  for(const e of panel.body.querySelectorAll('[data-mcp-eliminar]'))e.addEventListener('click',()=>run(()=>{const mcp={...o.mcp};delete mcp[e.dataset.mcpEliminar];return api.personalizacion({mcp});}));
  q('#anadirMcp')?.addEventListener('submit',e=>{e.preventDefault();run(()=>{const f=new FormData(e.target),id=f.get('nombre').trim(),url=f.get('url').trim();const spec=url?{url,enabled:false}:{command:f.get('comando').trim(),args:JSON.parse(f.get('args')),enabled:false};return api.personalizacion({mcp:{...o.mcp,[id]:spec}});});});
  q('#anadirMemoria')?.addEventListener('submit',e=>{e.preventDefault();run(()=>api.memoria({accion:'proponer',texto:new FormData(e.target).get('texto')}));});
  for(const e of panel.body.querySelectorAll('[data-memoria-aprobar]'))e.addEventListener('click',()=>run(()=>api.memoria({accion:'aprobar',id:e.dataset.memoriaAprobar})));
  for(const e of panel.body.querySelectorAll('[data-memoria-quitar]'))e.addEventListener('click',()=>run(()=>api.memoria({accion:'descartar',id:e.dataset.memoriaQuitar})));
  q('#guardarCatalogos')?.addEventListener('click',()=>run(()=>api.personalizacion({modelos:JSON.parse(q('#modelosNative').value),mcp:JSON.parse(q('#mcpNative').value),skills:JSON.parse(q('#skillsNative').value),harnesses:JSON.parse(q('#harnessesNative').value)})));
}
