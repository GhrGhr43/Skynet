// Fondo de estrellas: pocas, finas y tenues. Se aprecian sin competir con la nebulosa.
import * as THREE from 'three';

const VERT = /* glsl */ `
uniform float uTime;
uniform float uPixelRatio;
uniform float uGain;
attribute float aSize;
attribute float aSeed;
attribute vec3 aColor;
varying float vA;
varying vec3 vColor;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  float tw = 0.65 + 0.35 * sin(uTime * (0.3 + aSeed * 1.7) + aSeed * 40.0);
  tw *= 0.85 + 0.15 * sin(uTime * 7.0 * aSeed + aSeed * 13.0);
  gl_PointSize = aSize * uPixelRatio;
  vA = tw * uGain;
  vColor = aColor;
}
`;
const FRAG = /* glsl */ `
varying float vA;
varying vec3 vColor;
void main(){
  vec2 c = gl_PointCoord - 0.5;
  float d = length(c);
  if (d > 0.5) discard;
  float a = exp(-d * d * 24.0);
  // Rayitos de difracción muy suaves en las estrellas grandes.
  float spikes = exp(-abs(c.x) * 60.0) * exp(-abs(c.y) * 6.0) + exp(-abs(c.y) * 60.0) * exp(-abs(c.x) * 6.0);
  gl_FragColor = vec4(vColor * (a + spikes * 0.25) * vA, 1.0);
}
`;

export class Stars {
  constructor(count = 2600) {
    const pos = new Float32Array(count * 3);
    const size = new Float32Array(count);
    const seed = new Float32Array(count);
    const color = new Float32Array(count * 3);
    const tints = [[1, 1, 1], [0.78, 0.86, 1], [1, 0.92, 0.82], [0.85, 0.9, 1]];
    for (let i = 0; i < count; i++) {
      const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2;
      const s = Math.sqrt(1 - u * u);
      const r = 60 + Math.random() * 60;
      pos.set([s * Math.cos(th) * r, u * r, s * Math.sin(th) * r], i * 3);
      // Muchas diminutas y muy pocas grandes (distribución de potencia, como el cielo real).
      const m = Math.pow(Math.random(), 7);
      size[i] = 1.2 + m * 5.5;
      seed[i] = Math.random();
      const t = tints[Math.floor(Math.random() * tints.length)];
      const b = 0.35 + m * 0.9 + Math.random() * 0.15;
      color.set([t[0] * b, t[1] * b, t[2] * b], i * 3);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('aSize', new THREE.BufferAttribute(size, 1));
    geo.setAttribute('aSeed', new THREE.BufferAttribute(seed, 1));
    geo.setAttribute('aColor', new THREE.BufferAttribute(color, 3));
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 }, uPixelRatio: { value: 1 }, uGain: { value: 0 } },
      transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    });
    this.points = new THREE.Points(geo, this.material);
    this.points.frustumCulled = false;
  }

  update(t, gain) {
    this.material.uniforms.uTime.value = t;
    this.material.uniforms.uGain.value = gain;
    this.points.rotation.y = t * 0.004;
    this.points.rotation.x = Math.sin(t * 0.01) * 0.02;
  }

  setPixelRatio(pr) {
    this.material.uniforms.uPixelRatio.value = pr;
  }
}
