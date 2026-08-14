"""Python 与浏览器端 (web/compute.js) 计算引擎交叉验证。

确保两端物理公式与输出字段保持一致，防止手工移植后失同步。
依赖 Node.js（缺失时自动跳过）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from lib.compute import compute_accel_grid, compute_climb_route, compute_optimal
from lib.schema import build_record
from tests.fixtures import make_flat_jet_fm, make_jet_fm, make_prop_fm

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "tests" / "js_runner.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="未找到 Node.js")

# 数值比较公差：两端算法一致，仅存在浮点舍入差异
RTOL = 1e-9
ATOL = 1e-6


def py_analyze(fm: dict, fuel_pct: float, afterburner: bool = True) -> dict:
    """复现 analyzeAircraft 的 Python 等价计算（仅保留可对比字段）。"""
    mass = fm.get("Mass", {}) or {}
    empty = float(mass.get("EmptyMass", 0.0))
    max_fuel = float(mass.get("MaxFuelMass0", 0.0))
    mass_kg = empty + fuel_pct * max_fuel
    samples, grid = compute_accel_grid(fm, mass_kg, afterburner=afterburner)
    optimal = compute_optimal(samples, grid)
    climb_route = compute_climb_route(samples, grid)
    record = build_record(
        "test", fm, samples, grid, optimal,
        {"afterburner": afterburner, "fuel_pct": fuel_pct, "wt_fm_version": ""},
        climb_route,
    )
    record["metadata"]["computed_at"] = ""  # 与 js_runner 一致，不比较时间戳
    return {
        "metadata": record["metadata"],
        "grid": grid,
        "samples": samples,
        "optimal": optimal,
        "climb_route": climb_route,
    }


def js_analyze(fm: dict, fuel_pct: float, afterburner: bool = True) -> dict:
    fm_path = ROOT / "data" / "_js_fixture_tmp.json"
    fm_path.write_text(json.dumps(fm), encoding="utf-8")
    try:
        proc = subprocess.run(
            [NODE, str(RUNNER), str(fm_path), str(fuel_pct), str(afterburner)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=120,
        )
    finally:
        fm_path.unlink(missing_ok=True)
    assert proc.returncode == 0, f"js_runner 失败:\n{proc.stderr}"
    result = json.loads(proc.stdout)
    result.pop("aircraft", None)  # 两端均可空，不参与比较
    return result


def _compare_dict(py_val, js_val, path: str):
    """递归比较两端的嵌套结构（dict/list/数值）。"""
    if isinstance(py_val, dict) and isinstance(js_val, dict):
        assert set(py_val.keys()) == set(js_val.keys()), (
            f"{path}: 字段不一致 py={sorted(py_val)} js={sorted(js_val)}")
        for k in py_val:
            _compare_dict(py_val[k], js_val[k], f"{path}.{k}")
    elif isinstance(py_val, list) and isinstance(js_val, list):
        assert len(py_val) == len(js_val), (
            f"{path}: 长度不一致 py={len(py_val)} js={len(js_val)}")
        for i, (a, b) in enumerate(zip(py_val, js_val)):
            _compare_dict(a, b, f"{path}[{i}]")
    elif isinstance(py_val, bool):
        assert py_val == js_val, f"{path}: bool 不一致 {py_val} vs {js_val}"
    elif isinstance(py_val, (int, float)):
        assert np.isclose(float(py_val), float(js_val), rtol=RTOL, atol=ATOL), (
            f"{path}: 数值不一致 py={py_val} js={js_val}")
    elif isinstance(py_val, str) and isinstance(js_val, str):
        assert py_val == js_val, f"{path}: 字符串不一致 {py_val!r} vs {js_val!r}"
    else:
        assert py_val is None and js_val is None, f"{path}: 类型不一致 {py_val!r} vs {js_val!r}"


@pytest.mark.parametrize("fuel_pct", [0.3, 0.5, 1.0])
def test_jet_analysis_matches(fuel_pct):
    py = py_analyze(make_jet_fm(), fuel_pct)
    js = js_analyze(make_jet_fm(), fuel_pct)
    _compare_dict(py, js, "jet")


@pytest.mark.parametrize("afterburner", [True, False])
def test_jet_afterburner_flag(afterburner):
    py = py_analyze(make_jet_fm(), 0.5, afterburner=afterburner)
    js = js_analyze(make_jet_fm(), 0.5, afterburner=afterburner)
    _compare_dict(py, js, "jet-ab")


def test_prop_analysis_matches():
    py = py_analyze(make_prop_fm(), 0.5)
    js = js_analyze(make_prop_fm(), 0.5)
    _compare_dict(py, js, "prop")


def test_flat_jet_analysis_matches():
    """老格式（平坦气动 + 动态推力轴）两端一致性。"""
    py = py_analyze(make_flat_jet_fm(), 0.5)
    js = js_analyze(make_flat_jet_fm(), 0.5)
    _compare_dict(py, js, "flat-jet")


def test_multi_engine_matches():
    py = py_analyze(make_jet_fm(n_engines=2), 0.5)
    js = js_analyze(make_jet_fm(n_engines=2), 0.5)
    _compare_dict(py, js, "jet-2eng")


@pytest.mark.skipif(not (ROOT / "data" / "raw").exists(), reason="无原始数据")
def test_real_aircraft_matches():
    """用真实 .blkx 数据做端到端交叉验证（要求 data/raw 存在）。"""
    raw_dir = ROOT / "data" / "raw"
    blkx_files = sorted(raw_dir.glob("*.blkx"))
    if not blkx_files:
        pytest.skip("data/raw 为空")
    # 采样少量真实飞机覆盖不同结构（喷气/螺旋桨/多发）
    picked = [f for f in blkx_files if f.stem in ("j_10c", "f-16a", "bf-109f-4", "yak-9k", "su-27")]
    if not picked:
        picked = blkx_files[:3]
    for blkx in picked:
        fm = json.loads(blkx.read_text(encoding="utf-8"))
        py = py_analyze(fm, 0.5)
        js = js_analyze(fm, 0.5)
        _compare_dict(py, js, f"real:{blkx.stem}")
