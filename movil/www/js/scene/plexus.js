// Red de plexo sobre la envoltura de la nebulosa: nodos repartidos por la esfera y unidos con sus
// vecinos más cercanos, muy tenue (como un holograma de datos). Gira con la nebulosa y respira con
// ella; no reacciona al cursor (eso es cosa de las partículas) y se apaga al estallar.
import * as THREE from 'three';

function mulberry32(a) {
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export class Plexus {
  // gain: con pocas partículas (móvil) la red debe pesar menos para no tapar la nebulosa.
  constructor(n = 90, radius = 2.05, gain = 1) {
    this.gain = gain;
    const rand = mulberry32(31);
    // Esfera de Fibonacci con algo de desorden: reparto uniforme pero no de cuadrícula.
    const nodes = [];
    const golden = Math.PI * (3 - Math.sqrt(5));
    for (let i = 0; i < n; i++) {
      const y = 1 - (2 * (i + 0.5)) / n;
      const r = Math.sqrt(1 - y * y);
      const th = golden * i + (rand() - 0.5) * 0.5;
      const k = radius * (0.94 + rand() * 0.12);
      nodes.push(new THREE.Vector3(Math.cos(th) * r * k, (y + (rand() - 0.5) * 0.06) * k, Math.sin(th) * r * k));
    }
    // Cada nodo con sus 3 vecinos más cercanos (sin repetir aristas).
    const seen = new Set(), seg = [];
    nodes.forEach((a, i) => {
      nodes.map((b, j) => [a.distanceToSquared(b), j]).filter(([, j]) => j !== i).sort((x, y) => x[0] - y[0]).slice(0, 3)
        .forEach(([d, j]) => {
          const key = i < j ? `${i}-${j}` : `${j}-${i}`;
          if (seen.has(key) || Math.sqrt(d) > radius * 0.8) return;
          seen.add(key);
          seg.push(a.x, a.y, a.z, nodes[j].x, nodes[j].y, nodes[j].z);
        });
    });
    const lg = new THREE.BufferGeometry();
    lg.setAttribute('position', new THREE.Float32BufferAttribute(seg, 3));
    this.lineMat = new THREE.LineBasicMaterial({ color: 0xcfe0ff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false });
    const pg = new THREE.BufferGeometry().setFromPoints(nodes);
    this.dotMat = new THREE.PointsMaterial({ color: 0xffffff, size: 0.045, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, depthTest: false });
    this.group = new THREE.Group();
    this.group.add(new THREE.LineSegments(lg, this.lineMat), new THREE.Points(pg, this.dotMat));
    this.color = new THREE.Color();
  }

  // Mismo giro y respiración que la envoltura (ver homeAt en nebula.js, radio ≈ 2).
  update(t, p, fade) {
    this.group.rotation.y = t * p.spin * (0.35 + 0.9 / 2.6);
    this.group.scale.setScalar(1 + p.breath * Math.sin(t * 1.25 - 4.4) * 0.035);
    this.color.copy(p.tint).lerp(p.accent, 0.45);
    this.lineMat.color.copy(this.color);
    this.dotMat.color.copy(this.color).lerp(new THREE.Color(1, 1, 1), 0.5);
    const a = p.intro * fade;
    this.lineMat.opacity = 0.2 * a * this.gain;
    this.dotMat.opacity = 0.7 * a * this.gain;
  }
}
