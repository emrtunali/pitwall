"""Pit-loss measurement and model-based "what if we had stopped on lap X" curves."""

from __future__ import annotations

import numpy as np

from .laps import Window, pit_stops
from .model import PaceModel
from .race import Race


def _stint_for(race: Race, driver: int, lap: int) -> dict | None:
    return next(
        (s for s in race.stints if s["driver_number"] == driver and s["lap_start"] <= lap <= (s["lap_end"] or 999)),
        None,
    )


def pit_loss(race: Race, model: PaceModel, windows: list[Window]) -> dict:
    """Time lost to a stop = (in-lap + out-lap) − model prediction for the same two laps raced normally.

    Only green-flag stops are used, and the median keeps slow stops and out-lap traffic from
    dominating.
    """
    lap_by = {(lap.driver, lap.lap): lap for lap in race.laps}
    losses = []
    for d, n_out in pit_stops(race):
        lin, lout = lap_by.get((d, n_out - 1)), lap_by.get((d, n_out))
        if d not in model.pace or not (lin and lout and lin.duration and lout.duration):
            continue
        a, b = lin.start, lout.start + lout.duration
        if any(a < w.end + 10 and b > w.start - 10 for w in windows):
            continue
        s_in, s_out = _stint_for(race, d, n_out - 1), _stint_for(race, d, n_out)
        if not (s_in and s_out) or s_in["compound"] not in model.offset or s_out["compound"] not in model.offset:
            continue
        age_in = (s_in.get("tyre_age_at_start") or 0) + (n_out - 1) - s_in["lap_start"]
        expected = model.predict(d, s_in["compound"], age_in, n_out - 1) + model.predict(
            d, s_out["compound"], s_out.get("tyre_age_at_start") or 0, n_out
        )
        losses.append(lin.duration + lout.duration - expected)
    if len(losses) < 4:  # too few green-flag stops to say anything about this circuit
        return {"median": None, "n": len(losses)}
    return {"median": round(float(np.median(losses)), 2), "iqr": [round(float(q), 2) for q in
            np.percentile(losses, [25, 75])], "n": len(losses)}


def what_if(race: Race, model: PaceModel, loss: float, driver: int, span: int = 12) -> list[dict]:
    """For each pit stop of ``driver``, model race time if that stop had been on a different lap.

    Other stops, compounds and tyre ages at fitting stay as they were. Values are seconds relative
    to the stop lap actually used (negative = the model thinks that lap would have been faster).
    Neutralised laps are priced like racing laps, so this is a strategy model, not a race replay.
    """
    stints = sorted((s for s in race.stints if s["driver_number"] == driver), key=lambda s: s["stint_number"])
    stints = [s for s in stints if s.get("compound") in model.offset]
    if len(stints) < 2 or driver not in model.pace:
        return []
    last_lap = max((lap.lap for lap in race.laps if lap.driver == driver), default=0)
    if last_lap < race.total_laps:
        return []  # did not finish; a total-time comparison is meaningless
    stops = [s["lap_end"] for s in stints[:-1]]

    def total(stop_laps: list[int]) -> float:
        bounds = [1] + [x + 1 for x in stop_laps] + [last_lap + 1]
        t = 0.0
        for st, a, b in zip(stints, bounds[:-1], bounds[1:], strict=True):
            age0 = st.get("tyre_age_at_start") or 0
            laps = np.arange(a, b)
            t += float(np.sum([model.predict(driver, st["compound"], age0 + (lp - a), lp) for lp in laps]))
        return t + loss * len(stop_laps)

    base = total(stops)
    out = []
    for j, actual in enumerate(stops):
        lo = (stops[j - 1] + 3) if j else 3
        hi = (stops[j + 1] - 3) if j + 1 < len(stops) else last_lap - 2
        curve = []
        for lap in range(max(lo, actual - span), min(hi, actual + span) + 1):
            trial = stops.copy()
            trial[j] = lap
            curve.append([lap, round(total(trial) - base, 2)])
        best = min(curve, key=lambda c: c[1]) if curve else None
        out.append({"stop": j + 1, "actual_lap": actual, "from": stints[j]["compound"],
                    "to": stints[j + 1]["compound"], "curve": curve, "model_best_lap": best[0] if best else None})
    return out
