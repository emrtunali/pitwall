import numpy as np

from pitwall.build import slugify
from pitwall.laps import neutral_windows
from pitwall.openf1 import OpenF1
from pitwall.track import MISSING, rdp, resample_positions
from tests.conftest import make_race, rc


def test_vsc_window_from_messages():
    race = make_race(race_control=[rc(300, "VSC DEPLOYED"), rc(400, "VSC ENDING")])
    assert [(w.start, w.end, w.kind) for w in neutral_windows(race)] == [(300, 400, "VSC")]


def test_unclosed_safety_car_ends_when_pace_returns():
    race = make_race(race_control=[rc(500, "SAFETY CAR DEPLOYED")])
    w = neutral_windows(race)[0]
    assert w.kind == "SC" and 500 < w.end < race.end_time  # closed from timing, not at the chequered flag


def test_red_flag_detected_from_timing_when_message_missing():
    race = make_race()
    for lap in race.laps:
        if lap.lap == 10:
            lap.duration += 1800  # suspension
    assert any(w.kind == "RED" for w in neutral_windows(race))


def test_rdp_keeps_corners_drops_collinear():
    pts = np.array([[0, 0], [1, 0], [2, 0], [3, 0], [3, 1], [3, 2]], dtype=float)
    assert rdp(pts, 0.1).tolist() == [[0, 0], [3, 0], [3, 2]]


def test_resample_marks_gaps_missing():
    race = make_race(pace=(0.0,))
    race.locations = {1: np.array([[0, 0, 0], [1, 10, 0], [2, 20, 0], [10, 100, 0], [11, 110, 0]], dtype=float)}
    grid, t0, order = resample_positions(race, hz=2)
    assert order == [1] and t0 == 0
    assert grid[0, 1].tolist() == [5, 0]  # interpolated at t=0.5
    assert grid[0, 12, 0] == MISSING  # t=6 s is >3 s from any real sample


def test_slugify():
    assert slugify("São Paulo Grand Prix") == "s-o-paulo-grand-prix"


def test_openf1_cache_round_trip(tmp_path):
    import httpx

    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json=[{"ok": 1}])

    api = OpenF1(tmp_path, min_interval=0, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert api.get("laps", session_key=1) == [{"ok": 1}]
    assert api.get("laps", session_key=1) == [{"ok": 1}]
    assert len(calls) == 1


def test_chequered_flag_is_not_a_red_flag():
    race = make_race(race_control=[rc(2000, "CHEQUERED FLAG", category="Flag", flag="CHEQUERED", scope="Track")])
    assert neutral_windows(race) == []


def test_red_flag_message_without_scope():
    race = make_race(race_control=[rc(300, "RED FLAG - RACE SUSPENDED", category="Other")])
    assert [w.kind for w in neutral_windows(race)] == ["RED"]
