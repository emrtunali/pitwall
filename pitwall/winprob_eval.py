"""Calibration and evaluation of the live win probability.

Three ingredients are tuned on the development races only (the first ``N_DEV`` of the season):

* ``kappa`` — how much to inflate each driver's pace uncertainty in the simulator,
* ``tau``   — temperature scaling of the simulated probabilities,
* ``w``     — weight of a learned "running order" prior in the final mix.

The running-order prior is a conditional-logit model, P(win) ∝ exp(β·x), with x = [log pos, log pos*,
f·log pos, f·log pos*]: ``pos`` is the current position, ``pos*`` the position once every car has served
the pit stop it still owes (cars that have not used two dry compounds are charged the pit loss), and
``f`` the fraction of the race completed. The fit decides how much each view of the order matters.
It is the strongest simple baseline ("whoever leads usually wins") and is reported on its own as well.

Everything is then scored once on the test races: mean log-loss and Brier score of the eventual
winner over every lap from 15 % distance, top-pick accuracy, and checkpoints at 25 / 50 / 75 %.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np

from .build import completed_races
from .laps import neutral_windows
from .openf1 import OpenF1
from .race import fetch_race
from .winprob import N_PRIOR_RACES, estimate_priors, win_probabilities

N_DEV = N_PRIOR_RACES
EPS = 1e-3
KAPPAS = (1.0, 2.0, 4.0, 8.0)
TAUS = (0.75, 1.0, 1.5, 2.0, 3.0)
WEIGHTS = (0.0, 0.2, 0.35, 0.5, 0.65, 0.8)


def _features(state: dict) -> np.ndarray:
    raw, adj, f = np.log(np.array(state["pos_raw"], float)), np.log(np.array(state["pos"], float)), state["frac"]
    return np.stack([raw, adj, f * raw, f * adj], axis=1)


def fit_order_prior(states: list[dict], iters: int = 800, lr: float = 0.5) -> np.ndarray:
    """Conditional logit by gradient ascent on the log-likelihood of the eventual winner."""
    beta = np.zeros(4)
    for _ in range(iters):
        grad = np.zeros(4)
        for s in states:
            X = _features(s)
            z = X @ beta
            p = np.exp(z - z.max())
            p /= p.sum()
            grad += X[s["winner_idx"]] - p @ X
        beta += lr * grad / len(states)
    return beta


def order_prior(state: dict, beta: np.ndarray) -> np.ndarray:
    z = _features(state) @ beta
    p = np.exp(z - z.max())
    return p / p.sum()


def combine(p_sim: np.ndarray, p_prior: np.ndarray, tau: float, w: float) -> np.ndarray:
    q = np.maximum(p_sim, EPS) ** (1 / tau)
    q /= q.sum()
    out = (1 - w) * q + w * p_prior
    return out / out.sum()


def score(states: list[dict], probs: list[np.ndarray]) -> dict:
    ll, brier, top = [], [], []
    for s, p in zip(states, probs, strict=True):
        y = np.zeros(len(p))
        y[s["winner_idx"]] = 1
        ll.append(-np.log(max(p[s["winner_idx"]], 1e-9)))
        brier.append(float(((p - y) ** 2).sum()))
        top.append(int(np.argmax(p) == s["winner_idx"]))
    return {"n": len(states), "log_loss": float(np.mean(ll)), "brier": float(np.mean(brier)),
            "top_pick_accuracy": float(np.mean(top))}


def _attach_winners(race, states):
    winner = next(r["driver_number"] for r in race.results if r.get("position") == 1)
    keep = []
    for s in states:
        if winner in s["drivers"]:
            keep.append(s | {"winner_idx": s["drivers"].index(winner), "race": race.circuit})
    return keep


def run(api: OpenF1, out_dir: Path, year: int = 2026, sims: int = 1000) -> dict:
    sessions = sorted(completed_races(api, year), key=lambda s: s["date_start"])
    races = [fetch_race(api, s, with_locations=False) for s in sessions]
    windows = [neutral_windows(r) for r in races]
    priors = estimate_priors(list(zip(races[:N_DEV], windows[:N_DEV], strict=True)))
    raw: dict[float, list[list[dict]]] = {}
    for kappa in KAPPAS:
        raw[kappa] = [_attach_winners(r, win_probabilities(r, w, priors, sims=sims, kappa=kappa)["states"])
                      for r, w in zip(races, windows, strict=True)]

    def flat(kappa, which):
        rng = range(N_DEV) if which == "dev" else range(N_DEV, len(races))
        return [s for i in rng for s in raw[kappa][i]]

    beta = fit_order_prior(flat(KAPPAS[0], "dev"))
    best = None
    grid = []
    for kappa, tau, w in itertools.product(KAPPAS, TAUS, WEIGHTS):
        dev = flat(kappa, "dev")
        sc = score(dev, [combine(np.array(s["p"]), order_prior(s, beta), tau, w) for s in dev])
        grid.append({"kappa": kappa, "tau": tau, "w": w, "dev_log_loss": sc["log_loss"]})
        if best is None or sc["log_loss"] < best[0]:
            best = (sc["log_loss"], kappa, tau, w)
    _, kappa, tau, w = best

    def evaluate(which):
        st = flat(kappa, which)
        base = flat(KAPPAS[0], which)
        res = {
            "calibrated_simulator": score(st, [combine(np.array(s["p"]), order_prior(s, beta), tau, w) for s in st]),
            "raw_simulator": score(base, [np.maximum(np.array(s["p"]), EPS) / np.maximum(np.array(s["p"]), EPS).sum()
                                          for s in base]),
            "running_order_prior": score(st, [order_prior(s, beta) for s in st]),
            "leader_takes_all": score(st, [np.where(np.array(s["pos_raw"]) == 1, 1 - EPS * (len(s["pos"]) - 1), EPS)
                                           for s in st]),
        }
        checkpoints = {}
        for f in (0.25, 0.5, 0.75):
            pick = []
            for i in (range(N_DEV) if which == "dev" else range(N_DEV, len(races))):
                states = raw[kappa][i]
                if states:
                    pick.append(min(states, key=lambda s: abs(s["frac"] - f)))
            checkpoints[str(f)] = {
                "calibrated_simulator": score(pick, [combine(np.array(s["p"]), order_prior(s, beta), tau, w)
                                                     for s in pick]),
                "running_order_prior": score(pick, [order_prior(s, beta) for s in pick]),
            }
        res["checkpoints"] = checkpoints
        return res

    test_states = flat(kappa, "test")
    probs = [combine(np.array(s["p"]), order_prior(s, beta), tau, w) for s in test_states]
    bins = np.linspace(0, 1, 11)
    allp = np.concatenate(probs)
    ally = np.concatenate([np.eye(len(p))[s["winner_idx"]] for s, p in zip(test_states, probs, strict=True)])
    reliability = []
    for a, b in zip(bins[:-1], bins[1:], strict=True):
        m = (allp >= a) & (allp < b if b < 1 else allp <= b)
        if m.sum():
            reliability.append({"bin": [round(a, 1), round(b, 1)], "mean_pred": float(allp[m].mean()),
                                "observed": float(ally[m].mean()), "n": int(m.sum())})
    result = {
        "protocol": {"dev_races": [r.circuit for r in races[:N_DEV]],
                     "test_races": [r.circuit for r in races[N_DEV:]], "sims": sims,
                     "priors": priors.__dict__},
        "chosen": {"kappa": kappa, "tau": tau, "w": w, "order_prior_beta": beta.tolist()},
        "dev": evaluate("dev"), "test": evaluate("test"), "reliability_test": reliability, "grid": grid,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "winprob.json").write_text(json.dumps(result, indent=2))
    (out_dir / "WINPROB.md").write_text(to_markdown(result))
    return result


def to_markdown(r: dict) -> str:
    names = ["calibrated_simulator", "raw_simulator", "running_order_prior", "leader_takes_all"]
    c = r["chosen"]
    lines = ["# Live win probability: evaluation", "",
             f"Dev races (tuning): {', '.join(r['protocol']['dev_races'])}",
             f"Test races (scored once): {', '.join(r['protocol']['test_races'])}",
             f"Chosen on dev: kappa={c['kappa']}, tau={c['tau']}, w={c['w']}", "",
             "Scored on every lap from 15 % race distance (lower log-loss / Brier is better):", "",
             "| Method | Split | Laps | Log-loss | Brier | Top-pick accuracy |", "|---|---|---|---|---|---|"]
    for split in ("dev", "test"):
        for n in names:
            s = r[split][n]
            lines.append(f"| {n} | {split} | {s['n']} | {s['log_loss']:.3f} | {s['brier']:.3f} | "
                         f"{s['top_pick_accuracy']:.1%} |")
    lines += ["", "## Test checkpoints", "", "| Race distance | Method | Log-loss | Brier | Top pick |",
              "|---|---|---|---|---|"]
    for f, v in r["test"]["checkpoints"].items():
        for n, s in v.items():
            lines.append(f"| {float(f):.0%} | {n} | {s['log_loss']:.3f} | {s['brier']:.3f} | "
                         f"{s['top_pick_accuracy']:.0%} ({s['n']} races) |")
    lines += ["", "## Reliability (test, all drivers and laps)", "", "| Predicted | Mean predicted | Observed | n |",
              "|---|---|---|---|"]
    lines += [f"| {b['bin'][0]:.1f}–{b['bin'][1]:.1f} | {b['mean_pred']:.3f} | {b['observed']:.3f} | {b['n']} |"
              for b in r["reliability_test"]]
    return "\n".join(lines) + "\n"
