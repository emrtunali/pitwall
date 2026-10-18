"""The browser simulator (site/whatif.mjs) must give the same numbers as the Python reference."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from pitwall.laps import clean_laps, neutral_windows
from pitwall.model import fit
from pitwall.strategy import pit_loss
from pitwall.whatif import actual_plan, sim_block, simulate
from tests.conftest import make_race, rc

ROOT = Path(__file__).resolve().parent.parent
PLANS = [
    [],
    [{"lap": 12, "compound": "HARD"}],
    [{"lap": 22, "compound": "HARD"}],
    [{"lap": 10, "compound": "HARD"}, {"lap": 25, "compound": "SOFT"}],
]


def _sim():
    race = make_race(laps_per_driver=40, pace=(0, 0.3, 0.6, 0.9), noise=0.1, seed=11,
                     race_control=[rc(1500, "VSC DEPLOYED"), rc(1600, "VSC ENDING")])
    race.results = [r | {"dnf": False, "dns": False} for r in race.results]
    w = neutral_windows(race)
    m = fit(clean_laps(race, w))
    return sim_block(race, m, w, pit_loss(race, m, w)["median"] or 22.0)


def test_actual_plan_reproduces_itself():
    sim = _sim()
    res = simulate(sim, 1, 5, actual_plan(sim, 1, 5))
    assert res["delta"] == 0 and res["position_estimated"] == res["position_actual"]


def test_running_degrading_softs_too_long_costs_time():
    sim = _sim()  # softs lose 0.08 s/lap, hards 0.03 s/lap; the real stop is on lap 15
    assert simulate(sim, 1, 1, [{"lap": 32, "compound": "HARD"}])["delta"] > 0


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_javascript_matches_python(tmp_path):
    sim = _sim()
    cases = [{"driver": d, "from": f, "plan": p} for d in (1, 2, 3) for f in (1, 8, 20) for p in PLANS]
    expected = [simulate(sim, c["driver"], c["from"], c["plan"]) for c in cases]
    (tmp_path / "in.json").write_text(json.dumps({"sim": sim, "cases": cases}))
    script = f"""
      import {{ simulate }} from {json.dumps((ROOT / "site" / "whatif.mjs").as_uri())};
      import {{ readFileSync }} from "node:fs";
      const {{ sim, cases }} = JSON.parse(readFileSync({json.dumps(str(tmp_path / "in.json"))}, "utf8"));
      console.log(JSON.stringify(cases.map((c) => simulate(sim, c.driver, c.from, c.plan))));
    """
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    got = json.loads(out.stdout)
    assert len(got) == len(expected)
    for g, e in zip(got, expected, strict=True):
        assert g["position_estimated"] == e["position_estimated"]
        assert g["delta"] == pytest.approx(e["delta"], abs=1e-6)
        assert g["estimated_finish"] == pytest.approx(e["estimated_finish"], abs=1e-6)
