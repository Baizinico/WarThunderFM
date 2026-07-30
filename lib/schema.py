"""War Thunder 加速度数据统一 JSON Schema 模块。

定义加速度计算结果的统一 JSON Schema，提供：
  - 常量：必填字段列表、数值范围
  - validate：校验数据是否符合 schema
  - build_record：从 fm / samples / grid / optimal 组装合规 dict
  - save_json / load_json：带校验的 JSON 读写

仅依赖标准库（json、datetime、pathlib、math）。
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 1. 常量定义
# ============================================================

# 顶层必填字段
REQUIRED_FIELDS: list[str] = [
    "aircraft",
    "metadata",
    "grid",
    "samples",
    "optimal",
]

# metadata 子对象的必填字段
METADATA_FIELDS: list[str] = [
    "empty_mass_kg",
    "fuel_mass_kg",
    "flight_mass_kg",
    "afterburner",
    "thrust_max0_kgf",
    "computed_at",
    "wt_fm_version",
]

# 每个 sample 必填字段
SAMPLE_FIELDS: list[str] = [
    "altitude_m",
    "mach",
    "tas_mps",
    "thrust_mil_n",
    "thrust_ab_n",
    "drag_n",
    "net_force_n",
    "accel_mps2",
]

# optimal.max_speed_per_alt 元素必填字段
OPTIMAL_MAX_SPEED_FIELDS: list[str] = [
    "altitude_m",
    "mach_max",
    "tas_max_kmh",
]

# optimal.best_alt_per_mach 元素必填字段
OPTIMAL_BEST_ALT_FIELDS: list[str] = [
    "mach",
    "best_alt_m",
    "accel_mps2",
]

# 数值范围常量（闭区间）
# ACCEL_RANGE 拓宽至 -20000：超轻型无人机（如 uav_inf_recon_drone, EmptyMass=1kg）在
# 超声速+低高度时减速度可达 -8687 m/s²（数学正确值——无人机无法在高马赫数飞行）。
# 上限 500 m/s² 对应超高 TWR 装备。
# DRAG/NET_FORCE 拓宽至 1e8：大型飞行器（齐柏林、BV-238、B-52H）在包线外的阻力
# 可达 94M N。1e8 (100M N) 提供充足余量。
MACH_RANGE: tuple[float, float] = (0.0, 5.0)
ALTITUDE_RANGE: tuple[float, float] = (-1000.0, 50000.0)
ACCEL_RANGE: tuple[float, float] = (-20000.0, 500.0)
TAS_MPS_RANGE: tuple[float, float] = (0.0, 3000.0)
THRUST_N_RANGE: tuple[float, float] = (0.0, 1.0e8)
DRAG_N_RANGE: tuple[float, float] = (0.0, 1.0e8)
NET_FORCE_N_RANGE: tuple[float, float] = (-1.0e8, 1.0e8)
MASS_KG_RANGE: tuple[float, float] = (0.0, 1.0e6)
TAS_KMH_RANGE: tuple[float, float] = (0.0, 10000.0)


# ============================================================
# 辅助函数
# ============================================================
def _is_number(value: Any) -> bool:
    """判断 value 是否为有限数值（排除 bool、None、NaN、Inf）。

    Python 中 bool 是 int 的子类，需显式排除以免 True/False 被当作数字。
    """
    if isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _in_range(value: float, rng: tuple[float, float]) -> bool:
    """判断 value 是否落在闭区间 rng 内。"""
    lo, hi = rng
    return lo <= value <= hi


def _check_number(errors: list[str], path: str, value: Any,
                  rng: tuple[float, float]) -> None:
    """检查 value 是否为有限数值且在 rng 范围内，出错则追加中文错误到 errors。"""
    if not _is_number(value):
        errors.append(f"{path} 必须是有限数值，当前值：{value!r}")
        return
    if not _in_range(float(value), rng):
        errors.append(f"{path} 超出范围 {rng}，当前值：{value}")


def _check_optional_number(errors: list[str], path: str, value: Any,
                           rng: tuple[float, float]) -> None:
    """检查 value 是否为 None 或有限数值且在 rng 范围内。"""
    if value is None:
        return
    if not _is_number(value):
        errors.append(f"{path} 必须是有限数值或 None，当前值：{value!r}")
        return
    if not _in_range(float(value), rng):
        errors.append(f"{path} 超出范围 {rng}，当前值：{value}")


def _safe_float(value: Any, default: float = 0.0) -> float:
    """安全转换为有限 float；None / NaN / Inf / 非数值 返回 default。"""
    if value is None:
        return default
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    return f


# ============================================================
# 2. validate
# ============================================================
def validate(data: dict) -> tuple[bool, list[str]]:
    """校验 data 是否符合统一 JSON Schema。

    参数:
        data: 待校验的字典。

    返回:
        (is_valid, errors)：
        - is_valid: 是否通过校验
        - errors: 人类可读的中文错误信息列表（校验失败时非空）
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        errors.append("顶层对象必须是 dict 类型")
        return False, errors

    # --- 顶层字段齐全 ---
    for field in REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"顶层缺少必填字段：{field}")

    # --- aircraft 是非空字符串 ---
    aircraft = data.get("aircraft")
    if not isinstance(aircraft, str) or not aircraft.strip():
        errors.append("aircraft 必须是非空字符串")

    # --- metadata 子对象 ---
    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        errors.append("metadata 必须是 dict 类型")
    else:
        for field in METADATA_FIELDS:
            if field not in metadata:
                errors.append(f"metadata 缺少必填字段：{field}")

        # 数值字段必须为 number 且 >= 0（含范围检查）
        for field in ("empty_mass_kg", "fuel_mass_kg", "flight_mass_kg"):
            if field in metadata:
                v = metadata.get(field)
                if not _is_number(v):
                    errors.append(f"metadata.{field} 必须是有限数值，当前值：{v!r}")
                elif v < 0:
                    errors.append(f"metadata.{field} 必须 >= 0，当前值：{v}")
                elif not _in_range(float(v), MASS_KG_RANGE):
                    errors.append(f"metadata.{field} 超出范围 {MASS_KG_RANGE}，当前值：{v}")

        if "thrust_max0_kgf" in metadata:
            v = metadata.get("thrust_max0_kgf")
            if not _is_number(v):
                errors.append(f"metadata.thrust_max0_kgf 必须是有限数值，当前值：{v!r}")
            elif v < 0:
                errors.append(f"metadata.thrust_max0_kgf 必须 >= 0，当前值：{v}")

        # afterburner 必须是 bool
        if "afterburner" in metadata and not isinstance(metadata.get("afterburner"), bool):
            errors.append("metadata.afterburner 必须是 bool 类型")

        # computed_at 必须是非空字符串（ISO 8601 格式可选）
        computed_at = metadata.get("computed_at")
        if not isinstance(computed_at, str) or not computed_at.strip():
            errors.append("metadata.computed_at 必须是非空字符串")

        # wt_fm_version 必须是字符串
        wt_ver = metadata.get("wt_fm_version")
        if not isinstance(wt_ver, str):
            errors.append("metadata.wt_fm_version 必须是字符串")

    # --- grid ---
    grid = data.get("grid")
    if not isinstance(grid, dict):
        errors.append("grid 必须是 dict 类型")
    else:
        altitudes = grid.get("altitudes_m")
        if not isinstance(altitudes, list) or len(altitudes) == 0:
            errors.append("grid.altitudes_m 必须是非空 list")
        else:
            for i, alt in enumerate(altitudes):
                _check_number(errors, f"grid.altitudes_m[{i}]", alt, ALTITUDE_RANGE)

        machs = grid.get("machs")
        if not isinstance(machs, list) or len(machs) == 0:
            errors.append("grid.machs 必须是非空 list")
        else:
            for i, m in enumerate(machs):
                _check_number(errors, f"grid.machs[{i}]", m, MACH_RANGE)

    # --- samples ---
    samples = data.get("samples")
    if not isinstance(samples, list) or len(samples) == 0:
        errors.append("samples 必须是非空 list")
    else:
        for i, s in enumerate(samples):
            if not isinstance(s, dict):
                errors.append(f"samples[{i}] 必须是 dict 类型")
                continue
            for field in SAMPLE_FIELDS:
                if field not in s:
                    errors.append(f"samples[{i}] 缺少必填字段：{field}")

            # 字段类型与范围检查（仅检查存在的字段，accel_mps2 允许负值）
            if "altitude_m" in s:
                _check_number(errors, f"samples[{i}].altitude_m",
                              s["altitude_m"], ALTITUDE_RANGE)
            if "mach" in s:
                _check_number(errors, f"samples[{i}].mach",
                              s["mach"], MACH_RANGE)
            if "tas_mps" in s:
                _check_number(errors, f"samples[{i}].tas_mps",
                              s["tas_mps"], TAS_MPS_RANGE)
            if "thrust_mil_n" in s:
                _check_number(errors, f"samples[{i}].thrust_mil_n",
                              s["thrust_mil_n"], THRUST_N_RANGE)
            if "thrust_ab_n" in s:
                _check_number(errors, f"samples[{i}].thrust_ab_n",
                              s["thrust_ab_n"], THRUST_N_RANGE)
            if "drag_n" in s:
                _check_number(errors, f"samples[{i}].drag_n",
                              s["drag_n"], DRAG_N_RANGE)
            if "net_force_n" in s:
                _check_number(errors, f"samples[{i}].net_force_n",
                              s["net_force_n"], NET_FORCE_N_RANGE)
            if "accel_mps2" in s:
                _check_number(errors, f"samples[{i}].accel_mps2",
                              s["accel_mps2"], ACCEL_RANGE)

    # --- optimal ---
    optimal = data.get("optimal")
    if not isinstance(optimal, dict):
        errors.append("optimal 必须是 dict 类型")
    else:
        # max_speed_per_alt
        msp = optimal.get("max_speed_per_alt")
        if not isinstance(msp, list):
            errors.append("optimal.max_speed_per_alt 必须是 list")
        else:
            for i, item in enumerate(msp):
                if not isinstance(item, dict):
                    errors.append(f"optimal.max_speed_per_alt[{i}] 必须是 dict 类型")
                    continue
                for field in OPTIMAL_MAX_SPEED_FIELDS:
                    if field not in item:
                        errors.append(f"optimal.max_speed_per_alt[{i}] 缺少必填字段：{field}")
                if "altitude_m" in item:
                    _check_number(errors, f"optimal.max_speed_per_alt[{i}].altitude_m",
                                  item["altitude_m"], ALTITUDE_RANGE)
                # mach_max 允许 None
                if "mach_max" in item:
                    _check_optional_number(errors,
                                           f"optimal.max_speed_per_alt[{i}].mach_max",
                                           item["mach_max"], MACH_RANGE)
                # tas_max_kmh 允许 None（与 mach_max 成对出现）
                if "tas_max_kmh" in item:
                    _check_optional_number(errors,
                                           f"optimal.max_speed_per_alt[{i}].tas_max_kmh",
                                           item["tas_max_kmh"], TAS_KMH_RANGE)

        # best_alt_per_mach
        bap = optimal.get("best_alt_per_mach")
        if not isinstance(bap, list):
            errors.append("optimal.best_alt_per_mach 必须是 list")
        else:
            for i, item in enumerate(bap):
                if not isinstance(item, dict):
                    errors.append(f"optimal.best_alt_per_mach[{i}] 必须是 dict 类型")
                    continue
                for field in OPTIMAL_BEST_ALT_FIELDS:
                    if field not in item:
                        errors.append(f"optimal.best_alt_per_mach[{i}] 缺少必填字段：{field}")
                if "mach" in item:
                    _check_number(errors, f"optimal.best_alt_per_mach[{i}].mach",
                                  item["mach"], MACH_RANGE)
                if "best_alt_m" in item:
                    _check_number(errors, f"optimal.best_alt_per_mach[{i}].best_alt_m",
                                  item["best_alt_m"], ALTITUDE_RANGE)
                if "accel_mps2" in item:
                    _check_number(errors, f"optimal.best_alt_per_mach[{i}].accel_mps2",
                                  item["accel_mps2"], ACCEL_RANGE)

    return (len(errors) == 0), errors


# ============================================================
# 3. build_record
# ============================================================
def build_record(aircraft: str, fm: dict, samples: list[dict], grid: dict,
                 optimal: dict, params: dict) -> dict:
    """组装符合 schema 的加速度记录 dict。

    参数:
        aircraft: 机型代号（如 "j_10c"）。
        fm: 飞行模型 JSON 字典（含 Mass、EngineType0 等节点）。
        samples: compute_accel_grid 返回的样本列表。
        grid: compute_accel_grid 返回的网格描述。
        optimal: compute_optimal 返回的最优剖面（须含 best_alt_m 字段）。
        params: 参数字典，含
            - afterburner: bool 是否启用加力
            - fuel_pct: float 燃油比例（0-1）
            - wt_fm_version: str WT 数据版本标签

    返回:
        符合统一 schema 的 dict。

    说明:
        - 从 fm 提取 Mass.EmptyMass / Mass.MaxFuelMass0；
        - 从 fm 提取 EngineType0.Main.ThrustMax.ThrustMax0，
          兼容 EngineType0 / EngineType / EngineType1 命名变体（用 .get 兜底）；
        - fuel_mass_kg = fuel_pct * max_fuel_mass；
        - flight_mass_kg = empty_mass + fuel_mass_kg；
        - computed_at 使用北京时间（UTC+8）的 ISO 8601 字符串。
    """
    # 从 fm 提取质量信息（用 .get 兜底）
    mass = fm.get("Mass", {}) if isinstance(fm, dict) else {}
    if not isinstance(mass, dict):
        mass = {}
    empty_mass = _safe_float(mass.get("EmptyMass", 0.0), 0.0)
    max_fuel_mass = _safe_float(mass.get("MaxFuelMass0", 0.0), 0.0)

    # 从 fm 提取 ThrustMax0（兼容 EngineType0 / EngineType / EngineType1 变体）
    # 多发战机的总推力 = 单发 ThrustMax0 × 引擎实例数（Engine0/Engine1/...）
    thrust_max0_kgf = 0.0
    if isinstance(fm, dict):
        for key in ("EngineType0", "EngineType", "EngineType1"):
            eng = fm.get(key)
            if not isinstance(eng, dict):
                continue
            main = eng.get("Main", {})
            if not isinstance(main, dict):
                continue
            tm = main.get("ThrustMax", {})
            if isinstance(tm, dict) and tm.get("ThrustMax0") is not None:
                single_thrust = _safe_float(tm.get("ThrustMax0"), 0.0)
                # 统计引擎实例数
                n_engines = 0
                for i in range(16):
                    if f"Engine{i}" in fm:
                        n_engines += 1
                n_engines = max(1, n_engines)
                thrust_max0_kgf = single_thrust * n_engines
                break

    # 从 params 提取参数
    afterburner = bool(params.get("afterburner", False))
    fuel_pct = _safe_float(params.get("fuel_pct", 0.0), 0.0)
    wt_fm_version_raw = params.get("wt_fm_version", "")
    wt_fm_version = wt_fm_version_raw if isinstance(wt_fm_version_raw, str) else str(wt_fm_version_raw)

    # 计算衍生质量
    fuel_mass_kg = fuel_pct * max_fuel_mass
    flight_mass_kg = empty_mass + fuel_mass_kg

    # 北京时间（UTC+8）ISO 8601 字符串
    beijing_tz = timezone(timedelta(hours=8))
    computed_at = datetime.now(beijing_tz).isoformat()

    return {
        "aircraft": aircraft,
        "metadata": {
            "empty_mass_kg": empty_mass,
            "fuel_mass_kg": fuel_mass_kg,
            "flight_mass_kg": flight_mass_kg,
            "afterburner": afterburner,
            "thrust_max0_kgf": thrust_max0_kgf,
            "computed_at": computed_at,
            "wt_fm_version": wt_fm_version,
        },
        "grid": grid,
        "samples": samples,
        "optimal": optimal,
    }


# ============================================================
# 4. save_json
# ============================================================
def save_json(record: dict, path: Path) -> None:
    """将 record 校验后写入 JSON 文件。

    参数:
        record: 待写入的字典（须符合 schema）。
        path: 目标文件路径。

    抛出:
        ValueError: record 未通过 schema 校验，错误信息中附详细 errors。
    """
    is_valid, errors = validate(record)
    if not is_valid:
        raise ValueError(
            "记录未通过 schema 校验：\n" + "\n".join(f"  - {e}" for e in errors)
        )
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(record, fp, ensure_ascii=False, indent=2)


# ============================================================
# 5. load_json
# ============================================================
def load_json(path: Path) -> dict:
    """读取 JSON 文件并校验，返回 dict。

    参数:
        path: JSON 文件路径。

    返回:
        符合 schema 的字典。

    抛出:
        ValueError: 文件内容未通过 schema 校验，错误信息中附详细 errors。
        json.JSONDecodeError: 文件不是合法 JSON。
    """
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    is_valid, errors = validate(data)
    if not is_valid:
        raise ValueError(
            "文件内容未通过 schema 校验：\n" + "\n".join(f"  - {e}" for e in errors)
        )
    return data
