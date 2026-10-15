// Iconos de las apps: cada una es una pequeña nebulosa planetaria (como la de la Hélice) con su
// propia paleta: un «ojo» de color en el centro, una envoltura filamentosa y un borde más intenso,
// con nudos que dejan estelas hacia dentro. Se dibujan una vez en un canvas 2D (luz aditiva) y se
// usan como imagen: no cuestan nada mientras están en pantalla.

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

// Ruido de valor 2D periódico en el ángulo: la envoltura no tiene costura.
function angularNoise(rand, n = 24) {
  const g = Array.from({ length: n }, () => rand());
  const s = (t) => t * t * (3 - 2 * t);
  const at = (x) => { const i = Math.floor(x), f = x - i; const a = g[((i % n) + n) % n], b = g[(((i + 1) % n) + n) % n]; return a + (b - a) * s(f); };
  return (th, oct = 3) => {
    let v = 0, amp = 0.55, f = n / (2 * Math.PI);
    for (let o = 0; o < oct; o++) { v += at(th * f + o * 7.3) * amp; amp *= 0.5; f *= 2; }
    return v / 0.9625;
  };
}

const hex = (h) => { const n = parseInt(h.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; };
const mix = (a, b, t) => a.map((x, i) => Math.round(x + (b[i] - x) * t));
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

const cache = new Map();

// paleta: { ojo, capa, borde } en hex. semilla: número estable por app (misma forma en cada carga).
export function nebulaIcon(paleta, semilla, size = 176) {
  const key = `${paleta.ojo}|${paleta.capa}|${paleta.borde}|${semilla}|${size}`;
  if (cache.has(key)) return cache.get(key);
  const rand = mulberry32(semilla);
  const noise = angularNoise(rand);
  const ojo = hex(paleta.ojo), capa = hex(paleta.capa), borde = hex(paleta.borde);
  const cv = document.createElement('canvas');
  cv.width = cv.height = size;
  const ctx = cv.getContext('2d');
  const c = size / 2, R = size * 0.27, squash = 0.84 + rand() * 0.1, rot = rand() * Math.PI;
  const at = (r, th) => {
    const x = Math.cos(th) * r, y = Math.sin(th) * r * squash;
    return [c + x * Math.cos(rot) - y * Math.sin(rot), c + x * Math.sin(rot) + y * Math.cos(rot)];
  };
  ctx.globalCompositeOperation = 'lighter';
  // Un lado más luminoso que otro (como en las fotos reales): nada es perfectamente simétrico.
  const lado = rand() * Math.PI * 2;
  const luz = (th) => 0.55 + 0.45 * (0.5 + 0.5 * Math.cos(th - lado));
  // Nube suave: un círculo con degradado radial (el gas), en vez de un punto duro.
  const nube = (x, y, rad, col, a) => {
    const gr = ctx.createRadialGradient(x, y, 0, x, y, rad);
    gr.addColorStop(0, rgba(col, a)); gr.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = gr; ctx.fillRect(x - rad, y - rad, rad * 2, rad * 2);
  };
  // Forma irregular: el radio de la envoltura varía despacio con el ángulo.
  const radio = (th) => R * (1 + (noise(th, 2) - 0.5) * 0.42);

  // Halo exterior del color del borde, en nubes amplias y tenues (el gas que se escapa).
  for (let i = 0; i < 70; i++) {
    const th = rand() * Math.PI * 2;
    const [x, y] = at(radio(th) * (1.15 + Math.abs(gauss(rand)) * 0.35), th);
    nube(x, y, R * (0.35 + rand() * 0.4), borde, 0.05 * luz(th));
  }
  // Ojo: más oscuro en el centro y más luminoso hacia la cara interna de la envoltura.
  let g = ctx.createRadialGradient(c, c, 0, c, c, R * 1.02);
  g.addColorStop(0, rgba(ojo, 0.12)); g.addColorStop(0.55, rgba(ojo, 0.22)); g.addColorStop(0.85, rgba(mix(ojo, capa, 0.35), 0.32));
  g.addColorStop(1, rgba(ojo, 0));
  ctx.fillStyle = g; ctx.fillRect(0, 0, size, size);

  // Envoltura: primero el gas (nubes), luego el grano fino con filamentos. Del color de la capa
  // por dentro al del borde por fuera.
  const color = (r, th) => mix(capa, borde, Math.min(1, Math.max(0, (r / radio(th) - 0.9) * 2.4)));
  for (let i = 0; i < 260; i++) {
    const th = rand() * Math.PI * 2;
    const r = radio(th) * (1 + gauss(rand) * 0.13);
    const [x, y] = at(r, th);
    nube(x, y, R * (0.12 + rand() * 0.16), color(r, th), 0.11 * luz(th) * (0.5 + noise(th * 2 + 5)));
  }
  const pts = Math.round(size * size * 0.06);
  for (let i = 0; i < pts; i++) {
    const th = rand() * Math.PI * 2;
    const r = radio(th) * (1 + gauss(rand) * 0.12);
    const fil = Math.pow(noise(th * 4 + 11), 3);
    if (rand() > 0.2 + fil * 1.1) continue;
    const [x, y] = at(r, th);
    const s = 0.6 + rand() * 0.9;
    ctx.fillStyle = rgba(color(r, th), (0.12 + fil * 0.45) * luz(th));
    ctx.fillRect(x - s / 2, y - s / 2, s, s);
  }
  // Unos pocos nudos cometarios: estelas cortas y suaves hacia el centro.
  for (let i = 0; i < 22; i++) {
    const th = rand() * Math.PI * 2;
    const r0 = radio(th) * (0.86 + rand() * 0.08), r1 = r0 - R * (0.08 + rand() * 0.12);
    const [x0, y0] = at(r0, th), [x1, y1] = at(r1, th);
    const lg = ctx.createLinearGradient(x0, y0, x1, y1);
    lg.addColorStop(0, rgba(mix(capa, [255, 255, 255], 0.25), 0.3 * luz(th))); lg.addColorStop(1, rgba(ojo, 0));
    ctx.strokeStyle = lg; ctx.lineWidth = 0.8;
    ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
  }

  // Resplandor: una copia desenfocada encima, como el bloom de la nebulosa grande.
  const glow = document.createElement('canvas');
  glow.width = glow.height = size;
  const gx = glow.getContext('2d');
  gx.filter = `blur(${Math.max(3, size / 30)}px)`;
  gx.drawImage(cv, 0, 0);
  ctx.globalAlpha = 0.7;
  ctx.drawImage(glow, 0, 0);
  ctx.globalAlpha = 1;
  // Bordes del lienzo fundidos a transparente: el halo nunca se corta en cuadrado.
  ctx.globalCompositeOperation = 'destination-in';
  g = ctx.createRadialGradient(c, c, size * 0.3, c, c, size * 0.5);
  g.addColorStop(0, 'rgba(0,0,0,1)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, size, size);
  ctx.globalCompositeOperation = 'lighter';

  // Estrellas de campo dentro del icono: dos o tres puntos nítidos, nada más.
  for (let i = 0; i < 3; i++) {
    const [x, y] = at(R * (0.3 + rand() * 1.3), rand() * Math.PI * 2);
    ctx.fillStyle = 'rgba(255,255,255,0.8)';
    ctx.fillRect(x, y, 1.2, 1.2);
  }
  const url = cv.toDataURL('image/png');
  cache.set(key, url);
  return url;
}
