// Launcher: el «espacio» de inicio. En el centro, la nebulosa: la app madre (el agente). Alrededor
// flotan las apps hijas (apps/), unidas a ella por líneas tenues. Pulsar la nebulosa abre el agente;
// cada app se abre en su propia ventana, que sale de su icono.
import { icon } from '../icons.js';
import { esc } from '../md.js';
import { APPS } from './apps/index.js';

const TACTIL = window.matchMedia('(pointer: coarse)').matches;

export class Launcher {
  constructor(app) {
    this.app = app;
    this.apps = APPS;
    this.root = document.getElementById('home');
    this.box = document.getElementById('homeApps');
    this.lines = document.getElementById('homeLines');
    this.box.innerHTML = this.apps.map((a, i) => `
      <button type="button" class="app" data-app="${esc(a.id)}" style="--i:${i};--app:${esc(a.color || '#c9d1e0')}">
        <span class="app-float"><span class="app-orb">${icon(a.icono)}<span class="app-badge" hidden></span></span>
        <span class="app-name">${esc(a.nombre)}</span><span class="app-sub"></span></span>
      </button>`).join('');
    this.els = [...this.box.querySelectorAll('.app')];
    this.els.forEach((el, i) => {
      el.addEventListener('click', () => this.open(this.apps[i], el));
      el.addEventListener('pointerenter', () => this.hover(i, true));
      el.addEventListener('pointerleave', () => this.hover(i, false));
      el.addEventListener('focus', () => this.hover(i, true));
      el.addEventListener('blur', () => this.hover(i, false));
    });
    const core = document.getElementById('homeCore');
    core.addEventListener('click', () => this.app.enterAgent());
    core.addEventListener('pointerenter', () => this.root.classList.add('core-hover'));
    core.addEventListener('pointerleave', () => this.root.classList.remove('core-hover'));
    // Clic en el vacío con una app abierta: se cierra (como pulsar fuera de una ventana).
    this.root.addEventListener('click', (e) => {
      if (this.app.panels.current && !e.target.closest('.app, .home-core, .home-top')) this.app.panels.close();
    });
    window.addEventListener('resize', () => this.layout());
    this.layout();
  }

  // Abre una app hija: acción directa, interfaz propia o un panel existente, en una ventana.
  open(a, el) {
    if (a.accion) { a.accion(this.app); return; }
    const from = el?.querySelector('.app-orb')?.getBoundingClientRect();
    this.app.panels.open(a.panel || a.id, { section: a.seccion, app: a, from });
  }

  // Al volver del agente: las apps llegan desde la nebulosa y lo demás aparece despacio.
  // (Con la API de animaciones: cambiar la animación CSS la reiniciaría y parpadearían.)
  arrive() {
    const easing = 'cubic-bezier(0.22, 1, 0.36, 1)';
    this.els.forEach((el, i) => {
      const dx = el.style.getPropertyValue('--dx') || '0px', dy = el.style.getPropertyValue('--dy') || '0px';
      el.animate([
        { opacity: 0, filter: 'blur(4px)', transform: `translate(-50%, -50%) translate(calc(${dx} * -0.85), calc(${dy} * -0.85)) scale(0.4)` },
        { opacity: 1, filter: 'blur(0px)', transform: 'translate(-50%, -50%)' },
      ], { duration: 1100, delay: 100 + i * 50, easing, fill: 'backwards' });
    });
    for (const el of this.root.querySelectorAll('.home-top, .home-caption, .home-foot, .home-lines')) {
      el.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 900, delay: 450, easing, fill: 'backwards' });
    }
  }

  hover(i, on) {
    this.lines.querySelectorAll('line')[i]?.classList.toggle('on', on);
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
    const inner = Math.min(w, h) * 0.17;
    this.lines.setAttribute('viewBox', `0 0 ${w} ${h}`);
    this.lines.innerHTML = `<defs>${pts.map(([x, y], i) => `<linearGradient id="hl${i}" gradientUnits="userSpaceOnUse" x1="${x}" y1="${y}" x2="${cx}" y2="${cy}">
        <stop offset="0" stop-color="${esc(this.apps[i].color || '#cdd9ff')}" stop-opacity=".38"/><stop offset=".75" stop-color="#cdd9ff" stop-opacity="0"/></linearGradient>`).join('')}</defs>`
      + pts.map(([x, y], i) => {
        const d = Math.hypot(cx - x, cy - y) || 1, ux = (cx - x) / d, uy = (cy - y) / d;
        const end = Math.max(40, d - inner);
        return `<line x1="${(x + ux * 38).toFixed(1)}" y1="${(y + uy * 38).toFixed(1)}" x2="${(x + ux * end).toFixed(1)}" y2="${(y + uy * end).toFixed(1)}" stroke="url(#hl${i})"/>`;
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
    hint.textContent = s.ocupado ? `${state.label}${titulo ? ` · ${titulo.length > 46 ? `${titulo.slice(0, 45)}…` : titulo}` : ''}`
      : state.connected ? (TACTIL ? 'Toca la nebulosa para hablar' : 'Pulsa la nebulosa para hablar') : 'Sin conexión con Skynet';
    this.root.classList.toggle('busy', !!s.ocupado);
  }
}
