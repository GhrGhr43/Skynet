// Interfaz real; las mutaciones se simulan para no aprobar memoria ni cambiar opciones del usuario.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async()=>{
 const snapshot=await (await fetch('http://127.0.0.1:8765/api/estado')).json();
 assert.equal(snapshot.harness,'pi');
 const state=structuredClone(snapshot);
 state.personalizacion.memoria=[{id:'prueba-a',texto:'Memoria de prueba A',aprobada:false},{id:'prueba-b',texto:'Memoria de prueba B',aprobada:false}];
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--disable-gpu']});
 const errors=[];
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(String(e)));
  await page.route('**/api/estado',r=>r.fulfill({json:state}));
  await page.route('**/api/stream',r=>r.fulfill({contentType:'text/event-stream',body:`event: hola\ndata: ${JSON.stringify(state)}\n\n`,status:200}));
  await page.route('**/api/personalizacion',async r=>{
   Object.assign(state.personalizacion,r.request().postDataJSON());
   state.harness=state.personalizacion.harness;
   await r.fulfill({json:state});
  });
  await page.route('**/api/memoria',async r=>{
   const b=r.request().postDataJSON();
   if(b.accion==='aprobar') state.personalizacion.memoria.find(e=>e.id===b.id).aprobada=true;
   await r.fulfill({json:state});
  });
  await page.goto('http://127.0.0.1:8765/?calidad=baja');
  await page.waitForFunction(()=>window.ready&&window.app.snap);
  await page.locator('#btnHarness').click();
  await page.locator('#harnessSelect').waitFor();
  assert.equal(await page.locator('#harnessSelect').inputValue(),'pi');
  assert.equal(await page.locator('[data-nativa]').count(),4);
  await page.locator('[data-memoria-aprobar="prueba-a"]').click();
  await page.waitForFunction(()=>app.snap.personalizacion.memoria[0].aprobada);
  assert.equal(await page.locator('[data-memoria-aprobar="prueba-b"]').count(),1);
  assert.equal(await page.locator('[data-memoria-aprobar="prueba-a"]').count(),0);
  await page.locator('[data-opcion="mcp_activo"]').check();
  await page.locator('#guardarNative').click();
  await page.waitForFunction(()=>app.snap.personalizacion.mcp_activo);
  await page.locator('#anadirMcp [name="nombre"]').fill('prueba-ui');
  await page.locator('#anadirMcp [name="comando"]').fill('node');
  await page.locator('#anadirMcp [type="submit"]').click();
  await page.waitForFunction(()=>!!app.snap.personalizacion.mcp['prueba-ui']);
  await page.locator('[data-mcp="prueba-ui"]').check();
  await page.waitForFunction(()=>app.snap.personalizacion.mcp['prueba-ui'].enabled);
  await page.locator('[data-mcp-eliminar="prueba-ui"]').click();
  await page.waitForFunction(()=>!app.snap.personalizacion.mcp['prueba-ui']);
  for(const width of [1440,768,390]){
   await page.setViewportSize({width,height:1000});
   assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
  }
  await page.screenshot({path:'data/pruebas/pi/configuracion-motor.png',fullPage:true});
  assert.deepEqual(errors,[]);
  fs.writeFileSync('data/pruebas/pi/revision-motor-ui.json',JSON.stringify({ok:true,harness:true,herramientas:4,memoriaIndividual:true,mcpAnadirActivarEliminar:true,anchos:[1440,768,390],mutaciones:'simuladas; preferencias reales conservadas',errores:errors},null,2));
  console.log('OK: configuración Pi, memoria individual, MCP y tres anchos; sin errores JavaScript.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
