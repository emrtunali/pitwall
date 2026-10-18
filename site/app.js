import { simulate, lapTimes, actualPlan } from "./whatif.mjs";
// Pitwall front-end: track replay (canvas), live timing board, and SVG analysis charts.
// No build step and no dependencies; data comes from data/<year>/<race>/{race.json,positions.bin}.

const YEAR = 2026;
const COMPOUND = { SOFT: "#ff3b3b", MEDIUM: "#ffd400", HARD: "#f2f2f2", INTERMEDIATE: "#39b54a", WET: "#2f7de1" };
const NEUTRAL = { SC: "#ffcc00", VSC: "#ff9f1a", RED: "#ff3b30" };
const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";

const S = {
  index: null, race: null, pos: null, t: 0, playing: false, speed: 16, focus: null,
  selected: new Set(), chart: "win", showPasses: false, gapMode: "leader", lastFrame: 0, derived: null,
};

// ---------- helpers ----------
const fmtClock = (s) => {
  s = Math.max(0, s);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = Math.floor(s % 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}`;
};
const fmtLap = (s) => (s == null ? "–" : `${Math.floor(s / 60)}:${(s % 60).toFixed(3).padStart(6, "0")}`);
function bisect(arr, t, key = (x) => x[0]) { // index of last element with key <= t, or -1
  let lo = 0, hi = arr.length - 1, ans = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (key(arr[mid]) <= t) { ans = mid; lo = mid + 1; } else hi = mid - 1; }
  return ans;
}
function el(tag, attrs = {}, parent) {
  const e = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
}
const scale = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);
function niceTicks(min, max, n = 6) {
  const span = max - min || 1, step0 = span / n, mag = 10 ** Math.floor(Math.log10(step0));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= n) || 10 * mag;
  const out = []; for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

// ---------- data ----------
async function loadIndex() {
  S.index = await (await fetch(`data/${YEAR}/index.json`)).json();
  const nx = S.index.next_race, upd = S.index.updated_at;
  if (upd) {
    let txt = `Data ${upd.slice(0, 10)}`;
    if (nx) { const days = Math.ceil((new Date(nx.start) - new Date()) / 864e5); txt += ` · next: ${nx.circuit} in ${days}d`; }
    $("status").textContent = txt;
  }
  const sel = $("raceSelect");
  sel.innerHTML = "";
  [...S.index.races].reverse().forEach((r) => {
    const o = document.createElement("option");
    o.value = r.slug; o.textContent = `${r.date.slice(5)} · ${r.name}`;
    sel.appendChild(o);
  });
}

async function loadRace(slug) {
  $("loading").hidden = false;
  S.playing = false; updatePlay();
  const base = `data/${YEAR}/${slug}`;
  const [race, buf] = await Promise.all([
    fetch(`${base}/race.json`).then((r) => r.json()),
    fetch(`${base}/positions.bin`).then((r) => r.arrayBuffer()),
  ]);
  S.race = race; S.pos = new Int16Array(buf);
  S.derived = derive(race);
  const finishers = [...race.results].filter((r) => r.pos).sort((a, b) => a.pos - b.pos);
  S.selected = new Set(finishers.slice(0, 5).map((r) => r.driver));
  S.focus = null;
  S.t = S.derived.lapStart1 - 30;
  $("raceSelect").value = slug;
  history.replaceState(null, "", `#race=${slug}`);
  $("lapTotal").textContent = `/ ${race.meta.total_laps}`;
  $("loading").hidden = true;
  resizeCanvas(); drawTimeline(); renderChart(); renderFrame();
}

function derive(race) {
  const d = { byNum: {}, idx: {}, lapStarts: {}, lapEnds: {}, posTl: {}, intervals: {}, stints: {}, pits: {} };
  race.drivers.forEach((x, i) => { d.byNum[x.num] = x; d.idx[x.num] = i; });
  for (const [num, laps] of Object.entries(race.laps)) {
    d.lapStarts[num] = laps.map((l) => [l[1], l[0]]);
    d.lapEnds[num] = {};
    laps.forEach((l, i) => {
      const next = laps[i + 1];
      const end = l[2] != null ? l[1] + l[2] : next ? next[1] : null;
      if (end != null) d.lapEnds[num][l[0]] = end;
    });
  }
  for (const [t, num, p] of race.positions_timeline) (d.posTl[num] ||= []).push([t, p]);
  for (const [num, arr] of Object.entries(race.intervals)) d.intervals[num] = arr;
  for (const s of race.stints) (d.stints[s.driver] ||= []).push(s);
  for (const p of race.pits) (d.pits[p.driver] ||= []).push(p);
  const all = Object.values(d.lapStarts).flat();
  d.lapStart1 = Math.min(...all.filter((x) => x[1] === 1).map((x) => x[0]));
  // leader lap start times (first car to start each lap) -> lap counter and timeline ticks
  d.leaderLapStart = [];
  for (const [t, n] of all) if (!d.leaderLapStart[n] || t < d.leaderLapStart[n]) d.leaderLapStart[n] = t;
  d.order = race.drivers.map((x) => x.num);
  // per-lap classification from timing: order by time each car completed lap n
  d.lapOrder = [];
  for (let n = 1; n <= race.meta.total_laps; n++) {
    const row = d.order.filter((num) => d.lapEnds[num]?.[n] != null).map((num) => [num, d.lapEnds[num][n]]);
    row.sort((a, b) => a[1] - b[1]);
    d.lapOrder[n] = row;
  }
  return d;
}

// ---------- state at time t ----------
function lapOf(num, t) {
  const arr = S.derived.lapStarts[num]; if (!arr) return 0;
  const i = bisect(arr, t); return i < 0 ? 0 : arr[i][1];
}
function leaderLap(t) {
  const ls = S.derived.leaderLapStart; let lap = 0;
  for (let n = 1; n < ls.length; n++) if (ls[n] != null && ls[n] <= t) lap = n;
  return Math.min(lap, S.race.meta.total_laps);
}
function positionOf(num, t) {
  const arr = S.derived.posTl[num]; if (!arr) return 99;
  const i = bisect(arr, t); return i < 0 ? arr[0][1] : arr[i][1];
}
function intervalOf(num, t) {
  const arr = S.derived.intervals[num]; if (!arr) return null;
  const i = bisect(arr, t); return i < 0 ? null : arr[i];
}
function tyreOf(num, lap) {
  const st = S.derived.stints[num] || [];
  const s = st.find((x) => x.from <= Math.max(lap, 1) && Math.max(lap, 1) <= (x.to ?? 999)) || st[st.length - 1];
  return s ? { compound: s.compound, age: (s.age || 0) + Math.max(lap, 1) - s.from } : null;
}
function inPit(num, t) {
  // stop times come from the out-lap start (the timing line is in the pit lane); ±12 s covers the box
  return (S.derived.pits[num] || []).some((p) => p.t != null && t >= p.t - 12 && t <= p.t + 12);
}
function neutralAt(t) { return S.race.neutral.find(([a, b]) => t >= a && t <= b); }
function finishedAt(num, t) {
  const res = S.race.results.find((r) => r.driver === num);
  const last = res?.laps; if (!last) return false;
  const end = S.derived.lapEnds[num]?.[last];
  return end != null && t > end + 2;
}
function carXY(i, t) {
  const m = S.race.meta.positions, n = m.samples;
  const s = (t - m.t_first) * m.hz; const k = Math.floor(s);
  if (k < 0 || k >= n - 1) return null;
  const f = s - k, o = (i * n + k) * 2, o2 = o + 2, P = S.pos;
  if (P[o] === m.missing || P[o2] === m.missing) return null;
  return [P[o] + (P[o2] - P[o]) * f, P[o + 1] + (P[o2 + 1] - P[o + 1]) * f];
}

// ---------- track canvas ----------
const cv = $("track"), ctx = cv.getContext("2d");
let view = null;
function resizeCanvas() {
  const r = cv.parentElement.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = r.width * dpr; cv.height = r.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  if (!S.race) return;
  const pts = S.race.track.outline;
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = 46, w = r.width - 2 * pad, h = r.height - 2 * pad - 30;
  const k = Math.min(w / (x1 - x0), h / (y1 - y0));
  const ox = pad + (w - k * (x1 - x0)) / 2, oy = pad + 10 + (h - k * (y1 - y0)) / 2;
  view = { k, tx: (x) => ox + (x - x0) * k, ty: (y) => oy + (y1 - y) * k, w: r.width, h: r.height };
}
function drawTrack(neutral) {
  const pts = S.race.track.outline;
  const path = () => { ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo : ctx.moveTo).call(ctx, view.tx(x), view.ty(y))); ctx.closePath(); };
  ctx.lineJoin = ctx.lineCap = "round";
  path(); ctx.strokeStyle = neutral ? NEUTRAL[neutral[2]] + "55" : "#ffffff10"; ctx.lineWidth = 22; ctx.stroke();
  path(); ctx.strokeStyle = "#3a404b"; ctx.lineWidth = 9; ctx.stroke();
  path(); ctx.strokeStyle = "#596172"; ctx.lineWidth = 1.2; ctx.stroke();
  const [sx, sy] = S.race.track.start, [nx, ny] = pts[1];
  const ang = Math.atan2(view.ty(ny) - view.ty(sy), view.tx(nx) - view.tx(sx)) + Math.PI / 2;
  ctx.save(); ctx.translate(view.tx(sx), view.ty(sy)); ctx.rotate(ang);
  for (let i = -3; i < 3; i++) { ctx.fillStyle = i % 2 ? "#fff" : "#111"; ctx.fillRect(i * 2.5, -2, 2.5, 4); }
  ctx.restore();
}
function renderFrame() {
  if (!S.race || !view) return;
  const t = S.t, neutral = neutralAt(t);
  ctx.clearRect(0, 0, view.w, view.h);
  drawTrack(neutral);
  const cars = [];
  S.race.drivers.forEach((d, i) => {
    if (finishedAt(d.num, t)) return;
    const xy = carXY(i, t); if (xy) cars.push({ d, x: view.tx(xy[0]), y: view.ty(xy[1]), pos: positionOf(d.num, t) });
  });
  if (S.showPasses) drawPasses(t);
  cars.sort((a, b) => b.pos - a.pos); // leader drawn last (on top)
  for (const c of cars) {
    const focus = S.focus === c.d.num;
    ctx.beginPath(); ctx.arc(c.x, c.y, focus ? 9 : 7, 0, Math.PI * 2);
    ctx.fillStyle = c.d.colour; ctx.fill();
    ctx.lineWidth = focus ? 3 : 1.5; ctx.strokeStyle = focus ? "#fff" : "#0d0f12"; ctx.stroke();
    if (c.pos <= 10 || focus) {
      ctx.font = `700 ${focus ? 12 : 10.5}px system-ui`; ctx.fillStyle = "#eef0f3";
      ctx.fillText(c.d.code, c.x + 10, c.y - 8);
    }
  }
  const lap = leaderLap(t);
  $("lapNow").textContent = lap || "–";
  const f = $("flag"); f.className = "flag " + (neutral ? neutral[2] : ""); f.textContent = neutral ? { SC: "SAFETY CAR", VSC: "VIRTUAL SAFETY CAR", RED: "RED FLAG" }[neutral[2]] : "";
  const w = S.race.weather[Math.max(0, bisect(S.race.weather, t))];
  $("weather").textContent = w ? `AIR ${w[1]}°  TRACK ${w[2]}°${w[3] ? "  RAIN" : ""}` : "";
  $("clock").textContent = fmtClock(t - S.derived.lapStart1);
  renderTicker(t); renderBoard(t); updateScrub(); updateCursor(lap);
}

function drawPasses(t) {
  for (const p of S.race.insights.overtakes) {
    if (p.x == null || p.t > t) continue;
    const age = t - p.t, fresh = age < 20;
    const d = S.derived.byNum[p.by];
    ctx.beginPath(); ctx.arc(view.tx(p.x), view.ty(p.y), fresh ? 10 - age / 4 : 3.5, 0, Math.PI * 2);
    ctx.fillStyle = fresh ? d.colour : "#ffffff55"; ctx.globalAlpha = fresh ? 0.55 : 1; ctx.fill(); ctx.globalAlpha = 1;
    if (fresh) { ctx.font = "700 10px system-ui"; ctx.fillStyle = "#fff"; ctx.fillText(`${d.code} ▸ ${S.derived.byNum[p.on]?.code ?? ""}`, view.tx(p.x) + 12, view.ty(p.y) + 14); }
  }
}
function renderTicker(t) {
  const rc = S.race.race_control; const i = bisect(rc, t);
  const items = rc.slice(Math.max(0, i - 3), i + 1).filter((m) => t - m[0] < 90 && m[4]);
  const ul = $("ticker"); const key = items.map((m) => m[0]).join();
  if (ul.dataset.key === key) return; ul.dataset.key = key; ul.innerHTML = "";
  for (const [, lap, cat, flag, msg] of items) {
    const li = document.createElement("li"); li.className = `${cat} ${flag || ""}`;
    li.innerHTML = `<b>L${lap ?? "-"}</b>`; li.append(msg); ul.appendChild(li);
  }
}

const fmtPct = (p) => (p >= 0.995 ? ">99%" : p < 0.005 ? "<1%" : `${Math.round(p * 100)}%`);
function winAt(lap) { // calibrated win probability at the end of the given leader lap
  const W = S.race.win_probability; if (!W || !W.laps.length || lap < W.laps[0]) return {};
  let i = W.laps.length - 1; while (i > 0 && W.laps[i] > lap) i--;
  const out = {}; for (const [num, arr] of Object.entries(W.win)) out[num] = arr[i];
  // drivers outside the published series are below 3 % all race
  for (const d of S.race.drivers) if (out[d.num] == null) out[d.num] = 0;
  return out;
}
function renderBoard(t) {
  const lap = leaderLap(t);
  const wp = winAt(lap - 1);
  const rows = S.race.drivers.map((d) => ({ d, pos: positionOf(d.num, t), iv: intervalOf(d.num, t), lap: lapOf(d.num, t) }));
  rows.sort((a, b) => a.pos - b.pos);
  const ol = $("leaderboard");
  if (ol.children.length !== rows.length) ol.innerHTML = rows.map(() => "<li></li>").join("");
  rows.forEach((r, k) => {
    const li = ol.children[k];
    const ty = tyreOf(r.d.num, r.lap);
    const res = S.race.results.find((x) => x.driver === r.d.num);
    const out = res && (res.dnf || res.dns) && t > (S.derived.lapEnds[r.d.num]?.[res.laps] ?? Infinity);
    let gap = "";
    if (r.pos === 1 && lap > 0) gap = "LEADER";
    else if (r.iv) { const v = S.gapMode === "leader" ? r.iv[1] : r.iv[2]; gap = typeof v === "string" ? v : v != null ? `+${v.toFixed(1)}` : ""; }
    li.className = (S.focus === r.d.num ? "sel " : "") + (out ? "out" : "");
    li.dataset.num = r.d.num;
    li.innerHTML = `<span class="pos">${r.pos < 99 ? r.pos : "–"}</span>
      <span class="drv"><i style="background:${r.d.colour}"></i>${r.d.code} <small>${r.d.team}</small></span>
      <span class="gap">${out ? "OUT" : inPit(r.d.num, t) ? '<span class="pitflag">IN PIT</span>' : gap}</span>
      <span class="tyre">${ty ? `<i class="c-${ty.compound}"></i>${ty.age}` : ""}</span>
      <span class="win ${wp[r.d.num] >= 0.2 ? "hot" : ""}">${wp[r.d.num] != null ? fmtPct(wp[r.d.num]) : ""}</span>`;
  });
}

// ---------- transport ----------
function updatePlay() { $("play").textContent = S.playing ? "❚❚" : "▶"; }
function bounds() { return [S.derived.lapStart1 - 60, S.race.meta.t_end + 20]; }
function updateScrub() {
  const [a, b] = bounds(); $("scrub").value = ((S.t - a) / (b - a)) * 1000;
  if (!S.tlImage) return;
  const c = $("timelineCanvas"), g = c.getContext("2d"), dpr = window.devicePixelRatio || 1, w = c.width / dpr;
  g.putImageData(S.tlImage, 0, 0);
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const x = ((S.t - a) / (b - a)) * w;
  g.fillStyle = "#fff"; g.fillRect(x - 1, 4, 2, 30);
}
function drawTimeline() {
  const c = $("timelineCanvas"), dpr = window.devicePixelRatio || 1, r = c.getBoundingClientRect();
  if (!r.width) return; // replay view hidden (season tab): nothing to draw
  c.width = r.width * dpr; c.height = r.height * dpr;
  const g = c.getContext("2d"); g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const [a, b] = bounds(), X = scale(a, b, 0, r.width);
  g.fillStyle = "#1c2027"; g.fillRect(0, 14, r.width, 10);
  for (const [s, e, kind] of S.race.neutral) { g.fillStyle = NEUTRAL[kind]; g.fillRect(X(s), 14, Math.max(2, X(e) - X(s)), 10); }
  g.fillStyle = "#8b93a1"; g.font = "10px ui-monospace, Menlo"; g.textAlign = "center";
  S.derived.leaderLapStart.forEach((t, n) => {
    if (t == null) return;
    g.fillStyle = n % 10 === 0 || n === 1 ? "#8b93a1" : "#ffffff22";
    g.fillRect(X(t), 26, 1, n % 10 === 0 ? 6 : 3);
    if (n % 10 === 0 || n === 1) g.fillText(`L${n}`, X(t), 10);
  });
  const fp = S.focus ?? S.race.results.find((x) => x.pos === 1)?.driver;
  for (const p of S.derived.pits[fp] || []) { g.fillStyle = "#e10600"; g.fillRect(X(p.t) - 1.5, 26, 3, 8); }
  S.tlImage = g.getImageData(0, 0, c.width, c.height);
}
function tick(now) {
  if (S.playing) {
    const dt = Math.min(0.1, (now - S.lastFrame) / 1000);
    S.t += dt * S.speed;
    const [, b] = bounds();
    if (S.t >= b) { S.t = b; S.playing = false; updatePlay(); }
    renderFrame();
  }
  S.lastFrame = now;
  requestAnimationFrame(tick);
}

// ---------- charts ----------
function frame(host, H = 340, M = { l: 52, r: 70, t: 14, b: 30 }) {
  host.innerHTML = "";
  const W = Math.max(320, host.clientWidth);
  const svg = el("svg", { viewBox: `0 0 ${W} ${H}` }, host);
  return { svg, W, H, M, iw: W - M.l - M.r, ih: H - M.t - M.b };
}
function axes(f, X, Y, xt, yt, fmtY = (v) => v) {
  const g = el("g", { class: "axis" }, f.svg);
  for (const v of yt) {
    el("line", { x1: f.M.l, x2: f.W - f.M.r, y1: Y(v), y2: Y(v) }, g);
    el("text", { x: f.M.l - 8, y: Y(v) + 4, "text-anchor": "end" }, g).textContent = fmtY(v);
  }
  for (const v of xt) el("text", { x: X(v), y: f.H - 8, "text-anchor": "middle" }, g).textContent = v;
}
function neutralLaps() { // map neutral time windows to leader-lap spans
  const ls = S.derived.leaderLapStart;
  return S.race.neutral.map(([a, b, k]) => {
    let la = 1, lb = 1;
    ls.forEach((t, n) => { if (t != null && t <= a) la = n; if (t != null && t <= b) lb = n; });
    return [la, lb + 1, k];
  });
}
function renderLegend() {
  const host = $("legend"); host.innerHTML = "";
  if (!["gaps", "positions", "pace"].includes(S.chart)) return;
  const order = [...S.race.results].sort((a, b) => (a.pos ?? 99) - (b.pos ?? 99)).map((r) => r.driver);
  for (const num of order) {
    const d = S.derived.byNum[num]; if (!d) continue;
    const b = document.createElement("button");
    b.className = S.selected.has(num) ? "on" : "";
    b.innerHTML = `<i style="background:${d.colour}"></i>${d.code}`;
    b.onclick = () => { S.selected.has(num) ? S.selected.delete(num) : S.selected.add(num); renderChart(); };
    host.appendChild(b);
  }
}
const HELP = {
  win: "Live win probability after every lap. A Monte Carlo race simulator that only uses data available at that moment (pace model refitted each lap, tyres, mandatory stops, pit loss, Safety Car and retirement risk), calibrated on the first 8 races of the season. See results/WINPROB.md for how well calibrated it is.",
  gaps: "Seconds behind the leader at the end of every lap, computed from official lap timing. Click drivers below to compare; the dashed line follows the replay.",
  positions: "Running order at the end of each lap. Shaded bands are Safety Car / VSC periods.",
  strategy: "Every stint by compound, in finishing order. Numbers are tyre age at the start of a stint when tyres were used before.",
  pace: "Clean green-flag laps (dots) and the race-pace model (line): driver pace + compound offset + degradation × tyre age + fuel/track evolution × lap. Excludes lap 1, in/out laps and neutralised laps.",
  sim: "Rewrite a driver's strategy and see where they would have finished. Estimate = real finish + (model time with your plan − model time with the real plan), so the model's own error cancels; rivals keep their real race and traffic is not simulated. Safety Car laps keep the field's real pace.",
  window: "What the model thinks each pit stop was worth: total race time if that stop had been made on a different lap, everything else unchanged. Negative = faster. A strategy model, not a prediction of what would have happened in traffic.",
};
function renderChart() {
  document.querySelectorAll("#chartTabs button").forEach((b) => b.classList.toggle("on", b.dataset.chart === S.chart));
  $("chartHelp").textContent = HELP[S.chart];
  ({ win: chartWin, gaps: chartGaps, positions: chartPositions, strategy: chartStrategy, pace: chartPace, window: chartWindow, sim: chartSim })[S.chart]();
  renderLegend(); updateCursor(leaderLap(S.t));
}
let cursorFn = null;
function updateCursor(lap) { if (cursorFn) cursorFn(lap); }
function addCursor(f, X) {
  const line = el("line", { class: "cursor", y1: f.M.t, y2: f.H - f.M.b }, f.svg);
  cursorFn = (lap) => { const x = X(Math.max(1, lap)); line.setAttribute("x1", x); line.setAttribute("x2", x); };
}
function shadeNeutral(f, X) {
  for (const [a, b, k] of neutralLaps()) el("rect", { x: X(a), y: f.M.t, width: Math.max(2, X(b) - X(a)), height: f.ih, fill: NEUTRAL[k], opacity: 0.08 }, f.svg);
}
function chartWin() {
  const W = S.race.win_probability, f = frame($("chart"), 340, { l: 52, r: 80, t: 14, b: 30 }), N = S.race.meta.total_laps;
  if (!W || !W.laps.length) { $("chart").innerHTML = '<p class="note">Not enough data to simulate this race.</p>'; return; }
  const X = scale(1, N, f.M.l, f.W - f.M.r), Y = scale(0, 1, f.H - f.M.b, f.M.t);
  shadeNeutral(f, X); axes(f, X, Y, niceTicks(1, N, 10), [0, 0.25, 0.5, 0.75, 1], (v) => `${v * 100}%`);
  const placed = [];
  const order = Object.entries(W.win).sort((a, b) => b[1][b[1].length - 1] - a[1][a[1].length - 1]);
  for (const [num, arr] of order) {
    const d = S.derived.byNum[num]; if (!d) continue;
    el("path", { d: "M" + W.laps.map((l, i) => `${X(l)},${Y(arr[i])}`).join("L"), stroke: d.colour, "stroke-width": 2.2, fill: "none" }, f.svg);
    let y = Y(arr[arr.length - 1]) + 4; while (placed.some((p) => Math.abs(p - y) < 12)) y -= 12; placed.push(y);
    el("text", { x: X(W.laps[W.laps.length - 1]) + 6, y, class: "label", fill: d.colour }, f.svg).textContent = `${d.code} ${fmtPct(arr[arr.length - 1])}`;
  }
  addCursor(f, X);
}
function chartGaps() {
  const f = frame($("chart")), N = S.race.meta.total_laps, D = S.derived;
  const series = [...S.selected].map((num) => {
    const pts = [];
    for (let n = 1; n <= N; n++) { const row = D.lapOrder[n]; const me = D.lapEnds[num]?.[n]; if (row?.length && me != null) pts.push([n, me - row[0][1]]); }
    return { num, pts };
  });
  const maxG = Math.min(120, Math.max(5, ...series.flatMap((s) => s.pts.map((p) => p[1]))));
  const X = scale(1, N, f.M.l, f.W - f.M.r), Y = scale(0, maxG, f.M.t, f.H - f.M.b);
  shadeNeutral(f, X); axes(f, X, Y, niceTicks(1, N, 10), niceTicks(0, maxG, 6), (v) => `+${v}s`);
  for (const s of series) {
    const d = D.byNum[s.num];
    el("path", { d: "M" + s.pts.map((p) => `${X(p[0])},${Y(Math.min(p[1], maxG))}`).join("L"), fill: "none", stroke: d.colour, "stroke-width": 2 }, f.svg);
    const last = s.pts[s.pts.length - 1];
    if (last) el("text", { x: X(last[0]) + 6, y: Y(Math.min(last[1], maxG)) + 4, class: "label", fill: d.colour }, f.svg).textContent = d.code;
  }
  addCursor(f, X);
}
function chartPositions() {
  const f = frame($("chart"), 420), N = S.race.meta.total_laps, D = S.derived, n0 = D.order.length;
  const X = scale(1, N, f.M.l, f.W - f.M.r), Y = scale(1, n0, f.M.t, f.H - f.M.b);
  shadeNeutral(f, X); axes(f, X, Y, niceTicks(1, N, 10), [1, 5, 10, 15, 20].filter((v) => v <= n0), (v) => `P${v}`);
  for (const num of D.order) {
    const pts = [];
    for (let n = 1; n <= N; n++) { const i = D.lapOrder[n]?.findIndex((r) => r[0] === num); if (i >= 0) pts.push([n, i + 1]); }
    if (!pts.length) continue;
    const d = D.byNum[num], on = S.selected.has(num);
    el("path", { d: "M" + pts.map((p) => `${X(p[0])},${Y(p[1])}`).join("L"), fill: "none", stroke: d.colour, "stroke-width": on ? 2.6 : 1, opacity: on ? 1 : 0.25 }, f.svg);
    const last = pts[pts.length - 1];
    el("text", { x: X(last[0]) + 6, y: Y(last[1]) + 4, class: on ? "label" : "muted", fill: on ? d.colour : undefined }, f.svg).textContent = d.code;
  }
  addCursor(f, X);
}
function chartStrategy() {
  const rows = [...S.race.results].sort((a, b) => (a.pos ?? 99) - (b.pos ?? 99)).filter((r) => S.derived.byNum[r.driver]);
  const f = frame($("chart"), 26 + rows.length * 22, { l: 52, r: 20, t: 8, b: 26 });
  const N = S.race.meta.total_laps, X = scale(0, N, f.M.l, f.W - f.M.r);
  axes(f, X, () => 0, niceTicks(0, N, 10), []);
  rows.forEach((r, k) => {
    const y = f.M.t + k * 22, d = S.derived.byNum[r.driver];
    el("text", { x: f.M.l - 8, y: y + 14, "text-anchor": "end", class: "label", fill: d.colour }, f.svg).textContent = d.code;
    for (const s of (S.derived.stints[r.driver] || []).sort((a, b) => a.stint - b.stint)) {
      const to = s.to ?? r.laps ?? N;
      el("rect", { x: X(s.from - 1) + 1, y: y + 3, width: Math.max(2, X(to) - X(s.from - 1) - 2), height: 15, rx: 4, fill: COMPOUND[s.compound] || "#666", opacity: 0.9 }, f.svg);
      if (s.age) el("text", { x: X(s.from - 1) + 6, y: y + 14, "font-size": 10, fill: "#000", "font-weight": 700 }, f.svg).textContent = `${s.age}`;
    }
    if (r.dnf || r.dns) el("text", { x: X(r.laps || 0) + 6, y: y + 14, class: "muted" }, f.svg).textContent = r.dns ? "DNS" : "DNF";
  });
  const leg = $("legend"); leg.innerHTML = Object.entries(COMPOUND).map(([c, col]) => `<button class="on"><i style="background:${col}"></i>${c}</button>`).join("");
}
function chartPace() {
  const host = $("chart"), m = S.race.model;
  const f = frame(host, 360);
  const pts = [];
  for (const num of S.selected) {
    const laps = Object.fromEntries((S.race.laps[num] || []).map((l) => [l[0], l[2]]));
    for (const [lap, pred] of m.predicted[num] || []) pts.push({ num, lap, actual: laps[lap], pred });
  }
  const vals = pts.flatMap((p) => [p.actual, p.pred]).filter((v) => v != null).sort((a, b) => a - b);
  if (!vals.length) { host.innerHTML = '<p class="note">Select drivers below.</p>'; return; }
  const lo = vals[Math.floor(vals.length * 0.01)] - 0.3, hi = vals[Math.floor(vals.length * 0.99)] + 0.3;
  const N = S.race.meta.total_laps, X = scale(1, N, f.M.l, f.W - f.M.r), Y = scale(lo, hi, f.H - f.M.b, f.M.t);
  shadeNeutral(f, X); axes(f, X, Y, niceTicks(1, N, 10), niceTicks(lo, hi, 6), (v) => fmtLap(v).replace(/\.\d+$/, ""));
  for (const num of S.selected) {
    const d = S.derived.byNum[num], mine = pts.filter((p) => p.num === num);
    for (const p of mine) if (p.actual >= lo && p.actual <= hi) el("circle", { cx: X(p.lap), cy: Y(p.actual), r: 2.6, fill: d.colour, opacity: 0.75 }, f.svg);
    // model line, broken at stint changes (gaps in clean laps)
    let seg = [];
    const flush = () => { if (seg.length > 1) el("path", { d: "M" + seg.join("L"), stroke: d.colour, "stroke-width": 2, fill: "none" }, f.svg); seg = []; };
    mine.forEach((p, i) => { if (i && p.lap - mine[i - 1].lap > 2) flush(); seg.push(`${X(p.lap)},${Y(p.pred)}`); });
    flush();
  }
  const chips = document.createElement("div"); chips.className = "picker";
  chips.innerHTML = Object.entries(m.deg_per_lap).map(([c, v]) => {
    const ci = m.deg_ci90[c];
    return `<span class="stat"><i class="c-${c}" style="width:10px;height:10px;border-radius:50%;border:3px solid"></i>${c} <b>${v >= 0 ? "+" : ""}${v.toFixed(3)} s/lap</b>${ci ? ` 90% CI ${ci[0].toFixed(3)}…${ci[1].toFixed(3)}` : ""}</span>`;
  }).join("") + `<span class="stat">fuel + track <b>${m.fuel_per_lap.toFixed(3)} s/lap</b></span><span class="stat">residual σ <b>${m.residual_sigma}s</b></span><span class="stat">laps fitted <b>${m.n_laps}</b></span>`;
  host.prepend(chips);
}
function chartWindow() {
  const host = $("chart"); host.innerHTML = "";
  const st = S.race.strategy, nums = Object.keys(st).map(Number);
  const loss = S.race.model.pit_loss;
  if (!nums.length) { host.innerHTML = '<p class="note">Not enough green-flag pit stops in this race to measure pit loss.</p>'; return; }
  const order = [...S.race.results].sort((a, b) => (a.pos ?? 99) - (b.pos ?? 99)).map((r) => r.driver).filter((n) => nums.includes(n));
  const cur = nums.includes(S.focus) ? S.focus : order[0];
  const bar = document.createElement("div"); bar.className = "picker";
  bar.innerHTML = `Driver <select id="wDriver">${order.map((n) => `<option value="${n}" ${n === cur ? "selected" : ""}>${S.derived.byNum[n].code}</option>`).join("")}</select>
    <span class="stat">measured pit loss <b>${loss.median}s</b> median of ${loss.n} stops</span>`;
  host.appendChild(bar);
  const plot = document.createElement("div"); host.appendChild(plot);
  bar.querySelector("select").onchange = (e) => { S.focus = +e.target.value; renderChart(); drawTimeline(); renderFrame(); };
  const stops = st[cur];
  const f = frame(plot, 320);
  const all = stops.flatMap((s) => s.curve);
  const xs = all.map((c) => c[0]), ys = all.map((c) => c[1]);
  const X = scale(Math.min(...xs) - 1, Math.max(...xs) + 1, f.M.l, f.W - f.M.r);
  const lo = Math.min(-1, ...ys), hi = Math.max(1, ...ys), Y = scale(lo, hi, f.H - f.M.b, f.M.t);
  axes(f, X, Y, niceTicks(Math.min(...xs), Math.max(...xs), 10).filter(Number.isInteger), niceTicks(lo, hi, 6), (v) => `${v > 0 ? "+" : ""}${v}s`);
  el("line", { x1: f.M.l, x2: f.W - f.M.r, y1: Y(0), y2: Y(0), stroke: "#ffffff40" }, f.svg);
  const colours = ["#e10600", "#3fa9f5", "#2ecc71"];
  stops.forEach((s, j) => {
    const c = colours[j % 3];
    el("path", { d: "M" + s.curve.map(([l, v]) => `${X(l)},${Y(v)}`).join("L"), stroke: c, "stroke-width": 2.2, fill: "none" }, f.svg);
    el("circle", { cx: X(s.actual_lap), cy: Y(0), r: 5, fill: c }, f.svg);
    const best = s.curve.find((p) => p[0] === s.model_best_lap);
    if (best) el("circle", { cx: X(best[0]), cy: Y(best[1]), r: 4, fill: "none", stroke: c, "stroke-width": 2 }, f.svg);
    el("text", { x: X(s.curve[s.curve.length - 1][0]) + 6, y: Y(s.curve[s.curve.length - 1][1]) + 4, class: "label", fill: c }, f.svg)
      .textContent = `Stop ${s.stop}: ${s.from[0]}→${s.to[0]} (L${s.actual_lap})`;
  });
  const lines = stops.map((s) => {
    const best = s.curve.find((p) => p[0] === s.model_best_lap);
    return best && best[0] !== s.actual_lap && best[1] <= -0.05 ? `Stop ${s.stop} on lap ${s.actual_lap}: model optimum lap ${best[0]} (${best[1].toFixed(1)} s).`
      : `Stop ${s.stop} on lap ${s.actual_lap}: already at the model optimum.`;
  });
  const p = document.createElement("p"); p.className = "note"; p.textContent = lines.join(" "); host.appendChild(p);
}

// ---------- strategy simulator ----------
function chartSim() {
  const host = $("chart"), sim = S.race.sim; host.innerHTML = "";
  const nums = Object.keys(sim.finish).map(Number).filter((n) => String(n) in sim.pace);
  if (!nums.length || sim.pit_loss == null) { host.innerHTML = '<p class="note">Not enough data to simulate strategies in this race.</p>'; return; }
  const order = [...S.race.results].sort((a, b) => (a.pos ?? 99) - (b.pos ?? 99)).map((r) => r.driver).filter((n) => nums.includes(n));
  if (!S.simDriver || !order.includes(S.simDriver)) S.simDriver = nums.includes(S.focus) ? S.focus : order[0];
  const d = S.simDriver, N = sim.finish[String(d)][0];
  if (S.simFrom == null || S.simFrom >= N - 1) S.simFrom = 1;
  if (!S.simPlan || S.simPlanFor !== `${d}:${S.simFrom}`) { S.simPlan = actualPlan(sim, d, S.simFrom).map((p) => ({ lap: p.lap, compound: p.compound })); S.simPlanFor = `${d}:${S.simFrom}`; }
  const comps = Object.keys(sim.offset);
  const bar = document.createElement("div"); bar.className = "picker";
  bar.innerHTML = `Driver <select id="sDriver">${order.map((n) => `<option value="${n}" ${n === d ? "selected" : ""}>${S.derived.byNum[n].code}</option>`).join("")}</select>
    change strategy after lap <input id="sFrom" type="number" min="1" max="${N - 2}" value="${S.simFrom}" style="width:64px" class="btn">
    <button class="btn" id="sReset">Real strategy</button><button class="btn" id="sUnder">Undercut −3</button><button class="btn" id="sOver">Overcut +3</button>`;
  host.appendChild(bar);
  const plan = document.createElement("div"); plan.className = "sim-plan";
  S.simPlan.forEach((p, i) => {
    const row = document.createElement("div");
    row.innerHTML = `Stop ${i + 1}: pit for <select data-i="${i}" class="sComp">${comps.map((c) => `<option ${c === p.compound ? "selected" : ""}>${c}</option>`).join("")}</select>
      at the end of lap <input data-i="${i}" class="sLap" type="number" min="${S.simFrom}" max="${N - 1}" value="${p.lap - 1}"> <button class="btn sDel" data-i="${i}">✕</button>`;
    plan.appendChild(row);
  });
  const add = document.createElement("button"); add.className = "btn"; add.textContent = "+ add stop";
  add.onclick = () => { const last = S.simPlan.length ? S.simPlan[S.simPlan.length - 1].lap : S.simFrom + 1; S.simPlan.push({ lap: Math.min(N - 1, last + 10), compound: comps[0] }); chartSim(); };
  plan.appendChild(add); host.appendChild(plan);
  const res = simulate(sim, d, S.simFrom, S.simPlan.map((p) => ({ ...p })));
  const out = document.createElement("div"); out.className = "sim-result";
  if (res) {
    const faster = res.delta < 0, gain = res.position_actual - res.position_estimated;
    out.innerHTML = `<span class="stat">Finish <b>P${res.position_actual} → P${res.position_estimated}</b></span>
      <span class="stat">Race time <b class="${faster ? "good" : res.delta > 0 ? "bad" : ""}">${res.delta > 0 ? "+" : ""}${res.delta.toFixed(1)} s</b></span>
      <span class="stat">${gain > 0 ? `gains ${gain} place${gain > 1 ? "s" : ""}` : gain < 0 ? `loses ${-gain} place${gain < -1 ? "s" : ""}` : "same position"}</span>
      <span class="stat">pit loss <b>${sim.pit_loss}s</b> green / <b>${sim.pit_loss_neutral}s</b> under SC/VSC${sim.pit_loss_neutral_measured ? "" : " (assumed)"}</span>`;
  }
  host.appendChild(out);
  const dry = new Set([...(S.derived.stints[d] || []).filter((s) => s.from <= S.simFrom).map((s) => s.compound), ...S.simPlan.map((p) => p.compound)]);
  const dryN = ["SOFT", "MEDIUM", "HARD"].filter((c) => dry.has(c)).length;
  if (dryN < 2 && !dry.has("INTERMEDIATE") && !dry.has("WET")) {
    const w = document.createElement("p"); w.className = "warn"; w.textContent = "⚠ In a dry race the rules require using two different dry compounds; this plan would be disqualified."; host.appendChild(w);
  }
  // cumulative time difference lap by lap
  const a = lapTimes(sim, d, S.simFrom, actualPlan(sim, d, S.simFrom)), b = lapTimes(sim, d, S.simFrom, S.simPlan);
  if (a && b) {
    const f = frame(host.appendChild(document.createElement("div")), 240, { l: 52, r: 30, t: 14, b: 30 });
    let ca = 0, cb = 0; const pts = a.map(([lap, t], i) => { ca += t; cb += b[i][1]; return [lap, cb - ca]; });
    const ys = pts.map((p) => p[1]), lo = Math.min(-1, ...ys), hi = Math.max(1, ...ys);
    const X = scale(S.simFrom, N, f.M.l, f.W - f.M.r), Y = scale(lo, hi, f.H - f.M.b, f.M.t);
    axes(f, X, Y, niceTicks(S.simFrom, N, 10).filter(Number.isInteger), niceTicks(lo, hi, 5), (v) => `${v > 0 ? "+" : ""}${v}s`);
    el("line", { x1: f.M.l, x2: f.W - f.M.r, y1: Y(0), y2: Y(0), stroke: "#ffffff40" }, f.svg);
    el("path", { d: "M" + pts.map(([l, v]) => `${X(l)},${Y(v)}`).join("L"), stroke: S.derived.byNum[d].colour, "stroke-width": 2.4, fill: "none" }, f.svg);
    el("text", { x: f.M.l + 4, y: f.M.t + 10, class: "muted" }, f.svg).textContent = "your plan vs the real one, cumulative (below 0 = ahead)";
  }
  $("sDriver").onchange = (e) => { S.simDriver = +e.target.value; S.simPlan = null; chartSim(); };
  $("sFrom").onchange = (e) => { S.simFrom = Math.max(1, Math.min(N - 2, +e.target.value || 1)); S.simPlan = null; chartSim(); };
  $("sReset").onclick = () => { S.simPlan = null; chartSim(); };
  const shift = (k) => { if (S.simPlan.length) S.simPlan[0].lap = Math.max(S.simFrom + 1, Math.min(N - 1, S.simPlan[0].lap + k)); chartSim(); };
  $("sUnder").onclick = () => shift(-3); $("sOver").onclick = () => shift(3);
  host.querySelectorAll(".sComp").forEach((x) => (x.onchange = (e) => { S.simPlan[+e.target.dataset.i].compound = e.target.value; chartSim(); }));
  host.querySelectorAll(".sLap").forEach((x) => (x.onchange = (e) => { S.simPlan[+e.target.dataset.i].lap = Math.max(S.simFrom + 1, Math.min(N - 1, +e.target.value + 1)); S.simPlan.sort((p, q) => p.lap - q.lap); chartSim(); }));
  host.querySelectorAll(".sDel").forEach((x) => (x.onclick = (e) => { S.simPlan.splice(+e.target.dataset.i, 1); chartSim(); }));
}

// ---------- season view ----------
async function renderSeason() {
  const cards = $("seasonCards"); cards.innerHTML = "";
  for (const r of [...S.index.races].reverse()) {
    const c = document.createElement("div"); c.className = "card";
    c.innerHTML = `<h3>${r.name}</h3><div class="date">${r.date} · ${r.laps} laps</div>
      <div class="win">${r.winner ?? "–"} <small>winner</small></div>`;
    if (r.outline) {
      const xs = r.outline.map((p) => p[0]), ys = r.outline.map((p) => p[1]);
      const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
      const svg = el("svg", { viewBox: `${x0} ${-y1} ${x1 - x0} ${y1 - y0}`, preserveAspectRatio: "xMidYMid meet" }, c);
      el("path", { d: "M" + r.outline.map(([x, y]) => `${x},${-y}`).join("L") + "Z", fill: "none", stroke: "#e10600", "stroke-width": (x1 - x0) / 60 }, svg);
    }
    c.onclick = () => { setView("replay"); loadRace(r.slug); };
    cards.appendChild(c);
  }
  seasonForecast(); seasonChamp(); seasonPasses(); seasonPace(); seasonDeg(); seasonLoss();
}
async function seasonForecast() {
  let fc;
  try { fc = await (await fetch(`data/${YEAR}/championship.json`)).json(); } catch { $("forecastBox").hidden = true; return; }
  const left = fc.forecast.remaining.length;
  $("fcMeta").textContent = ` after ${fc.after_round} · ${left} race${left === 1 ? "" : "s"} left`;
  const row = (colour, label, p, pts, lo, hi) => `<div class="fc-row"><i style="background:${colour}"></i><span><b style="text-align:left">${label}</b></span>
    <div class="bar"><span style="width:${Math.max(1, p * 100)}%;background:${colour}"></span></div><b>${fmtPct(p)}</b><small>${pts} → ${Math.round(lo)}–${Math.round(hi)}</small></div>`;
  $("fcDrivers").innerHTML = fc.forecast.drivers.slice(0, 8).map((d) => row(d.colour, d.code, d.p_title, d.points, d.p10, d.p90)).join("");
  $("fcTeams").innerHTML = fc.forecast.teams.slice(0, 8).map((t) => row(t.colour, t.team.replace(" F1 Team", "").replace(" Racing", ""), t.p_title, t.points, t.p10, t.p90)).join("");
  const H = fc.history, f = frame($("fcHistory"), 260, { l: 48, r: 70, t: 14, b: 50 });
  const X = scale(0, H.length - 1, f.M.l, f.W - f.M.r), Y = scale(0, 1, f.H - f.M.b, f.M.t);
  axes(f, () => 0, Y, [], [0, 0.25, 0.5, 0.75, 1], (v) => `${v * 100}%`);
  H.forEach((h, i) => el("text", { x: X(i), y: f.H - f.M.b + 14, transform: `rotate(35 ${X(i)} ${f.H - f.M.b + 14})`, class: "muted" }, f.svg).textContent = h.after);
  const keys = [...new Set(H.flatMap((h) => Object.keys(h.drivers)))];
  const byNum = Object.fromEntries(fc.forecast.drivers.map((d) => [String(d.num), d]));
  for (const k of keys) {
    const d = byNum[k]; if (!d) continue;
    el("path", { d: "M" + H.map((h, i) => `${X(i)},${Y(h.drivers[k] ?? 0)}`).join("L"), stroke: d.colour, "stroke-width": 2.2, fill: "none" }, f.svg);
    const last = H[H.length - 1].drivers[k] ?? 0;
    if (last > 0.02) el("text", { x: f.W - f.M.r + 6, y: Y(last) + 4, class: "label", fill: d.colour }, f.svg).textContent = `${d.code} ${fmtPct(last)}`;
  }
}
function seasonChamp() {
  const st = S.index.standings, rounds = st.rounds, last = rounds[rounds.length - 1].points;
  const top = Object.entries(last).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([n]) => n);
  const v = st.validation;
  $("champNote").textContent = `Points after each Grand Prix (sprints included), computed from session results. Checked against the official standings after every round: ${v.driver_round_pairs_checked} driver-round totals, ${v.mismatches.length} mismatches.`;
  const f = frame($("champChart"), 380, { l: 48, r: 90, t: 14, b: 60 });
  const hi = Math.max(...Object.values(last)) * 1.05;
  const X = scale(0, rounds.length - 1, f.M.l, f.W - f.M.r), Y = scale(0, hi, f.H - f.M.b, f.M.t);
  axes(f, () => 0, Y, [], niceTicks(0, hi, 6));
  rounds.forEach((r, i) => el("text", { x: X(i), y: f.H - f.M.b + 14, transform: `rotate(35 ${X(i)} ${f.H - f.M.b + 14})`, class: "muted" }, f.svg).textContent = r.circuit + (r.sprint ? " ·S" : ""));
  const placed = [];
  top.slice().reverse().forEach((num) => {
    const d = st.drivers[num], pts = rounds.map((r, i) => [i, r.points[num] ?? 0]);
    el("path", { d: "M" + pts.map(([i, p]) => `${X(i)},${Y(p)}`).join("L"), stroke: d.colour, "stroke-width": 2.2, fill: "none" }, f.svg);
    let y = Y(pts[pts.length - 1][1]) + 4;
    while (placed.some((p) => Math.abs(p - y) < 12)) y += 12; // keep end labels from overlapping
    placed.push(y);
    el("text", { x: f.W - f.M.r + 6, y, class: "label", fill: d.colour }, f.svg).textContent = `${d.code} ${last[num]}`;
  });
}
function seasonPasses() {
  const races = S.index.races.filter((r) => r.dirty_air?.cost != null);
  const f = frame($("passChart"), 360, { l: 56, r: 30, t: 14, b: 40 });
  const xs = races.flatMap((r) => r.dirty_air.ci90), ys = races.map((r) => r.overtakes);
  const X = scale(Math.min(0, ...xs), Math.max(...xs) * 1.05, f.M.l, f.W - f.M.r), Y = scale(0, Math.max(...ys) * 1.1, f.H - f.M.b, f.M.t);
  axes(f, X, Y, niceTicks(Math.min(0, ...xs), Math.max(...xs), 8).map((v) => +v.toFixed(2)), niceTicks(0, Math.max(...ys), 5));
  el("text", { x: f.W - f.M.r, y: f.H - 22, "text-anchor": "end", class: "muted" }, f.svg).textContent = "time lost per lap within 1 s of the car ahead (s) →";
  el("text", { x: f.M.l + 4, y: f.M.t + 10, class: "muted" }, f.svg).textContent = "↑ on-track passes";
  for (const r of races) {
    const [a, b] = r.dirty_air.ci90, x = X(r.dirty_air.cost), y = Y(r.overtakes);
    el("line", { x1: X(a), x2: X(b), y1: y, y2: y, stroke: "#ffffff40" }, f.svg);
    el("circle", { cx: x, cy: y, r: 5, fill: "#e10600" }, f.svg);
    el("text", { x: x + 8, y: y - 6, class: "muted" }, f.svg).textContent = r.circuit;
  }
}
function seasonPace() {
  const races = S.index.races, teams = {};
  races.forEach((r, i) => Object.entries(r.team_pace || {}).forEach(([t, v]) => ((teams[t] ||= [])[i] = v)));
  // median, so one wet race does not dominate a team's season figure
  const avg = (a) => { const v = a.filter((x) => x != null).sort((x, y) => x - y), m = v.length >> 1; return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2; };
  const rows = Object.entries(teams).sort((a, b) => avg(a[1]) - avg(b[1]));
  const cell = (v) => {
    if (v == null) return "<td>–</td>";
    if (v > 3) return `<td title="${v.toFixed(2)} s/lap (mostly wet laps)">3+</td>`;
    const a = Math.max(0.08, 1 - Math.min(v, 1.5) / 1.5);
    return `<td style="background:rgba(225,6,0,${a.toFixed(2)})">${v.toFixed(2)}</td>`;
  };
  $("paceTable").innerHTML = `<div class="heat-wrap"><table class="heat"><tr><th>Team</th>${races.map((r) => `<th>${r.circuit.slice(0, 6)}</th>`).join("")}<th>median</th></tr>
    ${rows.map(([t, v]) => `<tr><td>${t}</td>${races.map((_, i) => cell(v[i])).join("")}<td>${avg(v).toFixed(2)}</td></tr>`).join("")}</table></div>`;
}
function seasonDeg() {
  const races = S.index.races, comps = ["SOFT", "MEDIUM", "HARD"];
  const f = frame($("degChart"), 320, { l: 56, r: 20, t: 14, b: 70 });
  const vals = races.flatMap((r) => comps.flatMap((c) => r.deg_ci?.[c] ?? (r.deg[c] != null ? [r.deg[c]] : [])));
  const lo = Math.min(-0.02, ...vals), hi = Math.max(0.05, ...vals);
  const bw = f.iw / races.length, Y = scale(lo, hi, f.H - f.M.b, f.M.t);
  axes(f, () => 0, Y, [], niceTicks(lo, hi, 6), (v) => `${v.toFixed(2)}`);
  el("line", { x1: f.M.l, x2: f.W - f.M.r, y1: Y(0), y2: Y(0), stroke: "#ffffff40" }, f.svg);
  races.forEach((r, i) => {
    const x0 = f.M.l + i * bw;
    comps.forEach((c, j) => {
      const v = r.deg[c]; if (v == null) return;
      const x = x0 + bw * (0.2 + j * 0.22);
      el("rect", { x, y: Math.min(Y(v), Y(0)), width: bw * 0.18, height: Math.abs(Y(v) - Y(0)), fill: COMPOUND[c], opacity: 0.85, rx: 2 }, f.svg);
      const ci = r.deg_ci?.[c];
      if (ci) el("line", { x1: x + bw * 0.09, x2: x + bw * 0.09, y1: Y(ci[0]), y2: Y(ci[1]), stroke: "#fff", "stroke-width": 1.2 }, f.svg);
    });
    el("text", { x: x0 + bw / 2, y: f.H - f.M.b + 14, transform: `rotate(35 ${x0 + bw / 2} ${f.H - f.M.b + 14})`, class: "muted" }, f.svg).textContent = r.circuit;
  });
}
function seasonLoss() {
  const races = S.index.races.filter((r) => r.pit_loss != null);
  const f = frame($("lossChart"), 280, { l: 56, r: 20, t: 14, b: 70 });
  const hi = Math.max(...races.map((r) => r.pit_loss)) * 1.1, Y = scale(0, hi, f.H - f.M.b, f.M.t), bw = f.iw / races.length;
  axes(f, () => 0, Y, [], niceTicks(0, hi, 5), (v) => `${v}s`);
  races.forEach((r, i) => {
    const x = f.M.l + i * bw + bw * 0.2;
    el("rect", { x, y: Y(r.pit_loss), width: bw * 0.6, height: Y(0) - Y(r.pit_loss), fill: "#e10600", rx: 3, opacity: 0.85 }, f.svg);
    el("text", { x: x + bw * 0.3, y: Y(r.pit_loss) - 5, "text-anchor": "middle", class: "muted" }, f.svg).textContent = r.pit_loss.toFixed(1);
    el("text", { x: x + bw * 0.3, y: f.H - f.M.b + 14, transform: `rotate(35 ${x + bw * 0.3} ${f.H - f.M.b + 14})`, class: "muted" }, f.svg).textContent = r.circuit;
  });
}

// ---------- wiring ----------
function setView(v) {
  document.querySelectorAll("#viewTabs button").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
  $("replayView").hidden = v !== "replay"; $("seasonView").hidden = v !== "season";
  $("raceSelect").parentElement.style.visibility = v === "replay" ? "visible" : "hidden";
  if (v === "season") renderSeason(); else { resizeCanvas(); drawTimeline(); renderChart(); renderFrame(); }
}
function wire() {
  $("play").onclick = () => { S.playing = !S.playing; updatePlay(); };
  $("passToggle").onclick = () => { S.showPasses = !S.showPasses; $("passToggle").classList.toggle("on", S.showPasses); renderFrame(); };
  $("scrub").oninput = (e) => { const [a, b] = bounds(); S.t = a + (e.target.value / 1000) * (b - a); renderFrame(); };
  $("speeds").onclick = (e) => {
    const b = e.target.closest("button"); if (!b) return;
    S.speed = +b.dataset.speed; document.querySelectorAll("#speeds button").forEach((x) => x.classList.toggle("on", x === b));
  };
  $("raceSelect").onchange = (e) => loadRace(e.target.value);
  $("gapMode").onclick = () => { S.gapMode = S.gapMode === "leader" ? "interval" : "leader"; $("gapMode").textContent = S.gapMode === "leader" ? "GAP" : "INT"; renderFrame(); };
  $("leaderboard").onclick = (e) => {
    const li = e.target.closest("li"); if (!li) return;
    const n = +li.dataset.num; S.focus = S.focus === n ? null : n; S.selected.add(n);
    drawTimeline(); renderFrame(); renderChart();
  };
  $("chartTabs").onclick = (e) => { const b = e.target.closest("button"); if (b) { S.chart = b.dataset.chart; renderChart(); } };
  $("viewTabs").onclick = (e) => { const b = e.target.closest("button"); if (b) setView(b.dataset.view); };
  window.addEventListener("resize", () => { if (!S.race) return; resizeCanvas(); drawTimeline(); renderChart(); renderFrame(); });
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "SELECT" || e.target.tagName === "INPUT" && e.target.type !== "range") return;
    if (e.code === "Space") { e.preventDefault(); S.playing = !S.playing; updatePlay(); }
    if (e.code === "ArrowRight") { S.t += 30; renderFrame(); }
    if (e.code === "ArrowLeft") { S.t -= 30; renderFrame(); }
  });
}

(async function main() {
  wire();
  await loadIndex();
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("race");
  const slug = S.index.races.some((r) => r.slug === fromHash) ? fromHash : S.index.races[S.index.races.length - 1].slug;
  await loadRace(slug);
  requestAnimationFrame((t) => { S.lastFrame = t; tick(t); });
})();
