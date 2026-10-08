"""多机对比数据构建模块。

把若干架飞机的加速度记录（lib.schema 统一 schema，见 build_record）聚合为
一份可直接渲染的对比数据，供 CLI（``analyze.py compare``）与网页共用：

  - ``compute_compare_metrics``: 从单条记录提取可对比的关键指标
  - ``pick_profile_altitudes``: 选取用于「定高加速度剖面」的高度层
  - ``normalize_metric``: 指标归一化（雷达图用，0-100）
  - ``build_comparison``: 组装完整对比数据（指标表 / 最优值 / 剖面 / 爬升路线 / 雷达）
  - ``validate_comparison`` / ``save_comparison`` / ``load_comparison``: 校验与读写
  - ``format_comparison_table``: 终端可读的等宽对比表

本模块与浏览器端 ``web/compare.js`` 逐字段保持一致（tests/test_compare_cross_js.py
用 Node.js 做交叉验证），修改任意一侧都必须同步另一侧。

仅依赖标准库（json、math、datetime、pathlib、unicodedata）。
"""

from __future__ import annotations

import json
import math
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ============================================================
# 1. 指标定义
# ============================================================
# 参与对比的指标（顺序即表格行序）：
#   key               指标键（entries[].metrics 中的字段名）
#   label             中文标签
#   unit              单位（空字符串表示无量纲）
#   decimals          显示小数位
#   higher_is_better  是否「越大越好」（飞行质量越低越好，故为 False）
COMPARE_METRICS: list[dict] = [
    {"key": "flight_mass_kg", "label": "飞行质量", "unit": "kg", "decimals": 0,
     "higher_is_better": False},
    {"key": "thrust_max0_kgf", "label": "静推力", "unit": "kgf", "decimals": 0,
     "higher_is_better": True},
    {"key": "twr", "label": "推重比", "unit": "", "decimals": 2,
     "higher_is_better": True},
    {"key": "max_accel_mps2", "label": "最大加速度", "unit": "m/s²", "decimals": 2,
     "higher_is_better": True},
    {"key": "max_climb_mps", "label": "最大爬升率", "unit": "m/s", "decimals": 1,
     "higher_is_better": True},
    {"key": "ceiling_m", "label": "实用升限", "unit": "m", "decimals": 0,
     "higher_is_better": True},
    {"key": "top_mach", "label": "极速马赫", "unit": "Mach", "decimals": 2,
     "higher_is_better": True},
    {"key": "top_tas_kmh", "label": "极速 TAS", "unit": "km/h", "decimals": 0,
     "higher_is_better": True},
]

# 雷达图使用的指标（要求对每架飞机都可用且量纲可比，均按「越大越好」归一化）
RADAR_METRIC_KEYS: list[str] = [
    "twr",
    "max_accel_mps2",
    "max_climb_mps",
    "ceiling_m",
    "top_mach",
    "top_tas_kmh",
]

# 「定高加速度剖面」优先使用的高度层（m）；缺失时按网格均匀取样
PROFILE_PREFERRED_ALTITUDES: list[float] = [0.0, 5000.0, 10000.0, 15000.0]
# 剖面最多保留的高度层数
PROFILE_MAX_LAYERS: int = 4


# ============================================================
# 2. 辅助函数（与 web/compare.js 中的 cmp* 辅助函数逐一对应）
# ============================================================
def _cmp_number(value: Any) -> float | None:
    """把 value 转为有限 float；None / bool / NaN / Inf / 非数值 返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    f = float(value)
    if not math.isfinite(f):
        return None
    return f


def _metric_def(key: str) -> dict | None:
    """按 key 查找指标定义。"""
    for m in COMPARE_METRICS:
        if m["key"] == key:
            return m
    return None


def compute_compare_metrics(record: dict) -> dict:
    """从单条加速度记录提取可对比指标。

    参数:
        record: 统一 schema 记录（含 samples / optimal / climb_route / metadata）。

    返回:
        {metric_key: float | None}，缺失数据用 None 表示（不参与最优值判定）。

    指标口径（与网页元数据面板一致）:
        - flight_mass_kg: metadata.flight_mass_kg
        - thrust_max0_kgf: metadata.thrust_max0_kgf（多发为总推力）
        - twr: thrust_max0_kgf / flight_mass_kg（无量纲推重比）
        - max_accel_mps2: 网格内加速度峰值（含负值，可能是负的）
        - max_climb_mps: 最佳爬升路线中 SEP 爬升率峰值
        - ceiling_m: 最佳爬升路线中的最高高度层（SEP>0 的最高层）
        - top_mach / top_tas_kmh: optimal.max_speed_per_alt 中平飞可加速的最高马赫及其 TAS
    """
    metrics: dict[str, float | None] = {}

    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict):
        metadata = {}
    flight_mass = _cmp_number(metadata.get("flight_mass_kg"))
    thrust_kgf = _cmp_number(metadata.get("thrust_max0_kgf"))
    metrics["flight_mass_kg"] = flight_mass
    metrics["thrust_max0_kgf"] = thrust_kgf
    # 推重比：静推力(kgf) / 飞行质量(kg)；质量非正或缺失时视为不可用
    if flight_mass is not None and flight_mass > 0.0 and thrust_kgf is not None:
        metrics["twr"] = thrust_kgf / flight_mass
    else:
        metrics["twr"] = None

    # 最大加速度：网格内峰值
    samples = record.get("samples") if isinstance(record, dict) else None
    max_accel: float | None = None
    if isinstance(samples, list):
        for s in samples:
            if not isinstance(s, dict):
                continue
            v = _cmp_number(s.get("accel_mps2"))
            if v is None:
                continue
            if max_accel is None or v > max_accel:
                max_accel = v
    metrics["max_accel_mps2"] = max_accel

    # 爬升相关：SEP 峰值 + 最高可用高度层
    climb_route = record.get("climb_route") if isinstance(record, dict) else None
    max_sep: float | None = None
    ceiling: float | None = None
    if isinstance(climb_route, list):
        for p in climb_route:
            if not isinstance(p, dict):
                continue
            sep = _cmp_number(p.get("sep_mps"))
            if sep is not None and (max_sep is None or sep > max_sep):
                max_sep = sep
            alt = _cmp_number(p.get("altitude_m"))
            if alt is not None and (ceiling is None or alt > ceiling):
                ceiling = alt
    metrics["max_climb_mps"] = max_sep
    metrics["ceiling_m"] = ceiling

    # 极速：平飞可加速的最高马赫（及其对应 TAS）
    optimal = record.get("optimal") if isinstance(record, dict) else None
    if not isinstance(optimal, dict):
        optimal = {}
    max_speed_rows = optimal.get("max_speed_per_alt")
    top_mach: float | None = None
    top_tas: float | None = None
    if isinstance(max_speed_rows, list):
        for row in max_speed_rows:
            if not isinstance(row, dict):
                continue
            mach = _cmp_number(row.get("mach_max"))
            if mach is None:
                continue
            if top_mach is None or mach > top_mach:
                top_mach = mach
                top_tas = _cmp_number(row.get("tas_max_kmh"))
    metrics["top_mach"] = top_mach
    metrics["top_tas_kmh"] = top_tas

    return metrics


def pick_profile_altitudes(altitudes: list[float]) -> list[float]:
    """选取用于定高加速度剖面的高度层。

    规则:
        1. 优先取 PROFILE_PREFERRED_ALTITUDES 中确实存在于网格的高度（按升序）；
        2. 若命中不足 2 层（非标准网格），则在网格上均匀取 PROFILE_MAX_LAYERS 层；
        3. 网格层数不超过 PROFILE_MAX_LAYERS 时全部保留。

    说明:
        均匀取样使用 floor(i*(n-1)/3 + 0.5) 计算下标（两端对齐的半数进位取整），
        与 web/compare.js 的实现逐位一致，避免两端选取不同高度层。
    """
    values = [_cmp_number(a) for a in altitudes]
    grid = [a for a in values if a is not None]
    if not grid:
        return []

    picked = [a for a in PROFILE_PREFERRED_ALTITUDES if a in grid]
    if len(picked) >= 2:
        return sorted(picked)

    n = len(grid)
    if n <= PROFILE_MAX_LAYERS:
        return list(grid)
    idx: list[int] = []
    for i in range(PROFILE_MAX_LAYERS):
        j = int(math.floor(i * (n - 1) / 3.0 + 0.5))
        if j not in idx:
            idx.append(j)
    return sorted({grid[j] for j in idx})


def normalize_metric(values: list[float | None],
                     higher_is_better: bool = True) -> list[float | None]:
    """把一组指标值归一化到 0-100（雷达图用）。

    规则:
        - 仅用非 None 值确定上下界；None 保持 None；
        - 全部相等（或只有一个有效值）时所有有效值记为 100；
        - 越大越好：最优值 = 100，最差 = 0；越小越好则取反；
        - 单架飞机的对比集合（无差异）同样记为 100。

    参数:
        values: 指标值列表（可含 None）。
        higher_is_better: True 表示数值越大越好。

    返回:
        与输入等长的列表，元素为 0-100 的 float 或 None。
    """
    present = [v for v in values if v is not None]
    if not present:
        return [None for _ in values]
    lo = min(present)
    hi = max(present)
    out: list[float | None] = []
    for v in values:
        if v is None:
            out.append(None)
            continue
        if hi == lo:
            out.append(100.0)
            continue
        t = (v - lo) / (hi - lo)
        if not higher_is_better:
            t = 1.0 - t
        out.append(t * 100.0)
    return out


def _beijing_now_iso() -> str:
    """当前北京时间（UTC+8）ISO 8601 字符串。"""
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


# ============================================================
# 3. build_comparison
# ============================================================
def build_comparison(records: list[dict]) -> dict:
    """把多架飞机的加速度记录组装为完整对比数据。

    参数:
        records: 记录列表；每条记录为统一 schema dict，可附带以下可选字段
            - ``nation``: 国家代号（用于表格副标题）
            - ``fuel_pct``: 该机使用的燃油比例
            - ``payload_kg``: 该机使用的挂载质量 kg

    返回:
        {
          "aircraft": ["j_10c", ...],
          "generated_at": ISO 8601（北京时间）,
          "metrics": [指标定义...],
          "radar_indicators": [{key,label,unit}...],
          "entries": [{name,nation,fuel_pct,payload_kg,flight_mass_kg,afterburner,
                       metrics:{...}, radar:[...]}...],
          "best": {metric_key: [取得最优的机型名...]},
          "profiles": [{altitude_m, series:[{name,mach:[],accel_mps2:[]}]}],
          "climb_routes": [{name, altitude_m:[], mach:[], sep_mps:[]}]
        }

    说明:
        - ``best`` 仅统计有值（非 None）的机型；并列时包含全部机型名；
        - ``radar`` 逐指标在本次对比集合内归一化，因此「满分」只表示相对最优；
        - ``profiles`` 中的马赫数轴由各机自身网格给出，允许不同网格对比。
    """
    entries: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = record.get("aircraft")
        if not isinstance(name, str) or not name:
            name = "unknown"
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        nation = record.get("nation")
        if not isinstance(nation, str):
            nation = ""
        flight_mass_raw = metadata.get("flight_mass_kg")
        entries.append({
            "name": name,
            "nation": nation,
            "fuel_pct": _cmp_number(record.get("fuel_pct")),
            "payload_kg": _cmp_number(record.get("payload_kg")),
            "flight_mass_kg": _cmp_number(flight_mass_raw),
            "afterburner": bool(metadata.get("afterburner")),
            "metrics": compute_compare_metrics(record),
            "radar": [],
        })

    # ---- 最优值判定 ----
    best: dict[str, list[str]] = {}
    for m in COMPARE_METRICS:
        key = m["key"]
        higher = bool(m["higher_is_better"])
        candidates: list[tuple[str, float]] = []
        for e in entries:
            v = e["metrics"].get(key)
            if v is None:
                continue
            candidates.append((e["name"], v))
        if not candidates:
            best[key] = []
            continue
        target = max(v for _, v in candidates) if higher else min(v for _, v in candidates)
        best[key] = [n for n, v in candidates if v == target]

    # ---- 雷达图（仅取 RADAR_METRIC_KEYS，逐指标在本次对比集合内归一化）----
    radar_indicators: list[dict] = []
    radar_columns: list[list[float | None]] = []
    for key in RADAR_METRIC_KEYS:
        definition = _metric_def(key)
        if definition is None:
            continue
        radar_indicators.append({
            "key": key,
            "label": definition["label"],
            "unit": definition["unit"],
        })
        radar_columns.append(normalize_metric(
            [e["metrics"].get(key) for e in entries],
            bool(definition["higher_is_better"]),
        ))
    for i, e in enumerate(entries):
        e["radar"] = [col[i] for col in radar_columns]

    # ---- 定高加速度剖面 ----
    altitudes_source: list[float] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        grid = record.get("grid")
        if isinstance(grid, dict) and isinstance(grid.get("altitudes_m"), list):
            for a in grid["altitudes_m"]:
                v = _cmp_number(a)
                if v is not None and v not in altitudes_source:
                    altitudes_source.append(v)
    altitudes_source.sort()
    profile_alts = pick_profile_altitudes(altitudes_source)

    profiles: list[dict] = []
    for alt in profile_alts:
        series: list[dict] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            name = record.get("aircraft")
            if not isinstance(name, str) or not name:
                name = "unknown"
            samples = record.get("samples")
            machs: list[float] = []
            accels: list[float | None] = []
            if isinstance(samples, list):
                for s in samples:
                    if not isinstance(s, dict):
                        continue
                    if _cmp_number(s.get("altitude_m")) != alt:
                        continue
                    mach = _cmp_number(s.get("mach"))
                    if mach is None:
                        continue
                    machs.append(mach)
                    accels.append(_cmp_number(s.get("accel_mps2")))
            series.append({"name": name, "mach": machs, "accel_mps2": accels})
        profiles.append({"altitude_m": alt, "series": series})

    # ---- 最佳爬升路线（叠加用）----
    climb_routes: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        name = record.get("aircraft")
        if not isinstance(name, str) or not name:
            name = "unknown"
        alts: list[float] = []
        machs: list[float] = []
        seps: list[float | None] = []
        route = record.get("climb_route")
        if isinstance(route, list):
            for p in route:
                if not isinstance(p, dict):
                    continue
                alt = _cmp_number(p.get("altitude_m"))
                mach = _cmp_number(p.get("mach"))
                if alt is None or mach is None:
                    continue
                alts.append(alt)
                machs.append(mach)
                seps.append(_cmp_number(p.get("sep_mps")))
        climb_routes.append({
            "name": name,
            "altitude_m": alts,
            "mach": machs,
            "sep_mps": seps,
        })

    return {
        "aircraft": [e["name"] for e in entries],
        "generated_at": _beijing_now_iso(),
        "metrics": [dict(m) for m in COMPARE_METRICS],
        "radar_indicators": radar_indicators,
        "entries": entries,
        "best": best,
        "profiles": profiles,
        "climb_routes": climb_routes,
    }


# ============================================================
# 4. validate_comparison / 读写
# ============================================================
def validate_comparison(data: dict) -> tuple[bool, list[str]]:
    """校验对比数据结构。

    参数:
        data: build_comparison 的返回值。

    返回:
        (is_valid, errors)：errors 为中文错误信息列表。
    """
    errors: list[str] = []
    if not isinstance(data, dict):
        errors.append("顶层对象必须是 dict 类型")
        return False, errors

    for field in ("aircraft", "metrics", "entries", "best", "profiles", "climb_routes"):
        if field not in data:
            errors.append(f"顶层缺少必填字段：{field}")
    if errors:
        return False, errors

    aircraft = data.get("aircraft")
    if not isinstance(aircraft, list) or len(aircraft) < 2:
        errors.append("aircraft 必须是长度 >= 2 的 list（对比至少需要两架飞机）")
    else:
        for i, name in enumerate(aircraft):
            if not isinstance(name, str) or not name:
                errors.append(f"aircraft[{i}] 必须是非空字符串")

    metrics = data.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        errors.append("metrics 必须是非空 list")
    else:
        for i, m in enumerate(metrics):
            if not isinstance(m, dict):
                errors.append(f"metrics[{i}] 必须是 dict 类型")
                continue
            for field in ("key", "label", "unit", "decimals", "higher_is_better"):
                if field not in m:
                    errors.append(f"metrics[{i}] 缺少必填字段：{field}")
            if "decimals" in m and not isinstance(m.get("decimals"), int):
                errors.append(f"metrics[{i}].decimals 必须是 int")
            if "higher_is_better" in m and not isinstance(m.get("higher_is_better"), bool):
                errors.append(f"metrics[{i}].higher_is_better 必须是 bool")

    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) < 2:
        errors.append("entries 必须是长度 >= 2 的 list")
    else:
        for i, e in enumerate(entries):
            if not isinstance(e, dict):
                errors.append(f"entries[{i}] 必须是 dict 类型")
                continue
            if not isinstance(e.get("name"), str) or not e.get("name"):
                errors.append(f"entries[{i}].name 必须是非空字符串")
            if not isinstance(e.get("metrics"), dict):
                errors.append(f"entries[{i}].metrics 必须是 dict 类型")
            radar = e.get("radar")
            if not isinstance(radar, list):
                errors.append(f"entries[{i}].radar 必须是 list")
            else:
                for j, v in enumerate(radar):
                    if v is None:
                        continue
                    if not isinstance(v, (int, float)) or isinstance(v, bool) \
                            or not math.isfinite(float(v)):
                        errors.append(f"entries[{i}].radar[{j}] 必须是有限数值或 None")
                    elif not (0.0 <= float(v) <= 100.0):
                        errors.append(f"entries[{i}].radar[{j}] 超出 0-100，当前值：{v}")

    best = data.get("best")
    if not isinstance(best, dict):
        errors.append("best 必须是 dict 类型")
    else:
        for key, names in best.items():
            if not isinstance(names, list):
                errors.append(f"best.{key} 必须是 list")
                continue
            for n in names:
                if not isinstance(n, str):
                    errors.append(f"best.{key} 中的机型名必须是字符串")

    profiles = data.get("profiles")
    if not isinstance(profiles, list):
        errors.append("profiles 必须是 list")
    else:
        for i, p in enumerate(profiles):
            if not isinstance(p, dict):
                errors.append(f"profiles[{i}] 必须是 dict 类型")
                continue
            if _cmp_number(p.get("altitude_m")) is None:
                errors.append(f"profiles[{i}].altitude_m 必须是有限数值")
            if not isinstance(p.get("series"), list):
                errors.append(f"profiles[{i}].series 必须是 list")
                continue
            for j, s in enumerate(p["series"]):
                if not isinstance(s, dict):
                    errors.append(f"profiles[{i}].series[{j}] 必须是 dict 类型")
                    continue
                machs = s.get("mach")
                accels = s.get("accel_mps2")
                if not isinstance(machs, list) or not isinstance(accels, list):
                    errors.append(f"profiles[{i}].series[{j}] 的 mach/accel_mps2 必须是 list")
                elif len(machs) != len(accels):
                    errors.append(
                        f"profiles[{i}].series[{j}] 的 mach 与 accel_mps2 长度不一致")

    climb_routes = data.get("climb_routes")
    if not isinstance(climb_routes, list):
        errors.append("climb_routes 必须是 list")
    else:
        for i, c in enumerate(climb_routes):
            if not isinstance(c, dict):
                errors.append(f"climb_routes[{i}] 必须是 dict 类型")
                continue
            for field in ("name", "altitude_m", "mach", "sep_mps"):
                if field not in c:
                    errors.append(f"climb_routes[{i}] 缺少必填字段：{field}")
            alts = c.get("altitude_m")
            machs = c.get("mach")
            seps = c.get("sep_mps")
            if isinstance(alts, list) and isinstance(machs, list) and isinstance(seps, list):
                if not (len(alts) == len(machs) == len(seps)):
                    errors.append(f"climb_routes[{i}] 的三条序列长度不一致")

    return (len(errors) == 0), errors


def save_comparison(data: dict, path: Path) -> None:
    """校验后把对比数据写入 JSON 文件。

    抛出:
        ValueError: 数据未通过 validate_comparison。
    """
    is_valid, errors = validate_comparison(data)
    if not is_valid:
        raise ValueError(
            "对比数据未通过校验：\n" + "\n".join(f"  - {e}" for e in errors))
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


def load_comparison(path: Path) -> dict:
    """读取并校验对比数据文件。

    抛出:
        ValueError: 内容未通过 validate_comparison。
        json.JSONDecodeError: 文件不是合法 JSON。
    """
    with open(path, "r", encoding="utf-8") as fp:
        data = json.load(fp)
    is_valid, errors = validate_comparison(data)
    if not is_valid:
        raise ValueError(
            "对比数据未通过校验：\n" + "\n".join(f"  - {e}" for e in errors))
    return data


# ============================================================
# 5. 终端表格输出
# ============================================================
def _disp_width(text: str) -> int:
    """计算字符串在等宽终端中的显示宽度（CJK 全角字符按 2 计）。"""
    width = 0
    for ch in text:
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def _pad(text: str, width: int, align: str = "left") -> str:
    """按显示宽度补空格（align: left/right）。"""
    gap = max(0, width - _disp_width(text))
    return text + " " * gap if align == "left" else " " * gap + text


def _format_metric(value: float | None, definition: dict) -> str:
    """按指标定义格式化数值（None → —）。"""
    if value is None:
        return "—"
    decimals = int(definition.get("decimals", 2))
    return f"{float(value):,.{decimals}f}"


def format_comparison_table(data: dict) -> str:
    """把对比数据渲染为终端可读的等宽表格（最优值以 * 标记）。"""
    entries = data.get("entries") or []
    metrics = data.get("metrics") or []
    if not entries or not metrics:
        return "（无可对比数据）"

    best = data.get("best") or {}
    name_w = max(14, max(_disp_width(str(e.get("name", ""))) for e in entries) + 2)
    col_w = 12

    lines: list[str] = []
    header = _pad("机型", name_w)
    for m in metrics:
        header += _pad(str(m.get("label", m.get("key", ""))), col_w, "right")
    lines.append(header)

    unit_row = _pad("单位", name_w)
    for m in metrics:
        unit_row += _pad(str(m.get("unit") or "—"), col_w, "right")
    lines.append(unit_row)
    lines.append("-" * (name_w + col_w * len(metrics)))

    for e in entries:
        row = _pad(str(e.get("name", "")), name_w)
        values = e.get("metrics") or {}
        for m in metrics:
            key = m.get("key", "")
            text = _format_metric(values.get(key), m)
            if e.get("name") in (best.get(key) or []):
                text += "*"
            row += _pad(text, col_w, "right")
        lines.append(row)

    lines.append("")
    lines.append("* = 该指标最优；推重比 / 加速度 / 爬升率 / 升限 / 极速越大越好，飞行质量越小越好")
    return "\n".join(lines)
