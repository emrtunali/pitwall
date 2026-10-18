"""Fetch one race from OpenF1 and normalise it onto a single race clock.

All timestamps become seconds since ``t0`` (the start of lap 1), which is the clock the
replay, the charts and the model share.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

from .openf1 import OpenF1


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s)


@dataclass
class Lap:
    driver: int
    lap: int
    start: float  # seconds since t0
    duration: float | None
    sectors: tuple[float | None, float | None, float | None]
    pit_out: bool


@dataclass
class Race:
    session_key: int
    meeting_key: int
    name: str
    circuit: str
    country: str
    date: str
    t0: datetime
    drivers: list[dict]
    laps: list[Lap]
    stints: list[dict]
    pits: list[dict]
    race_control: list[dict]
    weather: list[dict]
    positions: list[dict]
    intervals: list[dict]
    results: list[dict]
    locations: dict[int, np.ndarray] = field(default_factory=dict)  # driver -> (n, 3) [t, x, y]

    def rel(self, ts: str) -> float:
        return (parse_ts(ts) - self.t0).total_seconds()

    @property
    def total_laps(self) -> int:
        finished = [r["number_of_laps"] for r in self.results if r.get("number_of_laps")]
        return max(finished) if finished else max(lap.lap for lap in self.laps)

    @property
    def end_time(self) -> float:
        ends = [lap.start + lap.duration for lap in self.laps if lap.duration]
        return max(ends) if ends else 0.0


def _meeting_name(api: OpenF1, meeting_key: int) -> str:
    meetings = api.get("meetings", meeting_key=meeting_key)
    return meetings[0]["meeting_name"] if meetings else ""


def fetch_race(api: OpenF1, session: dict, with_locations: bool = True, window_s: int = 300) -> Race:
    key = session["session_key"]
    raw_laps = api.get("laps", session_key=key)
    starts = [parse_ts(lap["date_start"]) for lap in raw_laps if lap["lap_number"] == 1 and lap.get("date_start")]
    if not starts:
        raise ValueError(f"session {key} has no lap data")
    t0 = min(starts)

    race = Race(
        session_key=key,
        meeting_key=session["meeting_key"],
        name=_meeting_name(api, session["meeting_key"]),
        circuit=session["circuit_short_name"],
        country=session["country_name"],
        date=session["date_start"][:10],
        t0=t0,
        drivers=api.get("drivers", session_key=key),
        laps=[],
        stints=api.get("stints", session_key=key),
        pits=api.get("pit", session_key=key),
        race_control=api.get("race_control", session_key=key),
        weather=api.get("weather", session_key=key),
        positions=api.get("position", session_key=key),
        intervals=api.get("intervals", session_key=key),
        results=api.get("session_result", session_key=key),
    )
    for lap in raw_laps:
        if not lap.get("date_start"):
            continue
        race.laps.append(
            Lap(
                driver=lap["driver_number"],
                lap=lap["lap_number"],
                start=race.rel(lap["date_start"]),
                duration=lap.get("lap_duration"),
                sectors=(lap.get("duration_sector_1"), lap.get("duration_sector_2"), lap.get("duration_sector_3")),
                pit_out=bool(lap.get("is_pit_out_lap")),
            )
        )
    if with_locations:
        race.locations = fetch_locations(api, race, window_s)
    return race


def fetch_locations(api: OpenF1, race: Race, window_s: int = 300) -> dict[int, np.ndarray]:
    """Car x/y positions (~3.7 Hz) from 2 minutes before lap 1 to the end of the race.

    One request per time window covers all cars, which keeps a full race to ~25 requests.
    """
    start = race.t0 - timedelta(seconds=120)
    end = race.t0 + timedelta(seconds=race.end_time + 120)
    rows: dict[int, list[tuple[float, float, float]]] = {d["driver_number"]: [] for d in race.drivers}
    t = start
    while t < end:
        t_next = min(t + timedelta(seconds=window_s), end)
        chunk = api.get(
            "location", session_key=race.session_key, **{"date>": t.isoformat(), "date<": t_next.isoformat()}
        )
        for p in chunk:
            rows.setdefault(p["driver_number"], []).append((race.rel(p["date"]), p["x"], p["y"]))
        t = t_next
    return {num: np.array(sorted(set(r)), dtype=np.float64).reshape(-1, 3) for num, r in rows.items() if r}
