import numpy as np
import pytest

from pitwall.championship import fit_strengths, order_log_likelihood, points_tables, simulate_season


def _res(order, points=(25, 18, 15, 12, 10, 8, 6, 4, 2, 1), dnf=()):
    out = [{"driver_number": d, "position": i + 1, "points": points[i] if i < len(points) else 0}
           for i, d in enumerate(order)]
    out += [{"driver_number": d, "position": None, "points": 0, "dnf": True} for d in dnf]
    return out


def test_points_tables_are_read_from_results():
    rounds = [{"race": _res([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]), "sprint": _res([1, 2, 3], points=(8, 7, 6))}]
    race, sprint = points_tables(rounds)
    assert race == [25, 18, 15, 12, 10, 8, 6, 4, 2, 1] and sprint == [8, 7, 6]


def test_plackett_luce_gradient_matches_finite_differences():
    orders, w, drivers = [[1, 2, 3, 4], [2, 1, 4, 3], [1, 3, 2, 4]], [1.0, 0.7, 0.4], [1, 2, 3, 4]
    th = fit_strengths(orders, w, drivers, prior=0.5, iters=4000, lr=0.5)

    def objective(t):
        d = dict(zip(drivers, t, strict=True))
        return sum(wi * order_log_likelihood(o, d) for o, wi in zip(orders, w, strict=True)) - 0.25 * np.sum(t ** 2)

    t0 = np.array([th[d] for d in drivers])
    for j in range(4):  # at the optimum every partial derivative of the penalised likelihood is ~0
        e = np.zeros(4)
        e[j] = 1e-5
        assert (objective(t0 + e) - objective(t0 - e)) / 2e-5 == pytest.approx(0, abs=1e-3)
    assert th[1] > th[2] > th[4]


def test_dominant_leader_with_big_margin_wins_title():
    info = {d: {"code": f"D{d}", "name": f"Driver {d}", "team": f"T{(d + 1) // 2}", "colour": "#fff"}
            for d in range(1, 7)}
    rounds = [{"race": _res([1, 2, 3, 4, 5, 6]), "sprint": []} for _ in range(10)]
    upcoming = [{"circuit": "X", "date": "2026-12-01", "sprint": False}]
    res = simulate_season(rounds, upcoming, info, half_life=4.0, prior=1.0, sims=2000)
    top = res["drivers"][0]
    assert top["num"] == 1 and top["p_title"] == 1.0  # 70-point lead with 25 points left
    assert abs(sum(d["p_title"] for d in res["drivers"]) - 1) < 1e-9


def test_open_title_fight_is_uncertain():
    info = {d: {"code": f"D{d}", "name": f"Driver {d}", "team": f"T{d}", "colour": "#fff"} for d in range(1, 5)}
    rounds = [{"race": _res([1, 2, 3, 4] if k % 2 else [2, 1, 3, 4]), "sprint": []} for k in range(6)]
    upcoming = [{"circuit": "X", "date": "2026-12-01", "sprint": False}] * 6
    res = simulate_season(rounds, upcoming, info, half_life=4.0, prior=1.0, sims=4000)
    p = {d["num"]: d["p_title"] for d in res["drivers"]}
    assert 0.25 < p[1] < 0.75 and 0.25 < p[2] < 0.75
