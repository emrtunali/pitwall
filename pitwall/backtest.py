"""Stint forecasting backtest — the question a pit wall actually asks.

After the first ``k`` clean laps of a stint, forecast every remaining lap of that stint.
The model is fitted on all *other* stints of the race (no leakage from the target stint),
then shifted so its mean error over the ``k`` observed laps is zero.

Baselines:
* ``flat``   — the remaining laps will be as fast as the mean of the first k laps,
* ``linear`` — extend a straight line fitted to the first k laps,
* ``driver_median`` — the driver's median clean lap in the rest of the race (same information as the model),
* ``no_deg`` — the same model and calibration, but without the tyre-age terms.

``shrink`` (n0) controls how far the first k laps move the forecast away from the model: the bias is
scaled by k/(k+n0). It was chosen on the first half of the season only (see ``pitwall.evaluate``).
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

from .model import fit

DEFAULT_SHRINK = 12.0  # n0, chosen on the development races (see pitwall.evaluate)


def forecast_stints(rows: list[dict], k: int = 3, min_len: int = 8, shrink: float = DEFAULT_SHRINK) -> list[dict]:
    stints: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for r in rows:
        stints[(r["driver"], r["stint"])].append(r)
    out = []
    for key, laps in stints.items():
        laps = sorted(laps, key=lambda r: r["lap"])
        if len(laps) < min_len:
            continue
        train = [r for r in rows if (r["driver"], r["stint"]) != key]
        known_driver = any(r["driver"] == key[0] for r in train)
        known_compound = any(r["compound"] == laps[0]["compound"] for r in train)
        if not (known_driver and known_compound):
            continue  # the driver's pace or this compound would be unidentified without the target stint
        seen, future = laps[:k], laps[k:]
        y_seen = np.array([r["time"] for r in seen])
        y_future = np.array([r["time"] for r in future])
        preds = {"flat": np.full(len(future), y_seen.mean())}
        slope, icpt = np.polyfit([r["lap"] for r in seen], y_seen, 1)
        preds["linear"] = icpt + slope * np.array([r["lap"] for r in future])
        preds["driver_median"] = np.full(len(future), np.median([r["time"] for r in train if r["driver"] == key[0]]))
        try:
            models = {name: fit(train, use_age=use_age) for name, use_age in (("model", True), ("no_deg", False))}
        except ValueError:
            continue  # the remaining laps cannot identify the model; skip rather than guess
        for name, m in models.items():

            def p(r, m=m):
                return m.predict(r["driver"], r["compound"], r["tyre_age"], r["lap"])

            bias = float(np.mean(y_seen - np.array([p(r) for r in seen]))) * k / (k + shrink)
            preds[name] = np.array([p(r) for r in future]) + bias
        for i, r in enumerate(future):
            out.append(
                {"driver": key[0], "stint": key[1], "compound": r["compound"], "horizon": i + 1,
                 "actual": float(y_future[i]), **{n: float(v[i]) for n, v in preds.items()}}
            )
    return out


def summarize(points: list[dict], methods=("model", "no_deg", "driver_median", "flat", "linear")) -> dict:
    def mae(ps, m):
        return float(np.mean([abs(p[m] - p["actual"]) for p in ps])) if ps else float("nan")

    buckets = {"1-5": (1, 5), "6-10": (6, 10), "11+": (11, 10_000)}
    return {
        "n_laps": len(points),
        "n_stints": len({(p["race"], p["driver"], p["stint"]) if "race" in p else (p["driver"], p["stint"])
                         for p in points}),
        "mae": {m: mae(points, m) for m in methods},
        "mae_by_horizon": {
            b: {m: mae([p for p in points if lo <= p["horizon"] <= hi], m) for m in methods}
            | {"n": sum(lo <= p["horizon"] <= hi for p in points)}
            for b, (lo, hi) in buckets.items()
        },
    }
