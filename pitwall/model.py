"""Race-pace model: driver pace, compound offset, tyre degradation and fuel/track evolution.

For every clean green-flag lap::

    lap_time = pace[driver] + offset[compound] + deg[compound] * tyre_age + fuel * lap_number + ε

* ``pace`` absorbs car + driver speed on the reference compound,
* ``deg`` is seconds lost per lap of tyre age, separately per compound,
* ``fuel`` captures everything that changes with race distance (fuel burn, track rubbering-in);
  it is estimated from the data rather than assumed.

The fit is robust (Huber loss via iteratively re-weighted least squares) because traffic, lock-ups
and yellow flags produce one-sided outliers that would otherwise inflate degradation estimates.
Uncertainty comes from a cluster bootstrap over stints: laps within a stint are not independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

COMPOUND_ORDER = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"]
MIN_COMPOUND_LAPS = 10


@dataclass
class PaceModel:
    drivers: list[int]
    compounds: list[str]
    reference: str
    pace: dict[int, float]
    offset: dict[str, float]
    deg: dict[str, float]
    fuel: float
    sigma: float
    n_laps: int
    deg_ci: dict[str, tuple[float, float]] = field(default_factory=dict)
    support: dict[str, dict[str, int]] = field(default_factory=dict)  # compound -> {"laps", "stints"}

    MIN_LAPS, MIN_STINTS = 30, 3

    def reliable(self, compound: str) -> bool:
        sup = self.support.get(compound, {})
        return sup.get("laps", 0) >= self.MIN_LAPS and sup.get("stints", 0) >= self.MIN_STINTS

    def predict(self, driver: int, compound: str, tyre_age: float, lap: float) -> float:
        return (
            self.pace[driver] + self.offset.get(compound, 0.0) + self.deg.get(compound, 0.0) * tyre_age
            + self.fuel * lap
        )

    def to_json(self) -> dict:
        return {
            "reference_compound": self.reference,
            "pace": {str(k): round(v, 3) for k, v in self.pace.items()},
            "compound_offset": {k: round(v, 3) for k, v in self.offset.items()},
            # Degradation is only published for compounds with enough laps and stints to estimate it.
            "deg_per_lap": {k: round(v, 4) for k, v in self.deg.items() if self.reliable(k)},
            "deg_ci90": {k: [round(a, 4), round(b, 4)] for k, (a, b) in self.deg_ci.items() if self.reliable(k)},
            "support": self.support,
            "fuel_per_lap": round(self.fuel, 4),
            "residual_sigma": round(self.sigma, 3),
            "n_laps": self.n_laps,
        }


def _design(rows: list[dict], drivers: list[int], compounds: list[str], reference: str, use_age: bool,
            use_fuel: bool) -> np.ndarray:
    d_idx = {d: i for i, d in enumerate(drivers)}
    others = [c for c in compounds if c != reference]
    c_idx = {c: i for i, c in enumerate(others)}
    n_cols = len(drivers) + len(others) + (len(compounds) if use_age else 0) + (1 if use_fuel else 0)
    X = np.zeros((len(rows), n_cols))
    for r_i, r in enumerate(rows):
        X[r_i, d_idx[r["driver"]]] = 1.0
        col = len(drivers)
        if r["compound"] in c_idx:
            X[r_i, col + c_idx[r["compound"]]] = 1.0
        col += len(others)
        if use_age:
            X[r_i, col + compounds.index(r["compound"])] = r["tyre_age"]
            col += len(compounds)
        if use_fuel:
            X[r_i, col] = r["lap"]
    return X


def _huber_irls(X: np.ndarray, y: np.ndarray, k: float = 1.345, iters: int = 30) -> tuple[np.ndarray, float]:
    w = np.ones(len(y))
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    scale = 1.0
    for _ in range(iters):
        r = y - X @ beta
        scale = 1.4826 * np.median(np.abs(r - np.median(r))) or 1e-6
        u = np.abs(r) / scale
        w = np.where(u <= k, 1.0, k / np.maximum(u, 1e-12))
        sw = np.sqrt(w)
        new = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)[0]
        if np.allclose(new, beta, atol=1e-6):
            beta = new
            break
        beta = new
    return beta, float(scale)


def fit(rows: list[dict], use_age: bool = True, use_fuel: bool = True, bootstrap: int = 0,
        seed: int = 0) -> PaceModel:
    # A compound seen on a handful of laps (e.g. one lap on intermediates) adds columns the data cannot
    # pin down; leave it out of the fit instead of letting it absorb noise.
    # A compound used by a single driver is confounded with that driver's pace for the same reason.
    ages: dict[str, set[int]] = {}
    users: dict[str, set[int]] = {}
    for r in rows:
        ages.setdefault(r["compound"], set()).add(r["tyre_age"])
        users.setdefault(r["compound"], set()).add(r["driver"])
    n_by = {c: sum(r["compound"] == c for r in rows) for c in ages}
    rows = [r for r in rows if n_by[r["compound"]] >= MIN_COMPOUND_LAPS and len(ages[r["compound"]]) >= 2
            and len(users[r["compound"]]) >= 2]
    if not rows:
        raise ValueError("no laps to fit")
    drivers = sorted({r["driver"] for r in rows})
    present = {r["compound"] for r in rows}
    compounds = [c for c in COMPOUND_ORDER if c in present] + sorted(present - set(COMPOUND_ORDER))
    counts = {c: sum(r["compound"] == c for r in rows) for c in compounds}
    reference = max(compounds, key=lambda c: counts[c])
    X = _design(rows, drivers, compounds, reference, use_age, use_fuel)
    y = np.array([r["time"] for r in rows])
    if np.linalg.matrix_rank(X) < X.shape[1]:
        # e.g. every car stopped on the same lap: tyre age and lap number move together, so degradation
        # and fuel effect cannot be separated. Refuse rather than return arbitrary numbers.
        raise ValueError("model not identifiable on these laps (tyre age collinear with lap number)")
    beta, sigma = _huber_irls(X, y)

    def unpack(b: np.ndarray) -> tuple[dict, dict, dict, float]:
        pace = {d: float(b[i]) for i, d in enumerate(drivers)}
        col = len(drivers)
        others = [c for c in compounds if c != reference]
        offset = {reference: 0.0} | {c: float(b[col + i]) for i, c in enumerate(others)}
        col += len(others)
        deg = {}
        if use_age:
            deg = {c: float(b[col + i]) for i, c in enumerate(compounds)}
            col += len(compounds)
        fuel = float(b[col]) if use_fuel else 0.0
        return pace, offset, deg, fuel

    pace, offset, deg, fuel = unpack(beta)
    model = PaceModel(drivers, compounds, reference, pace, offset, deg, fuel, sigma, len(rows))
    model.support = {
        c: {"laps": counts[c], "stints": len({(r["driver"], r["stint"]) for r in rows if r["compound"] == c})}
        for c in compounds
    }

    if bootstrap and use_age:
        # Stratified cluster bootstrap: resample each driver's stints from that driver's own stints,
        # so every driver stays identifiable while within-stint correlation is respected.
        rng = np.random.default_rng(seed)
        by_driver: dict[int, dict[int, list[int]]] = {}
        for i, r in enumerate(rows):
            by_driver.setdefault(r["driver"], {}).setdefault(r["stint"], []).append(i)
        samples: dict[str, list[float]] = {c: [] for c in compounds}
        for _ in range(bootstrap):
            idx = []
            for stints in by_driver.values():
                keys = list(stints)
                for p in rng.integers(0, len(keys), len(keys)):
                    idx += stints[keys[p]]
            idx = np.array(idx)
            if {rows[i]["compound"] for i in idx} != set(compounds):
                continue  # a compound vanished from the resample; its column would be unidentified
            b, _ = _huber_irls(X[idx], y[idx])
            for c, v in unpack(b)[2].items():
                samples[c].append(v)
        model.deg_ci = {c: (float(np.percentile(v, 5)), float(np.percentile(v, 95)))
                        for c, v in samples.items() if len(v) >= 20}
    return model
