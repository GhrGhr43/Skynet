// Launcher: el «espacio» de inicio. Al entrar solo está la nebulosa (la app madre, el agente), limpia,
// sin estrellas ni objetos. Un toque la abre (modo agente). Si se mantiene pulsada, brotan de ella las
// apps hijas (apps/), cada una su pequeña nebulosa con su plexo, y vuelven las estrellas. Cada app se
// abre en su propia ventana, que sale de su icono.
import { icon } from '../icons.js';
import { esc } from '../md.js';
import { APPS } from './apps/index.js';
import { nebulaIcon, IconoNebulosa, seedOf } from './nebulas.js';

// Imagen de la nebulosa de una app (para la cabecera de su ventana).
export function appNebula(a) {
  return nebulaIcon(a.color || '#86a8ff', seedOf(a.id)).url;
}

const TACTIL = window.matchMedia('(pointer: coarse)').matches;
const REDUCED = window.matchMedia('(prefers-reduced-motion: reduce)');
const HOLD_MS = 460;     // mantener pulsado
const MOVE_PX = 14;      // más que esto es arrastrar (jugar con la nebulosa), no pulsar
const EASE = 'cubic-bezier(0.22, 1, 0.36, 1)';

export class Launcher {
  constructor(app) {
    this.app = app;
    this.apps = APPS;
    this.abierto = false;
    this.iconos = [];
    this.root = document.getElementById('home');
    this.box = document.getElementById('homeApps');
    this.lines = document.getElementById('homeLines');
    this.box.innerHTML = this.apps.map((a, i) => `
      <button type="button" class="app" data-app="${esc(a.id)}" style="--i:${i};--app:${esc(a.color || '#c9d1e0')}" tabindex="-1">
        <span class="app-float"><span class="app-orb"><canvas class="app-neb" aria-hidden="true"></canvas>${icon(a.icono)}<span class="app-badge" hidden></span></span>
        <span class="app-name">${esc(a.nombre)}</span><span class="app-sub"></span></span>
      </button>`).join('');
    this.box.inert = true;
    this.els = [...this.box.querySelectorAll('.app')];
    this.els.forEach((el, i) => {
      el.addEventListener('click', () => this.open(this.apps[i], el));
      el.addEventListener('pointerenter', () => this.hover(i, true));
      el.addEventListener('pointerleave', () => this.hover(i, false));
      el.addEventListener('focus', () => this.hover(i, true));
      el.addEventListener('blur', () => this.hover(i, false));
    });
    this.bindCore();
    // Clic en el vacío: cierra la ventana abierta o, si no hay ninguna, recoge las apps.
    this.root.addEventListener('click', (e) => {
      if (e.target.closest('.app, .home-core, .home-top')) return;
      if (this.app.panels.current) this.app.panels.close();
      else if (this.abierto) this.ocultar();
    });
    // Esc recoge las apps antes que nada (si no, en el inicio pararía la tarea en marcha).
    window.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape' || this.app.mode === 'agent' || !this.abierto || this.app.panels.current) return;
      if (!document.getElementById('palette').hidden || !document.getElementById('ask').hidden) return;
      e.preventDefault(); e.stopImmediatePropagation();
      this.ocultar();
    });
    window.addEventListener('resize', () => this.layout());
    this.layout();
  }

  // Toque = abrir el agente; mantener = mostrar u ocultar las apps; arrastrar = jugar con la nebulosa.
  bindCore() {
    const core = document.getElementById('homeCore');
    let down = null, timer = 0, held = false;
    const cancel = () => { clearTimeout(timer); timer = 0; this.root.classList.remove('holding'); };
    core.addEventListener('contextmenu', (e) => e.preventDefault());  // mantener en el móvil no abre menús
    core.addEventListener('pointerdown', (e) => {
      if (e.button > 0) return;
      down = [e.clientX, e.clientY];
      held = false;
      this.root.classList.add('holding');
      this.app.engine?.pulse(0.25);
      timer = setTimeout(() => {
        timer = 0; held = true;
        this.root.classList.remove('holding');
        try { navigator.vibrate?.(12); } catch { /* sin vibración */ }
        if (this.abierto) this.ocultar(); else this.mostrar();
      }, HOLD_MS);
    });
    core.addEventListener('pointermove', (e) => {
      if (timer && down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > MOVE_PX) cancel();
    });
    for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) core.addEventListener(ev, cancel);
    core.addEventListener('click', (e) => {
      const moved = down && e.clientX ? Math.hypot(e.clientX - down[0], e.clientY - down[1]) : 0;
      down = null;
      if (held) { held = false; return; }
      if (moved < MOVE_PX) this.app.enterAgent();
    });
    core.addEventListener('pointerenter', () => this.root.classList.add('core-hover'));
    core.addEventListener('pointerleave', () => this.root.classList.remove('core-hover'));
  }

  // Las apps brotan de la nebulosa, con las estrellas de fondo.
  mostrar() {
    if (this.abierto || this.app.mode === 'agent') return;
    this.abierto = true;
    this.box.inert = false;
    this.els.forEach((el) => { el.tabIndex = 0; });
    this.root.classList.add('apps-open');
    this.app.engine?.setStars(true);
    this.app.engine?.pulse(1.3);
    this.crearIconos();
    this.animar(true);
    this.latir();
    this.app.paintState();
  }

  // Vuelven a la nebulosa y el espacio queda limpio otra vez.
  ocultar(instant = false) {
    if (!this.abierto) return;
    this.abierto = false;
    this.box.inert = true;
    this.els.forEach((el) => { el.tabIndex = -1; });
    this.app.engine?.setStars(false);
    if (this.app.panels.ventana) this.app.panels.close();
    this.app.paintState();
    const fin = () => { if (!this.abierto) { this.root.classList.remove('apps-open'); cancelAnimationFrame(this.raf); this.raf = 0; } };
    if (instant || REDUCED.matches) { fin(); return; }
    this.app.engine?.pulse(0.5);
    this.animar(false).then(fin);
  }

  // Salida (o recogida) de las apps desde el centro, escalonada, con un leve desenfoque.
  animar(entrar) {
    if (REDUCED.matches) return Promise.resolve();
    const n = this.els.length;
    const anims = this.els.map((el, i) => {
      const dx = el.style.getPropertyValue('--dx') || '0px', dy = el.style.getPropertyValue('--dy') || '0px';
      const fuera = { opacity: 0, filter: 'blur(6px)', transform: `translate(-50%, -50%) translate(calc(${dx} * -1), calc(${dy} * -1)) scale(0.2)` };
      const dentro = { opacity: 1, filter: 'blur(0px)', transform: 'translate(-50%, -50%)' };
      return el.animate(entrar ? [fuera, dentro] : [dentro, fuera], {
        duration: entrar ? 900 : 520, delay: (entrar ? i : n - 1 - i) * (entrar ? 55 : 30),
        easing: entrar ? EASE : 'cubic-bezier(0.5, 0, 0.75, 0)', fill: 'both',
      });
    });
    for (const el of this.root.querySelectorAll('.home-lines, .home-top, .home-foot')) {
      anims.push(el.animate([{ opacity: entrar ? 0 : 1 }, { opacity: entrar ? 1 : 0 }], { duration: entrar ? 900 : 400, delay: entrar ? 350 : 0, easing: EASE, fill: 'both' }));
    }
    return Promise.all(anims.map((a) => a.finished.catch(() => {}))).then(() => anims.forEach((a) => a.cancel()));
  }

  crearIconos() {
    if (this.iconos.length) return;
    this.iconos = this.els.map((el, i) => new IconoNebulosa(el.querySelector('canvas'), this.apps[i].color || '#86a8ff', seedOf(this.apps[i].id)));
  }

  // El plexo de cada icono gira mientras las apps están a la vista (a unos 30 fps, gasta muy poco).
  latir() {
    if (this.raf) return;
    let last = 0;
    const loop = (now) => {
      if (!this.abierto && !this.root.classList.contains('apps-open')) { this.raf = 0; return; }
      this.raf = requestAnimationFrame(loop);
      if (now - last < 33) return;
      last = now;
      for (const ic of this.iconos) ic.draw(now / 1000);
    };
    this.raf = requestAnimationFrame(loop);
  }

  // Abre una app hija: acción directa, interfaz propia o un panel existente, en una ventana.
  open(a, el) {
    if (a.accion) { a.accion(this.app); return; }
    const from = el?.querySelector('.app-orb')?.getBoundingClientRect();
    this.app.panels.open(a.panel || a.id, { section: a.seccion, app: a, from });
  }

  // Al volver del agente: espacio limpio, solo la nebulosa recomponiéndose y el texto apareciendo.
  arrive() {
    this.ocultar(true);
    for (const el of this.root.querySelectorAll('.home-caption')) {
      el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 900, delay: 450, easing: EASE, fill: 'backwards' });
    }
  }

  hover(i, on) {
    this.lines.querySelectorAll('line')[i]?.classList.toggle('on', on);
    if (this.iconos[i]) this.iconos[i].brillo = on ? 1.35 : 1;
    if (on) this.app.engine?.pulse(0.2);
  }

  // Centro de la nebulosa en pantalla. Las ventanas de las apps flotan encima: no la desplazan.
  center() {
    const w = window.innerWidth, h = window.innerHeight;
    return [w / 2, h / 2, w, h];
  }

  // Las apps van en una elipse alrededor de la nebulosa, repartidas en un arco que deja libre
  // la parte de abajo (ahí va el rótulo del agente) y simétricas respecto a la vertical.
  layout() {
    const [cx, cy, w, h] = this.center();
    const narrow = w < 720;
    const rx = narrow ? w * 0.38 : Math.min(w * 0.36, 560);
    const ry = narrow ? Math.min(h * 0.37, w * 0.95) : Math.min(h * 0.33, 320);
    const n = this.els.length;
    const gap = (80 * Math.PI) / 180;
    const pts = this.els.map((el, i) => {
      const a = Math.PI / 2 + gap / 2 + (i * (2 * Math.PI - gap)) / Math.max(1, n - 1);
      const x = cx + Math.cos(a) * rx, y = cy + Math.sin(a) * ry;
      el.style.left = `${x}px`;
      el.style.top = `${y}px`;
      el.style.setProperty('--dx', `${(x - cx).toFixed(0)}px`);
      el.style.setProperty('--dy', `${(y - cy).toFixed(0)}px`);
      return [x, y];
    });
    // El rótulo del agente cabe justo entre las dos apps de abajo.
    this.root.style.setProperty('--capw', `${Math.max(160, 2 * rx * Math.sin(gap / 2) - (narrow ? 104 : 172))}px`);
    this.root.style.setProperty('--cx', `${cx}px`);
    this.root.style.setProperty('--cy', `${cy}px`);
    // Líneas: del borde de cada app hacia la nebulosa, apagándose antes de tocar el núcleo.
    const inner = Math.min(w, h) * 0.2;
    this.lines.setAttribute('viewBox', `0 0 ${w} ${h}`);
    this.lines.innerHTML = `<defs>${pts.map(([x, y], i) => `<linearGradient id="hl${i}" gradientUnits="userSpaceOnUse" x1="${x}" y1="${y}" x2="${cx}" y2="${cy}">
        <stop offset="0" stop-color="${esc(this.apps[i].color || '#cdd9ff')}" stop-opacity=".3"/><stop offset=".75" stop-color="#cdd9ff" stop-opacity="0"/></linearGradient>`).join('')}</defs>`
      + pts.map(([x, y], i) => {
        const d = Math.hypot(cx - x, cy - y) || 1, ux = (cx - x) / d, uy = (cy - y) / d;
        const end = Math.max(40, d - inner);
        return `<line x1="${(x + ux * 44).toFixed(1)}" y1="${(y + uy * 44).toFixed(1)}" x2="${(x + ux * end).toFixed(1)}" y2="${(y + uy * end).toFixed(1)}" stroke="url(#hl${i})"/>`;
      }).join('');
  }

  // Datos vivos de cada app y el rótulo del agente (estado, en qué trabaja).
  render(s, state) {
    if (!s) return;
    this.apps.forEach((a, i) => {
      const el = this.els[i];
      const sub = a.resumen ? a.resumen(s, this.app) : '';
      el.querySelector('.app-sub').textContent = sub;
      const n = a.insignia ? a.insignia(s) : 0;
      const b = el.querySelector('.app-badge');
      b.hidden = !n;
      b.textContent = n ? String(n) : '';
      el.setAttribute('aria-label', sub ? `${a.nombre}: ${sub}` : a.nombre);
      el.classList.toggle('open', this.app.panels.ventana?.id === a.id);
    });
    const hint = document.getElementById('homeHint');
    const titulo = String(s.sesion?.titulo || '');
    // Con las apps a la vista hay poco sitio entre ellas: guía corta.
    const guia = this.abierto ? (TACTIL ? 'Mantén para recoger' : 'Clic para hablar · mantén para recoger')
      : TACTIL ? 'Toca para hablar · mantén para ver tus apps' : 'Clic para hablar · mantén pulsado para ver tus apps';
    hint.textContent = s.ocupado ? `${state.label}${titulo ? ` · ${titulo.length > 46 ? `${titulo.slice(0, 45)}…` : titulo}` : ''}`
      : state.connected ? guia : 'Sin conexión con Skynet';
    this.root.classList.toggle('busy', !!s.ocupado);
  }
}
