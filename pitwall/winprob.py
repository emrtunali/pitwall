"""Live win probability: a Monte Carlo race simulator that only knows what had happened so far.

At the end of every lap of the leader, the simulator

1. refits the race-pace model on clean laps completed *up to that moment* (no future data),
2. for each car takes the time already raced, current compound and tyre age,
3. simulates the remaining laps thousands of times with
   * lap-time noise (the model's residual scale) and uncertainty in each driver's pace,
   * a mandatory stop for any car that has not yet used two dry compounds, at a random lap,
   * the measured pit loss of this race (season prior until enough stops have been seen),
   * Safety Cars that bunch the field, and retirements, at rates estimated on earlier races,
4. and counts how often each driver finishes first.

Sums of lap times over a stint have closed forms (the model is linear in tyre age and lap number), so
each simulated race is a handful of vector operations rather than a lap-by-lap loop.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .laps import Window, clean_laps, pit_stops
from .model import fit
from .race import Race
from .strategy import _stint_for

DRY = ("SOFT", "MEDIUM", "HARD")

# Chosen on the development races (first 8 of 2026) by ``pitwall.winprob_eval``; frozen here so the site
# build does not depend on running the evaluation first. See results/WINPROB.md.
CALIBRATION = {"kappa": 4.0, "tau": 1.0, "w": 0.8,
               "beta": [-2.11809, 1.767454, -3.451583, -1.652089]}
N_PRIOR_RACES = 8


@dataclass
class Priors:
    """Season-level rates, estimated from earlier races only (see ``estimate_priors``)."""

    sc_per_lap: float = 0.02
    dnf_per_car_lap: float = 0.0012
    pit_loss: float = 24.0


def estimate_priors(races: list[tuple[Race, list[Window]]]) -> Priors:
    laps = sum(r.total_laps for r, _ in races)
    sc = sum(sum(w.kind in ("SC", "VSC") for w in ws) for _, ws in races)
    car_laps = sum(len([lap for lap in r.laps if lap.duration]) for r, _ in races)
    dnf = sum(sum(bool(x.get("dnf")) for x in r.results) for r, _ in races)
    return Priors(sc_per_lap=sc / max(laps, 1), dnf_per_car_lap=dnf / max(car_laps, 1))


def _next_compound(current: str, available: set[str]) -> str:
    for c in {"SOFT": ("HARD", "MEDIUM"), "MEDIUM": ("HARD", "SOFT"), "HARD": ("MEDIUM", "SOFT")}.get(current, ()):
        if c in available:
            return c
    return current


def _seg_sum(n0, a, b, s, P, off1, deg1, age1, off2, deg2, F):
    """Sum of predicted lap times over relative laps [a, b) when the stop happens at relative lap s.

    Relative lap j is race lap n0 + j. Laps before s use the current tyre (age age1 + j), laps from s on
    use the new tyre (age j - s). All arguments broadcast.
    """
    def lin_sum(x, y):  # count and sum of j over [x, y)
        c = np.maximum(y - x, 0)
        return c, (x + y - 1) * c / 2.0

    c1, j1 = lin_sum(a, np.minimum(b, s))
    c2, j2 = lin_sum(np.maximum(a, s), b)
    pre = c1 * (P + off1 + deg1 * age1 + F * n0) + (deg1 + F) * j1
    post = c2 * (P + off2 + F * n0) + deg2 * (j2 - s * c2) + F * j2
    return pre + post, c1 + c2


def win_probabilities(race: Race, windows: list[Window], priors: Priors, sims: int = 2000, seed: int = 0,
                      start_frac: float = 0.15, kappa: float = 1.0) -> dict:
    """``kappa`` inflates per-driver pace uncertainty; it is tuned on earlier races (see winprob_eval)."""
    N = race.total_laps
    rng = np.random.default_rng(seed)
    all_rows = clean_laps(race, windows, slow_factor=None)
    lap_by = {(lap.driver, lap.lap): lap for lap in race.laps}
    ends = {k: v.start + v.duration for k, v in lap_by.items() if v.duration}
    leader_end = {}
    for (_d, n), t in ends.items():
        leader_end[n] = min(leader_end.get(n, np.inf), t)
    stops_all = pit_stops(race)
    out_laps, probs, podium, states = [], {}, {}, []
    model = None
    for L in range(max(3, int(start_frac * N)), N):
        if L not in leader_end:
            continue
        T = leader_end[L]
        rows = [r for r in all_rows if ends.get((r["driver"], r["lap"]), np.inf) <= T]
        rows = _drop_slow(rows)
        try:
            model = fit(rows)
        except ValueError:
            # Before the first pit stops tyre age moves in lockstep with lap number, so tyre wear and
            # fuel burn cannot be told apart. Fit their combined trend instead (fuel term off).
            try:
                model = fit(rows, use_fuel=False)
            except ValueError:
                if model is None:
                    continue
        drivers, E, n_done = [], [], []
        median_lap = np.median([r["time"] for r in rows]) if rows else 100.0
        for d in [x["driver_number"] for x in race.drivers]:
            done = [n for (dd, n), t in ends.items() if dd == d and t <= T]
            if not done or d not in model.pace:
                continue
            n = max(done)
            if ends[(d, n)] < T - 2.5 * median_lap and n < L:
                continue  # stopped running: retired before this point
            drivers.append(d)
            E.append(ends[(d, n)])
            n_done.append(n)
        if len(drivers) < 2:
            continue
        D = len(drivers)
        E, n_done = np.array(E), np.array(n_done)
        R = N - n_done  # laps still to run for each car
        P = np.array([model.pace[d] for d in drivers])
        comp_now, age_now, need_stop, new_comp = [], [], [], []
        avail = set(model.offset)
        for d, n in zip(drivers, n_done, strict=True):
            st = [s for s in race.stints if s["driver_number"] == d and s["lap_start"] <= n]
            cur = max(st, key=lambda s: s["lap_start"]) if st else None
            c = cur["compound"] if cur and cur.get("compound") in avail else model.reference
            comp_now.append(c)
            age_now.append(((cur.get("tyre_age_at_start") or 0) + n - cur["lap_start"]) if cur else n)
            used = {s.get("compound") for s in st}
            dry_race = used <= set(DRY) | {None}
            must = dry_race and len(used & set(DRY)) < 2 and R[len(comp_now) - 1] > 3
            need_stop.append(must)
            new_comp.append(_next_compound(c, avail) if must else c)
        off1 = np.array([model.offset[c] for c in comp_now])
        deg1 = np.array([model.deg.get(c, 0.0) for c in comp_now])
        off2 = np.array([model.offset[c] for c in new_comp])
        deg2 = np.array([model.deg.get(c, 0.0) for c in new_comp])
        age1 = np.array(age_now, dtype=float) + 1
        n0 = n_done + 1.0
        need = np.array(need_stop)
        seen_loss = _pit_loss_so_far(race, model, stops_all, ends, T, lap_by)
        loss = seen_loss if seen_loss is not None else priors.pit_loss
        n_clean = np.array([max(1, sum(r["driver"] == d for r in rows)) for d in drivers])
        pace_sd = kappa * np.maximum(model.sigma / np.sqrt(n_clean), 0.03)

        # ---- simulate (sims × drivers) ----
        S = sims
        s_stop = np.where(need[None, :], rng.random((S, D)) * np.maximum(R - 2, 1) // 1, R[None, :]).astype(float)
        pace_err = rng.normal(0, 1, (S, D)) * pace_sd
        sc_any = rng.random(S) < 1 - (1 - priors.sc_per_lap) ** R.max()
        sc_lap = (rng.random(S) * R.max()).astype(int)  # relative to the leader's remaining laps
        dnf = rng.random((S, D)) < 1 - (1 - priors.dnf_per_car_lap) ** R[None, :]

        args = (n0, P, off1, deg1, age1, off2, deg2, model.fuel)
        k = np.where(sc_any[:, None], np.minimum(sc_lap[:, None], R[None, :]), R[None, :]).astype(float)
        first, c_first = _seg_sum(args[0], 0.0, k, s_stop, *args[1:])
        t_k = (E + first + loss * (s_stop < k) + pace_err * c_first
               + rng.normal(0, 1, (S, D)) * model.sigma * np.sqrt(c_first))
        # Safety Car: the field closes up behind the leader in running order
        order = np.argsort(np.where(dnf, np.inf, t_k), axis=1)
        rank = np.empty_like(order)
        np.put_along_axis(rank, order, np.arange(D)[None, :].repeat(S, 0), axis=1)
        bunched = t_k.min(axis=1, keepdims=True) + 0.6 * rank
        t_k = np.where(sc_any[:, None], bunched, t_k)
        rest, c_rest = _seg_sum(args[0], k, R[None, :].astype(float), s_stop, *args[1:])
        final = (t_k + rest + loss * (s_stop >= k) * (s_stop < R[None, :]) + pace_err * c_rest
                 + rng.normal(0, 1, (S, D)) * model.sigma * np.sqrt(c_rest))
        final = np.where(dnf, np.inf, final)
        pos = np.argsort(np.argsort(final, axis=1), axis=1)  # 0 = winner
        p_win = (pos == 0).mean(axis=0)
        p_pod = (pos <= 2).mean(axis=0)
        # Running order, and the order once every car has served the stop it still owes (pit cycle).
        owed = E + loss * need
        rank_now = np.empty(D, dtype=int)
        rank_now[np.lexsort((E, -n_done))] = np.arange(1, D + 1)
        rank_adj = np.empty(D, dtype=int)
        rank_adj[np.lexsort((owed, -n_done))] = np.arange(1, D + 1)
        states.append({"lap": L, "frac": L / N, "drivers": drivers, "p": p_win.tolist(), "pos": rank_adj.tolist(),
                       "pos_raw": rank_now.tolist()})
        out_laps.append(L)
        idx = len(out_laps) - 1
        for d, pw, pp in zip(drivers, p_win, p_pod, strict=True):
            probs.setdefault(d, [0.0] * idx).append(round(float(pw), 4))
            podium.setdefault(d, [0.0] * idx).append(round(float(pp), 4))
        for d in probs:
            if len(probs[d]) < idx + 1:
                probs[d].append(0.0)
                podium[d].append(0.0)
    return {"laps": out_laps, "win": {str(k): v for k, v in probs.items()},
            "podium": {str(k): v for k, v in podium.items()}, "states": states}


def calibrated(states: list[dict]) -> dict:
    """Apply the frozen calibration (temperature + running-order prior mix) to simulator states."""
    beta = np.array(CALIBRATION["beta"])
    laps, series = [], {}
    for i, s in enumerate(states):
        raw, adj = np.log(np.array(s["pos_raw"], float)), np.log(np.array(s["pos"], float))
        z = np.stack([raw, adj, s["frac"] * raw, s["frac"] * adj], axis=1) @ beta  # same features as winprob_eval
        prior = np.exp(z - z.max())
        prior /= prior.sum()
        q = np.maximum(np.array(s["p"]), 1e-3) ** (1 / CALIBRATION["tau"])
        q /= q.sum()
        p = (1 - CALIBRATION["w"]) * q + CALIBRATION["w"] * prior
        p /= p.sum()
        laps.append(s["lap"])
        for d, v in zip(s["drivers"], p, strict=True):
            series.setdefault(d, [0.0] * i).append(round(float(v), 4))
        for d in series:
            if len(series[d]) < i + 1:
                series[d].append(0.0)
    keep = {d: v for d, v in series.items() if max(v) >= 0.03}
    return {"laps": laps, "win": {str(d): v for d, v in keep.items()}}


def _drop_slow(rows: list[dict], factor: float = 1.07) -> list[dict]:
    med: dict[int, list[float]] = {}
    for r in rows:
        med.setdefault(r["driver"], []).append(r["time"])
    m = {d: float(np.median(v)) for d, v in med.items()}
    return [r for r in rows if r["time"] <= factor * m[r["driver"]]]


def _pit_loss_so_far(race, model, stops, ends, T, lap_by) -> float | None:
    vals = []
    for d, n in stops:
        if ends.get((d, n), np.inf) > T or d not in model.pace:
            continue
        lin, lout = lap_by.get((d, n - 1)), lap_by.get((d, n))
        if not (lin and lout and lin.duration and lout.duration):
            continue
        s_in, s_out = _stint_for(race, d, n - 1), _stint_for(race, d, n)
        if not (s_in and s_out) or s_in["compound"] not in model.offset or s_out["compound"] not in model.offset:
            continue
        age_in = (s_in.get("tyre_age_at_start") or 0) + (n - 1) - s_in["lap_start"]
        expected = model.predict(d, s_in["compound"], age_in, n - 1) + model.predict(
            d, s_out["compound"], s_out.get("tyre_age_at_start") or 0, n)
        vals.append(lin.duration + lout.duration - expected)
    return float(np.median(vals)) if len(vals) >= 4 else None
