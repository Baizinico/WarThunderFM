"""多机对比模块（lib/compare.py）与 compare 子命令的单元测试。

覆盖：
  - 指标提取（推重比 / 峰值加速度 / SEP 爬升率 / 升限 / 极速）与缺失数据处理
  - 剖面高度层选取（优先层 + 均匀取样回退）
  - 雷达归一化（越大越好 / 越小越好 / 全等 / 全空）
  - build_comparison 结构、最优值方向与并列、剖面与爬升路线对齐
  - validate_comparison 负例、save/load 往返
  - analyze.py compare 子命令端到端（临时目录 + 合成 .blkx）
"""

from __future__ import annotations

import json

import pytest

import analyze
from lib.compare import (
    COMPARE_METRICS,
    RADAR_METRIC_KEYS,
    build_comparison,
    compute_compare_metrics,
    format_comparison_table,
    load_comparison,
    normalize_metric,
    pick_profile_altitudes,
    save_comparison,
    validate_comparison,
)
from lib.compute import compute_climb_route, compute_optimal
from tests.fixtures import make_jet_fm, make_prop_fm


# ============================================================
# 合成记录（避免每次都跑完整网格，同时覆盖最优/爬升推导链路）
# ============================================================
def make_synthetic_record(name: str, *, mass: float = 10000.0,
                          thrust_kgf: float = 6000.0,
                          accel_scale: float = 1.0,
                          zero_above: float | None = None,
                          altitudes=(0.0, 5000.0, 10000.0, 15000.0),
                          machs=(0.5, 1.0, 1.5),
                          nation: str = "other",
                          fuel_pct: float = 0.5,
                          payload_kg: float = 0.0) -> dict:
    """构造一条结构完整的合成记录（accel 随马赫与高度单调下降，便于断言）。"""
    samples = []
    for alt in altitudes:
        for mach in machs:
            accel = accel_scale * (2.0 - mach) * (1.0 - alt / 20000.0)
            if zero_above is not None and alt >= zero_above:
                accel = -1.0
            tas_mps = mach * 300.0
            thrust_n = thrust_kgf * 9.80665
            drag_n = thrust_n - accel * mass
            samples.append({
                "altitude_m": alt,
                "mach": mach,
                "tas_mps": tas_mps,
                "thrust_mil_n": thrust_n,
                "thrust_ab_n": thrust_n,
                "drag_n": max(0.0, drag_n),
                "net_force_n": accel * mass,
                "accel_mps2": accel,
            })
    grid = {"altitudes_m": list(altitudes), "machs": list(machs)}
    return {
        "aircraft": name,
        "metadata": {
            "empty_mass_kg": mass,
            "fuel_mass_kg": 0.0,
            "flight_mass_kg": mass,
            "afterburner": True,
            "thrust_max0_kgf": thrust_kgf,
            "computed_at": "2026-01-01T00:00:00+08:00",
            "wt_fm_version": "test",
        },
        "grid": grid,
        "samples": samples,
        "optimal": compute_optimal(samples, grid),
        "climb_route": compute_climb_route(samples, grid),
        "nation": nation,
        "fuel_pct": fuel_pct,
        "payload_kg": payload_kg,
    }


# ============================================================
# compute_compare_metrics
# ============================================================
def test_metrics_basic_values():
    record = make_synthetic_record("alpha", mass=10000.0, thrust_kgf=5000.0)
    metrics = compute_compare_metrics(record)

    assert metrics["flight_mass_kg"] == pytest.approx(10000.0)
    assert metrics["thrust_max0_kgf"] == pytest.approx(5000.0)
    assert metrics["twr"] == pytest.approx(0.5)
    # 峰值加速度出现在最低高度、最低马赫：(2-0.5)*(1-0) = 1.5
    assert metrics["max_accel_mps2"] == pytest.approx(1.5)
    # 最高可用高度层为 15000 m（该层仍有正加速度）
    assert metrics["ceiling_m"] == pytest.approx(15000.0)
    assert metrics["max_climb_mps"] is not None and metrics["max_climb_mps"] > 0
    assert metrics["top_mach"] == pytest.approx(1.5)
    assert metrics["top_tas_kmh"] == pytest.approx(1.5 * 300.0 * 3.6)


def test_metrics_ceiling_follows_positive_accel_layers():
    record = make_synthetic_record("beta", zero_above=10000.0)
    metrics = compute_compare_metrics(record)
    # 10000 m 及以上被置为负加速度，升限应退到 5000 m
    assert metrics["ceiling_m"] == pytest.approx(5000.0)


def test_metrics_missing_data_returns_none():
    empty = {
        "aircraft": "gamma",
        "metadata": {"flight_mass_kg": 0.0, "thrust_max0_kgf": 4000.0},
        "samples": [],
        "optimal": {},
        "climb_route": [],
    }
    metrics = compute_compare_metrics(empty)
    assert metrics["flight_mass_kg"] == pytest.approx(0.0)
    assert metrics["twr"] is None          # 质量非正 → 推重比不可用
    assert metrics["max_accel_mps2"] is None
    assert metrics["max_climb_mps"] is None
    assert metrics["ceiling_m"] is None
    assert metrics["top_mach"] is None
    assert metrics["top_tas_kmh"] is None


def test_metrics_match_real_compute_pipeline():
    """用合成 FM 走完整计算链路，确认指标来自真实数据而非空壳。"""
    fm = make_jet_fm()
    mass = fm["Mass"]["EmptyMass"] + 0.5 * fm["Mass"]["MaxFuelMass0"]
    record = analyze._build_record_for_fm("jet", fm, mass, True, 0.5)
    metrics = compute_compare_metrics(record)
    assert metrics["flight_mass_kg"] == pytest.approx(mass)
    assert metrics["twr"] == pytest.approx(metrics["thrust_max0_kgf"] / mass)
    assert metrics["max_accel_mps2"] > 0
    assert metrics["max_climb_mps"] > 0
    assert 0.0 < metrics["top_mach"] <= 2.5


def test_build_record_overrides_flight_mass_for_payload():
    """挂载质量的记录必须用实际计算质量覆盖 metadata，推重比才可信。"""
    fm = make_jet_fm()
    base = fm["Mass"]["EmptyMass"] + 0.5 * fm["Mass"]["MaxFuelMass0"]
    record = analyze._build_record_for_fm("jet", fm, base + 2000.0, True, 0.5)
    assert record["metadata"]["flight_mass_kg"] == pytest.approx(base + 2000.0)


# ============================================================
# pick_profile_altitudes
# ============================================================
def test_pick_profile_altitudes_prefers_standard_layers():
    alts = [float(a) for a in range(0, 16000, 1000)]
    assert pick_profile_altitudes(alts) == [0.0, 5000.0, 10000.0, 15000.0]


def test_pick_profile_altitudes_uniform_fallback():
    alts = [float(a) for a in range(1000, 10000, 1000)]  # 无 0 / 5000 层
    picked = pick_profile_altitudes(alts)
    # floor(i*(n-1)/3+0.5)，n=9 → 下标 0,3,5,8
    assert picked == [1000.0, 4000.0, 6000.0, 9000.0]


def test_pick_profile_altitudes_short_and_empty():
    assert pick_profile_altitudes([100.0, 200.0]) == [100.0, 200.0]
    assert pick_profile_altitudes([]) == []
    assert pick_profile_altitudes([None, "x"]) == []


# ============================================================
# normalize_metric
# ============================================================
def test_normalize_metric_directions():
    assert normalize_metric([1.0, 2.0, 3.0], True) == pytest.approx([0.0, 50.0, 100.0])
    assert normalize_metric([1.0, 2.0, 3.0], False) == pytest.approx([100.0, 50.0, 0.0])


def test_normalize_metric_edge_cases():
    assert normalize_metric([5.0, 5.0], True) == pytest.approx([100.0, 100.0])
    assert normalize_metric([None, None], True) == [None, None]
    assert normalize_metric([None, 7.0], True) == [None, 100.0]


# ============================================================
# build_comparison
# ============================================================
def test_build_comparison_structure_and_best():
    light = make_synthetic_record("light", mass=8000.0, thrust_kgf=6000.0)
    heavy = make_synthetic_record("heavy", mass=16000.0, thrust_kgf=9000.0)
    data = build_comparison([light, heavy])

    ok, errors = validate_comparison(data)
    assert ok, errors
    assert data["aircraft"] == ["light", "heavy"]
    assert data["generated_at"].endswith("+08:00")

    # 飞行质量越小越好 → light；静推力越大越好 → heavy
    assert data["best"]["flight_mass_kg"] == ["light"]
    assert data["best"]["thrust_max0_kgf"] == ["heavy"]

    by_name = {e["name"]: e for e in data["entries"]}
    assert by_name["light"]["metrics"]["twr"] == pytest.approx(6000.0 / 8000.0)
    assert by_name["heavy"]["metrics"]["twr"] == pytest.approx(9000.0 / 16000.0)
    # 推重比：light 0.75 > heavy 0.5625 → light 最优
    assert data["best"]["twr"] == ["light"]

    for e in data["entries"]:
        assert len(e["radar"]) == len(RADAR_METRIC_KEYS)
        for v in e["radar"]:
            assert v is None or 0.0 <= v <= 100.0
    assert [i["key"] for i in data["radar_indicators"]] == RADAR_METRIC_KEYS

    # 剖面：每个高度层包含全部机型，马赫/加速度等长
    assert len(data["profiles"]) >= 2
    for profile in data["profiles"]:
        assert [s["name"] for s in profile["series"]] == ["light", "heavy"]
        for s in profile["series"]:
            assert len(s["mach"]) == len(s["accel_mps2"])
    # 爬升路线：三条序列等长
    for route in data["climb_routes"]:
        assert len(route["altitude_m"]) == len(route["mach"]) == len(route["sep_mps"])


def test_build_comparison_lower_is_better_and_ties():
    a = make_synthetic_record("a", mass=9000.0, thrust_kgf=5000.0)
    b = make_synthetic_record("b", mass=9000.0, thrust_kgf=5000.0)
    data = build_comparison([a, b])
    # 指标全等 → 并列最优，且雷达分数都是 100
    assert sorted(data["best"]["twr"]) == ["a", "b"]
    assert data["entries"][0]["radar"] == pytest.approx([100.0] * len(RADAR_METRIC_KEYS))


def test_build_comparison_skips_missing_metrics():
    good = make_synthetic_record("good", mass=9000.0, thrust_kgf=5000.0)
    broken = {
        "aircraft": "broken",
        "metadata": {"flight_mass_kg": 0.0, "thrust_max0_kgf": 0.0},
        "samples": [],
        "grid": {"altitudes_m": [], "machs": []},
        "optimal": {},
        "climb_route": [],
    }
    data = build_comparison([good, broken])
    ok, errors = validate_comparison(data)
    assert ok, errors
    # 缺失指标不参与最优值判定，也不进入 best 列表
    assert "broken" not in data["best"]["max_climb_mps"]
    assert data["entries"][1]["metrics"]["max_climb_mps"] is None
    assert data["entries"][1]["radar"] == [None] * len(RADAR_METRIC_KEYS)


def test_format_comparison_table_marks_best():
    a = make_synthetic_record("alpha", mass=8000.0, thrust_kgf=6000.0)
    b = make_synthetic_record("bravo", mass=16000.0, thrust_kgf=9000.0)
    table = format_comparison_table(build_comparison([a, b]))
    assert "alpha" in table and "bravo" in table
    assert "飞行质量" in table
    assert "*" in table
    assert "8,000" in table  # 千位分隔符


# ============================================================
# validate_comparison / save / load
# ============================================================
def test_validate_comparison_rejects_bad_payloads():
    data = build_comparison([
        make_synthetic_record("a"), make_synthetic_record("b"),
    ])

    broken = json.loads(json.dumps(data))
    broken["entries"][0]["radar"][0] = 150.0
    ok, errors = validate_comparison(broken)
    assert not ok and any("radar" in e for e in errors)

    broken = json.loads(json.dumps(data))
    broken["profiles"][0]["series"][0]["accel_mps2"].append(1.0)
    ok, errors = validate_comparison(broken)
    assert not ok and any("长度不一致" in e for e in errors)

    broken = json.loads(json.dumps(data))
    del broken["climb_routes"]
    ok, errors = validate_comparison(broken)
    assert not ok and any("climb_routes" in e for e in errors)

    too_few = json.loads(json.dumps(data))
    too_few["aircraft"] = ["a"]
    too_few["entries"] = too_few["entries"][:1]
    ok, errors = validate_comparison(too_few)
    assert not ok and any("至少需要两架" in e or ">= 2" in e for e in errors)

    assert validate_comparison("not a dict")[0] is False


def test_save_and_load_comparison_roundtrip(tmp_path):
    data = build_comparison([
        make_synthetic_record("a"), make_synthetic_record("b"),
    ])
    path = tmp_path / "compare_ab.json"
    save_comparison(data, path)
    loaded = load_comparison(path)
    assert loaded == data
    assert COMPARE_METRICS[0]["key"] in loaded["best"]


def test_save_comparison_rejects_invalid(tmp_path):
    with pytest.raises(ValueError):
        save_comparison({"aircraft": []}, tmp_path / "bad.json")


# ============================================================
# CLI 端到端
# ============================================================
@pytest.fixture()
def temp_project(tmp_path, monkeypatch):
    """把 analyze 的 raw/computed 指向临时目录（避免污染真实数据）。"""
    raw = tmp_path / "raw"
    computed = tmp_path / "computed"
    raw.mkdir()
    computed.mkdir()
    monkeypatch.setattr(analyze, "RAW_DIR", raw)
    monkeypatch.setattr(analyze, "COMPUTED_DIR", computed)
    monkeypatch.setattr(analyze, "PROJECT_ROOT", tmp_path)
    return raw, computed


def test_cli_compare_prints_table_and_saves(temp_project, capsys):
    raw, computed = temp_project
    (raw / "jet_a.blkx").write_text(json.dumps(make_jet_fm()), encoding="utf-8")
    (raw / "prop_b.blkx").write_text(json.dumps(make_prop_fm()), encoding="utf-8")

    out_path = computed / "compare_jet_a_prop_b.json"
    rc = analyze.main(["compare", "jet_a", "prop_b", "--out", str(out_path)])
    assert rc == 0

    captured = capsys.readouterr().out
    assert "jet_a" in captured and "prop_b" in captured
    assert "飞行质量" in captured

    data = load_comparison(out_path)
    assert data["aircraft"] == ["jet_a", "prop_b"]
    assert set(data["best"].keys()) == {m["key"] for m in COMPARE_METRICS}


def test_cli_compare_requires_two_aircraft(temp_project, capsys):
    raw, _ = temp_project
    (raw / "jet_a.blkx").write_text(json.dumps(make_jet_fm()), encoding="utf-8")
    rc = analyze.main(["compare", "jet_a"])
    assert rc == 1
    assert "至少需要两架" in capsys.readouterr().err


def test_cli_compare_fails_when_aircraft_missing(temp_project, capsys):
    raw, _ = temp_project
    (raw / "jet_a.blkx").write_text(json.dumps(make_jet_fm()), encoding="utf-8")
    rc = analyze.main(["compare", "jet_a", "nope", "--no-save"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "不足两架" in err or "nope" in err


def test_cli_compare_from_computed_fallback(temp_project, capsys):
    """缺少原始数据但存在预计算结果时，退回使用 data/computed。"""
    raw, computed = temp_project
    (raw / "jet_a.blkx").write_text(json.dumps(make_jet_fm()), encoding="utf-8")

    # 先算一架飞机的预计算结果（走 compute 子命令）
    assert analyze.main(["compute", "jet_a"]) == 0
    assert (computed / "jet_a.json").exists()

    rc = analyze.main(["compare", "jet_a", "jet_a", "--from-computed", "--no-save"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "使用预计算" in out
