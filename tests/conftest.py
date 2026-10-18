from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from pitwall.race import Lap, Race

T0 = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def iso(seconds: float) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat()


def make_race(laps_per_driver: int = 30, pit_lap: int = 15, deg=(0.08, 0.03), fuel: float = -0.05,
              pace=(0.0, 0.5, 1.0), noise: float = 0.0, seed: int = 0,
              race_control: list[dict] | None = None) -> Race:
    """A synthetic one-stop race with known degradation, fuel effect and driver pace."""
    rng = np.random.default_rng(seed)
    base = {"SOFT": 90.0, "HARD": 90.6}
    laps, stints = [], []
    for i, offset in enumerate(pace):
        d = i + 1
        t = 0.0
        stop = pit_lap + 3 * i  # staggered stops: real races are what make tyre age and lap number separable
        stints += [
            {"driver_number": d, "stint_number": 1, "lap_start": 1, "lap_end": stop - 1, "compound": "SOFT",
             "tyre_age_at_start": 0},
            {"driver_number": d, "stint_number": 2, "lap_start": stop, "lap_end": laps_per_driver,
             "compound": "HARD", "tyre_age_at_start": 0},
        ]
        for n in range(1, laps_per_driver + 1):
            comp, age, k = ("SOFT", n - 1, 0) if n < stop else ("HARD", n - stop, 1)
            dur = base[comp] + offset + deg[k] * age + fuel * n + rng.normal(0, noise)
            if n == stop - 1:
                dur += 8.0  # in-lap
            if n == stop:
                dur += 14.0  # out-lap
            laps.append(Lap(d, n, t, dur, (None, None, None), n == stop))
            t += dur
    return Race(
        session_key=1, meeting_key=1, name="Test Grand Prix", circuit="Testring", country="Nowhere",
        date="2026-10-11", t0=T0, drivers=[{"driver_number": d, "name_acronym": f"D{d:02d}"[:3],
                                            "full_name": f"Driver {d}", "team_name": "Team", "team_colour": "FF0000"}
                                           for d in range(1, len(pace) + 1)],
        laps=laps, stints=stints, pits=[], race_control=race_control or [], weather=[], positions=[], intervals=[],
        results=[{"driver_number": d, "position": d, "number_of_laps": laps_per_driver}
                 for d in range(1, len(pace) + 1)],
    )


@pytest.fixture
def race() -> Race:
    return make_race()
