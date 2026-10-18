// Procedural 2026-regulation Formula 1 car for three.js (1 unit = 1 m, the car points towards -z).
//
// Proportions follow the 2026 technical regulations: 3.40 m maximum wheelbase, 1.90 m maximum width,
// 18-inch wheels with narrower tyres, a two-element front wing with an active flap, a three-element
// active rear wing with no beam wing and simplified endplates, halo, undercut sidepods and a partly flat floor.
// Liveries are colour schemes painted into a UV texture; no team or sponsor marks.

import * as THREE from "three";

export const DIMENSIONS = { wheelbase: 3.4, width: 1.9, wheelDiameter: 0.72, frontTyre: 0.28, rearTyre: 0.375 };
const FRONT_AXLE = -1.72, REAR_AXLE = FRONT_AXLE + DIMENSIONS.wheelbase;
const R_WHEEL = DIMENSIONS.wheelDiameter / 2, R_RIM = 0.229; // 18-inch rim
const TRACK_F = 1.90 - DIMENSIONS.frontTyre, TRACK_R = 1.90 - DIMENSIONS.rearTyre; // outer tyre edges at ±0.95 m

export const LIVERIES = {
  silver: { top: "#c9ced6", bottom: "#101215", accent: "#00d7b6", stripe2: "#7d8590", number: 12, metal: 0.65 },
  papaya: { top: "#ff7a00", bottom: "#14171c", accent: "#46b6ff", stripe2: "#ffffff", number: 4, metal: 0.15 },
};

// ---------------------------------------------------------------- textures
function canvas(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; return t;
}

/** Body livery in loft UV space: u = along the car (0 nose → 1 tail), v = around the section
 *  (0 = right side, 0.25 = top, 0.5 = left side, 0.75 = bottom). */
function liveryTexture(L) {
  return canvas(1024, 512, (g, W, H) => {
    // v 0–0.5 is the upper half of every section, v 0.5–1 the lower half and underside.
    const grad = g.createLinearGradient(0, 0, 0, H);
    // sides and top in the main colour; the dark band starts just below the waistline on each side
    grad.addColorStop(0.0, L.top); grad.addColorStop(0.47, L.top); grad.addColorStop(0.535, L.bottom);
    grad.addColorStop(0.955, L.bottom); grad.addColorStop(1, L.top);
    g.fillStyle = grad; g.fillRect(0, 0, W, H);
    for (const vy of [0.03, 0.46]) { // accent flank stripes along the waistline on both sides
      g.fillStyle = L.accent; g.fillRect(W * 0.2, H * vy, W * 0.6, H * 0.01);
      g.fillStyle = L.stripe2; g.fillRect(W * 0.28, H * (vy + (vy < 0.25 ? 0.016 : -0.012)), W * 0.44, H * 0.005);
    }
    g.fillStyle = L.accent; g.fillRect(W * 0.0, H * 0.235, W * 0.16, H * 0.03); // nose centre line
    g.save(); g.translate(W * 0.12, H * 0.25); g.rotate(Math.PI / 2);
    g.fillStyle = L.bottom; g.font = "italic 900 58px system-ui"; g.textAlign = "center"; g.textBaseline = "middle";
    g.fillText(String(L.number), 0, 0); g.restore();
  });
}
function carbonTexture() {
  const t = canvas(128, 128, (g) => {
    g.fillStyle = "#0f1012"; g.fillRect(0, 0, 128, 128);
    for (let y = 0; y < 128; y += 8) for (let x = 0; x < 128; x += 8) {
      const odd = ((x + y) / 8) % 2, gr = g.createLinearGradient(x, y, odd ? x + 8 : x, odd ? y : y + 8);
      gr.addColorStop(0, "#17181b"); gr.addColorStop(0.5, "#26282d"); gr.addColorStop(1, "#121315");
      g.fillStyle = gr; g.fillRect(x + 0.5, y + 0.5, 7, 7);
    }
  });
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(8, 8); return t;
}
function sidewallTexture(stripe) {
  return canvas(512, 512, (g, N) => {
    const m = N / 2, k = m / R_WHEEL;
    g.fillStyle = "#121212"; g.beginPath(); g.arc(m, m, m, 0, Math.PI * 2); g.fill();
    g.strokeStyle = stripe; g.lineWidth = 0.02 * k; g.beginPath(); g.arc(m, m, (R_RIM + 0.05) * k, 0, Math.PI * 2); g.stroke();
    g.fillStyle = "#e6e6e6"; g.font = `800 ${0.032 * k}px system-ui`; g.textAlign = "center"; g.textBaseline = "middle";
    for (const base of [0, Math.PI]) [..."P ZERO"].forEach((ch, i) => {
      const a = base - 0.3 + i * 0.11, r = (R_WHEEL - 0.045) * k;
      g.save(); g.translate(m + Math.cos(a) * r, m + Math.sin(a) * r); g.rotate(a + Math.PI / 2); g.fillText(ch, 0, 0); g.restore();
    });
  });
}
function numberTexture(num, colour) {
  return canvas(256, 128, (g) => {
    g.fillStyle = colour; g.font = "italic 900 100px system-ui"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(num), 128, 68);
  });
}

// ---------------------------------------------------------------- geometry
/** Loft through superellipse sections {z, w, h, y, n, flat}; UVs as described in liveryTexture. */
function loft(sections, { around = 48, along = 110, caps = true } = {}) {
  const zs = sections.map((s) => s.z);
  const P = new THREE.CatmullRomCurve3(sections.map((s) => new THREE.Vector3(s.w, s.h, s.y)), false, "centripetal");
  const Q = new THREE.CatmullRomCurve3(sections.map((s) => new THREE.Vector3(s.n ?? 2.8, s.flat ?? 1, s.x ?? 0)));
  const pos = [], uv = [], idx = [];
  for (let i = 0; i <= along; i++) {
    const u = i / along, z = zs[0] + (zs.at(-1) - zs[0]) * u;
    let k = 0; while (k < zs.length - 2 && z > zs[k + 1]) k++;
    const t = (k + (z - zs[k]) / (zs[k + 1] - zs[k] || 1)) / (zs.length - 1);
    const p = P.getPoint(t), q = Q.getPoint(t);
    for (let j = 0; j <= around; j++) {
      const a = (j / around) * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
      const x = (p.x / 2) * Math.sign(ca) * Math.abs(ca) ** (2 / q.x);
      let y = (p.y / 2) * Math.sign(sa) * Math.abs(sa) ** (2 / q.x);
      if (sa < 0) y *= q.y; // flatter underside
      pos.push(x + q.z, p.z + y, z); uv.push(u, j / around);
    }
  }
  const ring = around + 1;
  for (let i = 0; i < along; i++) for (let j = 0; j < around; j++) {
    const a = i * ring + j, b = a + 1, c = a + ring, d = c + 1;
    idx.push(a, c, b, b, c, d);
  }
  if (caps) for (const [r, flip] of [[0, false], [along * ring, true]]) {
    const ci = pos.length / 3; let cx = 0, cy = 0, cz = 0;
    for (let j = 0; j < around; j++) { cx += pos[(r + j) * 3]; cy += pos[(r + j) * 3 + 1]; cz += pos[(r + j) * 3 + 2]; }
    pos.push(cx / around, cy / around, cz / around); uv.push(flip ? 1 : 0, 0.5);
    for (let j = 0; j < around; j++) flip ? idx.push(ci, r + j + 1, r + j) : idx.push(ci, r + j, r + j + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setAttribute("uv", new THREE.Float32BufferAttribute(uv, 2));
  g.setIndex(idx); g.computeVertexNormals(); return g;
}

/** NACA-style cambered airfoil swept along the span, with the element rising towards its tips. */
function wingElement({ chord, span, thick = 0.1, camber = 0.07, rise = 0, risePow = 4, dip = 0, twist = 0, segments = 40 }) {
  const N = 18, prof = [];
  for (let i = 0; i <= N; i++) {
    const x = (1 - Math.cos((i / N) * Math.PI)) / 2;
    const yt = 5 * thick * (0.2969 * Math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1036 * x ** 4);
    const yc = camber * 4 * x * (1 - x);
    prof.push([x * chord, (yc + yt) * chord]);
  }
  for (let i = N - 1; i > 0; i--) { const x = prof[i][0] / chord; const yt = prof[i][1] / chord - camber * 4 * x * (1 - x); prof.push([x * chord, (camber * 4 * x * (1 - x) - yt) * chord]); }
  const M = prof.length, pos = [], idx = [];
  for (let s = 0; s <= segments; s++) {
    const f = s / segments, x = (f - 0.5) * span, e = Math.abs(2 * f - 1);
    const lift = rise * e ** risePow - dip * (1 - e ** 2), tw = twist * e ** 2;
    for (const [cz, cy] of prof) {
      const yy = cy * Math.cos(tw) + cz * Math.sin(tw), zz = cz * Math.cos(tw) - cy * Math.sin(tw);
      pos.push(x, yy + lift, zz);
    }
  }
  for (let s = 0; s < segments; s++) for (let i = 0; i < M; i++) {
    const a = s * M + i, b = s * M + ((i + 1) % M), c = a + M, d = b + M;
    idx.push(a, b, c, b, d, c);
  }
  for (const s of [0, segments]) for (let i = 1; i < M - 1; i++) { // end caps
    const o = s * M; s ? idx.push(o, o + i + 1, o + i) : idx.push(o, o + i, o + i + 1);
  }
  const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx); g.computeVertexNormals(); return g;
}

function tyreGeometry(width) {
  const pts = [], sh = 0.05;
  pts.push(new THREE.Vector2(R_RIM + 0.005, -width / 2 + 0.02));
  for (let i = 0; i <= 10; i++) { const a = -Math.PI / 2 + (i / 10) * (Math.PI / 2); pts.push(new THREE.Vector2(R_WHEEL - sh + Math.cos(a) * sh, -width / 2 + sh + Math.sin(a) * sh)); }
  for (let i = 0; i <= 10; i++) { const a = (i / 10) * (Math.PI / 2); pts.push(new THREE.Vector2(R_WHEEL - sh + Math.cos(a) * sh, width / 2 - sh + Math.sin(a) * sh)); }
  pts.push(new THREE.Vector2(R_RIM + 0.005, width / 2 - 0.02));
  const g = new THREE.LatheGeometry(pts, 64); g.rotateZ(Math.PI / 2); return g;
}

// ---------------------------------------------------------------- car
export function buildCar(liveryName = "silver", { compound = "#ffd400" } = {}) {
  const L = LIVERIES[liveryName];
  const car = new THREE.Group();
  const livery = liveryTexture(L);
  const paint = new THREE.MeshPhysicalMaterial({ map: livery, metalness: L.metal, roughness: 0.28, clearcoat: 1, clearcoatRoughness: 0.06 });
  const plain = new THREE.MeshPhysicalMaterial({ color: L.top, metalness: L.metal, roughness: 0.3, clearcoat: 1, clearcoatRoughness: 0.08 });
  const accent = new THREE.MeshPhysicalMaterial({ color: L.accent, metalness: 0.1, roughness: 0.3, clearcoat: 1 });
  const carbon = new THREE.MeshPhysicalMaterial({ map: carbonTexture(), roughness: 0.42, metalness: 0.15, clearcoat: 0.7, clearcoatRoughness: 0.2 });
  const satin = new THREE.MeshStandardMaterial({ color: L.bottom, roughness: 0.55, metalness: 0.2 });
  const rubber = new THREE.MeshStandardMaterial({ color: 0x161616, roughness: 0.95 });
  const rimMat = new THREE.MeshStandardMaterial({ color: 0x1c1d20, roughness: 0.35, metalness: 0.85 });
  const add = (geo, mat, x = 0, y = 0, z = 0, parent = car) => {
    const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = m.receiveShadow = true; parent.add(m); return m;
  };

  // ---- survival cell, nose and engine cover: one smooth, UV-mapped loft (painted with the livery)
  add(loft([
    { z: -2.98, w: 0.14, h: 0.09, y: 0.27, n: 2.2, flat: 0.8 },
    { z: -2.55, w: 0.24, h: 0.15, y: 0.30, n: 2.4, flat: 0.8 },
    { z: -1.95, w: 0.36, h: 0.25, y: 0.36, n: 2.6, flat: 0.75 },
    { z: -1.25, w: 0.50, h: 0.36, y: 0.43, n: 3.0, flat: 0.7 },
    { z: -0.65, w: 0.62, h: 0.42, y: 0.47, n: 3.6, flat: 0.65 },
    { z: 0.00, w: 0.66, h: 0.46, y: 0.48, n: 3.8, flat: 0.6 },
    { z: 0.60, w: 0.52, h: 0.54, y: 0.52, n: 3.2, flat: 0.6 },
    { z: 1.25, w: 0.36, h: 0.40, y: 0.47, n: 2.8, flat: 0.6 },
    { z: 1.85, w: 0.22, h: 0.24, y: 0.40, n: 2.4, flat: 0.7 },
    { z: 2.30, w: 0.12, h: 0.12, y: 0.36, n: 2.2, flat: 0.8 },
  ]), paint);

  // ---- sidepods with a deep undercut: wide shoulder, narrow base, ramping down to the rear
  for (const s of [-1, 1]) {
    add(loft([
      { z: -0.62, w: 0.10, h: 0.20, y: 0.50, n: 3, flat: 0.5, x: s * 0.42 },
      { z: -0.48, w: 0.34, h: 0.24, y: 0.50, n: 5, flat: 0.45, x: s * 0.50 },   // letterbox inlet
      { z: 0.10, w: 0.36, h: 0.26, y: 0.50, n: 5, flat: 0.4, x: s * 0.52 },
      { z: 0.75, w: 0.28, h: 0.20, y: 0.46, n: 4, flat: 0.45, x: s * 0.46 },
      { z: 1.35, w: 0.12, h: 0.10, y: 0.38, n: 3, flat: 0.6, x: s * 0.30 },
    ], { around: 36, along: 60 }), paint);
    const inlet = add(new THREE.PlaneGeometry(0.3, 0.12), new THREE.MeshBasicMaterial({ color: 0x050505 }), s * 0.5, 0.5, -0.49);
    inlet.rotation.y = Math.PI;
  }

  // ---- floor with edge, plank, diffuser and floor fences
  const fl = new THREE.Shape();
  fl.moveTo(-0.38, -1.30); fl.lineTo(0.38, -1.30); fl.quadraticCurveTo(0.62, -0.9, 0.70, -0.45); fl.lineTo(0.70, 1.10);
  fl.quadraticCurveTo(0.66, 1.45, 0.50, 1.62); fl.lineTo(-0.50, 1.62); fl.quadraticCurveTo(-0.66, 1.45, -0.70, 1.10); fl.lineTo(-0.70, -0.45); fl.quadraticCurveTo(-0.62, -0.9, -0.38, -1.30);
  const floor = add(new THREE.ExtrudeGeometry(fl, { depth: 0.02, bevelEnabled: true, bevelSize: 0.006, bevelThickness: 0.004, bevelSegments: 2 }), carbon, 0, 0.055, 0);
  floor.rotation.x = Math.PI / 2;
  for (const s of [-1, 1]) {
    const edge = add(new THREE.BoxGeometry(0.012, 0.05, 1.2), carbon, s * 0.69, 0.08, 0.4); edge.rotation.z = s * 0.2;
    for (let i = 0; i < 3; i++) add(new THREE.BoxGeometry(0.008, 0.11, 0.42), carbon, s * (0.22 + i * 0.1), 0.03, -1.0 + i * 0.05);
  }
  const diffuser = add(new THREE.BoxGeometry(0.98, 0.012, 0.48), carbon, 0, 0.13, 1.84); diffuser.rotation.x = -0.32;
  for (const s of [-1, 0, 1]) add(new THREE.BoxGeometry(0.01, 0.16, 0.44), carbon, s * 0.3, 0.12, 1.84);

  // ---- airbox, engine-cover fin with the number, T-camera
  add(loft([{ z: -0.18, w: 0.06, h: 0.05, y: 0.98 }, { z: -0.05, w: 0.26, h: 0.24, y: 0.92, n: 3 }, { z: 0.35, w: 0.22, h: 0.30, y: 0.82 }, { z: 0.95, w: 0.06, h: 0.08, y: 0.66 }], { around: 28, along: 36 }), plain);
  add(new THREE.CircleGeometry(0.075, 24), new THREE.MeshBasicMaterial({ color: 0x020202 }), 0, 0.95, -0.07).rotation.y = Math.PI;
  const fin = new THREE.Shape(); fin.moveTo(0, 0); fin.lineTo(1.15, 0.0); fin.lineTo(1.15, 0.05); fin.quadraticCurveTo(0.45, 0.09, 0.02, 0.17); fin.lineTo(0, 0);
  add(new THREE.ExtrudeGeometry(fin, { depth: 0.01, bevelEnabled: false }), plain, -0.005, 0.79, 0.72).rotation.y = -Math.PI / 2;
  const numMat = new THREE.MeshBasicMaterial({ map: numberTexture(L.number, L.accent), transparent: true, depthWrite: false });
  for (const s of [-1, 1]) { const n = new THREE.Mesh(new THREE.PlaneGeometry(0.28, 0.14), numMat); n.position.set(s * 0.011, 0.86, 1.05); n.rotation.y = s * Math.PI / 2; car.add(n); }
  add(new THREE.BoxGeometry(0.07, 0.03, 0.12), new THREE.MeshStandardMaterial({ color: 0xffd400, roughness: 0.4 }), 0, 1.06, -0.08); // T-cam

  // ---- cockpit, helmet, halo, mirrors
  add(new THREE.SphereGeometry(0.145, 32, 20), new THREE.MeshPhysicalMaterial({ color: L.accent, clearcoat: 1, roughness: 0.15 }), 0, 0.78, -0.4);
  const visor = add(new THREE.SphereGeometry(0.147, 32, 12, -Math.PI * 0.75, Math.PI * 0.5, Math.PI * 0.38, Math.PI * 0.22), new THREE.MeshPhysicalMaterial({ color: 0x080808, metalness: 0.9, roughness: 0.05 }), 0, 0.78, -0.4);
  visor.rotation.y = Math.PI;
  const rim = add(new THREE.TorusGeometry(0.29, 0.03, 12, 40), satin, 0, 0.72, -0.42); rim.rotation.x = Math.PI / 2; rim.scale.set(1, 1.5, 1);
  const halo = new THREE.CatmullRomCurve3([new THREE.Vector3(-0.31, 0.7, 0.08), new THREE.Vector3(-0.31, 0.88, -0.2), new THREE.Vector3(-0.2, 0.93, -0.46), new THREE.Vector3(0, 0.935, -0.52), new THREE.Vector3(0.2, 0.93, -0.46), new THREE.Vector3(0.31, 0.88, -0.2), new THREE.Vector3(0.31, 0.7, 0.08)]);
  add(new THREE.TubeGeometry(halo, 64, 0.028, 16), satin);
  const pillarPath = new THREE.CatmullRomCurve3([new THREE.Vector3(0, 0.935, -0.52), new THREE.Vector3(0, 0.84, -0.7), new THREE.Vector3(0, 0.72, -0.82)]);
  add(new THREE.TubeGeometry(pillarPath, 16, 0.024, 12), satin);
  for (const s of [-1, 1]) {
    const m = add(new THREE.SphereGeometry(0.06, 20, 10), plain, s * 0.47, 0.72, -0.66); m.scale.set(1.5, 0.7, 0.6);
    add(new THREE.PlaneGeometry(0.15, 0.06), new THREE.MeshPhysicalMaterial({ color: 0x9fb4c8, metalness: 1, roughness: 0.02 }), s * 0.47, 0.72, -0.63);
    const stalk = add(new THREE.BoxGeometry(0.16, 0.012, 0.04), satin, s * 0.39, 0.66, -0.66); stalk.rotation.z = -s * 0.5;
  }

  // ---- front wing: main plane + two-element active flap, rising to the endplates
  const fw = new THREE.Group(); fw.position.set(0, 0.075, -3.05); car.add(fw);
  add(wingElement({ chord: 0.36, span: 1.64, thick: 0.08, camber: 0.05, rise: 0.06, dip: 0.015 }), carbon, 0, 0, 0, fw);
  const fwFlap = new THREE.Group(); fwFlap.position.set(0, 0.05, 0.27); fw.add(fwFlap);
  add(wingElement({ chord: 0.17, span: 1.6, camber: 0.08, rise: 0.09 }), accent, 0, 0, 0, fwFlap);
  add(wingElement({ chord: 0.13, span: 1.56, camber: 0.08, rise: 0.12 }), plain, 0, 0.055, 0.13, fwFlap);
  for (const s of [-1, 1]) {
    const sh = new THREE.Shape(); sh.moveTo(-0.05, 0); sh.lineTo(0.52, 0); sh.quadraticCurveTo(0.6, 0.12, 0.42, 0.22); sh.lineTo(0.0, 0.17); sh.lineTo(-0.05, 0);
    add(new THREE.ExtrudeGeometry(sh, { depth: 0.012, bevelEnabled: true, bevelSize: 0.003, bevelThickness: 0.003, bevelSegments: 2 }), carbon, s * 0.82 - 0.006, -0.02, 0, fw).rotation.y = -Math.PI / 2;
  }
  for (const s of [-1, 1]) add(new THREE.BoxGeometry(0.012, 0.14, 0.24), satin, s * 0.1, 0.18, -2.85);

  // ---- rear wing: spoon-shaped main plane + two active elements; simplified endplates; swan-neck pylon
  const rw = new THREE.Group(); rw.position.set(0, 0.88, 2.24); car.add(rw);
  add(wingElement({ chord: 0.29, span: 0.98, camber: 0.06, dip: 0.03, rise: 0.02 }), carbon, 0, 0, 0, rw).rotation.x = -0.12;
  const rwActive = new THREE.Group(); rwActive.position.set(0, 0.075, 0.27); rw.add(rwActive);
  add(wingElement({ chord: 0.17, span: 0.96, camber: 0.08, dip: 0.02 }), plain, 0, 0, 0, rwActive);
  add(wingElement({ chord: 0.12, span: 0.94, camber: 0.08, dip: 0.015 }), accent, 0, 0.065, 0.13, rwActive);
  for (const s of [-1, 1]) {
    const sh = new THREE.Shape(); sh.moveTo(0.0, -0.17); sh.lineTo(0.44, -0.08); sh.quadraticCurveTo(0.54, 0.08, 0.47, 0.2); sh.lineTo(0.02, 0.15); sh.quadraticCurveTo(-0.05, 0, 0.0, -0.17);
    add(new THREE.ExtrudeGeometry(sh, { depth: 0.014, bevelEnabled: true, bevelSize: 0.004, bevelThickness: 0.004, bevelSegments: 2 }), carbon, s * 0.5 - 0.007, -0.02, -0.03, rw).rotation.y = -Math.PI / 2;
    add(new THREE.BoxGeometry(0.02, 0.025, 0.06), new THREE.MeshStandardMaterial({ color: 0x220000, emissive: 0xff1a1a, emissiveIntensity: 1.6 }), s * 0.5, 0.2, 0.42, rw);
  }
  const neck = new THREE.CatmullRomCurve3([new THREE.Vector3(0, 0.36, 2.0), new THREE.Vector3(0, 0.7, 2.16), new THREE.Vector3(0, 0.98, 2.3)]);
  add(new THREE.TubeGeometry(neck, 16, 0.02, 8), carbon);
  add(new THREE.BoxGeometry(0.1, 0.05, 0.02), new THREE.MeshStandardMaterial({ color: 0x220000, emissive: 0xff1a1a, emissiveIntensity: 1.6 }), 0, 0.3, 2.47);

  // ---- wheels: tyre, 18-inch rim with spokes, centre-lock nut, partial front wheel cover
  const wheels = [];
  const side = new THREE.MeshStandardMaterial({ map: sidewallTexture(compound), roughness: 0.9 });
  for (const [z, track, w] of [[FRONT_AXLE, TRACK_F, DIMENSIONS.frontTyre], [REAR_AXLE, TRACK_R, DIMENSIONS.rearTyre]]) {
    for (const s of [-1, 1]) {
      const wheel = new THREE.Group(); wheel.position.set(s * track / 2, R_WHEEL, z); car.add(wheel);
      add(tyreGeometry(w), rubber, 0, 0, 0, wheel);
      const sw = add(new THREE.RingGeometry(R_RIM + 0.004, R_WHEEL - 0.004, 72), side, s * (w / 2 + 0.001), 0, 0, wheel); sw.rotation.y = s * Math.PI / 2;
      const barrel = add(new THREE.CylinderGeometry(R_RIM, R_RIM, w - 0.03, 40, 1, true), rimMat, 0, 0, 0, wheel); barrel.rotation.z = Math.PI / 2;
      const face = new THREE.Group(); face.position.x = s * (w / 2 - 0.03); wheel.add(face);
      for (let i = 0; i < 10; i++) {
        const sp = add(new THREE.BoxGeometry(0.018, R_RIM * 0.9, 0.03), rimMat, 0, 0, 0, face);
        sp.rotation.x = (i / 10) * Math.PI * 2; sp.translateY(R_RIM * 0.48);
      }
      add(new THREE.CylinderGeometry(0.045, 0.045, 0.05, 20), new THREE.MeshStandardMaterial({ color: L.accent, metalness: 0.6, roughness: 0.3 }), s * (w / 2 - 0.01), 0, 0, wheel).rotation.z = Math.PI / 2;
      if (z === FRONT_AXLE) { // brake duct / drum fairing
        const duct = add(new THREE.CylinderGeometry(0.16, 0.18, 0.12, 28), carbon, -s * (w / 2 + 0.03), 0, 0, wheel); duct.rotation.z = Math.PI / 2;
      }
      wheels.push(wheel);
      // suspension: carbon wishbones + pushrod
      const inner = (dy, dz) => new THREE.Vector3(s * 0.24, 0.42 + dy, z + dz), outer = (dy) => new THREE.Vector3(s * (track / 2 - w / 2 - 0.05), R_WHEEL + dy, z);
      for (const [a, b] of [[inner(0.1, -0.22), outer(0.12)], [inner(0.1, 0.22), outer(0.12)], [inner(-0.14, -0.22), outer(-0.14)], [inner(-0.14, 0.22), outer(-0.14)], [inner(0.18, 0.05), outer(-0.12)]]) {
        const arm = new THREE.Mesh(new THREE.CapsuleGeometry(0.011, a.distanceTo(b), 4, 8), carbon);
        arm.position.copy(a.clone().add(b).multiplyScalar(0.5)); arm.lookAt(b); arm.rotateX(Math.PI / 2); arm.castShadow = true; car.add(arm);
      }
    }
  }
  car.userData = { wheels, fwFlap, rwActive, mode: "Z" };
  return car;
}

/** 2026 active aero: "X" = low-drag straight-line mode (flaps open), "Z" = high-downforce cornering mode. */
export function setAero(car, mode, t = 1) {
  const target = mode === "X" ? { fw: -0.2, rw: -1.0 } : { fw: 0.35, rw: 0.12 };
  const u = car.userData;
  u.fwFlap.rotation.x += (target.fw - u.fwFlap.rotation.x) * t;
  u.rwActive.rotation.x += (target.rw - u.rwActive.rotation.x) * t;
  u.mode = mode;
}
