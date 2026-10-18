"""Season-end championship forecast (drivers and constructors).

1. **Race model.** Finishing orders follow a Plackett–Luce model: each driver has a strength θ, and the
   order is drawn by repeatedly picking the next finisher with probability ∝ exp(θ). Strengths are fitted
   by maximum likelihood on the season so far, with recent races weighted more (exponential decay with a
   half-life in races) and a Gaussian prior that shrinks drivers with little data towards the field.
2. **Reliability.** Each driver retires with a probability shrunk from their own record towards the
   field's rate.
3. **Simulation.** The remaining Grands Prix (and sprints, if any are left on the calendar) are simulated
   20,000 times with the points tables read from the season's own results, and the title probability is
   the share of simulations each driver / team finishes on top.

The half-life and prior strength are chosen on the first races only and the race model is scored on the
rest of the season (``evaluate``): we cannot check a title forecast until the season ends, but we can
check the race predictions it is built from.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .build import completed_races, season_calendar
from .openf1 import OpenF1

N_DEV = 8
HALF_LIVES = (2.0, 4.0, 8.0, 1e9)
PRIORS = (1.0, 3.0, 10.0, 30.0, 100.0)
# Scale of log(1 + points) used as the prior mean. With a strong prior the model becomes the
# "standings predict the race" baseline, so the grid contains the baseline as a special case.
ANCHORS = (0.0, 0.5, 0.75, 1.0, 1.25, 1.5)


# ---------------------------------------------------------------- data
def season_results(api: OpenF1, year: int) -> tuple[list[dict], list[dict], dict]:
    """Completed rounds with race and sprint results, the upcoming rounds, and driver info."""
    calendar = season_calendar(api, year)
    done = sorted(completed_races(api, year, calendar), key=lambda s: s["date_start"])
    now = datetime.now(UTC)
    sprints = {s["meeting_key"]: s for s in api.get("sessions", cache=False, year=year, session_name="Sprint")
               if not s.get("is_cancelled")}
    rounds, info = [], {}
    for s in done:
        race = api.get("session_result", session_key=s["session_key"])
        sp = sprints.get(s["meeting_key"])
        sprint = api.get("session_result", session_key=sp["session_key"]) if sp else []
        for d in api.get("drivers", session_key=s["session_key"]):
            info[d["driver_number"]] = {"code": d["name_acronym"], "name": d["full_name"].title(),
                                        "team": d["team_name"], "colour": "#" + (d.get("team_colour") or "888888")}
        rounds.append({"circuit": s["circuit_short_name"], "date": s["date_start"][:10], "race": race,
                       "sprint": sprint})
    upcoming = []
    for s in sorted(calendar, key=lambda x: x["date_start"]):
        if s.get("is_cancelled") or s in done or datetime.fromisoformat(s["date_end"]) < now - _settle():
            continue
        upcoming.append({"circuit": s["circuit_short_name"], "date": s["date_start"][:10],
                         "sprint": s["meeting_key"] in sprints
                         and datetime.fromisoformat(sprints[s["meeting_key"]]["date_end"]) > now})
    return rounds, upcoming, info


def _settle():
    from .build import SETTLE

    return SETTLE


def points_tables(rounds: list[dict]) -> tuple[list[float], list[float]]:
    """Points by finishing position, read from the results (largest award seen per position)."""
    def table(key):
        best: dict[int, float] = {}
        for r in rounds:
            for x in r[key]:
                if x.get("position"):
                    best[x["position"]] = max(best.get(x["position"], 0.0), float(x.get("points") or 0))
        n = max([p for p, v in best.items() if v > 0], default=0)
        return [best.get(p, 0.0) for p in range(1, n + 1)]

    return table("race"), table("sprint")


def finishing_order(results: list[dict]) -> tuple[list[int], list[int]]:
    """Classified drivers in order, and drivers that did not finish."""
    cls = sorted((x for x in results if x.get("position")), key=lambda x: x["position"])
    out = [x["driver_number"] for x in results if not x.get("position")]
    return [x["driver_number"] for x in cls], out


# ---------------------------------------------------------------- Plackett–Luce
def fit_strengths(orders: list[list[int]], weights: list[float], drivers: list[int], prior: float,
                  iters: int = 300, lr: float = 0.3, mean: dict[int, float] | None = None) -> dict[int, float]:
    """MAP Plackett–Luce strengths with a Gaussian prior N(mean, 1/prior) (mean defaults to 0)."""
    idx = {d: i for i, d in enumerate(drivers)}
    mu = np.array([(mean or {}).get(d, 0.0) for d in drivers])
    mu = mu - mu.mean()
    theta = mu.copy()
    for _ in range(iters):
        grad = -prior * (theta - mu)
        for order, w in zip(orders, weights, strict=True):
            ix = np.array([idx[d] for d in order if d in idx])
            if len(ix) < 2:
                continue
            e = np.exp(theta[ix] - theta[ix].max())
            tail = np.maximum(np.cumsum(e[::-1])[::-1], 1e-300)  # sum over drivers still to be placed
            g = np.zeros(len(drivers))
            g[ix] += w
            # d/dθ_j of log(sum_{k≥i} e_k) for every step i where j is still in the set
            frac = np.cumsum(1.0 / tail)  # Σ_{i ≤ pos(j)} 1/tail_i
            g[ix] -= w * e * frac
            grad += g
        theta += lr * grad / (sum(weights) + prior)  # scaled so a strong prior cannot make the step unstable
        theta -= theta.mean()
    return {d: float(theta[idx[d]]) for d in drivers}


def order_log_likelihood(order: list[int], theta: dict[int, float], top: int | None = None) -> float:
    vals = np.array([theta.get(d, 0.0) for d in order])
    ll = 0.0
    for i in range(min(len(vals), top or len(vals)) - 1):
        rest = vals[i:]
        ll += vals[i] - (rest.max() + np.log(np.exp(rest - rest.max()).sum()))
    return float(ll)


def _weights(n: int, half_life: float) -> list[float]:
    return [0.5 ** ((n - 1 - i) / half_life) for i in range(n)]


def standings_points(rounds: list[dict]) -> dict[int, float]:
    pts: dict[int, float] = {}
    for r in rounds:
        for key in ("race", "sprint"):
            for x in r[key]:
                pts[x["driver_number"]] = pts.get(x["driver_number"], 0.0) + float(x.get("points") or 0)
    return pts


def strengths_from(rounds: list[dict], drivers: list[int], half_life: float, prior: float,
                   anchor: float = 0.0) -> dict[int, float]:
    """Strengths from finishing orders, shrunk towards ``anchor``·log(1 + championship points)."""
    pts = standings_points(rounds)
    mean = {d: anchor * np.log1p(pts.get(d, 0.0)) for d in drivers}
    orders, weights = [], []
    for w, r in zip(_weights(len(rounds), half_life), rounds, strict=True):
        cls, _ = finishing_order(r["race"])
        orders.append(cls)
        weights.append(w)
        if r["sprint"]:
            orders.append(finishing_order(r["sprint"])[0])
            weights.append(0.5 * w)  # sprints are shorter and noisier
    return fit_strengths(orders, weights, drivers, prior, mean=mean)


def dnf_rates(rounds: list[dict], drivers: list[int], k: float = 8.0) -> dict[int, float]:
    starts = {d: 0 for d in drivers}
    dnfs = {d: 0 for d in drivers}
    for r in rounds:
        for x in r["race"]:
            d = x["driver_number"]
            if d in starts and not x.get("dns"):
                starts[d] += 1
                dnfs[d] += bool(x.get("dnf"))
    field = sum(dnfs.values()) / max(sum(starts.values()), 1)
    return {d: (dnfs[d] + k * field) / (starts[d] + k) for d in drivers}


# ---------------------------------------------------------------- simulation
def simulate_season(rounds, upcoming, info, half_life, prior, sims=20000, seed=0, anchor: float = 0.0) -> dict:
    rng = np.random.default_rng(seed)
    last = rounds[-1]["race"]
    drivers = [x["driver_number"] for x in last if x["driver_number"] in info]
    theta = strengths_from(rounds, drivers, half_life, prior, anchor)
    dnf = dnf_rates(rounds, drivers)
    race_pts, sprint_pts = points_tables(rounds)
    now = {d: 0.0 for d in drivers}
    team_now: dict[str, float] = {}
    for r in rounds:
        for key in ("race", "sprint"):
            for x in r[key]:
                pts = float(x.get("points") or 0)
                d = x["driver_number"]
                if d in now:
                    now[d] += pts
                team = info.get(d, {}).get("team")
                if team:
                    team_now[team] = team_now.get(team, 0.0) + pts
    D = len(drivers)
    th = np.array([theta[d] for d in drivers])
    p_dnf = np.array([dnf[d] for d in drivers])
    total = np.tile(np.array([now[d] for d in drivers]), (sims, 1))

    def award(table):
        nonlocal total
        out = rng.random((sims, D)) < p_dnf[None, :]
        score = th[None, :] + rng.gumbel(size=(sims, D))  # Gumbel-max trick samples a Plackett–Luce order
        score[out] = -np.inf
        rank = np.argsort(np.argsort(-score, axis=1), axis=1)
        pts = np.array(list(table) + [0.0] * D)
        total += np.where(out, 0.0, pts[rank])

    for rd in upcoming:
        if rd["sprint"] and sprint_pts:
            award(sprint_pts)
        award(race_pts)
    teams = sorted({info[d]["team"] for d in drivers})
    team_total = np.zeros((sims, len(teams)))
    for j, d in enumerate(drivers):
        team_total[:, teams.index(info[d]["team"])] += total[:, j] - now[d]
    team_total += np.array([team_now.get(t, 0.0) for t in teams])[None, :]
    champ = np.argmax(total + rng.random(total.shape) * 1e-6, axis=1)  # random tie-break
    tchamp = np.argmax(team_total + rng.random(team_total.shape) * 1e-6, axis=1)
    drv = []
    for j, d in enumerate(drivers):
        col = total[:, j]
        drv.append({"num": d, **info[d], "points": now[d], "strength": round(theta[d], 3),
                    "p_title": float((champ == j).mean()), "expected": float(col.mean()),
                    "p10": float(np.percentile(col, 10)), "p90": float(np.percentile(col, 90))})
    tm = []
    for j, t in enumerate(teams):
        col = team_total[:, j]
        colour = next(info[d]["colour"] for d in drivers if info[d]["team"] == t)
        tm.append({"team": t, "colour": colour, "points": team_now.get(t, 0.0), "p_title": float((tchamp == j).mean()),
                   "expected": float(col.mean()), "p10": float(np.percentile(col, 10)),
                   "p90": float(np.percentile(col, 90))})
    drv.sort(key=lambda x: (-x["p_title"], -x["points"]))
    tm.sort(key=lambda x: (-x["p_title"], -x["points"]))
    return {"drivers": drv, "teams": tm, "remaining": upcoming, "sims": sims,
            "points_tables": {"race": race_pts, "sprint": sprint_pts}}


# ---------------------------------------------------------------- evaluation
def evaluate_race_model(rounds: list[dict]) -> dict:
    """Score next-race predictions: fit on rounds < k, predict round k (classified order log-likelihood
    of the top 10 and winner log-loss). Hyper-parameters chosen on rounds 2..N_DEV, scored on the rest."""
    def score(k, half_life, prior, anchor):
        order, _ = finishing_order(rounds[k]["race"])
        drivers = sorted({x["driver_number"] for r in rounds[: k + 1] for x in r["race"]})
        th = strengths_from(rounds[:k], drivers, half_life, prior, anchor)
        theta_top = np.array([th.get(d, 0.0) for d in order])
        p_win = np.exp(theta_top[0]) / np.exp(theta_top).sum()
        return order_log_likelihood(order, th, top=10), float(-np.log(p_win))

    def baseline(k):
        """Strength = log of championship points so far (+1): 'the standings predict the race'."""
        order, _ = finishing_order(rounds[k]["race"])
        pts = standings_points(rounds[:k])
        th = {d: np.log1p(pts.get(d, 0.0)) for d in order}
        theta_top = np.array([th[d] for d in order])
        return order_log_likelihood(order, th, top=10), float(-np.log(np.exp(theta_top[0]) / np.exp(theta_top).sum()))

    dev_k = range(1, min(N_DEV, len(rounds)))
    test_k = range(N_DEV, len(rounds))
    grid = []
    for h in HALF_LIVES:
        for pr in PRIORS:
            for an in ANCHORS:
                s = [score(k, h, pr, an) for k in dev_k]
                grid.append({"half_life": h, "prior": pr, "anchor": an,
                             "dev_top10_ll": float(np.mean([a for a, _ in s]))})
    best = max(grid, key=lambda g: g["dev_top10_ll"])
    h, pr, an = best["half_life"], best["prior"], best["anchor"]
    dev_base = float(np.mean([baseline(k)[0] for k in dev_k]))

    def summarize(ks, fn):
        vals = [fn(k) for k in ks]
        return {"n": len(vals), "top10_log_likelihood": float(np.mean([a for a, _ in vals])) if vals else None,
                "winner_log_loss": float(np.mean([b for _, b in vals])) if vals else None}

    uniform = {"top10_log_likelihood": float(np.mean([-sum(np.log(len(finishing_order(rounds[k]["race"])[0]) - i)
                                                            for i in range(9)) for k in test_k])) if test_k else None}
    return {"chosen": {"half_life": h, "prior": pr, "anchor": an}, "grid": grid,
            "dev": {"plackett_luce_top10_ll": best["dev_top10_ll"], "standings_baseline_top10_ll": dev_base},
            "test": {"plackett_luce": summarize(test_k, lambda k: score(k, h, pr, an)),
                     "standings_baseline": summarize(test_k, baseline), "uniform": uniform},
            "dev_rounds": [rounds[k]["circuit"] for k in dev_k], "test_rounds": [rounds[k]["circuit"] for k in test_k]}


def title_odds_history(rounds, upcoming_all, info, half_life, prior, anchor=0.0, sims=5000) -> list[dict]:
    """Title probability after each completed round, using only the rounds up to that point."""
    out = []
    for k in range(3, len(rounds) + 1):
        remaining = [{"circuit": r["circuit"], "date": r["date"], "sprint": bool(r["sprint"])} for r in rounds[k:]]
        res = simulate_season(rounds[:k], remaining + upcoming_all, info, half_life, prior, sims=sims, seed=k,
                              anchor=anchor)
        out.append({"after": rounds[k - 1]["circuit"],
                    "drivers": {str(d["num"]): round(d["p_title"], 4) for d in res["drivers"] if d["p_title"] >= 0.005},
                    "teams": {t["team"]: round(t["p_title"], 4) for t in res["teams"] if t["p_title"] >= 0.005}})
    return out


def run(api: OpenF1, out_dir: Path, site_dir: Path | None, year: int = 2026) -> dict:
    rounds, upcoming, info = season_results(api, year)
    ev = evaluate_race_model(rounds)
    h, pr, an = ev["chosen"]["half_life"], ev["chosen"]["prior"], ev["chosen"]["anchor"]
    forecast = simulate_season(rounds, upcoming, info, h, pr, anchor=an)
    history = title_odds_history(rounds, upcoming, info, h, pr, an)
    result = {"generated_at": datetime.now(UTC).isoformat(timespec="minutes"), "after_round": rounds[-1]["circuit"],
              "rounds_done": len(rounds), "model": ev["chosen"], "forecast": forecast, "history": history,
              "evaluation": {k: v for k, v in ev.items() if k != "grid"}}
    if site_dir is not None:
        (site_dir / str(year)).mkdir(parents=True, exist_ok=True)
        (site_dir / str(year) / "championship.json").write_text(json.dumps(result, separators=(",", ":")))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "championship_eval.json").write_text(json.dumps(ev, indent=2))
    return result
