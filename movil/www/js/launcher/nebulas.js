// Iconos de las apps: cada una es una pequeña nebulosa como la del agente (luz solo en el centro, el
// resto gas difuminado, redonda) en un tono suave de su color, envuelta en una esfera de plexo que gira
// despacio: nodos unidos por líneas finas, como un holograma de datos.
// La nebulosa se dibuja una vez (canvas 2D, luz aditiva); el plexo se anima solo mientras se ve.

function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gauss(rand) {
  let u = 0, v = 0;
  while (u === 0) u = rand();
  while (v === 0) v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

const hex = (h) => { const n = parseInt(String(h).slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const mix = (a, b, t) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const WHITE = [255, 255, 255];

export function seedOf(id) {
  let seed = 7;
  for (const ch of String(id)) seed = (seed * 31 + ch.charCodeAt(0)) | 0;
  return seed;
}

const cache = new Map();

// Nebulosa pequeña (imagen estática). color: el acento de la app; se suaviza hacia el blanco.
export function nebulaIcon(color, semilla, size = 176) {
  const key = `${color}|${semilla}|${size}`;
  if (cache.has(key)) return cache.get(key);
  const rand = mulberry32(semilla);
  const base = hex(color);
  const tinte = mix(base, WHITE, 0.3);
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const ctx = cv.getContext('2d');
  const c = size / 2, R = size * 0.42;
  ctx.globalCompositeOperation = 'lighter';
  const nube = (x, y, rad, col, a) => {
    const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
    g.addColorStop(0, rgba(col, a)); g.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = g; ctx.fillRect(x - rad, y - rad, rad * 2, rad * 2);
  };
  // Gas: nubes tenues, más densas cerca del centro y deshilachadas hacia fuera (no simétricas).
  for (let i = 0; i < 46; i++) {
    const th = rand() * Math.PI * 2, r = R * Math.min(0.85, Math.abs(gauss(rand)) * 0.34);
    nube(c + Math.cos(th) * r, c + Math.sin(th) * r, R * (0.18 + rand() * 0.3), tinte, 0.05 + rand() * 0.05);
  }
  // Grano: partículas como las de la nebulosa grande, casi todas cerca del núcleo.
  const n = Math.round(size * 7);
  for (let i = 0; i < n; i++) {
    const th = rand() * Math.PI * 2;
    const r = R * Math.min(1, Math.abs(gauss(rand)) * (rand() < 0.75 ? 0.22 : 0.45));
    const k = r / R;
    const s = 0.5 + rand() * 0.9;
    ctx.fillStyle = rgba(mix(WHITE, tinte, Math.min(1, k * 2.2)), (0.5 - k * 0.42) * (0.4 + rand() * 0.6));
    ctx.fillRect(c + Math.cos(th) * r - s / 2, c + Math.sin(th) * r - s / 2, s, s);
  }
  // Núcleo: la única parte brillante.
  let g = ctx.createRadialGradient(c, c, 0, c, c, R * 0.42);
  g.addColorStop(0, 'rgba(255,255,255,0.95)'); g.addColorStop(0.18, rgba(mix(WHITE, tinte, 0.35), 0.55));
  g.addColorStop(0.55, rgba(tinte, 0.12)); g.addColorStop(1, rgba(tinte, 0));
  ctx.fillStyle = g; ctx.fillRect(0, 0, size, size);
  // Resplandor y bordes fundidos.
  const glow = document.createElement('canvas');
  glow.width = glow.height = size;
  const gx = glow.getContext('2d');
  gx.filter = `blur(${Math.max(2, size / 40)}px)`;
  gx.drawImage(cv, 0, 0);
  ctx.globalAlpha = 0.6; ctx.drawImage(glow, 0, 0); ctx.globalAlpha = 1;
  ctx.globalCompositeOperation = 'destination-in';
  g = ctx.createRadialGradient(c, c, size * 0.28, c, c, size * 0.5);
  g.addColorStop(0, '#000'); g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, size, size);
  const url = cv.toDataURL('image/png');
  cache.set(key, { url, canvas: cv });
  return cache.get(key);
}

// Icono vivo: la nebulosa + una esfera de plexo que gira alrededor de un eje inclinado propio.
export class IconoNebulosa {
  constructor(canvas, color, semilla) {
    this.cv = canvas;
    this.ctx = canvas.getContext('2d');
    const pr = Math.min(window.devicePixelRatio || 1, 2);
    const css = canvas.clientWidth || 136;
    canvas.width = canvas.height = Math.round(css * pr);
    this.size = canvas.width;
    this.base = nebulaIcon(color, semilla, this.size).canvas;
    this.linea = mix(hex(color), WHITE, 0.55);
    const rand = mulberry32(semilla ^ 0x9e3779b9);
    // Nodos en la esfera (Fibonacci con desorden) y sus 3 vecinos más cercanos.
    const N = 26, golden = Math.PI * (3 - Math.sqrt(5));
    this.nodos = Array.from({ length: N }, (_, i) => {
      const y = 1 - (2 * (i + 0.5)) / N, r = Math.sqrt(1 - y * y), th = golden * i + (rand() - 0.5) * 0.7;
      const k = 0.92 + rand() * 0.16;
      return [Math.cos(th) * r * k, y * k, Math.sin(th) * r * k];
    });
    const seen = new Set();
    this.aristas = [];
    this.nodos.forEach((a, i) => {
      this.nodos.map((b, j) => [(a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2, j]).filter(([, j]) => j !== i)
        .sort((x, y) => x[0] - y[0]).slice(0, 3).forEach(([, j]) => {
          const key = i < j ? `${i}-${j}` : `${j}-${i}`;
          if (!seen.has(key)) { seen.add(key); this.aristas.push([i, j]); }
        });
    });
    this.tilt = 0.35 + rand() * 0.5;
    this.vel = (0.12 + rand() * 0.1) * (rand() < 0.5 ? -1 : 1);
    this.fase = rand() * Math.PI * 2;
    this.brillo = 1;
    this.draw(0);
  }

  draw(t) {
    const { ctx, size } = this;
    const c = size / 2, R = size * 0.3;
    ctx.globalCompositeOperation = 'source-over';
    ctx.clearRect(0, 0, size, size);
    ctx.globalAlpha = this.brillo;
    ctx.drawImage(this.base, 0, 0);
    // Proyección: giro alrededor de Y y luego inclinación sobre X; la profundidad atenúa.
    const a = this.fase + t * this.vel, ca = Math.cos(a), sa = Math.sin(a), ct = Math.cos(this.tilt), st = Math.sin(this.tilt);
    const p = this.nodos.map(([x, y, z]) => {
      const x1 = x * ca + z * sa, z1 = -x * sa + z * ca;
      const y2 = y * ct - z1 * st, z2 = y * st + z1 * ct;
      const persp = 1 / (1.9 - z2 * 0.35);
      return [c + x1 * R * persp * 1.9, c + y2 * R * persp * 1.9, (z2 + 1) / 2];
    });
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineWidth = Math.max(0.6, size / 220);
    for (const [i, j] of this.aristas) {
      const d = (p[i][2] + p[j][2]) / 2;
      ctx.strokeStyle = rgba(this.linea, (0.05 + d * 0.22) * this.brillo);
      ctx.beginPath(); ctx.moveTo(p[i][0], p[i][1]); ctx.lineTo(p[j][0], p[j][1]); ctx.stroke();
    }
    for (const [x, y, d] of p) {
      const s = (0.8 + d * 1.4) * (size / 136);
      ctx.fillStyle = rgba(this.linea, (0.2 + d * 0.6) * this.brillo);
      ctx.fillRect(x - s / 2, y - s / 2, s, s);
    }
    ctx.globalAlpha = 1;
  }
}
