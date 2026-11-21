"""`lib/fmdata.py` 引擎布局/质量解析单元测试（FIX_SPEC §8.2）。

覆盖：质量回退、老格式引擎、Type 类型判定、按类型计数、
垂直升力排除、多 Jet 类型逐实例求和、孤儿类型、thrust_summary。
"""

from __future__ import annotations

import pytest

from lib.fmdata import (
    count_engines,
    engine_instances,
    engine_type_entries,
    find_engine_dict,
    find_thrust_data,
    has_propeller,
    is_prop_aircraft,
    jet_instances,
    main_type,
    mass_info,
    prop_instances,
    thrust_data_of,
    thrust_summary,
    total_thrust0_kgf,
)
from tests.fixtures import (
    make_jet_fm,
    make_multi_jet_type_fm,
    make_multi_type_jet_fm,
    make_old_format_jet_fm,
    make_old_format_prop_fm,
    make_orphan_type_jet_fm,
    make_prop_fm,
    make_typed_prop_fm,
    make_vertical_lift_fm,
)


class TestMassInfo:
    def test_reads_max_fuel_mass0(self):
        fm = {"Mass": {"EmptyMass": 10000.0, "MaxFuelMass0": 3000.0}}
        assert mass_info(fm) == pytest.approx((10000.0, 3000.0))

    def test_falls_back_to_max_fuel_mass_when_mass0_zero(self):
        fm = {"Mass": {"EmptyMass": 7000.0, "MaxFuelMass0": 0.0, "MaxFuelMass": 2500.0}}
        assert mass_info(fm) == pytest.approx((7000.0, 2500.0))

    def test_missing_fuel_fields_returns_zero(self):
        fm = {"Mass": {"EmptyMass": 5000.0}}
        assert mass_info(fm) == pytest.approx((5000.0, 0.0))

    def test_missing_mass_node_returns_zeros(self):
        assert mass_info({}) == pytest.approx((0.0, 0.0))


class TestPropellerDetection:
    def test_propeller_type0(self):
        assert has_propeller(make_prop_fm()) is True

    def test_engine_propellor(self):
        fm = {"Engine0": {"Propellor": {"Diameter": 3.0}}}
        assert has_propeller(fm) is True

    def test_jet_with_placeholder_propellor_is_not_prop(self):
        # 老格式喷气常带占位 Propellor，但 Main.Type="Jet" 必须判为喷气
        fm = make_old_format_jet_fm()
        assert has_propeller(fm) is True
        assert is_prop_aircraft(fm) is False

    def test_typed_radial_is_prop(self):
        assert is_prop_aircraft(make_typed_prop_fm()) is True

    def test_typed_turboprop_is_prop(self):
        assert is_prop_aircraft(make_old_format_prop_fm()) is True

    def test_no_type_heuristic_jet_and_prop(self):
        assert is_prop_aircraft(make_jet_fm()) is False
        assert is_prop_aircraft(make_prop_fm()) is True


class TestThrustDataOf:
    def test_prefers_main_thrustmax(self):
        td = {"ThrustMax0": 1.0}
        type_dict = {"Main": {"ThrustMax": td}, "ThrustMax": {"ThrustMax0": 2.0}}
        assert thrust_data_of(type_dict) == td

    def test_falls_back_to_top_level_thrustmax(self):
        td = {"ThrustMax0": 3.0}
        assert thrust_data_of({"ThrustMax": td}) == td

    def test_returns_empty_dict_when_absent(self):
        assert thrust_data_of({"Main": {"Power": 100.0}}) == {}


class TestOldFormatJet:
    def test_type_and_count_and_total_thrust(self):
        fm = make_old_format_jet_fm()
        assert is_prop_aircraft(fm) is False
        assert main_type(fm) == "Jet"
        assert count_engines(fm) == 2
        assert total_thrust0_kgf(fm) == pytest.approx(1820.0)

    def test_find_thrust_data_non_empty(self):
        td = find_thrust_data(make_old_format_jet_fm())
        assert td
        assert td.get("ThrustMax0") == pytest.approx(910.0)

    def test_find_engine_dict_returns_engine_instance(self):
        engine = find_engine_dict(make_old_format_jet_fm())
        assert engine["Main"]["Type"] == "Jet"


class TestOldFormatProp:
    def test_prop_and_count(self):
        fm = make_old_format_prop_fm()
        assert is_prop_aircraft(fm) is True
        assert main_type(fm) == "TurboProp"
        assert count_engines(fm) == 2

    def test_prop_instances_names(self):
        names = [e["name"] for e in prop_instances(make_old_format_prop_fm())]
        assert names == ["Engine0", "Engine1"]


class TestTypedProp:
    def test_prop_and_count(self):
        fm = make_typed_prop_fm()
        assert is_prop_aircraft(fm) is True
        assert main_type(fm) == "Radial"
        assert count_engines(fm) == 1

    def test_placeholder_thrust_does_not_make_jet(self):
        # 占位的 ThrustMax0=2700 + 系数网格不能把 Radial 判成喷气
        fm = make_typed_prop_fm()
        assert is_prop_aircraft(fm) is True
        assert jet_instances(fm) == []


class TestMultiTypeJet:
    def test_count_and_total_thrust_9180(self):
        fm = make_multi_type_jet_fm()
        assert main_type(fm) == "Jet"
        assert count_engines(fm) == 2
        # 只计 Type=Jet 的 2×4590；Rocket(T0=453) ×12 应被排除
        assert total_thrust0_kgf(fm) == pytest.approx(9180.0)

    def test_engine_type_entries(self):
        entries = engine_type_entries(make_multi_type_jet_fm())
        assert [key for key, _ in entries] == ["EngineType0", "EngineType1"]
        assert all(isinstance(d, dict) for _, d in entries)


class TestVerticalLift:
    def test_count_and_thrust(self):
        fm = make_vertical_lift_fm()
        assert count_engines(fm) == 1
        assert total_thrust0_kgf(fm) == pytest.approx(10960.0)

    def test_vertical_engines_excluded_by_pitch(self):
        fm = make_vertical_lift_fm()
        names = [e["name"] for e in jet_instances(fm)]
        assert names == ["Engine0"]

    def test_engine_instances_pitch_parsing(self):
        fm = make_vertical_lift_fm()
        instances = {e["name"]: e for e in engine_instances(fm)}
        assert instances["Engine0"]["pitch"] == pytest.approx(0.0)
        assert instances["Engine1"]["pitch"] == pytest.approx(76.0)
        assert instances["Engine2"]["pitch"] == pytest.approx(76.0)


class TestMultiJetType:
    def test_total_thrust_sums_each_type(self):
        fm = make_multi_jet_type_fm()
        assert count_engines(fm) == 2
        # 逐实例取各自类型 T0：1652 + 821 = 2473（不能主类型 1652 × 2）
        assert total_thrust0_kgf(fm) == pytest.approx(2473.0)


class TestOrphanType:
    def test_unreferenced_type_not_counted(self):
        fm = make_orphan_type_jet_fm()
        assert count_engines(fm) == 1
        assert total_thrust0_kgf(fm) == pytest.approx(1200.0)

    def test_orphan_type_still_listed_as_entry(self):
        assert len(engine_type_entries(make_orphan_type_jet_fm())) == 2


class TestEmptyModel:
    def test_count_engines_at_least_one(self):
        assert count_engines({}) == 1


class TestThrustSummary:
    def test_old_format_jet_summary(self):
        summary = thrust_summary(make_old_format_jet_fm())
        assert summary["kind"] == "jet"
        assert summary["n_engines"] == 2
        assert summary["thrust_max0_kgf"] == pytest.approx(1820.0)
        assert summary["main_type"] == "Jet"

    def test_typed_prop_summary_zero_thrust(self):
        summary = thrust_summary(make_typed_prop_fm())
        assert summary["kind"] == "prop"
        assert summary["n_engines"] == 1
        assert summary["thrust_max0_kgf"] == pytest.approx(0.0)
        assert summary["main_type"] == "Radial"

    def test_multi_type_jet_summary(self):
        summary = thrust_summary(make_multi_type_jet_fm())
        assert summary["kind"] == "jet"
        assert summary["n_engines"] == 2
        assert summary["thrust_max0_kgf"] == pytest.approx(9180.0)

    def test_no_type_jet_summary(self):
        summary = thrust_summary(make_jet_fm())
        assert summary["kind"] == "jet"
        assert summary["n_engines"] == 1
        assert summary["thrust_max0_kgf"] == pytest.approx(5000.0)
        assert summary["main_type"] is None
