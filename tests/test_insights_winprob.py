import numpy as np
import pytest

from pitwall.insights import dirty_air, overtakes
from pitwall.laps import clean_laps
from pitwall.model import fit
from pitwall.winprob import Priors, calibrated, win_probabilities
from tests.conftest import iso, make_race


def test_win_probability_favours_the_clearly_faster_car():
    race = make_race(laps_per_driver=40, pace=(0.0, 0.8, 1.6, 2.4), noise=0.1, seed=2)
    wp = win_probabilities(race, [], Priors(sc_per_lap=0.0, dnf_per_car_lap=0.0), sims=500)
    assert wp["laps"], "simulator produced no states"
    late = wp["states"][-1]
    p = dict(zip(late["drivers"], late["p"], strict=True))
    assert p[1] > 0.95
    assert abs(sum(late["p"]) - 1) < 1e-9


def test_calibrated_series_are_probabilities():
    race = make_race(laps_per_driver=40, pace=(0.0, 0.3, 0.6, 0.9), noise=0.2, seed=5)
    states = win_probabilities(race, [], Priors(), sims=300)["states"]
    cal = calibrated(states)
    totals = np.sum([v for v in cal["win"].values()], axis=0)
    assert np.all(totals <= 1 + 1e-3) and np.all(totals > 0.9)  # rounded to 4 dp; drivers < 3 % all race dropped


def test_dirty_air_recovers_injected_penalty():
    race = make_race(laps_per_driver=40, pace=(0, 0.1, 0.2, 0.3, 0.4, 0.5), noise=0.05, seed=7)
    rng = np.random.default_rng(0)
    intervals = []
    for lap in race.laps:
        close = rng.random() < 0.35
        gap = 0.6 if close else 4.0
        if close and not lap.pit_out:
            lap.duration += 0.5  # stuck in dirty air
        intervals.append({"driver_number": lap.driver, "date": iso(lap.start + 5), "interval": gap})
    race.intervals = intervals
    rows = clean_laps(race)
    m = fit(rows)
    res = dirty_air(race, m, rows, bootstrap=100)
    assert res["cost"] == pytest.approx(0.5, abs=0.12)
    assert res["ci90"][0] < res["cost"] < res["ci90"][1]


def test_overtakes_ignore_pit_stops_and_pair_the_cars():
    race = make_race(laps_per_driver=30, pace=(0, 0.5, 1.0))
    t_pass, t_pit = 600.0, race.laps[[(lap.driver, lap.lap) for lap in race.laps].index((1, 15))].start
    def pos(d, p, t):
        return {"driver_number": d, "position": p, "date": iso(t)}

    race.positions = [
        pos(1, 1, 0), pos(2, 2, 0), pos(3, 3, 0),
        pos(3, 2, t_pass), pos(2, 3, t_pass),  # on-track pass: 3 takes P2 from 2
        pos(1, 2, t_pit), pos(3, 1, t_pit),  # pit-stop swap: 1 drops behind 3 while stopping -> not a pass
    ]
    passes = overtakes(race, [])
    assert [(p["by"], p["on"], p["position"]) for p in passes] == [(3, 2, 2)]


def test_site_calibration_matches_the_evaluated_model():
    """The frozen constants used by the site build must reproduce winprob_eval's combination exactly."""
    from pitwall.winprob import CALIBRATION
    from pitwall.winprob_eval import combine, order_prior

    state = {"lap": 30, "frac": 0.5, "drivers": [1, 2, 3, 4], "p": [0.6, 0.3, 0.1, 0.0],
             "pos": [2, 1, 3, 4], "pos_raw": [1, 2, 3, 4]}
    expected = combine(np.array(state["p"]), order_prior(state, np.array(CALIBRATION["beta"])),
                       CALIBRATION["tau"], CALIBRATION["w"])
    got = [calibrated([state])["win"].get(str(d), [0.0])[0] for d in state["drivers"]]
    assert np.allclose(got, np.where(expected >= 0.03, expected, 0.0), atol=1e-4)
