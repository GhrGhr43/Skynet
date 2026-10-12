// Perfil efímero y rutas limitadas: el HTML del proyecto no alcanza la red ni otros archivos.
const fs = require('node:fs');
const path = require('node:path');
const {pathToFileURL, fileURLToPath} = require('node:url');
const { chromium } = require('playwright');

(async () => {
  const request = JSON.parse(fs.readFileSync(0, 'utf8'));
  const root = fs.realpathSync(request.root);
  const browser = await chromium.launch({channel: process.env.SKYNET_BROWSER_CHANNEL || 'chrome', headless: true,
    args: ['--disable-gpu','--dns-prefetch-disable']});
  try {
    const context = await browser.newContext({viewport: {width: request.ancho, height: request.alto}, acceptDownloads: false,
      serviceWorkers: 'block'});
    await context.routeWebSocket('**/*', socket => socket.close());
    await context.addInitScript(() => {
      for (const key of ['RTCPeerConnection','webkitRTCPeerConnection','WebTransport']) {
        Object.defineProperty(globalThis,key,{value:undefined});
      }
    });
    await context.route('**/*', route => {
      const url = route.request().url();
      let allowed = url.startsWith('data:') || url.startsWith('blob:');
      if (url.startsWith('file:')) {
        try {
          const rel = path.relative(root, fs.realpathSync(fileURLToPath(url)));
          allowed = !rel.startsWith('..') && !path.isAbsolute(rel);
        } catch {allowed = false;}
      }
      return allowed ? route.continue() : route.abort();
    });
    const page = await context.newPage();
    page.setDefaultTimeout(4000);
    const errors = [];
    page.on('pageerror', error => errors.push(String(error).slice(0,500)));
    page.on('console', message => {if (message.type()==='error') errors.push(message.text().slice(0,500));});
    page.on('dialog', dialog => dialog.dismiss());
    await page.goto(pathToFileURL(request.path).href, {timeout: 10000});
    for (const action of request.acciones) {
      try {
        const locator = page.locator(action.selector);
        if (action.tipo === 'clic') await locator.click();
        else if (await locator.evaluate(el => el.type === 'range')) {
          await locator.evaluate((el,value) => {el.value=value;el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));}, action.valor || '');
        } else await locator.fill(action.valor || '');
      } catch (error) {errors.push('Acción '+action.tipo+' '+action.selector+': '+String(error).slice(0,300));}
    }
    await page.waitForTimeout(request.segundos*1000);
    const report = await page.evaluate(() => ({
      titulo: document.title,
      texto: document.body.innerText.slice(0,1800),
      controles: Array.from(document.querySelectorAll('button,input,select')).slice(0,30).map(el => ({
        tag: el.tagName.toLowerCase(), id: el.id, tipo: el.type, texto: (el.innerText || el.placeholder || '').slice(0,70), valor: el.value})),
      canvas: Array.from(document.querySelectorAll('canvas')).map(el => ({id:el.id,ancho:el.width,alto:el.height})),
      elementosAnchos: Array.from(document.body.querySelectorAll('*')).filter(el => {
        const r=el.getBoundingClientRect(); if(!r.width||r.right<=innerWidth+2)return false;
        for(let p=el.parentElement;p;p=p.parentElement){
          if(['auto','scroll','hidden','clip'].includes(getComputedStyle(p).overflowX)&&p.getBoundingClientRect().right<=innerWidth+2)return false;
        }return true;
      }).slice(0,20).map(el=>({tag:el.tagName.toLowerCase(),id:el.id,clase:el.className?.toString().slice(0,80),
        ancho:Math.round(el.getBoundingClientRect().width),derecha:Math.round(el.getBoundingClientRect().right),
        padre:el.parentElement?.id||el.parentElement?.className?.toString().slice(0,80)})),
      desbordamientoHorizontal: document.documentElement.scrollWidth > innerWidth+2
    }));
    if (report.desbordamientoHorizontal) errors.push('La página desborda horizontalmente en este ancho.');
    report.errores = errors.slice(0,12);
    report.ok = !errors.length;
    if (request.captura) report.imagen = (await page.screenshot({type:'jpeg',quality:75})).toString('base64');
    process.stdout.write(JSON.stringify(report));
  } finally {await browser.close();}
})().catch(error => {console.error(String(error));process.exitCode=1;});
