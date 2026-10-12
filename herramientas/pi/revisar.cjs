// Comprobación independiente del ejemplo y del selector, sin usar el modelo.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require(path.join(process.env.USERPROFILE, '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true,args:['--disable-gpu']});
  const errors=[];
  try {
    const page=await browser.newPage(); page.on('pageerror',e=>errors.push(String(e)));
    await page.goto(pathToFileURL(path.resolve('proyectos/prueba-pi/index.html')).href);
    assert.equal(await page.locator('#numero').innerText(),'0');
    await page.locator('#sumar').click(); assert.equal(await page.locator('#numero').innerText(),'1');
    await page.locator('#sumar').click(); assert.equal(await page.locator('#numero').innerText(),'2');
    await page.reload(); assert.equal(await page.locator('#numero').innerText(),'2');
    await page.locator('#reiniciar').click(); assert.equal(await page.locator('#numero').innerText(),'0');
    await page.reload(); assert.equal(await page.locator('#numero').innerText(),'0');
    for (const width of [390,768,1440]) {
      await page.setViewportSize({width,height:900});
      assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+2));
    }
    await page.screenshot({path:'data/pruebas/pi/contador.png'});
    await page.goto('http://127.0.0.1:8765/?calidad=baja');
    await page.waitForFunction(()=>window.ready&&window.app.snap);
    assert.equal(await page.evaluate(()=>app.snap.coder_motor),'pi');
    assert.equal(await page.evaluate(()=>app.snap.repo),'prueba-pi');
    await page.locator('#plusBtn').click();
    assert.ok(await page.locator('#menu').getByText('Agente para programar',{exact:true}).isVisible());
    assert.ok(await page.locator('#menu [data-v="motor-pi"]').isVisible());
    await page.locator('#menu [data-v="motor-skynet"]').click();
    await page.waitForFunction(()=>app.snap.coder_motor==='skynet');
    await page.locator('#plusBtn').click();
    await page.locator('#menu [data-v="motor-pi"]').click();
    await page.waitForFunction(()=>app.snap.coder_motor==='pi');
    assert.deepEqual(errors,[]);
    fs.writeFileSync('data/pruebas/pi/revision-ui.json',JSON.stringify({ok:true,controles:true,persistencia:true,movil:true,selectorPi:true,errores:errors},null,2));
    console.log('OK: contador, persistencia, tres anchos y selector Pi; sin errores JavaScript.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
