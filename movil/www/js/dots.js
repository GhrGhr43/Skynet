// Fondo del modo agente: una rejilla de puntos casi invisible. Alrededor del cursor se aviva un poco
// y cada clic lanza una onda que tiñe de azul los puntos que toca. Solo dibuja mientras algo se mueve:
// en reposo no gasta nada (la GPU es del modelo local).
const GAP = 22;
const RIPPLE_SPEED = 520;   // px/s
const RIPPLE_LIFE = 1.15;   // s
const NEAR = 130;           // radio de la luz del cursor (px)

export class Dots {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.ripples = [];
    this.mouse = null;
    this.lastMove = 0;
    this.on = false;
    this.raf = 0;
    this.color = [134, 168, 255];
    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.addEventListener('resize', () => this.resize());
    window.addEventListener('pointermove', (e) => {
      if (!this.on || e.pointerType === 'touch') return;
      this.mouse = [e.clientX, e.clientY];
      this.lastMove = performance.now();
      this.kick();
    }, { passive: true });
    window.addEventListener('pointerdown', (e) => {
      if (!this.on || this.reduced) return;
      this.ripples.push({ x: e.clientX, y: e.clientY, t0: performance.now() });
      if (this.ripples.length > 5) this.ripples.shift();
      this.kick();
    }, { passive: true });
    document.addEventListener('pointerleave', () => { this.mouse = null; this.kick(); });
    this.resize();
  }

  // El color de acento sigue al estado del agente (azul en reposo, violeta trabajando...).
  setAccent(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
    if (!m) return;
    const n = parseInt(m[1], 16);
    this.color = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    this.kick();
  }

  start() { this.on = true; this.resize(); }
  stop() { this.on = false; this.ripples = []; this.mouse = null; cancelAnimationFrame(this.raf); this.raf = 0; }

  resize() {
    const pr = Math.min(window.devicePixelRatio || 1, 2);
    this.pr = pr;
    this.w = window.innerWidth; this.h = window.innerHeight;
    this.canvas.width = Math.round(this.w * pr);
    this.canvas.height = Math.round(this.h * pr);
    this.kick();
  }

  kick() {
    if (this.on && !this.raf) this.raf = requestAnimationFrame(() => this.draw());
  }

  // Zona de lectura (la columna de la conversación): ahí los puntos se apagan más.
  readingBox() {
    const el = document.querySelector('.convo-inner');
    const r = el && el.offsetParent ? el.getBoundingClientRect() : null;
    return r && r.width ? [r.left + 12, r.right - 12] : null;
  }

  draw() {
    this.raf = 0;
    if (!this.on) return;
    const { ctx, pr, w, h } = this;
    const now = performance.now();
    ctx.setTransform(pr, 0, 0, pr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    this.ripples = this.ripples.filter((r) => (now - r.t0) / 1000 < RIPPLE_LIFE);
    // La luz del cursor se apaga suavemente si deja de moverse.
    const fade = Math.max(0, Math.min(1, (1500 - (now - this.lastMove)) / 600));
    const mouse = this.mouse && fade > 0 ? this.mouse : null;
    const read = this.readingBox();
    const [cr, cg, cb] = this.color;
    const ox = (w % GAP) / 2, oy = (h % GAP) / 2;
    for (let y = oy; y < h; y += GAP) {
      for (let x = ox; x < w; x += GAP) {
        let a = 0.11, glow = 0;
        if (read && x > read[0] && x < read[1]) a = 0.05;
        if (mouse) {
          const d = Math.hypot(x - mouse[0], y - mouse[1]);
          if (d < NEAR) glow = Math.max(glow, (1 - d / NEAR) ** 2 * 0.55 * fade);
        }
        for (const r of this.ripples) {
          const age = (now - r.t0) / 1000;
          const radius = age * RIPPLE_SPEED;
          const d = Math.hypot(x - r.x, y - r.y);
          const band = Math.exp(-(((d - radius) / 34) ** 2));
          glow = Math.max(glow, band * (1 - age / RIPPLE_LIFE) ** 1.5);
        }
        if (glow > 0.02) {
          ctx.fillStyle = `rgba(${cr},${cg},${cb},${Math.min(0.95, 0.12 + glow)})`;
          const s = 1.4 + glow * 1.6;
          ctx.fillRect(x - s / 2, y - s / 2, s, s);
        } else {
          ctx.fillStyle = `rgba(255,255,255,${a})`;
          ctx.fillRect(x - 0.7, y - 0.7, 1.4, 1.4);
        }
      }
    }
    // Sigue animando mientras haya ondas o el cursor se haya movido hace poco (para apagar la luz suave).
    if (this.ripples.length || (this.mouse && now - this.lastMove < 1600)) this.kick();
  }
}
