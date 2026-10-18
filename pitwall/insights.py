"""Derived metrics you will not find in the official feed.

* **Dirty-air cost**: how much slower a car lapped while running within 1 s of the car ahead, compared
  with running in clean air (> 3 s), after the race-pace model has removed tyres, fuel and driver pace.
* **On-track overtakes**: position swaps between two running cars that are not explained by a pit stop,
  a retirement, the start or a Safety Car — with the place on the circuit where timing registered them.
* **Corrected race pace**: each driver's pace term from the model, i.e. lap time on equal tyres and fuel.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from .laps import Window, pit_stops
from .model import PaceModel
from .race import Race

DIRTY, CLEAN = 1.0, 3.0  # seconds to the car ahead


def _interval_lookup(race: Race) -> dict[int, tuple[np.ndarray, np.ndarray]]:
    out = {}
    by: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for iv in race.intervals:
        v = iv.get("interval")
        if isinstance(v, (int, float)) and v > 0:
            by[iv["driver_number"]].append((race.rel(iv["date"]), float(v)))
    for d, rows in by.items():
        rows.sort()
        out[d] = (np.array([r[0] for r in rows]), np.array([r[1] for r in rows]))
    return out


def dirty_air(race: Race, model: PaceModel, rows: list[dict], bootstrap: int = 300, seed: int = 0) -> dict:
    """Mean model residual in dirty air minus mean residual in clean air (seconds per lap).

    The interval is the median of the gaps to the car ahead recorded during the lap. This is an
    observed cost, not a causal one: a car within 1 s may be attacking as well as being held up.
    """
    ivl = _interval_lookup(race)
    starts = {(lap.driver, lap.lap): (lap.start, lap.start + (lap.duration or 0)) for lap in race.laps}
    groups: dict[str, list[tuple[float, tuple[int, int]]]] = {"dirty": [], "clean": []}
    for r in rows:
        if r["driver"] not in model.pace or r["compound"] not in model.offset or r["driver"] not in ivl:
            continue
        a, b = starts[(r["driver"], r["lap"])]
        t, v = ivl[r["driver"]]
        inside = v[(t >= a) & (t <= b)]
        if len(inside) == 0:
            continue
        gap = float(np.median(inside))
        resid = r["time"] - model.predict(r["driver"], r["compound"], r["tyre_age"], r["lap"])
        key = (r["driver"], r["stint"])
        if gap < DIRTY:
            groups["dirty"].append((resid, key))
        elif gap > CLEAN:
            groups["clean"].append((resid, key))
    if len(groups["dirty"]) < 30 or len(groups["clean"]) < 30:
        return {"cost": None, "n_dirty": len(groups["dirty"]), "n_clean": len(groups["clean"])}

    def diff(d, c):
        return float(np.mean(d) - np.mean(c))

    dirty = np.array([x[0] for x in groups["dirty"]])
    clean = np.array([x[0] for x in groups["clean"]])
    rng = np.random.default_rng(seed)
    # cluster bootstrap over stints so correlated laps behind the same car are not counted as independent
    clusters = {g: defaultdict(list) for g in groups}
    for g, items in groups.items():
        for res, key in items:
            clusters[g][key].append(res)
    samples = []
    for _ in range(bootstrap):
        parts = []
        for g in ("dirty", "clean"):
            keys = list(clusters[g])
            pick = rng.integers(0, len(keys), len(keys))
            parts.append(np.concatenate([clusters[g][keys[i]] for i in pick]))
        samples.append(diff(*parts))
    lo, hi = np.percentile(samples, [5, 95])
    return {"cost": round(diff(dirty, clean), 3), "ci90": [round(float(lo), 3), round(float(hi), 3)],
            "n_dirty": len(dirty), "n_clean": len(clean)}


def overtakes(race: Race, windows: list[Window], pit_margin: float = 40.0) -> list[dict]:
    """Position swaps between two running cars, with the overtaking car's location.

    A gain by A paired with a loss by B at the same timing update is a pass when: it is after lap 1,
    outside neutralised periods, neither car is within ``pit_margin`` s of a pit stop, and B keeps racing
    for at least another minute (so retirements are not counted).
    """
    lap_by = {(lap.driver, lap.lap): lap for lap in race.laps}
    stops: dict[int, list[float]] = defaultdict(list)
    for d, n in pit_stops(race):
        stops[d].append(lap_by[(d, n)].start)
    last_end = defaultdict(float)
    for lap in race.laps:
        if lap.duration:
            last_end[lap.driver] = max(last_end[lap.driver], lap.start + lap.duration)
    lap2 = min((lap.start for lap in race.laps if lap.lap == 2), default=0.0)

    current: dict[int, int] = {}
    events: dict[float, list[tuple[int, int, int]]] = defaultdict(list)
    for p in sorted(race.positions, key=lambda x: x["date"]):
        d, pos, t = p["driver_number"], p["position"], race.rel(p["date"])
        old = current.get(d)
        current[d] = pos
        if old is not None and old != pos:
            events[round(t, 1)].append((d, old, pos))

    def near_pit(d: int, t: float) -> bool:
        return any(abs(t - s) < pit_margin for s in stops.get(d, []))

    out = []
    for t, changes in sorted(events.items()):
        if t < lap2 or any(w.start - 10 <= t <= w.end + 10 for w in windows):
            continue
        gainers = [c for c in changes if c[2] < c[1]]
        losers = {c[1]: c for c in changes if c[2] > c[1]}
        for a, _old, new in gainers:
            b = losers.get(new)  # the car that held the position A took
            if not b or b[0] == a:
                continue
            if near_pit(a, t) or near_pit(b[0], t) or last_end[b[0]] < t + 60:
                continue
            xy = _location(race, a, t)
            lap = max((lap.lap for lap in race.laps if lap.driver == a and lap.start <= t), default=0)
            out.append({"t": round(t, 1), "lap": lap, "by": a, "on": b[0], "position": new,
                        "x": xy[0] if xy else None, "y": xy[1] if xy else None})
    return out


def _location(race: Race, driver: int, t: float) -> tuple[int, int] | None:
    arr = race.locations.get(driver)
    if arr is None or len(arr) == 0 or t < arr[0, 0] or t > arr[-1, 0]:
        return None
    return int(round(np.interp(t, arr[:, 0], arr[:, 1]))), int(round(np.interp(t, arr[:, 0], arr[:, 2])))


def corrected_pace(model: PaceModel, race: Race) -> dict:
    """Driver and team pace on equal tyres and fuel, in seconds per lap behind the fastest."""
    teams = {d["driver_number"]: d["team_name"] for d in race.drivers}
    best = min(model.pace.values())
    drivers = {d: round(v - best, 3) for d, v in sorted(model.pace.items(), key=lambda kv: kv[1])}
    by_team: dict[str, list[float]] = defaultdict(list)
    for d, v in drivers.items():
        by_team[teams.get(d, "?")].append(v)
    team = {t: round(float(np.mean(v)), 3) for t, v in by_team.items()}
    tbest = min(team.values())
    return {"drivers": {str(k): v for k, v in drivers.items()},
            "teams": {t: round(v - tbest, 3) for t, v in sorted(team.items(), key=lambda kv: kv[1])}}
