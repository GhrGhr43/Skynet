// La "mente" de Skynet: una nube de partículas simulada en la GPU.
//
// Cada partícula tiene una posición de reposo (núcleo, órbitas o halo) y un muelle que la
// devuelve allí. El cursor empuja y arrastra las partículas cercanas a su rayo; al irse, el
// muelle (poco amortiguado) las recompone con un ligero rebote. El estado del agente cambia la
// turbulencia, el giro, los pulsos y el color. Física: GPUComputationRenderer (dos texturas
// ping-pong: velocidad y posición), así que el coste en CPU es casi cero.
import * as THREE from 'three';
import { GPUComputationRenderer } from 'three/addons/misc/GPUComputationRenderer.js';
import { NOISE } from './noise.glsl.js';

const RINGS = [
  // normal del plano de la órbita, radio, velocidad angular, grosor
  { n: [0.18, 1.0, 0.22], r: 1.62, w: 0.22, t: 0.030 },
  { n: [-0.62, 0.55, 0.55], r: 1.95, w: -0.15, t: 0.024 },
  { n: [0.85, 0.25, -0.46], r: 2.32, w: 0.10, t: 0.020 },
];

// --- distribución de reposo (CPU, una vez) -----------------------------------
function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function valueNoise3(rand) {
  const N = 32, g = new Float32Array(N * N * N);
  for (let i = 0; i < g.length; i++) g[i] = rand() * 2 - 1;
  const at = (x, y, z) => g[((x & 31) * N + (y & 31)) * N + (z & 31)];
  const s = (t) => t * t * (3 - 2 * t);
  return (x, y, z) => {
    const xi = Math.floor(x), yi = Math.floor(y), zi = Math.floor(z);
    const xf = s(x - xi), yf = s(y - yi), zf = s(z - zi);
    const l = (a, b, t) => a + (b - a) * t;
    return l(
      l(l(at(xi, yi, zi), at(xi + 1, yi, zi), xf), l(at(xi, yi + 1, zi), at(xi + 1, yi + 1, zi), xf), yf),
      l(l(at(xi, yi, zi + 1), at(xi + 1, yi, zi + 1), xf), l(at(xi, yi + 1, zi + 1), at(xi + 1, yi + 1, zi + 1), xf), yf),
      zf);
  };
}

function gauss(rand) {
  let u = 0, v = 0;
  while (u === 0) u = rand();
  while (v === 0) v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

function basis(n) {
  const N = new THREE.Vector3(...n).normalize();
  const a = Math.abs(N.y) < 0.9 ? new THREE.Vector3(0, 1, 0) : new THREE.Vector3(1, 0, 0);
  const U = new THREE.Vector3().crossVectors(N, a).normalize();
  const V = new THREE.Vector3().crossVectors(N, U).normalize();
  return { N, U, V };
}

function buildRest(size) {
  const count = size * size;
  const home = new Float32Array(count * 4);   // xyz reposo, w = grupo (0 núcleo, 1-3 órbita, 4 halo)
  const attr = new Float32Array(count * 4);   // x semilla, y brillo, z radio normalizado, w fase
  const start = new Float32Array(count * 4);  // posición inicial (intro: llegan desde lejos)
  const rand = mulberry32(7);
  const noise = valueNoise3(rand);
  const ringB = RINGS.map((r) => basis(r.n));
  const v = new THREE.Vector3();
  const fbm = (x, y, z) => noise(x, y, z) * 0.55 + noise(x * 2.03 + 5.2, y * 2.03 + 1.3, z * 2.03 + 7.7) * 0.3
    + noise(x * 4.1 + 9.1, y * 4.1 + 3.7, z * 4.1 + 2.9) * 0.15;
  // Ruido "ridged": crestas finas -> filamentos y velos, como una nebulosa real.
  const ridge = (x, y, z) => 1 - Math.abs(fbm(x, y, z));
  for (let i = 0; i < count; i++) {
    const q = rand();
    let group, bright;
    if (q < 0.10) {
      // Corazón: una semilla muy densa y caliente en el centro.
      group = 0;
      v.set(gauss(rand), gauss(rand), gauss(rand)).multiplyScalar(0.2);
      bright = 0.7 + rand() * 0.6;
    } else if (q < 0.52) {
      // Nebulosa: volumen con filamentos y huecos oscuros (muestreo por rechazo sobre el ruido).
      group = 0;
      let dens = 0;
      for (let tries = 0; tries < 40; tries++) {
        v.set(gauss(rand), gauss(rand), gauss(rand)).normalize().multiplyScalar(1.45 * Math.cbrt(rand()));
        const r = v.length();
        const shape = Math.exp(-(r * r) / 0.75);
        const fil = Math.pow(ridge(v.x * 1.5 + 3.1, v.y * 1.5 + 7.3, v.z * 1.5 + 1.9), 6);
        dens = shape * (0.05 + 0.95 * fil);
        if (rand() < dens) break;
      }
      bright = 0.35 + Math.min(1, dens * 1.4) * 0.9;
    } else if (q < 0.72) {
      // Órbitas: tres anillos finos inclinados, como orbitales de un átomo.
      const k = Math.min(2, Math.floor(rand() * 3));
      group = 1 + k;
      const R = RINGS[k], B = ringB[k];
      const th = rand() * Math.PI * 2;
      const rr = R.r + gauss(rand) * R.t * (rand() < 0.12 ? 5 : 1);
      const h = gauss(rand) * R.t * 0.7;
      v.copy(B.U).multiplyScalar(Math.cos(th) * rr)
        .addScaledVector(B.V, Math.sin(th) * rr)
        .addScaledVector(B.N, h);
      bright = 0.35 + rand() * 0.55;
    } else {
      // Halo: polvo tenue y aplanado con brazos (también filamentoso).
      group = 4;
      let dens = 0;
      for (let tries = 0; tries < 30; tries++) {
        v.set(gauss(rand), gauss(rand) * 0.45, gauss(rand)).normalize();
        v.multiplyScalar(1.2 + -Math.log(1 - rand() * 0.985) * 0.8);
        const fil = Math.pow(ridge(v.x * 0.9 + 11.0, v.y * 0.9 + 2.0, v.z * 0.9 + 5.0), 4);
        dens = 0.08 + 0.92 * fil;
        if (rand() < dens) break;
      }
      bright = 0.2 + dens * 0.6;
    }
    home.set([v.x, v.y, v.z, group], i * 4);
    attr.set([rand(), bright, Math.min(1, v.length() / 3.5), rand() * Math.PI * 2], i * 4);
    // Intro: nacen todas de un punto y se expanden hasta su sitio (el muelle hace el resto).
    const k0 = 0.02 + rand() * 0.05;
    start.set([v.x * k0, v.y * k0, v.z * k0, 1], i * 4);
  }
  return { home, attr, start };
}

// --- shaders de simulación ------------------------------------------------
const SIM_COMMON = /* glsl */ `
uniform sampler2D tHome;
uniform sampler2D tAttr;
uniform float uTime;
uniform float uDt;
uniform float uSpin;
uniform float uBreath;
uniform vec3 uRingN[3];
uniform float uRingW[3];
${NOISE}
vec3 rotAxis(vec3 p, vec3 a, float ang){
  float c=cos(ang), s=sin(ang);
  return p*c + cross(a,p)*s + a*dot(a,p)*(1.0-c);
}
// Posición de reposo animada: giro diferencial (el centro gira más rápido), anillos orbitando y respiración.
vec3 homeAt(vec4 home, vec4 attr){
  vec3 h = home.xyz;
  float g = home.w;
  float r = length(h);
  if (g > 0.5 && g < 3.5) {
    int k = int(g - 0.5);
    vec3 n = k == 0 ? uRingN[0] : (k == 1 ? uRingN[1] : uRingN[2]);
    float w = k == 0 ? uRingW[0] : (k == 1 ? uRingW[1] : uRingW[2]);
    h = rotAxis(h, n, uTime * w * (1.0 + uSpin * 3.0));
  }
  float ang = uTime * uSpin * (0.35 + 0.9 / (0.6 + r));
  h = rotAxis(h, vec3(0.0, 1.0, 0.0), ang);
  float beat = sin(uTime * 1.25 - r * 2.2);
  h *= 1.0 + uBreath * beat * 0.035;
  return h;
}
`;

const VELOCITY_SHADER = /* glsl */ `
${SIM_COMMON}
uniform vec3 uRayO;
uniform vec3 uRayD;
uniform vec3 uMouseVel;
uniform float uPointer;
uniform float uRadius;
uniform float uPush;
uniform float uSwirl;
uniform float uDrag;
uniform float uTurb;
uniform float uSpring;
uniform float uDamp;
uniform float uPulseR;
uniform float uPulseAmp;
uniform float uScanY;
uniform float uScanAmp;
uniform float uJitter;

void main(){
  vec2 uv = gl_FragCoord.xy / resolution.xy;
  vec4 p = texture2D(texturePosition, uv);
  vec4 v = texture2D(textureVelocity, uv);
  vec4 home = texture2D(tHome, uv);
  vec4 attr = texture2D(tAttr, uv);
  vec3 h = homeAt(home, attr);
  float r = length(h);
  float g = home.w;

  // Flujo turbulento alrededor del reposo (más libre en el halo, contenido en las órbitas).
  float freedom = g < 0.5 ? 0.16 : (g < 3.5 ? 0.06 : 0.42);
  vec3 flow = curlNoise(h * 0.55 + vec3(0.0, uTime * 0.07, uTime * 0.03)) * uTurb * freedom;
  vec3 target = h + flow;

  vec3 acc = (target - p.xyz) * uSpring;

  // Cursor: empuje radial desde el rayo, remolino alrededor y arrastre en la dirección del movimiento.
  vec3 rel = p.xyz - uRayO;
  vec3 closest = uRayO + uRayD * dot(rel, uRayD);
  vec3 perp = p.xyz - closest;
  float d = length(perp);
  vec3 dir = perp / max(d, 1e-4);
  float fall = exp(-(d * d) / (uRadius * uRadius));
  acc += dir * fall * uPush * uPointer;
  acc += cross(uRayD, dir) * fall * uSwirl * uPointer;
  acc += uMouseVel * fall * uDrag;

  // Onda expansiva (cada herramienta, clic o respuesta lanza una).
  float band = exp(-pow((length(p.xyz) - uPulseR) * 3.0, 2.0));
  acc += normalize(p.xyz + 1e-5) * band * uPulseAmp;

  // Barrido del verificador: una franja horizontal que recorre la nube.
  if (uScanAmp > 0.001) {
    float scan = exp(-pow((p.y - uScanY) * 6.0, 2.0));
    vec2 out2 = normalize(p.xz + 1e-5);
    acc += vec3(out2.x, 0.0, out2.y) * scan * uScanAmp;
  }

  // Error: temblor nervioso.
  if (uJitter > 0.001) acc += snoiseVec3(p.xyz * 3.0 + uTime * 9.0) * uJitter;

  v.xyz += acc * uDt;
  v.xyz *= exp(-uDamp * uDt);
  gl_FragColor = vec4(v.xyz, 1.0);
}
`;

const POSITION_SHADER = /* glsl */ `
uniform float uDt;
void main(){
  vec2 uv = gl_FragCoord.xy / resolution.xy;
  vec4 p = texture2D(texturePosition, uv);
  vec4 v = texture2D(textureVelocity, uv);
  p.xyz += v.xyz * uDt;
  gl_FragColor = p;
}
`;

// --- render de las partículas -----------------------------------------------
const POINTS_VERT = /* glsl */ `
uniform sampler2D tPos;
uniform sampler2D tVel;
uniform sampler2D tAttr;
uniform sampler2D tHome;
uniform float uSize;
uniform float uPixelRatio;
uniform float uTime;
uniform float uScanY;
uniform float uScanAmp;
uniform float uIntro;
attribute vec2 ref;
varying float vAlpha;
varying float vSpeed;
varying float vRad;
varying float vGroup;
varying float vScan;
void main(){
  vec4 p = texture2D(tPos, ref);
  vec3 vel = texture2D(tVel, ref).xyz;
  vec4 attr = texture2D(tAttr, ref);
  float g = texture2D(tHome, ref).w;
  vec4 mv = modelViewMatrix * vec4(p.xyz, 1.0);
  gl_Position = projectionMatrix * mv;
  float twinkle = 0.75 + 0.25 * sin(uTime * (0.6 + attr.x * 2.5) + attr.w);
  float sizeBy = g < 0.5 ? 1.0 : (g < 3.5 ? 0.9 : 0.85);
  gl_PointSize = min(uSize * sizeBy * (0.6 + attr.y * 0.8) * uPixelRatio * (1.0 / -mv.z), 40.0 * uPixelRatio);
  vSpeed = length(vel);
  vRad = length(p.xyz);
  vGroup = g;
  vScan = exp(-pow((p.y - uScanY) * 7.0, 2.0)) * uScanAmp;
  float groupA = g < 0.5 ? 0.30 : (g < 3.5 ? 0.30 : 0.22);
  vAlpha = groupA * attr.y * twinkle * uIntro;
}
`;

const POINTS_FRAG = /* glsl */ `
uniform vec3 uCore;
uniform vec3 uTint;
uniform vec3 uAccent;
uniform float uGain;
varying float vAlpha;
varying float vSpeed;
varying float vRad;
varying float vGroup;
varying float vScan;
void main(){
  vec2 c = gl_PointCoord - 0.5;
  float d = length(c);
  if (d > 0.5) discard;
  float a = exp(-d * d * 18.0);
  // Centro casi blanco; cuanto más lejos del núcleo, más color del estado.
  float edge = smoothstep(0.55, 2.6, vRad);
  vec3 col = mix(uCore, uTint, edge);
  // Las partículas deformadas (rápidas) se iluminan con el acento: se ve el rastro del cursor.
  float hot = clamp(vSpeed * 0.55, 0.0, 1.0);
  col = mix(col, uAccent * 1.6, hot * 0.85);
  col += uAccent * vScan * 1.5;
  float alpha = vAlpha * (1.0 + hot * 1.8 + vScan * 2.0);
  gl_FragColor = vec4(col * alpha * uGain, 1.0);
}
`;

export class Nebula {
  constructor(renderer, size) {
    this.renderer = renderer;
    this.size = size;
    this.count = size * size;
    const { home, attr, start } = buildRest(size);

    const gpu = new GPUComputationRenderer(size, size, renderer);
    if (!renderer.capabilities.isWebGL2) gpu.setDataType(THREE.HalfFloatType);
    const pos0 = gpu.createTexture();
    const vel0 = gpu.createTexture();
    pos0.image.data.set(start);
    vel0.image.data.fill(0);

    const mkTex = (data) => {
      const t = new THREE.DataTexture(data, size, size, THREE.RGBAFormat, THREE.FloatType);
      t.needsUpdate = true;
      return t;
    };
    this.tHome = mkTex(home);
    this.tAttr = mkTex(attr);

    this.velVar = gpu.addVariable('textureVelocity', VELOCITY_SHADER, vel0);
    this.posVar = gpu.addVariable('texturePosition', POSITION_SHADER, pos0);
    gpu.setVariableDependencies(this.velVar, [this.velVar, this.posVar]);
    gpu.setVariableDependencies(this.posVar, [this.velVar, this.posVar]);

    const ringN = RINGS.map((r) => new THREE.Vector3(...r.n).normalize());
    const common = () => ({
      tHome: { value: this.tHome },
      tAttr: { value: this.tAttr },
      uTime: { value: 0 },
      uDt: { value: 0.016 },
      uSpin: { value: 0.06 },
      uBreath: { value: 1 },
      uRingN: { value: ringN },
      uRingW: { value: RINGS.map((r) => r.w) },
    });
    Object.assign(this.velVar.material.uniforms, common(), {
      uRayO: { value: new THREE.Vector3(0, 0, 100) },
      uRayD: { value: new THREE.Vector3(0, 0, -1) },
      uMouseVel: { value: new THREE.Vector3() },
      uPointer: { value: 0 },
      uRadius: { value: 0.55 },
      uPush: { value: 7.0 },
      uSwirl: { value: 4.0 },
      uDrag: { value: 1.6 },
      uTurb: { value: 0.35 },
      uSpring: { value: 1.2 },
      uDamp: { value: 2.4 },
      uPulseR: { value: 99 },
      uPulseAmp: { value: 0 },
      uScanY: { value: 99 },
      uScanAmp: { value: 0 },
      uJitter: { value: 0 },
    });
    this.posVar.material.uniforms.uDt = { value: 0.016 };
    for (const v of [this.velVar, this.posVar]) {
      v.wrapS = THREE.ClampToEdgeWrapping;
      v.wrapT = THREE.ClampToEdgeWrapping;
    }
    let err = gpu.init();
    if (err) {
      // Algunas GPUs no pueden renderizar a float32: se reintenta con half float.
      gpu.setDataType(THREE.HalfFloatType);
      err = gpu.init();
    }
    if (err) throw new Error(err);
    this.gpu = gpu;
    this.velU = this.velVar.material.uniforms;

    // Geometría: un vértice por partícula; solo lleva la coordenada de su texel.
    const geo = new THREE.BufferGeometry();
    const ref = new Float32Array(this.count * 2);
    for (let i = 0; i < this.count; i++) {
      ref[i * 2] = ((i % size) + 0.5) / size;
      ref[i * 2 + 1] = (Math.floor(i / size) + 0.5) / size;
    }
    geo.setAttribute('ref', new THREE.BufferAttribute(ref, 2));
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(this.count * 3), 3));
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 50);

    // Más partículas = cada una más tenue, para que el brillo total no dependa de la calidad.
    const density = Math.sqrt(262144 / this.count);
    this.material = new THREE.ShaderMaterial({
      vertexShader: POINTS_VERT,
      fragmentShader: POINTS_FRAG,
      uniforms: {
        tPos: { value: null },
        tVel: { value: null },
        tAttr: { value: this.tAttr },
        tHome: { value: this.tHome },
        uSize: { value: 15 },
        uPixelRatio: { value: renderer.getPixelRatio() },
        uTime: { value: 0 },
        uScanY: { value: 99 },
        uScanAmp: { value: 0 },
        uIntro: { value: 0 },
        uCore: { value: new THREE.Color(1, 1, 1) },
        uTint: { value: new THREE.Color('#cfdcff') },
        uAccent: { value: new THREE.Color('#7aa2ff') },
        uGain: { value: 0.38 * density },
      },
      transparent: true,
      depthWrite: false,
      depthTest: false,
      blending: THREE.AdditiveBlending,
    });
    this.points = new THREE.Points(geo, this.material);
    this.points.frustumCulled = false;
    this.pu = this.material.uniforms;
  }

  setPixelRatio(pr) {
    this.pu.uPixelRatio.value = pr;
  }

  update(t, dt, p) {
    const sub = dt > 1 / 45 ? 2 : 1;  // dos subpasos si el frame es largo: el muelle no explota
    const h = dt / sub;
    for (const u of [this.velU, this.posVar.material.uniforms]) {
      u.uDt.value = h;
    }
    const v = this.velU;
    v.uTime.value = t;
    v.uSpin.value = p.spin;
    v.uBreath.value = p.breath;
    v.uTurb.value = p.turb;
    v.uSpring.value = p.spring;
    v.uDamp.value = p.damp;
    v.uPointer.value = p.pointer;
    v.uRayO.value.copy(p.rayO);
    v.uRayD.value.copy(p.rayD);
    v.uMouseVel.value.copy(p.mouseVel);
    v.uPulseR.value = p.pulseR;
    v.uPulseAmp.value = p.pulseAmp;
    v.uScanY.value = p.scanY;
    v.uScanAmp.value = p.scanAmp;
    v.uJitter.value = p.jitter;
    for (let i = 0; i < sub; i++) this.gpu.compute();

    const pu = this.pu;
    pu.tPos.value = this.gpu.getCurrentRenderTarget(this.posVar).texture;
    pu.tVel.value = this.gpu.getCurrentRenderTarget(this.velVar).texture;
    pu.uTime.value = t;
    pu.uScanY.value = p.scanY;
    pu.uScanAmp.value = p.scanAmp;
    pu.uIntro.value = p.intro;
    pu.uTint.value.copy(p.tint);
    pu.uAccent.value.copy(p.accent);
    pu.uCore.value.copy(p.core);
    pu.uSize.value = p.size;
  }

  dispose() {
    this.gpu.dispose();
    this.points.geometry.dispose();
    this.material.dispose();
    this.tHome.dispose();
    this.tAttr.dispose();
  }
}
