// Procedural 2026-regulation Formula 1 car for three.js (1 unit = 1 m, car points towards -z).
//
// Proportions follow the 2026 technical regulations: 3.40 m maximum wheelbase, 1.90 m maximum width,
// 18-inch wheels with narrower tyres, a two-element front wing with an active flap, a three-element
// active rear wing with no beam wing and simplified endplates, halo, undercut sidepods and a partly flat floor.
// No team logos or sponsor marks: liveries are colour schemes only.

import * as THREE from "three";

const WHEELBASE = 3.4, FRONT_AXLE = -1.75, REAR_AXLE = FRONT_AXLE + WHEELBASE;
const WHEEL_D = 0.72, FRONT_TYRE_W = 0.28, REAR_TYRE_W = 0.375;
const TRACK_F = 1.52, TRACK_R = 1.49; // wheel centre to wheel centre, keeping overall width ≤ 1.90 m

// ---------------------------------------------------------------- textures
function carbonTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#121315"; g.fillRect(0, 0, 128, 128);
  for (let y = 0; y < 128; y += 8) for (let x = 0; x < 128; x += 8) {
    const odd = ((x + y) / 8) % 2;
    const grad = g.createLinearGradient(x, y, odd ? x + 8 : x, odd ? y : y + 8);
    grad.addColorStop(0, "#1d1f23"); grad.addColorStop(0.5, "#2b2e33"); grad.addColorStop(1, "#16171a");
    g.fillStyle = grad; g.fillRect(x + 0.5, y + 0.5, 7, 7);
  }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(6, 6);
  t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}
function numberTexture(num, fg) {
  const c = document.createElement("canvas"); c.width = 256; c.height = 128;
  const g = c.getContext("2d");  // transparent: the number is painted straight onto the bodywork
  g.fillStyle = fg; g.font = "italic 900 104px system-ui, sans-serif"; g.textAlign = "center"; g.textBaseline = "middle";
  g.fillText(String(num), 128, 70);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}
/** Square, radially drawn sidewall so planar UVs on a ring map correctly (compound colour band + lettering). */
function sidewallTexture(stripe, rOuter, rInner) {
  const N = 512, c = document.createElement("canvas"); c.width = c.height = N;
  const g = c.getContext("2d"), m = N / 2, k = m / rOuter;
  g.fillStyle = "#151515"; g.beginPath(); g.arc(m, m, m, 0, Math.PI * 2); g.fill();
  g.strokeStyle = stripe; g.lineWidth = 0.022 * k; g.beginPath(); g.arc(m, m, (rInner + 0.055) * k, 0, Math.PI * 2); g.stroke();
  g.fillStyle = "#d8d8d8"; g.font = `800 ${0.034 * k}px system-ui`; g.textAlign = "center"; g.textBaseline = "middle";
  for (const base of [0, Math.PI]) {
    const word = "P ZERO", r = (rOuter - 0.05) * k;
    [...word].forEach((ch, i) => {
      const a = base - 0.32 + i * 0.12;
      g.save(); g.translate(m + Math.cos(a) * r, m + Math.sin(a) * r); g.rotate(a + Math.PI / 2); g.fillText(ch, 0, 0); g.restore();
    });
  }
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; return t;
}

// ---------------------------------------------------------------- geometry helpers
/** Loft a smooth body through superellipse cross-sections {z, w, h, y, n}. */
function loft(sections, { around = 40, along = 90, capStart = true, capEnd = true, bottomCut = null } = {}) {
  const zs = sections.map((s) => s.z);
  const curve = new THREE.CatmullRomCurve3(sections.map((s) => new THREE.Vector3(s.w, s.h, s.y)), false, "centripetal");
  const nCurve = new THREE.CatmullRomCurve3(sections.map((s) => new THREE.Vector3(s.n ?? 2.6, 0, 0)));
  const pos = [], idx = [];
  for (let i = 0; i <= along; i++) {
    const u = i / along, z = zs[0] + (zs[zs.length - 1] - zs[0]) * u;
    // map z to curve parameter (sections are not evenly spaced)
    let k = 0; while (k < zs.length - 2 && z > zs[k + 1]) k++;
    const local = (z - zs[k]) / (zs[k + 1] - zs[k] || 1), t = (k + local) / (zs.length - 1);
    const p = curve.getPoint(t), n = nCurve.getPoint(t).x;
    for (let j = 0; j < around; j++) {
      const a = (j / around) * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a);
      let x = (p.x / 2) * Math.sign(ca) * Math.abs(ca) ** (2 / n);
      let y = (p.y / 2) * Math.sign(sa) * Math.abs(sa) ** (2 / n);
      if (bottomCut != null && sa < 0) y *= bottomCut; // flatter underside (the undercut)
      pos.push(x, p.z + y, z);
    }
  }
  for (let i = 0; i < along; i++) for (let j = 0; j < around; j++) {
    const a = i * around + j, b = i * around + ((j + 1) % around), c = a + around, d = b + around;
    idx.push(a, c, b, b, c, d);
  }
  const cap = (ring, flip) => {
    const center = pos.length / 3; let cx = 0, cy = 0, cz = 0;
    for (let j = 0; j < around; j++) { cx += pos[(ring + j) * 3]; cy += pos[(ring + j) * 3 + 1]; cz += pos[(ring + j) * 3 + 2]; }
    pos.push(cx / around, cy / around, cz / around);
    for (let j = 0; j < around; j++) { const a = ring + j, b = ring + ((j + 1) % around); flip ? idx.push(center, b, a) : idx.push(center, a, b); }
  };
  if (capStart) cap(0, false);
  if (capEnd) cap(along * around, true);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3)); g.setIndex(idx); g.computeVertexNormals();
  return g;
}

/** Cambered airfoil extruded along x (span), chord along z. */
function airfoil(chord, span, thick = 0.1, camber = 0.06) {
  const s = new THREE.Shape(), N = 24, up = [], lo = [];
  for (let i = 0; i <= N; i++) {
    const x = (1 - Math.cos((i / N) * Math.PI)) / 2;
    const yt = 5 * thick * (0.2969 * Math.sqrt(x) - 0.126 * x - 0.3516 * x * x + 0.2843 * x ** 3 - 0.1036 * x ** 4);
    const yc = camber * 4 * x * (1 - x);
    up.push([x * chord, (yc + yt) * chord]); lo.push([x * chord, (yc - yt) * chord]);
  }
  s.moveTo(...up[0]); up.slice(1).forEach((p) => s.lineTo(...p)); lo.reverse().forEach((p) => s.lineTo(...p));
  const g = new THREE.ExtrudeGeometry(s, { depth: span, bevelEnabled: false, curveSegments: 4 });
  g.translate(0, 0, -span / 2); g.rotateY(Math.PI / 2); // span along x, chord towards +z
  return g;
}

function tyreGeometry(width) {
  const r = WHEEL_D / 2, rim = 0.23, pts = [];
  const sh = 0.045; // shoulder radius
  pts.push(new THREE.Vector2(rim, -width / 2));
  for (let i = 0; i <= 8; i++) { const a = -Math.PI / 2 + (i / 8) * (Math.PI / 2); pts.push(new THREE.Vector2(r - sh + Math.cos(a) * sh, -width / 2 + sh + Math.sin(a) * sh)); }
  for (let i = 0; i <= 8; i++) { const a = (i / 8) * (Math.PI / 2); pts.push(new THREE.Vector2(r - sh + Math.cos(a) * sh, width / 2 - sh + Math.sin(a) * sh)); }
  pts.push(new THREE.Vector2(rim, width / 2));
  const g = new THREE.LatheGeometry(pts, 48); g.rotateZ(Math.PI / 2); return g;
}

// ---------------------------------------------------------------- car
export const LIVERIES = {
  silver: { body: 0xb8bec6, accent: 0x00d2be, dark: 0x0b0c0e, number: 12, numFg: "#00d2be", numBg: "#0b0c0e" },
  papaya: { body: 0xff8000, accent: 0x0e2b4a, dark: 0x111316, number: 4, numFg: "#ffffff", numBg: "#ff8000" },
};

export function buildCar(liveryName = "silver", { compound = "#ffd400", env = null } = {}) {
  const L = LIVERIES[liveryName];
  const car = new THREE.Group();
  const carbon = new THREE.MeshPhysicalMaterial({ map: carbonTexture(), color: 0xffffff, roughness: 0.45, metalness: 0.2, clearcoat: 0.6, clearcoatRoughness: 0.25 });
  const paint = new THREE.MeshPhysicalMaterial({ color: L.body, metalness: liveryName === "silver" ? 0.75 : 0.25, roughness: 0.32, clearcoat: 1, clearcoatRoughness: 0.08, envMapIntensity: 1.2 });
  const accent = new THREE.MeshPhysicalMaterial({ color: L.accent, metalness: 0.2, roughness: 0.3, clearcoat: 1 });
  const dark = new THREE.MeshStandardMaterial({ color: L.dark, roughness: 0.5, metalness: 0.3 });
  const rubber = new THREE.MeshStandardMaterial({ color: 0x141414, roughness: 0.92 });
  const metal = new THREE.MeshStandardMaterial({ color: 0x9aa0a8, roughness: 0.25, metalness: 0.95 });
  [carbon, paint, accent, dark, metal].forEach((m) => { if (env) m.envMap = env; });
  const add = (geo, mat, x = 0, y = 0, z = 0) => { const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; car.add(m); return m; };

  // survival cell + nose + engine cover as one smooth loft
  add(loft([
    { z: -2.95, w: 0.12, h: 0.10, y: 0.24, n: 2.2 },   // nose tip
    { z: -2.55, w: 0.22, h: 0.18, y: 0.27 },
    { z: -1.95, w: 0.34, h: 0.28, y: 0.34 },
    { z: -1.20, w: 0.52, h: 0.42, y: 0.42 },          // front bulkhead
    { z: -0.55, w: 0.70, h: 0.52, y: 0.48, n: 3.2 },  // cockpit opening area
    { z: 0.10, w: 0.80, h: 0.70, y: 0.55, n: 3.4 },
    { z: 0.70, w: 0.62, h: 0.88, y: 0.62, n: 3 },     // engine cover peak behind the airbox
    { z: 1.45, w: 0.40, h: 0.62, y: 0.55 },
    { z: 2.05, w: 0.24, h: 0.34, y: 0.42 },           // coke-bottle tail
    { z: 2.40, w: 0.16, h: 0.18, y: 0.36 },
  ], { bottomCut: 0.7 }), paint);

  // undercut sidepods (one loft per side)
  for (const s of [-1, 1]) {
    const pod = add(loft([
      { z: -0.55, w: 0.08, h: 0.30, y: 0.44, n: 3 },
      { z: -0.40, w: 0.42, h: 0.36, y: 0.46, n: 4 },   // inlet
      { z: 0.20, w: 0.44, h: 0.34, y: 0.47, n: 4 },
      { z: 0.95, w: 0.30, h: 0.24, y: 0.44, n: 3 },
      { z: 1.55, w: 0.08, h: 0.14, y: 0.38, n: 2.4 },
    ], { bottomCut: 0.35, around: 32, along: 50 }), paint, s * 0.52);
    pod.rotation.y = s * -0.04;
    add(new THREE.BoxGeometry(0.36, 0.2, 0.02), dark, s * 0.53, 0.47, -0.56); // radiator inlet
    // accent stripe along the sidepod shoulder
    const stripe = add(new THREE.BoxGeometry(0.02, 0.05, 1.3), accent, s * 0.74, 0.58, 0.25); stripe.rotation.x = 0.06;
  }

  // airbox / roll hoop and the engine-cover fin
  add(loft([{ z: -0.15, w: 0.10, h: 0.10, y: 1.03 }, { z: 0.05, w: 0.24, h: 0.30, y: 0.98 }, { z: 0.45, w: 0.22, h: 0.36, y: 0.88 }, { z: 0.9, w: 0.08, h: 0.12, y: 0.72 }], { around: 24, along: 30 }), paint);
  add(new THREE.CircleGeometry(0.075, 24), dark, 0, 1.0, -0.05).rotation.y = Math.PI;
  const finShape = new THREE.Shape(); finShape.moveTo(0, 0); finShape.lineTo(1.3, 0); finShape.lineTo(1.3, 0.12); finShape.quadraticCurveTo(0.6, 0.18, 0, 0.32); finShape.lineTo(0, 0);
  const fin = add(new THREE.ExtrudeGeometry(finShape, { depth: 0.012, bevelEnabled: false }), paint, -0.006, 0.86, 0.75); fin.rotation.y = -Math.PI / 2;
  const numMat = new THREE.MeshBasicMaterial({ map: numberTexture(L.number, L.numFg), transparent: true, depthWrite: false });
  for (const s of [-1, 1]) {  // race number on both sides of the engine-cover fin
    const n = new THREE.Mesh(new THREE.PlaneGeometry(0.34, 0.17), numMat); n.position.set(s * 0.012, 0.97, 1.2); n.rotation.y = s * Math.PI / 2; car.add(n);
  }
  add(new THREE.BoxGeometry(0.06, 0.035, 0.11), dark, 0, 1.1, -0.05); // T-camera

  // cockpit, driver helmet, halo
  add(new THREE.SphereGeometry(0.15, 24, 16), new THREE.MeshPhysicalMaterial({ color: 0xf2f2f2, clearcoat: 1, roughness: 0.2 }), 0, 0.82, -0.38);
  add(new THREE.BoxGeometry(0.2, 0.05, 0.13), new THREE.MeshPhysicalMaterial({ color: 0x111111, roughness: 0.05, metalness: 0.6 }), 0, 0.84, -0.5); // visor
  const haloCurve = new THREE.CatmullRomCurve3([new THREE.Vector3(-0.34, 0.74, 0.1), new THREE.Vector3(-0.33, 0.92, -0.25), new THREE.Vector3(0, 0.97, -0.52), new THREE.Vector3(0.33, 0.92, -0.25), new THREE.Vector3(0.34, 0.74, 0.1)]);
  add(new THREE.TubeGeometry(haloCurve, 40, 0.032, 12), dark);
  const pillar = add(new THREE.CylinderGeometry(0.025, 0.035, 0.3, 12), dark, 0, 0.82, -0.62); pillar.rotation.x = 0.55;
  for (const s of [-1, 1]) { // mirrors
    add(new THREE.BoxGeometry(0.16, 0.06, 0.04), dark, s * 0.5, 0.74, -0.62);
    add(new THREE.CylinderGeometry(0.01, 0.01, 0.14, 8), dark, s * 0.44, 0.68, -0.62).rotation.z = s * 0.9;
  }

  // floor, edge wings, plank and diffuser
  const floorShape = new THREE.Shape();
  floorShape.moveTo(-0.55, -1.25); floorShape.lineTo(0.55, -1.25); floorShape.lineTo(0.70, -0.6); floorShape.lineTo(0.70, 1.05);
  floorShape.quadraticCurveTo(0.62, 1.4, 0.48, 1.55); floorShape.lineTo(-0.48, 1.55); floorShape.quadraticCurveTo(-0.62, 1.4, -0.70, 1.05); floorShape.lineTo(-0.70, -0.6); floorShape.lineTo(-0.55, -1.25);
  const floor = add(new THREE.ExtrudeGeometry(floorShape, { depth: 0.025, bevelEnabled: false }), carbon, 0, 0.06, 0); floor.rotation.x = Math.PI / 2;
  const diff = add(new THREE.BoxGeometry(0.95, 0.02, 0.5), carbon, 0, 0.13, 1.78); diff.rotation.x = -0.28;
  for (const s of [-1, 1]) add(new THREE.BoxGeometry(0.02, 0.22, 0.5), carbon, s * 0.48, 0.17, 1.78);
  add(new THREE.BoxGeometry(0.3, 0.01, 2.4), new THREE.MeshStandardMaterial({ color: 0x8a6a3a, roughness: 0.8 }), 0, 0.045, 0.2); // plank

  // ---------------- front wing: main plane + active flap (2026: two-element flap, narrower)
  const fw = new THREE.Group(); fw.position.set(0, 0.11, -2.92); car.add(fw);
  const fwMain = new THREE.Mesh(airfoil(0.34, 1.62, 0.09, 0.05), carbon); fwMain.castShadow = true; fw.add(fwMain);
  const fwFlap = new THREE.Group(); fwFlap.position.set(0, 0.06, 0.24); fw.add(fwFlap);
  const flap1 = new THREE.Mesh(airfoil(0.17, 1.56, 0.1, 0.07), accent); flap1.castShadow = true; fwFlap.add(flap1);
  const flap2 = new THREE.Mesh(airfoil(0.13, 1.5, 0.1, 0.07), paint); flap2.position.set(0, 0.06, 0.11); flap2.castShadow = true; fwFlap.add(flap2);
  for (const s of [-1, 1]) {
    const epShape = new THREE.Shape(); epShape.moveTo(0, 0); epShape.lineTo(0.5, 0); epShape.quadraticCurveTo(0.52, 0.1, 0.38, 0.15); epShape.lineTo(0.05, 0.12); epShape.lineTo(0, 0);
    const ep = new THREE.Mesh(new THREE.ExtrudeGeometry(epShape, { depth: 0.014, bevelEnabled: false }), carbon);
    ep.rotation.y = -Math.PI / 2; ep.position.set(s * 0.81 - 0.007, -0.03, -0.04); ep.castShadow = true; fw.add(ep);
  }
  for (const s of [-1, 1]) { const p = add(new THREE.BoxGeometry(0.02, 0.17, 0.2), carbon, s * 0.12, 0.2, -2.72); p.rotation.x = 0.3; } // wing pylons

  // ---------------- rear wing: three elements, active upper elements, no beam wing
  const rw = new THREE.Group(); rw.position.set(0, 0.93, 2.28); car.add(rw);
  const rwMain = new THREE.Mesh(airfoil(0.3, 0.98, 0.1, 0.06), carbon); rwMain.rotation.x = -0.1; rwMain.castShadow = true; rw.add(rwMain);
  const rwActive = new THREE.Group(); rwActive.position.set(0, 0.08, 0.26); rw.add(rwActive);
  const rwE2 = new THREE.Mesh(airfoil(0.17, 0.96, 0.1, 0.07), paint); rwE2.castShadow = true; rwActive.add(rwE2);
  const rwE3 = new THREE.Mesh(airfoil(0.12, 0.94, 0.1, 0.07), accent); rwE3.position.set(0, 0.07, 0.12); rwE3.castShadow = true; rwActive.add(rwE3);
  for (const s of [-1, 1]) { // simplified 2026 endplates: a curved blade, no louvres or beam-wing connection
    const sh = new THREE.Shape(); sh.moveTo(0, -0.22); sh.lineTo(0.42, -0.1); sh.quadraticCurveTo(0.52, 0.12, 0.44, 0.22); sh.lineTo(-0.02, 0.18); sh.quadraticCurveTo(-0.06, 0, 0, -0.22);
    const ep = new THREE.Mesh(new THREE.ExtrudeGeometry(sh, { depth: 0.016, bevelEnabled: true, bevelSize: 0.004, bevelThickness: 0.004, bevelSegments: 2 }), carbon);
    ep.rotation.y = -Math.PI / 2; ep.position.set(s * 0.5 - 0.008, -0.02, -0.03); ep.castShadow = true; rw.add(ep);
  }
  const pylon = add(new THREE.BoxGeometry(0.03, 0.55, 0.16), carbon, 0, 0.62, 2.25); pylon.rotation.x = -0.2; // swan-neck pylon
  const rainLight = add(new THREE.BoxGeometry(0.12, 0.05, 0.02), new THREE.MeshStandardMaterial({ color: 0x330000, emissive: 0xff1010, emissiveIntensity: 0 }), 0, 0.3, 2.48);
  for (const s of [-1, 1]) add(new THREE.BoxGeometry(0.035, 0.035, 0.02), rainLight.material, s * 0.49, 0.72, 2.5); // 2026 wing-endplate lights

  // ---------------- wheels, wheel covers, suspension
  const wheels = [];
  const tyreSide = new THREE.MeshStandardMaterial({ map: sidewallTexture(compound, 0.355, 0.235), roughness: 0.85 });
  for (const [z, track, w] of [[FRONT_AXLE, TRACK_F, FRONT_TYRE_W], [REAR_AXLE, TRACK_R, REAR_TYRE_W]]) {
    for (const s of [-1, 1]) {
      const wheel = new THREE.Group(); wheel.position.set(s * track / 2, WHEEL_D / 2, z); car.add(wheel);
      const tyre = new THREE.Mesh(tyreGeometry(w), rubber); tyre.castShadow = true; wheel.add(tyre);
      const side = new THREE.Mesh(new THREE.RingGeometry(0.235, 0.355, 64), tyreSide); side.rotation.y = s * Math.PI / 2; side.position.x = s * (w / 2 + 0.002); wheel.add(side);
      const cover = new THREE.Mesh(new THREE.CircleGeometry(0.235, 40), new THREE.MeshPhysicalMaterial({ color: L.dark, metalness: 0.5, roughness: 0.4, clearcoat: 0.6 }));
      cover.rotation.y = s * Math.PI / 2; cover.position.x = s * (w / 2 + 0.001); wheel.add(cover);
      const hub = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.05, w + 0.04, 16), metal); hub.rotation.z = Math.PI / 2; wheel.add(hub);
      wheels.push(wheel);
      // wishbones from the chassis to the upright
      const inner = new THREE.Vector3(s * 0.25, 0.42, z), outer = new THREE.Vector3(s * (track / 2 - w / 2 - 0.04), 0.42, z);
      for (const [dy, dz] of [[0.08, -0.12], [0.08, 0.12], [-0.12, -0.12], [-0.12, 0.12]]) {
        const a = inner.clone().add(new THREE.Vector3(0, dy, dz)), b = outer.clone().add(new THREE.Vector3(0, dy * 0.6, 0));
        const arm = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, a.distanceTo(b), 8), carbon);
        arm.position.copy(a.clone().add(b).multiplyScalar(0.5)); arm.lookAt(b); arm.rotateX(Math.PI / 2); car.add(arm);
      }
    }
  }
  car.userData = { wheels, fwFlap, rwActive, rainLight, mode: "Z" };
  return car;
}

/** 2026 active aero: "X" = low-drag straight-line mode (flaps open), "Z" = high-downforce cornering mode. */
export function setAero(car, mode, t = 1) {
  const target = mode === "X" ? { fw: -0.18, rw: -0.95 } : { fw: 0.38, rw: 0.15 };
  const u = car.userData;
  u.fwFlap.rotation.x += (target.fw - u.fwFlap.rotation.x) * t;
  u.rwActive.rotation.x += (target.rw - u.rwActive.rotation.x) * t;
  u.mode = mode;
}
