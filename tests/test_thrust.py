"""推力插值单元测试（喷气双线性插值 + 螺旋桨轴功率模型）。"""

import math

import numpy as np
import pytest

from lib.compute import (
    ETA_PROP,
    ETA_STATIC,
    G,
    HP_TO_WATT,
    _bilinear_interp,
    _count_engines,
    _get_engine_power,
    _get_prop_radius,
    _get_thrust_axes,
    _is_prop_aircraft,
    _propeller_thrust,
    interpolate_thrust,
    isa_atmosphere,
)
from tests.fixtures import make_flat_jet_fm, make_jet_fm, make_prop_fm


class TestJetThrust:
    def test_constant_grid_thrust(self):
        fm = make_jet_fm()
        mil, ab = interpolate_thrust(fm, 0.0, 0.0, afterburner=True)
        # 5000 kgf × g × 1 发 × coeff(0,0)=1.0
        assert mil == pytest.approx(5000.0 * G, rel=1e-9)
        # 加力 = 军用 × 1.5
        assert ab == pytest.approx(mil * 1.5, rel=1e-9)

    def test_multi_engine_doubles_thrust(self):
        fm = make_jet_fm(n_engines=2)
        mil2, _ = interpolate_thrust(fm, 0.0, 0.0, afterburner=True)
        fm1 = make_jet_fm(n_engines=1)
        mil1, _ = interpolate_thrust(fm1, 0.0, 0.0, afterburner=True)
        assert mil2 == pytest.approx(2.0 * mil1, rel=1e-9)
        assert _count_engines(fm) == 2

    def test_bilinear_midpoint(self):
        # 构造非恒定网格：(0,0)=0.5 (0,1)=0.7 (1,0)=0.9 (1,1)=1.3
        # 在 alt=1000 m、vel=100 km/h（两个维度的中点）应为 0.85
        grid = np.array([[0.5, 0.7], [0.9, 1.3]])
        x_nodes = [0.0, 2000.0]
        y_nodes = [0.0, 200.0]
        assert _bilinear_interp(grid, x_nodes, y_nodes, 1000.0, 100.0) == pytest.approx(0.85, rel=1e-9)

    def test_bilinear_clamps_out_of_range(self):
        grid = np.array([[0.5, 0.7], [0.9, 1.3]])
        x_nodes = [0.0, 2000.0]
        y_nodes = [0.0, 200.0]
        # x=-5000 钳制到 x_nodes[0]（fx=0），y=999 钳制到 y_nodes[-1]（fy=1）
        # → 线性插值落在 grid[0][1] = 0.7
        assert _bilinear_interp(grid, x_nodes, y_nodes, -5000.0, 999.0) == pytest.approx(0.7, rel=1e-9)

    def test_altitude_clamped_above_25km(self):
        fm = make_jet_fm()
        mil_above, _ = interpolate_thrust(fm, 40000.0, 0.0, afterburner=True)
        mil_top, _ = interpolate_thrust(fm, 25000.0, 0.0, afterburner=True)
        assert mil_above == pytest.approx(mil_top, rel=1e-9)


class TestDynamicThrustAxes:
    """datamine 新格式：ThrustMax 自带 Altitude_*/Velocity_* 轴（9×13 等）。"""

    def test_axes_parsed_and_tas_marker_skipped(self):
        alts, vels = _get_thrust_axes(make_flat_jet_fm()["EngineType0"]["Main"]["ThrustMax"])
        assert alts == pytest.approx([0.0, 4000.0, 8000.0, 12000.0, 16000.0, 20000.0,
                                      24000.0, 28000.0, 32000.0])
        assert len(vels) == 12
        assert vels[0] == pytest.approx(0.0)
        assert vels[-1] == pytest.approx(1100.0)

    def test_axes_missing_returns_none(self):
        fm = make_jet_fm()
        assert _get_thrust_axes(fm["EngineType0"]["Main"]["ThrustMax"]) is None

    def test_high_alt_high_vel_grid_reachable(self):
        # (8,12) 系数为 2.0，位于旧硬编码 7×12 网格之外；新格式必须能读到。
        # 旧实现会钳制到 (6,11)=1.0 → 返回 5000×G。
        fm = make_flat_jet_fm()
        mil, _ = interpolate_thrust(fm, 40000.0, 2000.0, afterburner=True)
        assert mil == pytest.approx(5000.0 * G * 2.0, rel=1e-9)

    def test_mid_grid_still_interpolates(self):
        fm = make_flat_jet_fm()
        mil_1, _ = interpolate_thrust(fm, 2000.0, 100.0, afterburner=True)
        mil_0, _ = interpolate_thrust(fm, 0.0, 0.0, afterburner=True)
        # 恒定 1.0 网格：任意点推力 = 5000×G
        assert mil_0 == pytest.approx(5000.0 * G, rel=1e-9)
        assert mil_1 == pytest.approx(mil_0, rel=1e-9)

    def test_afterburner_uses_dynamic_axes(self):
        fm = make_flat_jet_fm()
        _, ab = interpolate_thrust(fm, 40000.0, 2000.0, afterburner=True)
        assert ab == pytest.approx(5000.0 * G * 2.0 * 1.5, rel=1e-9)


class TestPropThrust:
    def test_is_prop_aircraft(self):
        assert _is_prop_aircraft(make_prop_fm()) is True
        assert _is_prop_aircraft(make_jet_fm()) is False

    def test_prop_radius_from_propeller_type0(self):
        assert _get_prop_radius(make_prop_fm()) == pytest.approx(1.5)

    def test_static_thrust_formula(self):
        # T = (2·ρ·A·P²)^(1/3) × η_static，A = π·1.5²，P = 1000 HP
        fm = make_prop_fm()
        rho = isa_atmosphere(0.0)[2]
        p_watts = 1000.0 * HP_TO_WATT
        area = math.pi * 1.5 * 1.5
        expected = (2.0 * rho * area * p_watts * p_watts) ** (1.0 / 3.0) * ETA_STATIC
        thrust = _propeller_thrust(fm, 0.0, 0.0, rho, 1000.0)
        assert thrust == pytest.approx(expected, rel=1e-9)

    def test_dynamic_thrust_formula(self):
        # 飞行推力 = P·η/V，被静推力钳制
        fm = make_prop_fm()
        rho = isa_atmosphere(0.0)[2]
        static = _propeller_thrust(fm, 0.0, 0.0, rho, 1000.0)
        dynamic = _propeller_thrust(fm, 0.0, 100.0, rho, 1000.0)
        expected = 1000.0 * HP_TO_WATT * ETA_PROP / 100.0
        assert dynamic == pytest.approx(expected, rel=1e-9)
        assert dynamic < static

    def test_zero_power_returns_zero(self):
        fm = make_prop_fm()
        rho = isa_atmosphere(0.0)[2]
        assert _propeller_thrust(fm, 0.0, 50.0, rho, 0.0) == 0.0

    def test_interpolate_thrust_prop_no_afterburner(self):
        fm = make_prop_fm()
        mil, ab = interpolate_thrust(fm, 0.0, 200.0, afterburner=True)
        # 螺旋桨无加力：军用 = 加力
        assert mil == ab
        assert mil > 0.0


class TestEnginePower:
    def test_compressor_stage_interpolation(self):
        fm = make_prop_fm()
        # 临界高度 3000 m 以下：满功率 1000 HP
        assert _get_engine_power(fm, 0.0) == pytest.approx(1000.0)
        # 临界高度 3000 m：满功率
        assert _get_engine_power(fm, 3000.0) == pytest.approx(1000.0)
        # 天花板 6000 m：700 HP
        assert _get_engine_power(fm, 6000.0) == pytest.approx(700.0)
        # 半程 4500 m：线性插值 = 850 HP
        assert _get_engine_power(fm, 4500.0) == pytest.approx(850.0, rel=1e-9)
        # 天花板以上继续衰减
        assert _get_engine_power(fm, 9000.0) < 700.0
