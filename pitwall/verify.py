"""Data audit: cross-check the timing feed against the official classification, race by race.

Checks (all independent of the models):

1. **Race time** — the winner's lap times summed vs. the official race time. Expected: a small,
   constant offset (lap 1 is timed from the line, the race clock from the start lights).
2. **Gaps** — every classified car on the lead lap: the gap computed from lap timing vs. the official
   gap. Differences of 5 / 10 / 20 s that match a stewards' time penalty for that car are expected
   (the official result includes penalties, on-track timing does not).
3. **Lap records** — laps per driver in the timing feed vs. laps in the classification. One extra lap
   for a retired car is expected (the lap it stopped on); missing laps are feed gaps.
4. **Championship** — handled in ``build.season_standings`` (computed vs. official table).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .build import completed_races, season_standings
from .openf1 import OpenF1
from .race import Race, fetch_race

PENALTY_RE = re.compile(r"(\d+) SECOND TIME PENALTY FOR CAR (\d+)")


def _penalties(race: Race) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for m in race.race_control:
        for secs, car in PENALTY_RE.findall((m.get("message") or "").upper()):
            if "SERVED" not in m["message"].upper():
                out.setdefault(int(car), []).append(int(secs))
    return out


def audit_race(race: Race) -> dict:
    winner = next(x for x in race.results if x.get("position") == 1)
    w = winner["driver_number"]
    wl = sorted((lap for lap in race.laps if lap.driver == w), key=lambda lap: lap.lap)
    missing_winner = [lap.lap for lap in wl if lap.duration is None]
    official = winner.get("duration")
    race_time = None
    if official and not missing_winner and len(wl) == winner.get("number_of_laps"):
        race_time = round(sum(lap.duration for lap in wl) - official, 3)

    end = {(lap.driver, lap.lap): lap.start + lap.duration for lap in race.laps if lap.duration}
    pens = _penalties(race)
    gaps = {"checked": 0, "within_1s": 0, "explained_by_penalty": 0, "round_penalty_without_message": [],
            "unexplained": []}
    n_lead = winner.get("number_of_laps")
    for x in race.results:
        gap = x.get("gap_to_leader")
        d = x["driver_number"]
        if d == w or x.get("number_of_laps") != n_lead or not isinstance(gap, (int, float)):
            continue
        if (d, n_lead) not in end or (w, n_lead) not in end:
            continue
        err = gap - (end[(d, n_lead)] - end[(w, n_lead)])
        gaps["checked"] += 1
        # the winner's own penalties shift everyone's official gap the other way
        candidates = [p - q for p in [0] + pens.get(d, []) + [sum(pens.get(d, []))]
                      for q in [0] + pens.get(w, [])]
        if abs(err) <= 1.0:
            gaps["within_1s"] += 1
        elif any(abs(err - c) <= 1.0 for c in candidates if c):
            gaps["explained_by_penalty"] += 1
        elif err > 0 and abs(err / 5 - round(err / 5)) * 5 <= 0.4:
            # an exact multiple of 5 s with no stewards' message in the feed: a penalty given after the race
            gaps["round_penalty_without_message"].append({"driver": d, "difference_s": round(err, 2)})
        else:
            gaps["unexplained"].append({"driver": d, "difference_s": round(err, 2)})

    laps_by_driver: dict[int, int] = {}
    for lap in race.laps:
        laps_by_driver[lap.driver] = laps_by_driver.get(lap.driver, 0) + 1
    lap_records = {"expected_extra_lap_on_retirement": 0, "missing": [], "other": []}
    for x in race.results:
        d, n = x["driver_number"], x.get("number_of_laps") or 0
        have = laps_by_driver.get(d, 0)
        if have == n:
            continue
        if have == n + 1 and (x.get("dnf") or x.get("dns")):
            lap_records["expected_extra_lap_on_retirement"] += 1
        elif have < n:
            lap_records["missing"].append({"driver": d, "classified": n, "in_feed": have})
        else:
            lap_records["other"].append({"driver": d, "classified": n, "in_feed": have})
    return {"circuit": race.circuit, "race_time_offset_s": race_time, "winner_missing_lap_times": missing_winner,
            "gaps": gaps, "lap_records": lap_records}


def run(api: OpenF1, out_dir: Path, year: int = 2026) -> dict:
    sessions = sorted(completed_races(api, year), key=lambda s: s["date_start"])
    races = [audit_race(fetch_race(api, s, with_locations=False)) for s in sessions]
    standings = season_standings(api, sessions, year)["validation"]
    total = {
        "races": len(races),
        "gaps_checked": sum(r["gaps"]["checked"] for r in races),
        "gaps_within_1s": sum(r["gaps"]["within_1s"] for r in races),
        "gaps_explained_by_penalty": sum(r["gaps"]["explained_by_penalty"] for r in races),
        "gaps_round_penalty_without_message": sum(len(r["gaps"]["round_penalty_without_message"]) for r in races),
        "gaps_unexplained": sum(len(r["gaps"]["unexplained"]) for r in races),
        "missing_lap_records": sum(len(r["lap_records"]["missing"]) for r in races),
        "standings_checks": standings["driver_round_pairs_checked"],
        "standings_mismatches": len(standings["mismatches"]),
    }
    out = {"summary": total, "races": races}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "data_checks.json").write_text(json.dumps(out, indent=2))
    (out_dir / "DATA_CHECKS.md").write_text(to_markdown(out))
    return out


def to_markdown(r: dict) -> str:
    s = r["summary"]
    lines = ["# Data audit", "",
             "Timing feed cross-checked against the official classification for every race (`pitwall verify`).", "",
             f"- Championship: **{s['standings_checks']}** computed driver totals vs the official table, "
             f"**{s['standings_mismatches']}** mismatches",
             f"- Finishing gaps: **{s['gaps_checked']}** checked — {s['gaps_within_1s']} within 1 s, "
             f"{s['gaps_explained_by_penalty']} differ by exactly a stewards' time penalty, "
             f"{s['gaps_round_penalty_without_message']} by an exact multiple of 5 s with no message in the feed "
             f"(post-race penalties), **{s['gaps_unexplained']}** unexplained",
             f"- Lap records missing from the feed: **{s['missing_lap_records']}** "
             "(listed below; charts fall back to the next lap's start time)", "",
             "| Race | Σ lap times − official race time | Gaps ≤1 s | Penalty | Post-race penalty | Unexplained |"
             " Missing laps |",
             "|---|---|---|---|---|---|---|"]
    for x in r["races"]:
        g, lr = x["gaps"], x["lap_records"]
        rt = "n/a (lap time missing)" if x["race_time_offset_s"] is None else f"{x['race_time_offset_s']:+.3f} s"
        miss = ", ".join(f"car {m['driver']} ({m['in_feed']}/{m['classified']})" for m in lr["missing"]) or "–"
        unex = ", ".join(f"car {u['driver']} ({u['difference_s']:+} s)" for u in g["unexplained"]) or "–"
        post = ", ".join(f"car {u['driver']} ({u['difference_s']:+} s)"
                         for u in g["round_penalty_without_message"]) or "–"
        lines.append(f"| {x['circuit']} | {rt} | {g['within_1s']}/{g['checked']} | {g['explained_by_penalty']} "
                     f"| {post} | {unex} | {miss} |")
    return "\n".join(lines) + "\n"
