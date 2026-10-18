// Wake model behind a 2026 car, for visualisation (car frame: the air moves towards +z).
//
// Physically motivated, not CFD:
//   * velocity deficit: a Gaussian wake whose width grows with distance and whose centre rises
//     (the diffuser and rear wing throw the air upwards — "upwash"),
//   * two counter-rotating rear-wing tip vortices (Lamb–Oseen profile). On a wing that makes downforce
//     the air spills from the upper surface around the tips to the underside, so on each side the
//     flow goes outwards over the top and inwards underneath,
//   * turbulence that is strongest where the deficit is.
// The *strength* of the wake along the track is not invented: it follows the lap-time cost measured
// from 2026 timing data at each gap (``envelope``), normalised to its value right behind the car.

export const SOURCE_Z = 2.5;   // rear wing trailing edge of the leading car (scene units ≈ metres)

/** Wake shape at distance d (metres behind the rear wing) for a given aero mode. */
export function shape(d, mode) {
  const k = mode === "Z" ? 1.25 : 0.8; // more downforce, stronger and wider wake
  return {
    sx: 0.42 + 0.055 * d * (0.8 + 0.2 * k),
    sy: 0.28 + 0.035 * d,
    yc: 0.72 + 0.014 * d,
    xv: 0.5 + 0.004 * d,
    yv: 0.95 + 0.013 * d,
    rc: 0.07 + 0.006 * d,
    gamma: 0.9 * k,
  };
}

/** Velocity (in units of the free-stream speed) and turbulence at (x, y) in the plane d metres behind. */
export function sample(x, y, d, amp, mode, t = 0) {
  const s = shape(d, mode);
  const g = Math.exp(-(x * x) / (2 * s.sx * s.sx) - ((y - s.yc) ** 2) / (2 * s.sy * s.sy));
  const deficit = amp * 0.55 * g;
  let vx = 0, vy = 0.06 * amp * g; // upwash
  for (const side of [-1, 1]) {
    const dx = x - side * s.xv, dy = y - s.yv, r2 = dx * dx + dy * dy + 1e-6;
    const vt = (amp * s.gamma / (2 * Math.PI * Math.sqrt(r2))) * (1 - Math.exp(-r2 / (s.rc * s.rc))) * 0.35;
    const dir = side; // right vortex: outward over the top, inward underneath
    vx += dir * vt * (dy / Math.sqrt(r2));
    vy += -dir * vt * (dx / Math.sqrt(r2));
  }
  const turb = amp * g * 0.9;
  // smooth pseudo-turbulence: a few travelling sinusoids (divergence-free in x–y)
  const ph = d * 0.9 - t * 4;
  vx += turb * 0.25 * (Math.sin(2.7 * y + ph) + 0.6 * Math.sin(4.3 * y - 1.3 * ph));
  vy += turb * 0.25 * (Math.cos(2.9 * x + ph * 1.1) + 0.6 * Math.cos(5.1 * x + 0.7 * ph));
  return { u: 1 - deficit, vx, vy, deficit, turb };
}

/** GLSL version of the deficit + turbulence for the cross-section heat map. */
export const WAKE_GLSL = /* glsl */ `
  float wakeIntensity(vec2 p, float d, float amp, float k, float t) {
    float sx = 0.42 + 0.055 * d * (0.8 + 0.2 * k), sy = 0.28 + 0.035 * d, yc = 0.72 + 0.014 * d;
    float g = exp(-(p.x * p.x) / (2.0 * sx * sx) - pow(p.y - yc, 2.0) / (2.0 * sy * sy));
    float xv = 0.5 + 0.004 * d, yv = 0.95 + 0.013 * d, rc = 0.07 + 0.006 * d;
    float vort = exp(-(pow(p.x - xv, 2.0) + pow(p.y - yv, 2.0)) / (2.0 * rc * rc * 4.0))
               + exp(-(pow(p.x + xv, 2.0) + pow(p.y - yv, 2.0)) / (2.0 * rc * rc * 4.0));
    float n = 0.5 + 0.5 * sin(9.0 * p.x + t * 3.0) * sin(7.0 * p.y - t * 2.3);
    return amp * (0.75 * g * (0.85 + 0.3 * n) + 0.55 * vort * k);
  }
`;
