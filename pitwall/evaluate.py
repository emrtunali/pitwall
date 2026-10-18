"""Season backtest with a chronological development / test split.

Races are ordered by date. Design choices (the bias shrinkage n0) were made on the development
races only; the test races were scored once with those choices frozen.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .backtest import DEFAULT_SHRINK, forecast_stints, summarize
from .build import completed_races
from .laps import clean_laps
from .openf1 import OpenF1
from .race import fetch_race

N_DEV = 8
METHODS = ("model", "no_deg", "driver_median", "flat", "linear")
SHRINK_GRID = (0.0, 1.0, 3.0, 6.0, 12.0, 1e9)


def run(api: OpenF1, out_dir: Path, year: int = 2026) -> dict:
    sessions = sorted(completed_races(api, year), key=lambda s: s["date_start"])
    rows = {}
    for s in sessions:
        race = fetch_race(api, s, with_locations=False)
        rows[s["session_key"]] = (race.circuit, clean_laps(race))
    dev_keys = [s["session_key"] for s in sessions[:N_DEV]]
    test_keys = [s["session_key"] for s in sessions[N_DEV:]]

    def points(keys, shrink):
        pts = []
        for k in keys:
            for p in forecast_stints(rows[k][1], shrink=shrink):
                pts.append(p | {"race": rows[k][0]})
        return pts

    tuning = {str(n0): summarize(points(dev_keys, n0), METHODS)["mae"]["model"] for n0 in SHRINK_GRID}
    dev = points(dev_keys, DEFAULT_SHRINK)
    test = points(test_keys, DEFAULT_SHRINK)
    per_race = {}
    for k in dev_keys + test_keys:
        name = rows[k][0]
        pts = [p for p in dev + test if p["race"] == name]
        per_race[name] = {"split": "dev" if k in dev_keys else "test"} | summarize(pts, METHODS)
    by_compound = {c: summarize([p for p in test if p["compound"] == c], METHODS)
                   for c in sorted({p["compound"] for p in test})}
    result = {
        "protocol": {"k_observed_laps": 3, "min_stint_clean_laps": 8, "shrink_n0": DEFAULT_SHRINK,
                     "dev_races": [rows[k][0] for k in dev_keys], "test_races": [rows[k][0] for k in test_keys]},
        "tuning_on_dev": tuning,
        "dev": summarize(dev, METHODS),
        "test": summarize(test, METHODS),
        "test_by_compound": by_compound,
        "per_race": per_race,
        "improvement_vs_flat_test": 1 - summarize(test)["mae"]["model"] / summarize(test)["mae"]["flat"],
        "abs_error_p90_test": float(np.percentile([abs(p["model"] - p["actual"]) for p in test], 90)),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "backtest.json").write_text(json.dumps(result, indent=2))
    (out_dir / "BACKTEST.md").write_text(to_markdown(result))
    return result


def to_markdown(r: dict) -> str:
    def row(name, s):
        m = s["mae"]
        return f"| {name} | {s['n_stints']} | {s['n_laps']} | " + " | ".join(f"{m[x]:.3f}" for x in METHODS) + " |"

    head = "| Split | Stints | Laps | " + " | ".join(METHODS) + " |\n|---|---|---|" + "---|" * len(METHODS)
    lines = ["# Stint forecasting backtest", "",
             f"Dev races (used to choose n0): {', '.join(r['protocol']['dev_races'])}",
             f"Test races (scored once): {', '.join(r['protocol']['test_races'])}", "",
             "Mean absolute error of the forecast lap time, seconds (lower is better):", "", head,
             row("dev", r["dev"]), row("**test**", r["test"]), "", "## Test MAE by forecast horizon", "",
             "| Laps ahead | n | " + " | ".join(METHODS) + " |", "|---|---|" + "---|" * len(METHODS)]
    for b, v in r["test"]["mae_by_horizon"].items():
        lines.append(f"| {b} | {v['n']} | " + " | ".join(f"{v[m]:.3f}" for m in METHODS) + " |")
    lines += ["", "## Test MAE by compound", "", "| Compound | Laps | " + " | ".join(METHODS) + " |",
              "|---|---|" + "---|" * len(METHODS)]
    for c, v in r["test_by_compound"].items():
        lines.append(f"| {c} | {v['n_laps']} | " + " | ".join(f"{v['mae'][m]:.3f}" for m in METHODS) + " |")
    lines += ["", "## Per race (model vs flat)", "", "| Race | Split | Laps | model | flat |", "|---|---|---|---|---|"]
    for name, v in r["per_race"].items():
        lines.append(f"| {name} | {v['split']} | {v['n_laps']} | {v['mae']['model']:.3f} | {v['mae']['flat']:.3f} |")
    lines += ["", "## Shrinkage tuning (dev only, model MAE)", "", "| n0 | MAE |", "|---|---|"]
    lines += [f"| {k} | {v:.3f} |" for k, v in r["tuning_on_dev"].items()]
    return "\n".join(lines) + "\n"
