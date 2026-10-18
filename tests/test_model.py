import numpy as np
import pytest

from pitwall.backtest import forecast_stints, summarize
from pitwall.laps import clean_laps, pit_stops
from pitwall.model import fit
from pitwall.strategy import pit_loss, what_if
from tests.conftest import make_race


def test_pit_stops_come_from_timing_flags(race):
    assert pit_stops(race) == [(1, 15), (2, 18), (3, 21)]


def test_clean_laps_drop_lap1_inlap_and_outlap(race):
    laps = {(r["driver"], r["lap"]) for r in clean_laps(race)}
    assert (1, 1) not in laps and (1, 14) not in laps and (1, 15) not in laps
    assert (1, 2) in laps and (1, 16) in laps


def test_model_recovers_known_degradation_fuel_and_pace():
    rows = clean_laps(make_race())
    m = fit(rows)
    assert m.deg["SOFT"] == pytest.approx(0.08, abs=1e-6)
    assert m.deg["HARD"] == pytest.approx(0.03, abs=1e-6)
    assert m.fuel == pytest.approx(-0.05, abs=1e-6)
    assert m.pace[2] - m.pace[1] == pytest.approx(0.5, abs=1e-6)


def test_model_is_robust_to_traffic_outliers():
    race = make_race(noise=0.05, seed=1)
    for lap in race.laps[3:60:7]:
        lap.duration += 2.5  # stuck behind a slower car: one-sided outliers
    m = fit(clean_laps(race))
    assert m.deg["SOFT"] == pytest.approx(0.08, abs=0.01)


def test_bootstrap_interval_contains_truth():
    m = fit(clean_laps(make_race(noise=0.15, seed=3, pace=(0, 0.3, 0.6, 0.9))), bootstrap=200)
    lo, hi = m.deg_ci["SOFT"]
    assert lo < 0.08 < hi


def test_pit_loss_measures_the_added_time():
    race = make_race(laps_per_driver=40, pace=(0, 0.2, 0.4, 0.6))
    m = fit(clean_laps(race))
    loss = pit_loss(race, m, [])
    assert loss["median"] == pytest.approx(22.0, abs=1e-6)  # +8 s in-lap, +14 s out-lap
    assert loss["n"] == 4


def test_what_if_curve_is_zero_at_actual_stop():
    race = make_race(deg=(0.3, 0.03))
    m = fit(clean_laps(race))
    curve = what_if(race, m, 22.0, 1)[0]
    assert dict(curve["curve"])[curve["actual_lap"]] == 0.0
    # softs fall off a cliff (0.3 s/lap), so the model wants driver 1 to stop earlier than lap 14
    assert curve["model_best_lap"] < curve["actual_lap"]


def test_forecast_beats_flat_when_degradation_is_real():
    rows = clean_laps(make_race(noise=0.1, seed=4, pace=(0, 0.2, 0.4, 0.6, 0.8)))
    s = summarize(forecast_stints(rows))
    assert s["mae"]["model"] < s["mae"]["flat"]
    assert s["mae"]["model"] < s["mae"]["no_deg"]


def test_compound_with_too_few_laps_is_not_published():
    m = fit(clean_laps(make_race(laps_per_driver=12, pit_lap=5)))
    assert m.to_json()["deg_per_lap"] == {}


def test_unidentifiable_design_is_rejected():
    race = make_race()
    for s in race.stints:  # everyone stops on the same lap -> tyre age is collinear with lap number
        s["lap_end"], s["lap_start"] = (14, 1) if s["stint_number"] == 1 else (s["lap_end"], 15)
    for lap in race.laps:
        lap.pit_out = lap.lap == 15
    with pytest.raises(ValueError, match="identif"):
        fit(clean_laps(race))


def test_huber_handles_constant_residuals():
    m = fit(clean_laps(make_race()))
    assert np.isfinite(m.sigma)
