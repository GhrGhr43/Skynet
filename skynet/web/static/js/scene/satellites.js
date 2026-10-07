// Una luz en órbita por cada tarea larga en marcha: se ve de un vistazo que Skynet trabaja solo.
import * as THREE from 'three';

const MAX = 6, TRAIL = 48;

const VERT = /* glsl */ `
uniform float uTime;
uniform float uPixelRatio;
uniform float uCount;
attribute vec2 aIdx;  // satélite, posición en la estela (0 = cabeza)
varying float vA;
vec3 rotAxis(vec3 p, vec3 a, float ang){ float c=cos(ang), s=sin(ang); return p*c + cross(a,p)*s + a*dot(a,p)*(1.0-c); }
void main(){
  float k = aIdx.x;
  float on = step(k + 0.5, uCount);
  float speed = 0.55 - k * 0.05;
  float ang = uTime * speed + k * 2.1 - aIdx.y * 0.022;
  float R = 2.75 + k * 0.22;
  vec3 p = vec3(cos(ang) * R, 0.0, sin(ang) * R);
  vec3 axis = normalize(vec3(sin(k * 1.7), 1.0, cos(k * 2.3)));
  p = rotAxis(p, normalize(cross(axis, vec3(0.0, 1.0, 0.0)) + 1e-4), 0.35 + k * 0.25);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  float head = 1.0 - aIdx.y / ${TRAIL}.0;
  gl_PointSize = (aIdx.y < 0.5 ? 26.0 : 9.0 * head + 2.0) * uPixelRatio * (6.0 / -mv.z);
  vA = on * (aIdx.y < 0.5 ? 1.0 : head * head * 0.5);
}
`;
const FRAG = /* glsl */ `
uniform vec3 uColor;
varying float vA;
void main(){
  float d = length(gl_PointCoord - 0.5);
  if (d > 0.5) discard;
  float a = exp(-d * d * 20.0);
  gl_FragColor = vec4(uColor * a * vA * 1.4, 1.0);
}
`;

export class Satellites {
  constructor() {
    const idx = new Float32Array(MAX * TRAIL * 2);
    for (let s = 0; s < MAX; s++) for (let i = 0; i < TRAIL; i++) idx.set([s, i], (s * TRAIL + i) * 2);
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('aIdx', new THREE.BufferAttribute(idx, 2));
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(MAX * TRAIL * 3), 3));
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 }, uPixelRatio: { value: 1 }, uCount: { value: 0 },
        uColor: { value: new THREE.Color('#9fd8ff') } },
      transparent: true, depthWrite: false, depthTest: false, blending: THREE.AdditiveBlending,
    });
    this.points = new THREE.Points(geo, this.material);
    this.points.frustumCulled = false;
    this.count = 0;
  }

  update(t, count) {
    this.material.uniforms.uTime.value = t;
    this.material.uniforms.uCount.value = Math.min(MAX, count);
  }

  setPixelRatio(pr) {
    this.material.uniforms.uPixelRatio.value = pr;
  }
}
