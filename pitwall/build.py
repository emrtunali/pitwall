"""Build the static site's data: one compact bundle per race plus a season index.

Per race:  ``site/data/2026/<slug>/race.json`` (timing, strategy, model) and
           ``positions.bin`` (int16 x/y for every car at 4 Hz, little-endian, driver-major).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from .insights import corrected_pace, dirty_air, overtakes
from .laps import clean_laps, neutral_windows, pit_stops
from .model import fit
from .openf1 import OpenF1
from .race import Race, fetch_race
from .strategy import pit_loss, what_if
from .track import rdp, resample_positions, track_outline
from .winprob import CALIBRATION, N_PRIOR_RACES, Priors, calibrated, estimate_priors, win_probabilities

HZ = 4.0


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(float(x), nd)


def race_bundle(race: Race, priors: Priors | None = None) -> tuple[dict, np.ndarray]:
    windows = neutral_windows(race)
    rows = clean_laps(race, windows)
    model = fit(rows, bootstrap=300)
    loss = pit_loss(race, model, windows)
    grid, t_first, order = resample_positions(race, HZ)
    track = track_outline(race)

    by_num = {d["driver_number"]: d for d in race.drivers}
    drivers = [
        {"num": n, "code": by_num[n]["name_acronym"], "name": by_num[n]["full_name"].title(),
         "team": by_num[n]["team_name"], "colour": "#" + (by_num[n].get("team_colour") or "888888")}
        for n in order
    ]
    laps: dict[str, list] = {}
    for lap in sorted(race.laps, key=lambda x: (x.driver, x.lap)):
        laps.setdefault(str(lap.driver), []).append(
            [lap.lap, _r(lap.start), _r(lap.duration), *[_r(s) for s in lap.sectors], int(lap.pit_out)]
        )
    predicted = {}
    for r in rows:
        if r["driver"] not in model.pace or r["compound"] not in model.offset:
            continue  # lap on a compound the model left out (too few laps / one driver)
        predicted.setdefault(str(r["driver"]), []).append(
            [r["lap"], _r(model.predict(r["driver"], r["compound"], r["tyre_age"], r["lap"]))]
        )
    intervals: dict[str, list] = {}
    for iv in race.intervals:
        gap, inter = iv.get("gap_to_leader"), iv.get("interval")
        intervals.setdefault(str(iv["driver_number"]), []).append(
            [_r(race.rel(iv["date"]), 1), gap if isinstance(gap, str) else _r(gap), inter if isinstance(inter, str)
             else _r(inter)]
        )
    bundle = {
        "meta": {
            "session_key": race.session_key, "name": race.name, "circuit": race.circuit, "country": race.country,
            "date": race.date, "total_laps": race.total_laps, "t_end": _r(race.end_time),
            "positions": {"hz": HZ, "t_first": _r(t_first), "samples": int(grid.shape[1]), "order": order,
                          "missing": -32768},
            "source": "OpenF1 (api.openf1.org)",
        },
        "drivers": drivers,
        "track": track,
        "laps": laps,
        "stints": [{"driver": s["driver_number"], "stint": s["stint_number"], "from": s["lap_start"],
                    "to": s["lap_end"], "compound": s.get("compound"), "age": s.get("tyre_age_at_start")}
                   for s in race.stints],
        "pits": pit_list(race),
        "race_control": [[_r(race.rel(m["date"]), 1), m.get("lap_number"), m.get("category"), m.get("flag"),
                          m.get("message")] for m in race.race_control if race.rel(m["date"]) > -600],
        "neutral": [[_r(w.start, 1), _r(w.end, 1), w.kind] for w in windows],
        "weather": [[_r(race.rel(w["date"]), 0), w.get("air_temperature"), w.get("track_temperature"),
                     w.get("rainfall"), w.get("wind_speed")] for w in race.weather],
        "positions_timeline": [[_r(race.rel(p["date"]), 1), p["driver_number"], p["position"]]
                               for p in race.positions],
        "intervals": intervals,
        "results": [{"driver": r["driver_number"], "pos": r.get("position"), "laps": r.get("number_of_laps"),
                     "points": r.get("points"), "dnf": r.get("dnf"), "dns": r.get("dns"), "dsq": r.get("dsq"),
                     "gap": r.get("gap_to_leader")} for r in race.results],
        "model": model.to_json() | {"pit_loss": loss, "predicted": predicted},
        "insights": {
            "dirty_air": dirty_air(race, model, rows),
            "overtakes": overtakes(race, windows),
            "corrected_pace": corrected_pace(model, race),
        },
        "win_probability": calibrated(win_probabilities(race, windows, priors or Priors(), sims=2000,
                                                        kappa=CALIBRATION["kappa"])["states"]),
        "strategy": {str(d): s for d in order if loss["median"] and (s := what_if(race, model, loss["median"], d))},
    }
    return bundle, grid


def pit_list(race: Race) -> list[dict]:
    """Stops from the timing flags; OpenF1's pit-lane time is attached when a record lies within 60 s."""
    lap_by = {(lap.driver, lap.lap): lap for lap in race.laps}
    out = []
    for d, n in pit_stops(race):
        t = lap_by[(d, n)].start
        near = [p for p in race.pits if p["driver_number"] == d and abs(race.rel(p["date"]) - t) < 60]
        lane = near[0].get("lane_duration") or near[0].get("pit_duration") if near else None
        out.append({"driver": d, "out_lap": n, "t": _r(t, 1), "lane": lane})
    return out


def write_race(race: Race, out_dir: Path, priors: Priors | None = None) -> dict:
    bundle, grid = race_bundle(race, priors)
    slug = slugify(race.name)
    d = out_dir / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "race.json").write_text(json.dumps(bundle, separators=(",", ":"), ensure_ascii=False))
    grid.astype("<i2").tofile(d / "positions.bin")
    winner = next((r for r in race.results if r.get("position") == 1), None)
    by_num = {x["driver_number"]: x for x in race.drivers}
    return {
        "slug": slug, "name": race.name, "circuit": race.circuit, "country": race.country, "date": race.date,
        "session_key": race.session_key, "laps": race.total_laps,
        "winner": by_num[winner["driver_number"]]["name_acronym"] if winner else None,
        "deg": bundle["model"]["deg_per_lap"], "deg_ci": bundle["model"]["deg_ci90"],
        "pit_loss": bundle["model"]["pit_loss"]["median"],
        "outline": rdp_outline(bundle["track"]["outline"]),
        "dirty_air": bundle["insights"]["dirty_air"],
        "overtakes": len(bundle["insights"]["overtakes"]),
        "team_pace": bundle["insights"]["corrected_pace"]["teams"],
    }


def rdp_outline(points: list[list[int]], eps: float = 60.0) -> list[list[int]]:
    """A coarse outline (~40-80 points) for the season overview thumbnails."""
    arr = np.array(points, dtype=float)
    mid = len(arr) // 2
    return np.vstack([rdp(arr[: mid + 1], eps), rdp(arr[mid:], eps)[1:]]).round().astype(int).tolist()


SETTLE = timedelta(hours=12)  # OpenF1 needs a little time after the chequered flag to publish everything


def season_calendar(api: OpenF1, year: int) -> list[dict]:
    return api.get("sessions", cache=False, year=year, session_name="Race")


def completed_races(api: OpenF1, year: int, calendar: list[dict] | None = None) -> list[dict]:
    """Races that finished at least SETTLE ago. Waiting matters: responses are cached forever, so
    caching a half-published race would freeze an incomplete copy of it."""
    now = datetime.now(UTC)
    calendar = season_calendar(api, year) if calendar is None else calendar
    return [s for s in calendar if not s.get("is_cancelled") and datetime.fromisoformat(s["date_end"]) + SETTLE < now]


def season_standings(api: OpenF1, sessions: list[dict], year: int) -> dict:
    """Championship progression computed from race + sprint results, checked against the official table.

    After every Grand Prix the computed driver totals are compared with OpenF1's ``championship_drivers``
    snapshot for that race session; any difference is recorded in ``validation``.
    """
    sprints = {s["meeting_key"]: s for s in api.get("sessions", year=year, session_name="Sprint")
               if not s.get("is_cancelled")}
    totals: dict[int, float] = {}
    info: dict[int, dict] = {}
    rounds, mismatches, checked = [], [], 0
    for s in sorted(sessions, key=lambda x: x["date_start"]):
        keys = [s["session_key"]] + ([sprints[s["meeting_key"]]["session_key"]] if s["meeting_key"] in sprints else [])
        for key in keys:
            for r in api.get("session_result", session_key=key):
                totals[r["driver_number"]] = totals.get(r["driver_number"], 0.0) + float(r.get("points") or 0)
        for d in api.get("drivers", session_key=s["session_key"]):
            info[d["driver_number"]] = {"code": d["name_acronym"], "team": d["team_name"],
                                        "colour": "#" + (d.get("team_colour") or "888888")}
        official = {c["driver_number"]: c["points_current"] for c in api.get("championship_drivers",
                                                                           session_key=s["session_key"])}
        for num, pts in official.items():
            checked += 1
            if abs(totals.get(num, 0.0) - pts) > 1e-6:
                mismatches.append({"circuit": s["circuit_short_name"], "driver": num, "computed": totals.get(num, 0.0),
                                   "official": pts})
        rounds.append({"circuit": s["circuit_short_name"], "date": s["date_start"][:10],
                       "sprint": s["meeting_key"] in sprints, "points": dict(sorted(totals.items()))})
    return {"rounds": rounds, "drivers": {str(k): v for k, v in info.items()},
            "validation": {"driver_round_pairs_checked": checked, "mismatches": mismatches}}


def build_site(api: OpenF1, out_root: Path, year: int = 2026, only: set[int] | None = None) -> list[dict]:
    out_dir = out_root / str(year)
    calendar = season_calendar(api, year)
    sessions = [s for s in completed_races(api, year, calendar) if not only or s["session_key"] in only]
    index, skipped = [], []
    first = sorted(completed_races(api, year, calendar), key=lambda s: s["date_start"])[:N_PRIOR_RACES]
    early = [fetch_race(api, s, with_locations=False) for s in first]
    priors = estimate_priors([(r, neutral_windows(r)) for r in early])
    for s in sessions:
        try:
            race = fetch_race(api, s)
            index.append(write_race(race, out_dir, priors))
            print(f"✓ {race.name}", flush=True)
        except Exception as exc:  # one broken race must not take the whole site down
            skipped.append({"circuit": s["circuit_short_name"], "error": f"{type(exc).__name__}: {exc}"})
            print(f"✗ {s['circuit_short_name']}: {exc}", flush=True)
    sessions = [s for s in sessions if s["circuit_short_name"] not in {x["circuit"] for x in skipped}]
    now = datetime.now(UTC)
    upcoming = sorted((s for s in calendar
                       if not s.get("is_cancelled") and datetime.fromisoformat(s["date_start"]) > now),
                      key=lambda s: s["date_start"])
    meta = {"updated_at": now.isoformat(timespec="minutes"), "skipped": skipped,
            "next_race": {"circuit": upcoming[0]["circuit_short_name"], "country": upcoming[0]["country_name"],
                          "start": upcoming[0]["date_start"]} if upcoming else None}
    standings = season_standings(api, sessions, year)
    v = standings["validation"]
    print(f"standings: {v['driver_round_pairs_checked']} checks against the official table, "
          f"{len(v['mismatches'])} mismatches", flush=True)
    (out_dir / "index.json").write_text(json.dumps({"year": year, "races": index, "standings": standings} | meta,
                                                   ensure_ascii=False, separators=(",", ":")))
    return index
