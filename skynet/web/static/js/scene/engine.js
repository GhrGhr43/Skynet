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

// Contenedores de la maqueta que dejan ver la escena (el ratón sobre ellos mueve la nebulosa).
const SCENE_THROUGH = '.main, .top, .hero, .hero *, .convo, .convo-scroll, .convo-inner, .dock, .suggest, .under';

// Cada estado del agente es una "personalidad" de la nube: color, turbulencia, giro...
export const STATES = {
  reposo:       { label: 'En espera',                tint: '#d4e0ff', accent: '#86a8ff', turb: 0.35, spin: 0.05, breath: 1.0, glyphRate: 0.35, glyphGain: 0.16, bloom: 0.8,  size: 11 },
  pensando:     { label: 'Pensando',                 tint: '#9fceff', accent: '#3a9dff', turb: 1.05, spin: 0.20, breath: 1.7, glyphRate: 3.0,  glyphGain: 0.40, bloom: 0.95, size: 11.5 },
  herramienta:  { label: 'Trabajando',               tint: '#c2b2ff', accent: '#9b78ff', turb: 0.8,  spin: 0.15, breath: 1.3, glyphRate: 2.0,  glyphGain: 0.32, bloom: 0.95, size: 11.5 },
  esperando:    { label: 'Esperando tu confirmación', tint: '#ffd6a3', accent: '#ffa63d', turb: 0.22, spin: 0.02, breath: 2.8, glyphRate: 0.2,  glyphGain: 0.14, bloom: 0.9,  size: 11 },
  verificando:  { label: 'Verificando',              tint: '#a6f3e1', accent: '#2fe3bd', turb: 0.5,  spin: 0.10, breath: 1.0, glyphRate: 1.2,  glyphGain: 0.26, bloom: 0.9,  size: 15, scan: 1 },
  exito:        { label: 'Hecho',                    tint: '#d3ffe6', accent: '#5bffaa', turb: 0.3,  spin: 0.08, breath: 1.0, glyphRate: 0.5,  glyphGain: 0.2,  bloom: 1.1,  size: 11.5 },
  error:        { label: 'Algo falló',               tint: '#ffbcc3', accent: '#ff4558', turb: 0.6,  spin: 0.04, breath: 1.0, glyphRate: 0.8,  glyphGain: 0.2,  bloom: 0.9,  size: 15, jitter: 1 },
  desconectado: { label: 'Sin conexión con Skynet',  tint: '#7d838e', accent: '#4c525c', turb: 0.15, spin: 0.01, breath: 0.4, glyphRate: 0.05, glyphGain: 0.06, bloom: 0.5,  size: 10 },
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
    this.scene.add(this.stars.points, this.nebula.points, this.glyphs.points, this.sats.points);

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
      mouseVel: new THREE.Vector3(), pulseR: 99, pulseAmp: 0, intro: 0, starGain: 0,
    };
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
      if (this.isScene(e.target)) this.pulse(0.9);
    });
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
    this.speedBoost = Math.min(1.6, this.speedBoost + Math.hypot(e.movementX || 0, e.movementY || 0) * 0.012);
  }

  // La interfaz tapa el lienzo: los huecos vacíos de la maqueta (no botones ni mensajes)
  // cuentan como escena, para que la nebulosa siga reaccionando al cursor.
  isScene(el) {
    return el === this.canvas || !!el?.matches?.(SCENE_THROUGH);
  }

  resize() {
    const w = window.innerWidth, h = window.innerHeight;
    this.w = w; this.h = h;
    this.renderer.setPixelRatio(this.pr);
    this.renderer.setSize(w, h, false);
    this.composer.setPixelRatio(this.pr);
    this.composer.setSize(w, h);
    this.camera.aspect = w / h;
    // En pantallas estrechas la nube se aleja un poco para que quepa entera.
    this.baseZ = w / h < 0.9 ? 15.5 : 11.5;
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

  setSatellites(n) {
    this.satCount = n;
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
    p.starGain = Math.min(1, t / 3.0) * (this.activeState === 'desconectado' ? 0.5 : 1);
    const springTarget = 7.5;
    p.spring = t < 4 ? 0.6 + (springTarget - 0.6) * Math.pow(t / 4, 2) : springTarget;
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
    this.camera.position.set(cx, cy, this.baseZ + Math.sin(t * 0.04) * 0.2);
    this.camera.lookAt(0, 0, 0);
    if (Math.abs(this.shiftTarget - this.shift) > 0.5) {
      this.shift += (this.shiftTarget - this.shift) * ease(4, dt);
      this.applyViewOffset();
    }

    this.nebula.update(t, dt, p);
    this.stars.update(t, p.starGain);
    this.glyphs.update(t, p);
    this.sats.update(t, this.satCount);
    this.bloom.strength = p.bloom;
    this.grade.uniforms.uTime.value = t;
    if (!draw) return;
    this.composer.render(dt);
    this.adapt(dtRaw);
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
