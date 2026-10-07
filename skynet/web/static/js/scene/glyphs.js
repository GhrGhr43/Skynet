// Cifras flotando alrededor de la nebulosa: el "pensamiento" hecho números.
// Son pocas y tenues en reposo; cuando Skynet piensa cambian más rápido y brillan más.
import * as THREE from 'three';

const CHARS = '0123456789ABCDEF';

function atlas() {
  const cell = 64, n = 4;
  const c = document.createElement('canvas');
  c.width = c.height = cell * n;
  const g = c.getContext('2d');
  g.fillStyle = '#fff';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.font = '300 44px "Inter Variable", "Segoe UI", ui-monospace, monospace';
  for (let i = 0; i < 16; i++) {
    g.fillText(CHARS[i], (i % n) * cell + cell / 2, Math.floor(i / n) * cell + cell / 2 + 2);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.NoColorSpace;
  t.generateMipmaps = true;
  t.minFilter = THREE.LinearMipmapLinearFilter;
  return t;
}

const VERT = /* glsl */ `
uniform float uTime;
uniform float uPixelRatio;
uniform float uRate;
uniform vec3 uRayO;
uniform vec3 uRayD;
uniform float uPointer;
attribute vec4 aOrbit;   // radio, ángulo inicial, altura, velocidad
attribute vec2 aSeed;
varying float vGlyph;
varying float vA;
void main(){
  float ang = aOrbit.y + uTime * aOrbit.w;
  vec3 p = vec3(cos(ang) * aOrbit.x, aOrbit.z, sin(ang) * aOrbit.x);
  // El cursor también los aparta (sin estado: se recolocan solos al irse).
  vec3 rel = p - uRayO;
  vec3 perp = p - (uRayO + uRayD * dot(rel, uRayD));
  float d = length(perp);
  p += perp / max(d, 1e-3) * exp(-d * d / 0.5) * 0.6 * uPointer;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = (9.0 + aSeed.y * 9.0) * uPixelRatio * (6.0 / -mv.z);
  vGlyph = mod(floor(aSeed.x * 16.0 + uTime * uRate * (0.3 + aSeed.y)), 16.0);
  float blink = smoothstep(0.2, 1.0, sin(uTime * (0.4 + aSeed.y * 1.3) + aSeed.x * 50.0) * 0.5 + 0.5);
  vA = blink;
}
`;

const FRAG = /* glsl */ `
uniform sampler2D tAtlas;
uniform vec3 uColor;
uniform float uGain;
varying float vGlyph;
varying float vA;
void main(){
  vec2 cell = vec2(mod(vGlyph, 4.0), floor(vGlyph / 4.0));
  vec2 uv = (cell + vec2(gl_PointCoord.x, gl_PointCoord.y)) / 4.0;
  uv.y = 1.0 - uv.y;
  float a = texture2D(tAtlas, uv).a;
  gl_FragColor = vec4(uColor * a * vA * uGain, 1.0);
}
`;

export class Glyphs {
  constructor(count = 520) {
    const orbit = new Float32Array(count * 4);
    const seed = new Float32Array(count * 2);
    for (let i = 0; i < count; i++) {
      const r = 2.5 + Math.pow(Math.random(), 0.7) * 1.9;
      const h = (Math.random() * 2 - 1) * (0.5 + Math.random() * 0.9);
      const dir = Math.random() < 0.5 ? -1 : 1;
      orbit.set([r, Math.random() * Math.PI * 2, h, dir * (0.015 + Math.random() * 0.05)], i * 4);
      seed.set([Math.random(), Math.random()], i * 2);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('aOrbit', new THREE.BufferAttribute(orbit, 4));
    geo.setAttribute('aSeed', new THREE.BufferAttribute(seed, 2));
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: {
        tAtlas: { value: atlas() },
        uTime: { value: 0 }, uPixelRatio: { value: 1 }, uRate: { value: 0.4 },
        uRayO: { value: new THREE.Vector3(0, 0, 100) }, uRayD: { value: new THREE.Vector3(0, 0, -1) },
        uPointer: { value: 0 },
        uColor: { value: new THREE.Color('#cfdcff') }, uGain: { value: 0.2 },
      },
      transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    });
    this.points = new THREE.Points(geo, this.material);
    this.points.frustumCulled = false;
  }

  update(t, p) {
    const u = this.material.uniforms;
    u.uTime.value = t;
    u.uRate.value = p.glyphRate;
    u.uGain.value = p.glyphGain * p.intro;
    u.uColor.value.copy(p.tint);
    u.uRayO.value.copy(p.rayO);
    u.uRayD.value.copy(p.rayD);
    u.uPointer.value = p.pointer;
  }

  setPixelRatio(pr) {
    this.material.uniforms.uPixelRatio.value = pr;
  }
}
