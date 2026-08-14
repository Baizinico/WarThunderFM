"""最优剖面与最佳爬升路线单元测试。"""

import math

import pytest

from lib.compute import (
    G,
    compute_accel_grid,
    compute_climb_route,
    compute_optimal,
)
from tests.fixtures import make_jet_fm

# 便捷构造：与 compute_accel_grid 输出字段一致的最小样本
def sample(alt, mach, accel, tas_mps=100.0):
    return {
        "altitude_m": alt,
        "mach": mach,
        "tas_mps": tas_mps,
        "thrust_mil_n": 0.0,
        "thrust_ab_n": 0.0,
        "drag_n": 0.0,
        "net_force_n": accel * 1000.0,
        "accel_mps2": accel,
    }


def make_grid(altitudes, machs):
    return {"altitudes_m": altitudes, "machs": machs}


class TestComputeOptimal:
    def test_max_speed_per_alt(self):
        grid = make_grid([0, 1000], [0.5, 1.0, 1.5])
        samples = [
            sample(0, 0.5, 1.0),
            sample(0, 1.0, 2.0),
            sample(0, 1.5, -1.0),   # 负加速度不计入
            sample(1000, 0.5, 1.0),
            sample(1000, 1.0, -1.0),
            sample(1000, 1.5, -1.0),
        ]
        optimal = compute_optimal(samples, grid)
        msp = optimal["max_speed_per_alt"]
        assert msp[0] == {"altitude_m": 0, "mach_max": 1.0, "tas_max_kmh": 360.0}
        assert msp[1] == {"altitude_m": 1000, "mach_max": 0.5, "tas_max_kmh": 360.0}

    def test_altitude_without_positive_accel(self):
        grid = make_grid([0], [0.5])
        optimal = compute_optimal([sample(0, 0.5, -2.0)], grid)
        entry = optimal["max_speed_per_alt"][0]
        assert entry["mach_max"] is None
        assert entry["tas_max_kmh"] is None

    def test_best_alt_per_mach(self):
        grid = make_grid([0, 1000, 2000], [0.5])
        samples = [
            sample(0, 0.5, 1.0),
            sample(1000, 0.5, 3.0),
            sample(2000, 0.5, -1.0),
        ]
        optimal = compute_optimal(samples, grid)
        assert optimal["best_alt_per_mach"] == [
            {"mach": 0.5, "best_alt_m": 1000, "accel_mps2": 3.0}
        ]

    def test_mach_without_positive_accel_skipped(self):
        grid = make_grid([0], [0.5, 1.0])
        samples = [
            sample(0, 0.5, 1.0),
            sample(0, 1.0, -1.0),
        ]
        optimal = compute_optimal(samples, grid)
        machs = [e["mach"] for e in optimal["best_alt_per_mach"]]
        assert machs == [0.5]


class TestComputeClimbRoute:
    def test_sep_maximization(self):
        # SEP = tas·accel/g：快而缓 vs 慢而急 → 选 SEP 大者
        grid = make_grid([0], [0.5, 1.0])
        samples = [
            sample(0, 0.5, 1.0, tas_mps=100.0),   # SEP ≈ 10.2
            sample(0, 1.0, 1.5, tas_mps=200.0),   # SEP ≈ 30.6 → 胜出
            sample(0, 1.5, -1.0, tas_mps=300.0),
        ]
        route = compute_climb_route(samples, grid)
        assert len(route) == 1
        assert route[0]["mach"] == 1.0
        assert route[0]["sep_mps"] == pytest.approx(200.0 * 1.5 / G, rel=1e-9)

    def test_climb_angle_deg_formula(self):
        # θ = arcsin(a/g)，单位 °
        grid = make_grid([0], [0.5])
        samples = [sample(0, 0.5, 5.0, tas_mps=100.0)]
        route = compute_climb_route(samples, grid)
        expected = math.degrees(math.asin(5.0 / G))
        assert route[0]["climb_angle_deg"] == pytest.approx(expected, rel=1e-9)

    def test_altitude_without_positive_accel_skipped(self):
        grid = make_grid([0, 1000], [0.5])
        samples = [
            sample(0, 0.5, 1.0),
            sample(1000, 0.5, -1.0),
        ]
        route = compute_climb_route(samples, grid)
        assert [r["altitude_m"] for r in route] == [0]


class TestFullPipeline:
    def test_end_to_end_on_jet(self):
        fm = make_jet_fm()
        mass_kg = 10000.0 + 0.5 * 3000.0
        samples, grid = compute_accel_grid(fm, mass_kg, afterburner=True)
        optimal = compute_optimal(samples, grid)
        route = compute_climb_route(samples, grid)

        assert len(grid["altitudes_m"]) == 16
        assert len(grid["machs"]) == 49
        assert len(samples) == 16 * 49
        # 高速区推力应高于低速区（加力开启）
        assert all(s["thrust_ab_n"] >= s["thrust_mil_n"] for s in samples)
        # 海平面应能加速（TWR 充足）
        assert optimal["max_speed_per_alt"][0]["mach_max"] is not None
        assert route[0]["mach"] > 0.5
        # 爬升路线高度单调
        alts = [r["altitude_m"] for r in route]
        assert alts == sorted(alts)
