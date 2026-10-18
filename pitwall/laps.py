"""Neutralised periods (SC / VSC / red flag) and clean-lap selection."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .race import Race


@dataclass
class Window:
    start: float
    end: float
    kind: str  # "SC" | "VSC" | "RED"


def _lap_medians(race: Race) -> tuple[dict[int, float], float]:
    """Median lap time of the field for every lap number (pit laps excluded) and the race median."""
    in_laps = {(lap.driver, lap.lap - 1) for lap in race.laps if lap.pit_out}
    by_lap: dict[int, list[float]] = {}
    for lap in race.laps:
        if lap.duration and not lap.pit_out and (lap.driver, lap.lap) not in in_laps:
            by_lap.setdefault(lap.lap, []).append(lap.duration)
    med = {n: float(np.median(v)) for n, v in by_lap.items() if len(v) >= 3}
    return med, float(np.median(list(med.values()))) if med else 0.0


def neutral_windows(race: Race) -> list[Window]:
    """Time windows in which racing was neutralised.

    Race-control messages give the windows (VSC DEPLOYED→ENDING, SAFETY CAR DEPLOYED→end of the lap in
    which "SAFETY CAR IN THIS LAP" was shown, RED→GREEN). OpenF1 occasionally misses the closing or
    the red-flag message, so timing data backs them up:

    * a Safety Car that is never called in ends at the first lap where the field is back to racing pace,
    * any lap on which the field median is ≥3× a normal lap is a suspension (red flag).
    """
    msgs = sorted(race.race_control, key=lambda m: m["date"])
    leader = {}
    for lap in race.laps:
        if lap.lap not in leader or lap.start < leader[lap.lap]:
            leader[lap.lap] = lap.start
    lap_starts = sorted(leader.values())
    med, normal = _lap_medians(race)

    def back_to_green(t: float) -> float:
        for n in sorted(leader):
            if leader[n] > t + 5 and med.get(n, 1e9) <= 1.07 * normal:
                return leader[n]
        return race.end_time

    out: list[Window] = []
    open_: dict[str, float] = {}
    for m in msgs:
        t, text = race.rel(m["date"]), (m.get("message") or "").upper()
        flag, scope = m.get("flag"), m.get("scope")
        if "VSC DEPLOYED" in text or "VIRTUAL SAFETY CAR DEPLOYED" in text:
            open_.setdefault("VSC", t)
        elif ("VSC ENDING" in text or "VIRTUAL SAFETY CAR ENDING" in text) and "VSC" in open_:
            out.append(Window(open_.pop("VSC"), t, "VSC"))
        elif "SAFETY CAR DEPLOYED" in text:
            open_.setdefault("SC", t)
        elif "SAFETY CAR IN THIS LAP" in text and "SC" in open_:
            nxt = [s for s in lap_starts if s > t + 5]
            out.append(Window(open_.pop("SC"), nxt[0] if nxt else t + 120, "SC"))
        elif flag == "RED" and scope == "Track":
            open_.setdefault("RED", t)
        elif flag == "GREEN" and scope == "Track" and "RED" in open_:
            out.append(Window(open_.pop("RED"), t, "RED"))
    for kind, start in open_.items():
        out.append(Window(start, back_to_green(start) if kind == "SC" else race.end_time, kind))
    for n, m in med.items():
        if normal and m >= 3 * normal and n in leader:
            start = leader[n]
            if not any(w.kind == "RED" and w.start <= start + m and w.end >= start for w in out):
                out.append(Window(start, start + m, "RED"))
    return sorted(out, key=lambda w: w.start)


def pit_stops(race: Race) -> list[tuple[int, int]]:
    """(driver, out-lap) for every stop, from the timing flag ``is_pit_out_lap``.

    OpenF1's pit endpoint is not consistent about whether ``lap_number`` is the in-lap or the
    out-lap (it differs between events), so the lap flags are the source of truth.
    """
    return sorted((lap.driver, lap.lap) for lap in race.laps if lap.pit_out and lap.lap > 1)


def clean_laps(race: Race, windows: list[Window] | None = None, slow_factor: float = 1.07) -> list[dict]:
    """Green-flag racing laps usable for pace and tyre modelling.

    Excludes lap 1, pit-out laps, in-laps, laps touching a neutralised window (plus 10 s margin),
    and laps slower than 107 % of the driver's median clean lap.
    """
    windows = neutral_windows(race) if windows is None else windows
    stints = race.stints
    in_laps = {(d, n - 1) for d, n in pit_stops(race)}
    rows = []
    for lap in race.laps:
        if not lap.duration or lap.lap == 1 or lap.pit_out or (lap.driver, lap.lap) in in_laps:
            continue
        a, b = lap.start, lap.start + lap.duration
        if any(a < w.end + 10 and b > w.start - 10 for w in windows):
            continue
        stint = next((s for s in stints if s["driver_number"] == lap.driver
                      and s["lap_start"] <= lap.lap <= (s["lap_end"] or 999)), None)
        if not stint or not stint.get("compound") or stint["compound"] == "UNKNOWN":
            continue
        rows.append(
            {
                "driver": lap.driver,
                "lap": lap.lap,
                "time": lap.duration,
                "compound": stint["compound"],
                "stint": stint["stint_number"],
                "tyre_age": (stint.get("tyre_age_at_start") or 0) + lap.lap - stint["lap_start"],
            }
        )
    by_driver: dict[int, list[float]] = {}
    for r in rows:
        by_driver.setdefault(r["driver"], []).append(r["time"])
    med = {d: float(np.median(v)) for d, v in by_driver.items()}
    return [r for r in rows if r["time"] <= slow_factor * med[r["driver"]]]
