"""多机对比数据的 Python / JavaScript 交叉验证。

确保 lib/compare.py 与 web/compare.js 的指标口径、最优值判定、雷达归一化、
剖面高度层选取与曲线序列完全一致（防止手工移植后失同步）。
依赖 Node.js（缺失时自动跳过）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from lib.compare import build_comparison
from tests.fixtures import make_jet_fm, make_prop_fm
from tests.test_cross_js import _compare_dict

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "tests" / "js_compare_runner.js"

pytestmark = pytest.mark.skipif(NODE is None, reason="未找到 Node.js")


def _tmp_records_path() -> Path:
    """返回可用于中转记录 JSON 的文件路径。

    优先沿用 test_cross_js.py 的 ``data/`` 约定；若该目录不可写
    （例如受限沙箱下子目录被 ACL 限制），退回仓库根目录，避免测试
    因环境权限问题失败。
    """
    for candidate in (ROOT / "data" / "_js_compare_tmp.json",
                      ROOT / "_js_compare_tmp.json"):
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text("[]", encoding="utf-8")
            return candidate
        except OSError:
            continue
    pytest.skip("无可写的临时目录（data/ 与仓库根目录均不可写）")


def _record(aircraft: str, fm: dict, *, fuel_pct: float = 0.5,
            payload_kg: float = 0.0, nation: str = "other") -> dict:
    """用 Python 计算链路生成记录（与 CLI / 网页口径一致）。"""
    import analyze

    empty, max_fuel = analyze._mass_info(fm)
    mass_kg = empty + fuel_pct * max_fuel + payload_kg
    record = analyze._build_record_for_fm(aircraft, fm, mass_kg, True, fuel_pct)
    record["nation"] = nation
    record["fuel_pct"] = fuel_pct
    record["payload_kg"] = payload_kg
    return record


def _js_build(records: list[dict]) -> dict:
    """在 Node 中构建对比数据（generated_at 置空以便比较）。"""
    tmp_path = _tmp_records_path()
    tmp_path.write_text(json.dumps(records), encoding="utf-8")
    try:
        proc = subprocess.run(
            [NODE, str(RUNNER), str(tmp_path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(ROOT), timeout=120,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    assert proc.returncode == 0, f"js_compare_runner 失败:\n{proc.stderr}"
    return json.loads(proc.stdout)


def _assert_matches(records: list[dict], path: str):
    py = build_comparison(records)
    py["generated_at"] = ""  # 与 js runner 一致，不比较时间戳
    js = _js_build(records)
    _compare_dict(py, js, path)


def test_compare_matches_for_mixed_aircraft():
    """喷气 + 螺旋桨 + 带挂载 → 两端对比数据逐字段一致。"""
    records = [
        _record("jet_a", make_jet_fm(), nation="usa"),
        _record("jet_b", make_jet_fm(n_engines=2), fuel_pct=1.0, nation="ussr"),
        _record("prop_c", make_prop_fm(), payload_kg=500.0, nation="britain"),
    ]
    _assert_matches(records, "mixed")


def test_compare_matches_with_missing_data():
    """缺爬升路线 / 空 optimal 的记录：两端都应给出 None 指标并跳过。"""
    jet = _record("jet_a", make_jet_fm(), nation="usa")
    broken = {
        "aircraft": "broken",
        "metadata": {"flight_mass_kg": 0.0, "thrust_max0_kgf": 0.0, "afterburner": True},
        "grid": {"altitudes_m": [], "machs": []},
        "samples": [],
        "optimal": {},
        "climb_route": [],
        "nation": "",
        "fuel_pct": None,
        "payload_kg": None,
    }
    _assert_matches([jet, broken], "missing")


def test_compare_matches_with_custom_altitude_grid():
    """非标准高度网格 → 剖面高度层的均匀取样回退逻辑必须一致。"""
    jet = _record("jet_a", make_jet_fm())
    other = _record("jet_b", make_jet_fm(n_engines=2))
    # 人为替换网格与样本高度（模拟老数据 / 不同网格），保留其余字段
    custom_alts = [1000.0, 2000.0, 3000.0, 4000.0, 5000.0, 6000.0, 7000.0, 8000.0, 9000.0]
    for record in (jet, other):
        record["grid"]["altitudes_m"] = list(custom_alts)
        for s in record["samples"]:
            s["altitude_m"] = custom_alts[int(s["altitude_m"] // 1000) % len(custom_alts)]
    _assert_matches([jet, other], "custom-grid")


@pytest.mark.skipif(not (ROOT / "data" / "raw").exists(), reason="无原始数据")
def test_compare_matches_for_real_aircraft():
    """用真实 .blkx 数据做端到端对比一致性验证。"""
    import analyze

    raw_dir = ROOT / "data" / "raw"
    picked = [f for f in sorted(raw_dir.glob("*.blkx"))
              if f.stem in ("j_10c", "su_27", "mig-21_bis")]
    if len(picked) < 2:
        pytest.skip("缺少用于对比的真实数据（j_10c / su_27 / mig-21_bis）")
    records = []
    for blkx in picked:
        fm = json.loads(blkx.read_text(encoding="utf-8"))
        records.append(_record(blkx.stem, fm, nation="ussr"))
    _assert_matches(records, "real")
