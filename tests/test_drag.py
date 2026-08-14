"""马赫阻力倍增器与总阻力单元测试。"""

import math

import pytest

from lib.compute import (
    _extract_drag_components,
    _flat_wing_area,
    _get_wing_data,
    _sum_areas,
    calculate_drag,
    mach_drag_multiplier,
)
from tests.fixtures import make_flat_jet_fm, make_jet_fm, make_prop_fm


def make_polar(**overrides) -> dict:
    polar = {
        "MachFactor": 3,
        "MultMachMax1": 5.0,
        "MachCrit1": 0.85,
        "MachMax1": 1.1,
        "MultLimit1": 8.0,
        "MultLineCoeff1": -0.5,
    }
    polar.update(overrides)
    return polar


class TestMachDragMultiplier:
    def test_below_crit_is_unity(self):
        assert mach_drag_multiplier(make_polar(), 0.5) == pytest.approx(1.0)

    def test_at_mach_max_equals_mult_max(self):
        # t = (MachMax-MachCrit)/(MachMax-MachCrit) = 1 → mult = MultMachMax
        assert mach_drag_multiplier(make_polar(), 1.1) == pytest.approx(5.0, rel=1e-9)

    def test_power_law_between(self):
        # t = (0.9-0.85)/(1.1-0.85) = 0.2 → mult = 1 + 4·0.2³ = 1.032
        assert mach_drag_multiplier(make_polar(), 0.9) == pytest.approx(1.032, rel=1e-9)

    def test_above_mach_max_exponential(self):
        # 远大于 MachMax（m=20，Δ=18.9）：exp(-0.5·18.9)≈7.9e-5 → mult ≈ MultLimit
        assert mach_drag_multiplier(make_polar(), 20.0) == pytest.approx(8.0, rel=1e-4)

    def test_reduction_channel_skipped(self):
        # MultMachMax < 1 的削减通道应被跳过，不参与连乘
        polar = make_polar(MultMachMax1=0.1)
        assert mach_drag_multiplier(polar, 2.0) == pytest.approx(1.0)

    def test_positive_line_coeff_skipped(self):
        # LineCoeff > 0 的通道应被跳过（原始公式会产生负倍率）
        polar = make_polar(MultLineCoeff1=2.0)
        assert mach_drag_multiplier(polar, 2.0) == pytest.approx(1.0)


class TestSumAreas:
    def test_dict_sum(self):
        assert _sum_areas({"Left": 7.0, "Right": 6.5}) == pytest.approx(13.5)

    def test_scalar(self):
        assert _sum_areas(5.0) == pytest.approx(5.0)

    def test_none_and_list(self):
        assert _sum_areas(None) == 0.0
        assert _sum_areas([1.0, 2.0, 3.0]) == pytest.approx(6.0)


class TestCalculateDrag:
    def test_parasite_only_with_zero_mass(self):
        # 零质量 → 诱导阻力为 0，仅寄生阻力 = q·Cd·S
        fm = make_jet_fm()
        rho = 1.225
        tas = 100.0
        q = 0.5 * rho * tas * tas
        drag = calculate_drag(fm, 0.3, tas, rho, 0.0)
        # 机翼 CdMin 0.02 × 面积 40 + 机身 CdMin 0.1 × 面积 5 = 0.8 + 0.5 = 1.3 m²
        assert drag == pytest.approx(q * 1.3, rel=1e-9)

    def test_induced_drag_increases_with_mass(self):
        fm = make_jet_fm()
        rho = 1.225
        tas = 100.0
        d_light = calculate_drag(fm, 0.3, tas, rho, 1000.0)
        d_heavy = calculate_drag(fm, 0.3, tas, rho, 10000.0)
        assert d_heavy > d_light

    def test_drag_never_negative(self):
        # 高马赫下 Mach 倍增器近似可能产生负倍率，但总阻力必须 ≥ 0
        fm = make_prop_fm()
        for mach in (0.5, 1.0, 1.5, 2.0, 2.5):
            assert calculate_drag(fm, mach, 300.0, 1.225, 5000.0) >= 0.0

    def test_transonic_wall_increases_drag(self):
        fm = make_jet_fm()
        rho = 1.225
        tas = 300.0
        d_sub = calculate_drag(fm, 0.7, tas, rho, 8000.0)
        # mach=1.1 恰好是通道 MachMax → 倍增器为 MultMachMax=5.0
        d_trans = calculate_drag(fm, 1.1, tas, rho, 8000.0)
        assert d_trans > 2.0 * d_sub


class TestFlatFormatWing:
    """老 datamine 格式：机翼面积在顶层 Areas（Wing* 键），展长在 Wingspan。"""

    def test_flat_wing_area_sums_top_level(self):
        fm = make_flat_jet_fm()
        assert _flat_wing_area(fm) == pytest.approx(16.0)

    def test_extract_components_uses_flat_wing_area(self):
        # 回归：修复前 NoFlaps 无自身面积 → 机翼面积 0.0，阻力被大幅低估
        fm = make_flat_jet_fm()
        comps = _extract_drag_components(fm)
        wing_polar, wing_area = comps[0]
        assert wing_polar.get("CdMin") == pytest.approx(0.02)
        assert wing_area == pytest.approx(16.0)
        assert len(comps) == 4  # 机翼 + 机身 + 平尾 + 垂尾
        assert comps[1][1] == pytest.approx(5.0)
        assert comps[2][1] == pytest.approx(2.0)
        assert comps[3][1] == pytest.approx(2.0)

    def test_wing_data_uses_wingspan(self):
        fm = make_flat_jet_fm()
        polar, area, span = _get_wing_data(fm)
        assert polar.get("CdMin") == pytest.approx(0.02)
        assert area == pytest.approx(16.0)
        assert span == pytest.approx(10.0)

    def test_flat_parasite_drag_matches_formula(self):
        # 寄生阻力 = q·Σ(Cd·S) = q·(0.02×16 + 0.1×5 + 0.1×2 + 0.1×2) = q·1.22
        fm = make_flat_jet_fm()
        rho, tas = 1.225, 100.0
        q = 0.5 * rho * tas * tas
        drag = calculate_drag(fm, 0.3, tas, rho, 0.0)
        assert drag == pytest.approx(q * 1.22, rel=1e-9)

    def test_flat_aircraft_channels_multiply_parasite(self):
        # 顶层通道 MachCrit1=0.7/MultMachMax1=3.0/MachMax1=1.0/LineCoeff=-1.0
        fm = make_flat_jet_fm()
        aero = fm["Aerodynamics"]
        aero["MachCrit1"] = 0.7
        aero["MachMax1"] = 1.0
        aero["MultMachMax1"] = 3.0
        aero["MultLimit1"] = 1.0
        aero["MultLineCoeff1"] = -1.0
        rho, tas = 1.225, 340.0  # M1.0
        q = 0.5 * rho * tas * tas
        # M1.0 = 顶层通道 MachMax → 整机倍率 3.0；
        # 部件侧：NoFlaps 自身通道 M1.0 时 mult = 1+4·0.6³ = 1.864
        wing_mult = mach_drag_multiplier(fm["Aerodynamics"]["NoFlaps"], 1.0)
        assert wing_mult == pytest.approx(1.864, rel=1e-9)
        cd_sum = 0.02 * 16.0 * wing_mult + 0.1 * 5.0 + 0.1 * 2.0 + 0.1 * 2.0
        drag = calculate_drag(fm, 1.0, tas, rho, 0.0)
        assert drag == pytest.approx(q * cd_sum * 3.0, rel=1e-9)

    def test_flat_fixed_drag_areas_included(self):
        fm = make_flat_jet_fm()
        aero = fm["Aerodynamics"]
        aero["RadiatorCd"] = 0.1
        aero["CockpitDoorCd"] = 0.2
        aero["GearCd"] = 0.5  # 起落架不计入巡航
        rho, tas = 1.225, 100.0
        q = 0.5 * rho * tas * tas
        # M0.3 低于所有 MachCrit → 各通道倍率 1.0，总阻力 = q·(1.22+0.3)
        drag = calculate_drag(fm, 0.3, tas, rho, 0.0)
        assert drag == pytest.approx(q * (1.22 + 0.3), rel=1e-9)

    def test_new_format_ignores_flat_channels(self):
        # 新格式（WingPlane）即使顶层有通道也不应用（顶层通道不存在时兜底）
        fm = make_jet_fm()
        rho, tas = 1.225, 100.0
        q = 0.5 * rho * tas * tas
        drag = calculate_drag(fm, 1.1, tas, rho, 0.0)
        assert drag > 0.0


class TestMachChannelClamp:
    def test_negative_limit_channel_clamped_at_zero(self):
        # 硬切断通道：MultLimit=-10 → m > MachMax 时原始公式为负，应钳制为 0
        polar = {
            "MachFactor": 3,
            "MultMachMax1": 1.0, "MachCrit1": 0.95, "MachMax1": 1.2,
            "MultLimit1": -10.0, "MultLineCoeff1": -2.0,
        }
        assert mach_drag_multiplier(polar, 2.5) == pytest.approx(0.0)
        # 通道钳制为 0 后，整体阻力应为 0（不产生负阻力）
        assert mach_drag_multiplier(polar, 2.5) >= 0.0

    def test_total_multiplier_never_negative(self):
        polar = {
            "MachFactor": 3,
            "MultMachMax1": 2.0, "MachCrit1": 0.8, "MachMax1": 1.0,
            "MultLimit1": -5.0, "MultLineCoeff1": -1.0,
        }
        for mach in (0.5, 0.9, 1.0, 1.2, 2.0):
            assert mach_drag_multiplier(polar, mach) >= 0.0

    def test_rise_channel_still_peaks(self):
        # 正常波阻墙通道不受钳制影响
        polar = {
            "MachFactor": 3,
            "MultMachMax1": 2.0, "MachCrit1": 0.8, "MachMax1": 1.0,
            "MultLimit1": 1.0, "MultLineCoeff1": -1.0,
        }
        assert mach_drag_multiplier(polar, 1.0) == pytest.approx(2.0, rel=1e-9)


def test_mach_drag_multiplier_interpolates_between_channels():
    # 两个通道连乘：ch1 已过 MachMax（exp 段），ch2 在中段（幂律段）
    polar = {
        "MachFactor": 3,
        "MultMachMax1": 2.0, "MachCrit1": 0.8, "MachMax1": 1.0, "MultLimit1": 3.0, "MultLineCoeff1": -1.0,
        "MultMachMax2": 4.0, "MachCrit2": 1.0, "MachMax2": 1.2, "MultLimit2": 5.0, "MultLineCoeff2": -1.0,
    }
    # m=1.1：ch1 = 2 + 1·(1-exp(-0.1)) ≈ 2.09516；ch2 = 1 + 3·0.5³ = 1.375
    expected = 2.09516 * 1.375
    assert mach_drag_multiplier(polar, 1.1) == pytest.approx(expected, rel=1e-4)
