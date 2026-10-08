"""JSON Schema 校验、record 构建与读写单元测试。"""

import math

import pytest

from lib.schema import (
    ACCEL_RANGE,
    build_record,
    load_json,
    save_json,
    validate,
)

# 小于 ACCEL_RANGE 下限的值（随常量变化自动跟随，避免阈值调整后用例失效）
ACCEL_BELOW_RANGE = ACCEL_RANGE[0] - 1.0
from tests.fixtures import make_jet_fm


def make_record(tmp_path=None, **kwargs):
    """构建一份通过校验的完整 record（可覆盖字段以构造失败用例）。"""
    fm = make_jet_fm()
    record = build_record(
        "test_jet",
        fm,
        samples=[make_sample()],
        grid={"altitudes_m": [0], "machs": [0.5]},
        optimal={
            "max_speed_per_alt": [{"altitude_m": 0, "mach_max": 1.0, "tas_max_kmh": 1224.0}],
            "best_alt_per_mach": [{"mach": 0.5, "best_alt_m": 0, "accel_mps2": 1.0}],
        },
        params={"afterburner": True, "fuel_pct": 0.5, "wt_fm_version": "test"},
        climb_route=[],
    )
    if kwargs:
        raise ValueError(f"不支持的覆盖字段: {sorted(kwargs)}")
    return record


def make_sample(alt=0, mach=0.5, accel=1.0):
    return {
        "altitude_m": alt,
        "mach": mach,
        "tas_mps": 170.0,
        "thrust_mil_n": 49000.0,
        "thrust_ab_n": 73500.0,
        "drag_n": 10000.0,
        "net_force_n": 20000.0,
        "accel_mps2": accel,
    }


class TestValidate:
    def test_empty_record_invalid(self):
        ok, errors = validate({})
        assert not ok
        assert any("顶层缺少必填字段" in e for e in errors)

    def test_build_record_is_valid(self):
        record = make_record()
        ok, errors = validate(record)
        assert ok, errors

    def test_metadata_mass_negative_invalid(self):
        record = make_record()
        record["metadata"]["empty_mass_kg"] = -1.0
        ok, errors = validate(record)
        assert not ok
        assert any("empty_mass_kg" in e for e in errors)

    def test_afterburner_type_invalid(self):
        record = make_record()
        record["metadata"]["afterburner"] = "yes"
        ok, errors = validate(record)
        assert not ok
        assert any("afterburner" in e for e in errors)

    def test_accel_out_of_range_invalid(self):
        record = make_record()
        record["samples"] = [make_sample(accel=ACCEL_BELOW_RANGE)]
        ok, errors = validate(record)
        assert not ok
        assert any("accel_mps2" in e for e in errors)

    def test_nan_rejected(self):
        record = make_record()
        record["samples"] = [make_sample()]
        record["samples"][0]["accel_mps2"] = math.nan
        ok, errors = validate(record)
        assert not ok

    def test_bool_not_a_number(self):
        record = make_record()
        record["samples"] = [make_sample()]
        record["samples"][0]["accel_mps2"] = True
        ok, errors = validate(record)
        assert not ok

    def test_mach_max_none_allowed(self):
        record = make_record()
        record["optimal"]["max_speed_per_alt"] = [
            {"altitude_m": 0, "mach_max": None, "tas_max_kmh": None}
        ]
        ok, errors = validate(record)
        assert ok, errors

    def test_climb_angle_deg_accepted(self):
        record = make_record()
        record["climb_route"] = [
            {
                "altitude_m": 0,
                "mach": 0.5,
                "tas_kmh": 600.0,
                "sep_mps": 50.0,
                "climb_angle_deg": 20.0,
                "accel_mps2": 2.0,
            }
        ]
        ok, errors = validate(record)
        assert ok, errors

    def test_climb_angle_deg_out_of_range(self):
        record = make_record()
        record["climb_route"] = [
            {
                "altitude_m": 0,
                "mach": 0.5,
                "tas_kmh": 600.0,
                "sep_mps": 50.0,
                "climb_angle_deg": 120.0,
                "accel_mps2": 2.0,
            }
        ]
        ok, errors = validate(record)
        assert not ok


class TestBuildRecord:
    def test_mass_computation(self):
        record = make_record()
        meta = record["metadata"]
        assert meta["empty_mass_kg"] == pytest.approx(10000.0)
        assert meta["fuel_mass_kg"] == pytest.approx(1500.0)  # 0.5 × 3000
        assert meta["flight_mass_kg"] == pytest.approx(11500.0)

    def test_thrust_max0_with_engine_count(self):
        fm = make_jet_fm()
        fm["Engine1"] = {}  # 双发
        record = build_record(
            "test_jet", fm, [], {"altitudes_m": [], "machs": []},
            {"max_speed_per_alt": [], "best_alt_per_mach": []},
            {"afterburner": True, "fuel_pct": 0.5, "wt_fm_version": "test"},
        )
        # 5000 kgf × 2 发
        assert record["metadata"]["thrust_max0_kgf"] == pytest.approx(10000.0)

    def test_computed_at_is_beijing_time(self):
        record = make_record()
        assert record["metadata"]["computed_at"].endswith("+08:00")


class TestRoundTrip:
    def test_save_and_load(self, tmp_path):
        record = make_record()
        record["samples"] = [make_sample(), make_sample(alt=1000, mach=1.0, accel=2.0)]
        out = tmp_path / "record.json"
        save_json(record, out)
        loaded = load_json(out)
        assert loaded == record

    def test_save_rejects_invalid(self, tmp_path):
        record = make_record()
        record["samples"] = [make_sample(accel=ACCEL_BELOW_RANGE)]
        out = tmp_path / "bad.json"
        with pytest.raises(ValueError):
            save_json(record, out)
        assert not out.exists()

    def test_load_rejects_invalid_json(self, tmp_path):
        out = tmp_path / "bad.json"
        out.write_text("{not json", encoding="utf-8")
        with pytest.raises(Exception):
            load_json(out)
