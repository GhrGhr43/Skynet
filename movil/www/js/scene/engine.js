// Escena: cámara, render con bloom, estados visuales del agente y el bucle de animación.
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { ShaderPass } from 'three/addons/postprocessing/ShaderPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { Nebula } from './nebula.js';
import { Stars } from './stars.js';
import { Glyphs } from './glyphs.js';
import { Satellites } from './satellites.js';
import { Plexus } from './plexus.js';

// Contenedores de la maqueta que dejan ver la escena (el ratón sobre ellos mueve la nebulosa).
const SCENE_THROUGH = '.home, .home-core, .home-top, .home-caption, .home-caption *, .home-apps, .home-lines';

// Cada estado del agente es una "personalidad" de la nube: color, turbulencia, giro...
export const STATES = {
  reposo:       { label: 'En espera',                tint: '#d4e0ff', accent: '#86a8ff', turb: 0.35, spin: 0.05, breath: 1.0, glyphRate: 0.35, glyphGain: 0.16, bloom: 0.8,  size: 11 },
  pensando:     { label: 'Pensando',                 tint: '#9fceff', accent: '#3a9dff', turb: 1.05, spin: 0.20, breath: 1.7, glyphRate: 3.0,  glyphGain: 0.40, bloom: 0.95, size: 11.5 },
  herramienta:  { label: 'Trabajando',               tint: '#c2b2ff', accent: '#9b78ff', turb: 0.8,  spin: 0.15, breath: 1.3, glyphRate: 2.0,  glyphGain: 0.32, bloom: 0.95, size: 11.5 },
  esperando:    { label: 'Esperando tu confirmación', tint: '#ffd6a3', accent: '#ffa63d', turb: 0.22, spin: 0.02, breath: 2.8, glyphRate: 0.2,  glyphGain: 0.14, bloom: 0.9,  size: 11 },
  verificando:  { label: 'Verificando',              tint: '#a6f3e1', accent: '#2fe3bd', turb: 0.5,  spin: 0.10, breath: 1.0, glyphRate: 1.2,  glyphGain: 0.26, bloom: 0.9,  size: 15, scan: 1 },
  exito:        { label: 'Hecho',                    tint: '#d3ffe6', accent: '#5bffaa', turb: 0.3,  spin: 0.08, breath: 1.0, glyphRate: 0.5,  glyphGain: 0.2,  bloom: 1.1,  size: 11.5 },
  error:        { label: 'Algo falló',               tint: '#ffbcc3', accent: '#ff4558', turb: 0.6,  spin: 0.04, breath: 1.0, glyphRate: 0.8,  glyphGain: 0.2,  bloom: 0.9,  size: 15, jitter: 1 },
  desconectado: { label: 'Sin conexión con JARVIS',  tint: '#7d838e', accent: '#4c525c', turb: 0.15, spin: 0.01, breath: 0.4, glyphRate: 0.05, glyphGain: 0.06, bloom: 0.5,  size: 10 },
};

export const QUALITY = { baja: 192, media: 320, alta: 448, ultra: 576 };

const GRADE = {
  uniforms: {
    tDiffuse: { value: null },
    uRes: { value: new THREE.Vector2(1, 1) },
    uTime: { value: 0 },
    uCA: { value: 0.012 },
    uVignette: { value: 1 },
    uGrain: { value: 0.07 },
  },
  vertexShader: /* glsl */ `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse; uniform vec2 uRes; uniform float uTime; uniform float uCA; uniform float uVignette; uniform float uGrain;
    varying vec2 vUv;
    float hash(vec2 p){ p = fract(p * vec2(443.897, 441.423)); p += dot(p, p.yx + 19.19); return fract((p.x + p.y) * p.x); }
    void main(){
      vec2 c = vUv - 0.5;
      float r2 = dot(c, c);
      vec2 off = c * r2 * uCA;
      vec3 col = vec3(texture2D(tDiffuse, vUv - off).r, texture2D(tDiffuse, vUv).g, texture2D(tDiffuse, vUv + off).b);
      col *= mix(1.0, 0.45, smoothstep(0.08, 0.55, r2) * uVignette);
      float lum = dot(col, vec3(0.2126, 0.7152, 0.0722));
      float n = hash(vUv * uRes + fract(uTime * 7.31) * 100.0) - 0.5;
      col += n * uGrain * lum;              // grano solo donde hay luz: el negro sigue siendo negro OLED
      col = max(col - 0.0025, 0.0);         // aplasta el casi-negro del bloom: fondo negro puro
      gl_FragColor = vec4(col, 1.0);
    }`,
};

const ease = (k, dt) => 1 - Math.exp(-k * dt);

export class Engine {
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: false, powerPreference: 'high-performance' });
    renderer.setClearColor(0x000000, 1);
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    this.renderer = renderer;
    this.maxPR = Math.min(window.devicePixelRatio || 1, 2);
    this.pr = this.maxPR;
    renderer.setPixelRatio(this.pr);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(38, 1, 0.1, 400);
    this.camera.position.set(0, 0, 7.4);

    this.quality = opts.quality || 'alta';
    this.nebula = new Nebula(renderer, QUALITY[this.quality] || QUALITY.alta);
    this.stars = new Stars(window.innerWidth < 700 ? 1400 : 2600);
    this.glyphs = new Glyphs(window.innerWidth < 700 ? 260 : 520);
    this.sats = new Satellites();
    // Sin satélites en órbita (decisión de diseño: nada de orbitales); el objeto se conserva por la API.
    this.plexus = new Plexus(window.innerWidth < 700 ? 64 : 90, 2.05, { baja: 0.4, media: 0.55, alta: 0.85, ultra: 1 }[this.quality] ?? 0.85);
    this.scene.add(this.stars.points, this.nebula.points, this.glyphs.points, this.plexus.group);

    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.8, 0.55, 0.08);
    composer.addPass(this.bloom);
    this.grade = new ShaderPass(GRADE);
    composer.addPass(this.grade);
    composer.addPass(new OutputPass());
    this.composer = composer;

    // Parámetros visuales: valor actual (p) que persigue suavemente al objetivo del estado.
    this.stateName = 'reposo';
    this.flash = null;
    const s = STATES.reposo;
    this.p = {
      tint: new THREE.Color(s.tint), accent: new THREE.Color(s.accent), core: new THREE.Color(1, 1, 1),
      turb: s.turb, spin: s.spin, breath: s.breath, glyphRate: s.glyphRate, glyphGain: s.glyphGain,
      bloom: s.bloom, size: s.size, scanAmp: 0, scanY: 99, jitter: 0,
      spring: 0.6, damp: 2.2, pointer: 0, rayO: new THREE.Vector3(0, 0, 100), rayD: new THREE.Vector3(0, 0, -1),
      mouseVel: new THREE.Vector3(), pulseR: 99, pulseAmp: 0, intro: 0, starGain: 0, burst: 0,
    };
    // Explosión (entrar al agente) y reformado (volver al inicio).
    this.springT0 = 0;
    this.springRamp = 4;
    this.burstUntil = 0;
    this.zoom = 0;
    this.zoomTarget = 0;
    this.bloomBoost = 0;
    this.paused = false;
    this.starsOn = false;  // estrellas de fondo: solo con las apps a la vista
    this.pulses = [];
    this.satCount = 0;
    this.shift = 0;
    this.shiftTarget = 0;

    // Cursor
    this.mouse = new THREE.Vector2(0, 0);
    this.mouseSmooth = new THREE.Vector2(0, 0);
    this.overScene = false;
    this.lastMove = 0;
    this.speedBoost = 0;
    this.raycaster = new THREE.Raycaster();
    this.plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    this.prevHit = null;
    this.hit = new THREE.Vector3();
    window.addEventListener('pointermove', (e) => this.onPointer(e), { passive: true });
    window.addEventListener('pointerdown', (e) => {
      // En el móvil no hay «pasar por encima»: el dedo aparece de golpe. Se coloca el cursor ahí mismo
      // (sin barrido desde la posición anterior) y arrastrarlo deforma la nebulosa como el ratón.
      if (e.pointerType !== 'mouse') {
        this.onPointer(e);
        this.mouseSmooth.copy(this.mouse);
        this.prevHit = null;
        this.lastTouch = [e.clientX, e.clientY];
      }
      if (!this.paused && this.isScene(e.target)) this.pulse(0.9);
    });
    const release = (e) => { if (e.pointerType !== 'mouse') { this.overScene = false; this.lastTouch = null; } };
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
    document.addEventListener('pointerleave', () => { this.overScene = false; });
    window.addEventListener('blur', () => { this.overScene = false; });
    window.addEventListener('resize', () => this.resize());

    this.reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.clock = new THREE.Clock();
    this.t = 0;
    this.frames = [];
    this.resize();
    this.onFps = null;
    renderer.setAnimationLoop(() => this.frame());
  }

  onPointer(e) {
    this.mouse.set((e.clientX / window.innerWidth) * 2 - 1, -(e.clientY / window.innerHeight) * 2 + 1);
    this.overScene = this.isScene(e.target);
    this.lastMove = performance.now();
    // movementX no siempre existe con el dedo: se calcula a partir del punto anterior.
    let mx = e.movementX || 0, my = e.movementY || 0;
    if (e.pointerType !== 'mouse' && this.lastTouch) {
      mx = e.clientX - this.lastTouch[0]; my = e.clientY - this.lastTouch[1];
      this.lastTouch = [e.clientX, e.clientY];
    }
    this.speedBoost = Math.min(1.6, this.speedBoost + Math.hypot(mx, my) * 0.012);
  }

  // La interfaz tapa el lienzo: los huecos vacíos de la maqueta (no botones ni mensajes)
  // cuentan como escena, para que la nebulosa siga reaccionando al cursor.
  isScene(el) {
    return el === this.canvas || !!el?.matches?.(SCENE_THROUGH);
  }

  resize() {
    // Nunca 0×0 (pestaña oculta al cargar): la proporción 0/0 metería NaN en la simulación para siempre.
    const w = Math.max(1, window.innerWidth), h = Math.max(1, window.innerHeight);
    this.w = w; this.h = h;
    this.renderer.setPixelRatio(this.pr);
    this.renderer.setSize(w, h, false);
    this.composer.setPixelRatio(this.pr);
    this.composer.setSize(w, h);
    this.camera.aspect = w / h;
    // En pantallas estrechas la nube se aleja un poco para que quepa entera.
    // En el móvil (muy vertical) aún más lejos: deja sitio a las herramientas alrededor.
    this.baseZ = w / h < 0.6 ? 19 : w / h < 0.9 ? 15.5 : 11.5;
    this.applyViewOffset();
    this.grade.uniforms.uRes.value.set(w * this.pr, h * this.pr);
    for (const o of [this.nebula, this.stars, this.glyphs, this.sats]) o.setPixelRatio(this.pr);
  }

  applyViewOffset() {
    const w = this.w, h = this.h;
    if (Math.abs(this.shift) < 0.5) this.camera.clearViewOffset();
    else this.camera.setViewOffset(w, h, -this.shift, 0, w, h);
    this.camera.updateProjectionMatrix();
  }

  // Desplaza la nebulosa (px) para que quede centrada en el hueco libre que dejan los paneles.
  setFocusShift(px) {
    this.shiftTarget = px;
  }

  // Estado de fondo (lo que está haciendo el agente).
  setState(name) {
    if (STATES[name]) this.stateName = name;
  }

  // Estado momentáneo encima del de fondo (un "Hecho" o un error durante unos segundos).
  flashState(name, secs = 2) {
    if (STATES[name]) this.flash = { name, until: this.t + secs };
  }

  get activeState() {
    return this.flash ? this.flash.name : this.stateName;
  }

  pulse(amp = 1) {
    this.pulses.push({ t0: this.t, amp });
    if (this.pulses.length > 4) this.pulses.shift();
  }

  setStars(on) {
    this.starsOn = !!on;
  }

  setSatellites(n) {
    this.satCount = n;
  }

  // La nebulosa estalla: empuje radial, muelle flojo, destello y la cámara se mete dentro.
  explode() {
    this.p.burst = 46;
    this.burstUntil = this.t + 1.1;
    this.zoomTarget = -6.5;
    this.bloomBoost = 0.55;
    this.pulse(2.2);
  }

  // Vuelve a condensarse: el muelle se endurece poco a poco, como en la intro.
  reform() {
    this.p.burst = 0;
    this.burstUntil = 0;
    this.springT0 = this.t;
    this.springRamp = 2.2;              // más rápido que la intro: vuelve a casa, no nace
    this.zoomTarget = 0;
    this.zoom = Math.max(this.zoom, -2.5);
    this.pulse(0.6);
  }

  // Sin dibujar nada (modo agente): la GPU queda libre para el modelo local.
  pause() {
    if (this.paused) return;
    this.paused = true;
    this.renderer.setAnimationLoop(null);
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.clock.getDelta();  // que el salto de tiempo en pausa no cuente como un frame larguísimo
    this.renderer.setAnimationLoop(() => this.frame());
  }

  // Avanza la simulación sin dibujar (pruebas y capturas: salta la intro).
  warmup(seconds, step = 1 / 60) {
    for (let i = 0; i < seconds / step; i++) this.frame(step, false);
  }

  frame(fixedDt = null, draw = true) {
    const dtRaw = fixedDt ?? this.clock.getDelta();
    this.frameCount = (this.frameCount || 0) + 1;
    const dt = Math.min(dtRaw, 1 / 20);
    this.t += dt;
    const t = this.t, p = this.p;

    if (this.flash && t >= this.flash.until) this.flash = null;
    const S = STATES[this.activeState];
    const k = ease(2.2, dt), kc = ease(3.0, dt);
    p.tint.lerp(new THREE.Color(S.tint), kc);
    p.accent.lerp(new THREE.Color(S.accent), kc);
    const motion = this.reduced ? 0.4 : 1;
    for (const key of ['turb', 'spin', 'breath', 'glyphRate', 'glyphGain', 'bloom', 'size']) {
      const target = key === 'turb' || key === 'spin' ? S[key] * motion : S[key];
      p[key] += (target - p[key]) * k;
    }
    p.scanAmp += ((S.scan ? 1.4 : 0) - p.scanAmp) * k;
    p.scanY = p.scanAmp > 0.01 ? Math.sin(t * 1.7) * 1.5 : 99;
    p.jitter += ((S.jitter ? 2.2 : 0) - p.jitter) * ease(6, dt);

    // Intro: aparece y se condensa; el muelle se endurece poco a poco.
    p.intro = Math.min(1, t / 2.2);
    // El inicio es limpio: las estrellas aparecen despacio solo cuando se muestran las apps.
    const starTarget = (this.starsOn ? 1 : 0) * (this.activeState === 'desconectado' ? 0.5 : 1);
    p.starGain += (starTarget - p.starGain) * ease(this.starsOn ? 1.4 : 2.2, dt);
    const springTarget = 7.5, st = t - this.springT0;
    const ramp = this.springRamp;
    p.spring = st < ramp ? 0.6 + (springTarget - 0.6) * Math.pow(st / ramp, 2) : springTarget;
    p.damp = 2.2;
    if (t < this.burstUntil) { p.spring = 0.12; p.damp = 0.5; }
    p.burst *= Math.exp(-2.6 * dt);
    this.bloomBoost *= Math.exp(-2.2 * dt);
    this.zoom += (this.zoomTarget - this.zoom) * ease(this.zoomTarget < this.zoom ? 2.4 : 1.6, dt);
    // Latido cuando espera confirmación.
    if (this.activeState === 'esperando') p.breath = 2.4 + Math.pow(Math.max(0, Math.sin(t * 2.6)), 12) * 4;

    // Cursor -> rayo en el espacio de la nube.
    this.mouseSmooth.lerp(this.mouse, ease(10, dt));
    this.raycaster.setFromCamera(this.mouseSmooth, this.camera);
    p.rayO.copy(this.raycaster.ray.origin);
    p.rayD.copy(this.raycaster.ray.direction);
    if (this.raycaster.ray.intersectPlane(this.plane, this.hit)) {
      if (this.prevHit) {
        const v = this.hit.clone().sub(this.prevHit).divideScalar(Math.max(dt, 1e-3));
        if (v.length() > 8) v.setLength(8);
        p.mouseVel.lerp(this.overScene ? v : new THREE.Vector3(), ease(8, dt));
      }
      this.prevHit = (this.prevHit || new THREE.Vector3()).copy(this.hit);
    }
    this.speedBoost *= Math.exp(-2.5 * dt);
    const idle = performance.now() - this.lastMove > 2500;
    const pointerTarget = this.overScene ? (idle ? 0.25 : 0.55 + this.speedBoost) : 0;
    p.pointer += (pointerTarget - p.pointer) * ease(5, dt);

    // Ondas expansivas
    let pr = 99, pa = 0;
    this.pulses = this.pulses.filter((q) => t - q.t0 < 3);
    for (const q of this.pulses) {
      const age = t - q.t0;
      const a = q.amp * 7 * Math.exp(-age * 1.6);
      if (a > pa) { pa = a; pr = age * 2.6; }
    }
    p.pulseR = pr;
    p.pulseAmp = pa;

    // Cámara: paralaje suave con el cursor y una deriva lenta, como si flotara.
    const cx = this.mouseSmooth.x * 0.45 + Math.sin(t * 0.07) * 0.25;
    const cy = this.mouseSmooth.y * 0.28 + Math.sin(t * 0.05 + 1.3) * 0.15;
    this.camera.position.set(cx, cy, this.baseZ + this.zoom + Math.sin(t * 0.04) * 0.2);
    this.camera.lookAt(0, 0, 0);
    if (Math.abs(this.shiftTarget - this.shift) > 0.5) {
      this.shift += (this.shiftTarget - this.shift) * ease(4, dt);
      this.applyViewOffset();
    }

    this.nebula.update(t, dt, p);
    this.stars.update(t, p.starGain);
    this.glyphs.update(t, p);
    this.plexus.update(t, p, Math.max(0, 1 - p.burst / 6) * Math.max(0, 1 + this.zoom / 3));
    this.sats.update(t, this.satCount);
    this.bloom.strength = p.bloom + this.bloomBoost;
    this.grade.uniforms.uTime.value = t;
    if (!draw) return;
    if (this.onSnapshot && t > 6 && p.burst < 0.3 && Math.abs(this.zoom) < 0.05 && this.h >= 240) this.snapshot(dt);
    this.composer.render(dt);
    this.adapt(dtRaw);
  }

  // Retrato de la nebulosa para los iconos (la marca del modo agente): un fotograma limpio, centrado,
  // sin estrellas ni glifos, recortado y reducido. Una vez por carga; quien escucha lo guarda.
  snapshot(dt) {
    const cb = this.onSnapshot;
    this.onSnapshot = null;
    const hidden = [this.stars.points, this.glyphs.points, this.sats.points, this.plexus.group];
    for (const o of hidden) o.visible = false;
    const pos = this.camera.position.clone();
    this.camera.clearViewOffset();
    this.camera.position.set(0, 0, 11.5);
    this.camera.lookAt(0, 0, 0);
    this.camera.updateProjectionMatrix();
    this.composer.render(dt);
    try {
      // A 11,5 de distancia se ven 2·11,5·tan(19°) ≈ 7,9 unidades de alto; la nebulosa con sus anillos ocupa unas 6; se deja margen.
      const src = this.renderer.domElement;
      const side = Math.min(src.height * 0.86, src.width);
      const out = document.createElement('canvas');
      out.width = out.height = 192;
      const ctx = out.getContext('2d', { willReadFrequently: true });
      ctx.drawImage(src, (src.width - side) / 2, (src.height - side) / 2, side, side, 0, 0, 192, 192);
      const img = ctx.getImageData(0, 0, 192, 192);
      const px = img.data;
      // Un retrato oscuro es un fotograma fallido (lienzo sin pintar): se reintenta más tarde.
      let lum = 0;
      for (let y = 80; y < 112; y++) for (let x = 80; x < 112; x++) { const i = (y * 192 + x) * 4; lum += px[i] + px[i + 1] + px[i + 2]; }
      if (lum / 1024 < 120) { this.onSnapshot = cb; } else {
        // La luz es aditiva sobre negro: el negro pasa a transparente y el retrato flota sobre cualquier fondo.
        for (let i = 0; i < px.length; i += 4) {
          const a = Math.max(px[i], px[i + 1], px[i + 2]);
          if (a) { const k = 255 / a; px[i] *= k; px[i + 1] *= k; px[i + 2] *= k; }
          px[i + 3] = a;
        }
        ctx.putImageData(img, 0, 0);
        cb(out.toDataURL('image/webp', 0.9));
      }
    } catch { /* sin retrato: los iconos usan el dibujo de reserva */ }
    for (const o of hidden) o.visible = true;
    this.camera.position.copy(pos);
    this.applyViewOffset();
  }

  // Si va lento, baja la resolución interna (nunca la cantidad de partículas en caliente).
  adapt(dt) {
    this.frames.push(dt);
    if (this.frames.length < 90) return;
    const avg = this.frames.reduce((a, b) => a + b, 0) / this.frames.length;
    this.frames = [];
    if (this.onFps) this.onFps(1 / avg, this.pr);
    if (this.t < 4) return;
    if (avg > 1 / 40 && this.pr > 1) {
      this.pr = Math.max(1, this.pr - 0.25);
      this.resize();
    } else if (avg < 1 / 100 && this.pr < this.maxPR) {
      this.pr = Math.min(this.maxPR, this.pr + 0.25);
      this.resize();
    }
  }
}
