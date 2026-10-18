"""Track geometry and position resampling for the replay."""

from __future__ import annotations

import numpy as np

from .race import Race

MISSING = -32768  # int16 sentinel: car not on track / no data


def resample_positions(race: Race, hz: float = 4.0, max_gap: float = 3.0) -> tuple[np.ndarray, float, list[int]]:
    """Resample every car onto one shared clock.

    Returns ``(grid, t_first, order)`` where ``grid`` is int16 of shape (drivers, samples, 2).
    Samples further than ``max_gap`` seconds from real data are marked MISSING so the
    viewer hides cars that have retired or lost telemetry instead of freezing them.
    """
    order = [d["driver_number"] for d in race.drivers if d["driver_number"] in race.locations]
    t_first = min(race.locations[n][0, 0] for n in order)
    t_last = max(race.locations[n][-1, 0] for n in order)
    t = np.arange(t_first, t_last, 1.0 / hz)
    grid = np.full((len(order), len(t), 2), MISSING, dtype=np.int16)
    for i, num in enumerate(order):
        arr = race.locations[num]
        ts = arr[:, 0]
        x = np.interp(t, ts, arr[:, 1])
        y = np.interp(t, ts, arr[:, 2])
        idx = np.clip(np.searchsorted(ts, t), 1, len(ts) - 1)
        near = np.minimum(np.abs(ts[idx] - t), np.abs(ts[idx - 1] - t))
        ok = (near <= max_gap) & (t >= ts[0]) & (t <= ts[-1])
        grid[i, ok, 0] = np.round(x[ok]).astype(np.int16)
        grid[i, ok, 1] = np.round(y[ok]).astype(np.int16)
    return grid, float(t_first), order


def rdp(points: np.ndarray, eps: float) -> np.ndarray:
    """Ramer–Douglas–Peucker polyline simplification (iterative, no recursion limit)."""
    keep = np.zeros(len(points), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg = points[b] - points[a]
        norm = np.hypot(*seg) or 1.0
        v = points[a + 1 : b] - points[a]
        d = np.abs(seg[0] * v[:, 1] - seg[1] * v[:, 0]) / norm
        i = int(np.argmax(d))
        if d[i] > eps:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    return points[keep]


def track_outline(race: Race, eps: float = 4.0) -> dict:
    """Outline from the fastest complete lap's position trace (OpenF1 units ≈ decimetres)."""
    candidates = sorted(
        (lap for lap in race.laps if lap.duration and not lap.pit_out and lap.lap > 1 and lap.driver in race.locations),
        key=lambda lap: lap.duration,
    )
    for lap in candidates[:300]:
        arr = race.locations[lap.driver]
        sel = arr[(arr[:, 0] >= lap.start) & (arr[:, 0] <= lap.start + lap.duration)]
        if len(sel) < 50:
            continue
        pts = sel[:, 1:]
        closure = np.hypot(*(pts[0] - pts[-1]))
        step = np.median(np.hypot(*np.diff(pts, axis=0).T))
        if closure > 25 * step:  # incomplete trace; try the next-fastest lap
            continue
        loop = np.vstack([pts, pts[:1]])
        mid = len(loop) // 2  # RDP needs distinct endpoints, so simplify a closed loop in two halves
        simple = np.vstack([rdp(loop[: mid + 1], eps), rdp(loop[mid:], eps)[1:]])
        return {
            "outline": simple.round().astype(int).tolist(),
            "start": pts[0].round().astype(int).tolist(),
            "from_lap": {"driver": lap.driver, "lap": lap.lap, "duration": lap.duration},
        }
    raise ValueError("no clean lap with a complete position trace")
