// Browser mirror of pitwall/whatif.py. Keep the two in sync: tests/test_whatif_parity.py runs both
// on the same race and plans and requires identical results.

export function actualPlan(sim, driver, fromLap) {
  return (sim.stops[String(driver)] || []).filter((x) => x.lap > fromLap).map((x) => ({ ...x }));
}

export function modelTime(sim, driver, fromLap, plan) {
  const laps = lapTimes(sim, driver, fromLap, plan);
  return laps == null ? null : laps.reduce((a, [, t]) => a + t, 0);
}

// Per-lap model times, [lap, seconds]; the pit loss is booked on the out-lap.
export function lapTimes(sim, driver, fromLap, plan) {
  const key = String(driver);
  if (!(key in sim.finish) || !(key in sim.pace)) return null;
  const nTotal = sim.finish[key][0];
  const st = sim.stints.filter((s) => s.driver === driver).sort((a, b) => a.from - b.from);
  const cur = st.filter((s) => s.from <= fromLap);
  if (!cur.length) return null;
  let comp = cur[cur.length - 1].compound, age = cur[cur.length - 1].age + fromLap - cur[cur.length - 1].from;
  const stops = Object.fromEntries(plan.map((p) => [p.lap, p]));
  const pace = sim.pace[key], fuel = sim.fuel, neutral = sim.neutral_laps[key] || {};
  const out = [];
  for (let n = fromLap + 1; n <= nTotal; n++) {
    let t = 0;
    if (n in stops) {
      const neutralStop = String(n) in neutral || String(n - 1) in neutral;
      t += stops[n].free ? 0 : (neutralStop ? sim.pit_loss_neutral : sim.pit_loss) || 0;
      comp = stops[n].compound; age = 0;
    } else age += 1;
    if (String(n) in neutral) t += neutral[String(n)];
    else t += pace + (sim.offset[comp] ?? 0) + (sim.deg[comp] ?? 0) * age + fuel * n;
    out.push([n, t]);
  }
  return out;
}

export function simulate(sim, driver, fromLap, plan) {
  const key = String(driver);
  const base = modelTime(sim, driver, fromLap, actualPlan(sim, driver, fromLap));
  const next = modelTime(sim, driver, fromLap, plan);
  if (base == null || next == null) return null;
  const actualFinish = sim.finish[key][1], nLaps = sim.finish[key][0];
  const est = actualFinish + (next - base);
  const rivals = Object.entries(sim.finish).filter(([d, v]) => v[0] === nLaps && d !== key).map(([, v]) => v[1]);
  const r3 = (x) => Math.round(x * 1000) / 1000;
  return {
    delta: r3(next - base), estimated_finish: r3(est), actual_finish: actualFinish,
    position_actual: 1 + rivals.filter((t) => t < actualFinish).length,
    position_estimated: 1 + rivals.filter((t) => t < est).length,
  };
}
