"""Interactive strategy simulator: "what if this driver had stopped on lap X for compound Y?"

The site lets you rewrite a driver's remaining stops from any lap. The estimate is a *difference*:

    estimated finish = actual finish + (model time with your plan − model time with the real plan)

Both model runs share the same assumptions (race-pace model, measured pit loss, neutralised laps priced
at the field's actual pace), so the model's own bias cancels and only the effect of the plan remains.
Other cars keep their real race. Traffic and track position are not simulated.

This module builds the compact ``sim`` block the browser needs and is the reference implementation of
the simulation; ``site/whatif.mjs`` mirrors it and a test checks both give identical numbers.
"""

from __future__ import annotations

import numpy as np

from .laps import Window, pit_stops
from .model import PaceModel
from .race import Race


def _neutral_laps(race: Race, windows: list[Window]) -> dict[int, dict[int, float]]:
    """Per driver: lap number -> lap time to use, for laps that overlapped a neutralised period.

    Matched by time, not lap number, because lapped cars meet the same Safety Car on a different lap.
    The driver's own lap time is used, unless that lap was a pit in/out lap (the plan may move the
    stop), in which case it is the median of the other cars' laps that started within 30 s of it.
    """
    stops = set()
    for d, n in pit_stops(race):
        stops |= {(d, n - 1), (d, n)}
    timed = [lap for lap in race.laps if lap.duration]
    out: dict[int, dict[int, float]] = {}
    for lap in timed:
        a, b = lap.start, lap.start + lap.duration
        if not any(a < w.end and b > w.start for w in windows):
            continue
        if (lap.driver, lap.lap) in stops:
            peers = [x.duration for x in timed if x.driver != lap.driver and abs(x.start - lap.start) < 30
                     and (x.driver, x.lap) not in stops]
            # under a red flag every car changes tyres, so there may be no peers: keep the real lap
            price = float(np.median(peers)) if peers else lap.duration
        else:
            price = lap.duration
        out.setdefault(lap.driver, {})[lap.lap] = price
    return out


def _neutral_pit_loss(race: Race, neutral: dict[int, dict[int, float]]) -> float | None:
    """Pit loss for stops made while the race was neutralised: (in + out) − what those laps cost the others."""
    lap_by = {(lap.driver, lap.lap): lap for lap in race.laps}
    vals = []
    for d, n in pit_stops(race):
        lin, lout, nd = lap_by.get((d, n - 1)), lap_by.get((d, n)), neutral.get(d, {})
        if lin and lout and lin.duration and lout.duration and n - 1 in nd and n in nd:
            vals.append(lin.duration + lout.duration - nd[n - 1] - nd[n])
    return float(np.median(vals)) if len(vals) >= 2 else None


def sim_block(race: Race, model: PaceModel, windows: list[Window], green_loss: float | None) -> dict:
    neutral = _neutral_laps(race, windows)
    nloss = _neutral_pit_loss(race, neutral)
    # With fewer than two stops under SC/VSC to measure, assume a stop costs 60 % of a green-flag stop
    # (the field is slow too). The site labels this value as an assumption.
    neutral_loss = round(nloss, 2) if nloss is not None else (round(0.6 * green_loss, 2) if green_loss else None)
    lap_by = {(lap.driver, lap.lap): lap for lap in race.laps}
    finish = {}
    for x in race.results:
        d, n = x["driver_number"], x.get("number_of_laps")
        if n and (d, n) in lap_by and lap_by[(d, n)].duration and not (x.get("dnf") or x.get("dns")):
            finish[str(d)] = [n, round(lap_by[(d, n)].start + lap_by[(d, n)].duration, 3)]
    ends = {}
    for (d, n), lap in lap_by.items():
        if lap.duration:
            ends.setdefault(str(d), {})[str(n)] = round(lap.start + lap.duration, 3)
    return {
        "pace": {str(k): round(v, 4) for k, v in model.pace.items()},
        "offset": {k: round(v, 4) for k, v in model.offset.items()},
        "deg": {k: round(v, 5) for k, v in model.deg.items()},
        "fuel": round(model.fuel, 5),
        "neutral_laps": {str(d): {str(n): round(v, 3) for n, v in laps.items()} for d, laps in neutral.items()},
        "pit_loss": green_loss,
        "pit_loss_neutral": neutral_loss,
        "pit_loss_neutral_measured": nloss is not None,
        "finish": finish,
        "lap_ends": ends,
        "stints": [{"driver": s["driver_number"], "from": s["lap_start"], "to": s["lap_end"],
                    "compound": s.get("compound"), "age": s.get("tyre_age_at_start") or 0} for s in race.stints],
        "stops": _actual_stops(race),
    }


def _actual_stops(race: Race) -> dict[str, list[dict]]:
    """Every tyre change per driver. ``free`` marks changes that cost no time: made during a red-flag
    suspension (the in-lap lasted over 3× a normal lap) or without a pit-out lap in the timing."""
    lap_by = {(lap.driver, lap.lap): lap for lap in race.laps}
    normal = float(np.median([lap.duration for lap in race.laps if lap.duration]))
    pit_out = set(pit_stops(race))
    out: dict[str, list[dict]] = {}
    for s in sorted(race.stints, key=lambda s: (s["driver_number"], s["lap_start"])):
        d, n = s["driver_number"], s["lap_start"]
        if n <= 1:
            continue
        prev = lap_by.get((d, n - 1))
        red = bool(prev and prev.duration and prev.duration > 3 * normal)
        out.setdefault(str(d), []).append({"lap": n, "compound": s.get("compound"),
                                           "free": red or (d, n) not in pit_out})
    return out


def actual_plan(sim: dict, driver: int, from_lap: int) -> list[dict]:
    """The driver's real tyre changes after ``from_lap`` as [{"lap": out-lap, "compound": c, "free": bool}]."""
    return [dict(x) for x in sim["stops"].get(str(driver), []) if x["lap"] > from_lap]


def model_time(sim: dict, driver: int, from_lap: int, plan: list[dict]) -> float | None:
    """Model race time for laps from_lap+1 .. finish, starting from the real state after ``from_lap``."""
    laps = lap_times(sim, driver, from_lap, plan)
    return None if laps is None else sum(t for _, t in laps)


def lap_times(sim: dict, driver: int, from_lap: int, plan: list[dict]) -> list[tuple[int, float]] | None:
    """Per-lap model times (pit loss is booked on the out-lap)."""
    key = str(driver)
    if key not in sim["finish"] or key not in sim["pace"]:
        return None
    n_total = sim["finish"][key][0]
    st = sorted((s for s in sim["stints"] if s["driver"] == driver), key=lambda s: s["from"])
    cur = [s for s in st if s["from"] <= from_lap]
    if not cur:
        return None
    comp, age = cur[-1]["compound"], cur[-1]["age"] + from_lap - cur[-1]["from"]
    stops = {p["lap"]: p for p in plan}
    pace, fuel = sim["pace"][key], sim["fuel"]
    neutral = sim["neutral_laps"].get(key, {})
    out = []
    for n in range(from_lap + 1, n_total + 1):
        t = 0.0
        if n in stops:
            neutral_stop = str(n) in neutral or str(n - 1) in neutral
            loss = sim["pit_loss_neutral"] if neutral_stop else sim["pit_loss"]
            t += 0.0 if stops[n].get("free") else (loss or 0.0)
            comp, age = stops[n]["compound"], 0
        else:
            age += 1
        if str(n) in neutral:
            t += neutral[str(n)]
        else:  # a compound the model left out (too few laps) is priced like the reference compound
            t += pace + sim["offset"].get(comp, 0.0) + sim["deg"].get(comp, 0.0) * age + fuel * n
        out.append((n, t))
    return out


def simulate(sim: dict, driver: int, from_lap: int, plan: list[dict]) -> dict | None:
    key = str(driver)
    base = model_time(sim, driver, from_lap, actual_plan(sim, driver, from_lap))
    new = model_time(sim, driver, from_lap, plan)
    if base is None or new is None:
        return None
    actual_finish = sim["finish"][key][1]
    est = actual_finish + (new - base)
    n_laps = sim["finish"][key][0]
    rivals = sorted((v[1], int(d)) for d, v in sim["finish"].items() if v[0] == n_laps and d != key)
    position_now = 1 + sum(1 for t, _ in rivals if t < actual_finish)
    position_new = 1 + sum(1 for t, _ in rivals if t < est)
    return {"delta": round(new - base, 3), "estimated_finish": round(est, 3), "actual_finish": actual_finish,
            "position_actual": position_now, "position_estimated": position_new}


def replay_error(race: Race, sim: dict, from_frac: float = 0.0) -> list[float]:
    """Model race time with the *real* plan minus the real race time, per finisher (model accuracy)."""
    out = []
    for key, (n, fin) in sim["finish"].items():
        d = int(key)
        k = max(1, int(from_frac * n))
        start = sim["lap_ends"].get(key, {}).get(str(k))
        t = model_time(sim, d, k, actual_plan(sim, d, k))
        if start is not None and t is not None:
            out.append(start + t - fin)
    return out

