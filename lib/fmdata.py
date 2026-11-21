"""飞行模型的引擎布局与质量解析（纯标准库，不依赖 numpy）。

FIX_SPEC §3 的共享实现，供 ``lib/compute.py``、``lib/schema.py``、``analyze.py``
与 ``scripts/_compute_all.py`` 复用。WT 的 FM 数据存在两种引擎布局：

- **新格式**：``EngineType0..EngineType15``（或 ``EngineType``）定义引擎类型，
  ``Engine{i}.Type`` 是整数索引，指向对应类型；``Engine{i}`` 自身通常只带少量
  挂载信息。多发动机类型很常见（如 4 台活塞 + 6 台火箭助推）。
- **老格式**（234 架）：没有 ``EngineType{i}``，引擎定义直接内联在
  ``Engine{i}.Main``（含 ``Main.Type``、``Main.ThrustMax``、``Compressor`` 等）。

因此“是否螺旋桨 / 发动机台数 / 总推力”不能看是否存在 ThrustMaxCoeff 网格，
也不能简单数 ``Engine{i}`` 槽位，必须按 ``Main.Type`` 判定，并对喷气主类型
排除火箭助推与俯仰角 >45° 的垂直升力发动机。

本模块只依赖标准库，因此不会破坏 ``lib/schema.py`` 的“仅标准库”承诺。
"""

from __future__ import annotations

# 主引擎类型分类（FIX_SPEC §3）
PROP_TYPES = {"Radial", "Inline", "TurboProp"}
JET_TYPES = {"Jet", "Rocket", "PVRD"}
ENGINE_SLOTS = 16
VERTICAL_PITCH_DEG = 45.0

# 旧启发式（仅在主引擎缺 Main.Type 时使用）的 ThrustMaxCoeff 抽样节点
_HEURISTIC_COEFF_NODES = ((0, 0), (0, 6), (3, 0), (3, 6), (6, 0), (6, 11))


# ============================================================
# 内部工具
# ============================================================
def _as_float(value) -> float:
    """把任意值安全转为 float；None / bool / 不可转换返回 0.0。"""
    if value is None or isinstance(value, bool):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _non_empty_dict(value) -> bool:
    """是否为非空 dict（WT 的占位字段多为 True/0 等非 dict 值）。"""
    return isinstance(value, dict) and bool(value)


def _type_index(value) -> int | None:
    """解析 ``Engine{i}.Type`` 的整数索引；不是有效索引返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _entry_type(entry: dict) -> dict:
    """取出实例项引用的引擎类型 dict（容错）。"""
    engine_type = entry.get("type")
    return engine_type if isinstance(engine_type, dict) else {}


def _entry_main_type(entry: dict) -> str | None:
    """取出实例项引用类型的 ``Main.Type`` 字符串。"""
    main = _entry_type(entry).get("Main")
    if not isinstance(main, dict):
        return None
    main_type = main.get("Type")
    return main_type if isinstance(main_type, str) else None


def _raw_engine_instance_count(fm: dict) -> int:
    """统计原始 ``Engine{i}`` 实例槽位数量（用于总推力兜底）。"""
    count = 0
    for i in range(ENGINE_SLOTS):
        if isinstance(fm.get(f"Engine{i}"), dict):
            count += 1
    return count


# ============================================================
# 质量信息
# ============================================================
def mass_info(fm) -> tuple[float, float]:
    """提取 ``(空重 kg, 最大内油质量 kg)``。

    - ``empty_mass``：``Mass.EmptyMass``（缺失为 0）；
    - ``max_fuel_mass``：优先 ``Mass.MaxFuelMass0``，为 0/缺失时回退
      ``Mass.MaxFuelMass``（7 架老格式 FM 只有后者），都没有则为 0。
    """
    if not isinstance(fm, dict):
        return 0.0, 0.0
    mass = fm.get("Mass")
    if not isinstance(mass, dict):
        return 0.0, 0.0
    empty_mass = _as_float(mass.get("EmptyMass"))
    max_fuel_mass = _as_float(mass.get("MaxFuelMass0"))
    if max_fuel_mass <= 0.0:
        max_fuel_mass = _as_float(mass.get("MaxFuelMass"))
    if max_fuel_mass <= 0.0:
        max_fuel_mass = 0.0
    return empty_mass, max_fuel_mass


# ============================================================
# 引擎类型 / 实例解析
# ============================================================
def has_propeller(fm) -> bool:
    """FM 是否带螺旋桨数据（PropellerType0 / Propeller0 / Engine{i}.Propellor）。

    注意：老格式喷气机常带占位 ``Engine{i}.Propellor``，所以本函数只作为
    ``Main.Type`` 缺失时旧启发式的一个条件，不能单独用于判定机型。
    """
    if not isinstance(fm, dict):
        return False
    if _non_empty_dict(fm.get("PropellerType0")):
        return True
    if _non_empty_dict(fm.get("Propeller0")):
        return True
    for i in range(ENGINE_SLOTS):
        eng = fm.get(f"Engine{i}")
        if isinstance(eng, dict) and _non_empty_dict(eng.get("Propellor")):
            return True
    return False


def thrust_data_of(type_dict) -> dict:
    """从引擎类型 dict 取 ``ThrustMax`` 推力数据。

    优先 ``type_dict["Main"]["ThrustMax"]``（老格式与新格式均常见），
    否则回退顶层 ``type_dict["ThrustMax"]``；没有则返回 ``{}``。
    """
    if not isinstance(type_dict, dict):
        return {}
    main = type_dict.get("Main")
    if isinstance(main, dict):
        thrust_data = main.get("ThrustMax")
        if isinstance(thrust_data, dict) and thrust_data:
            return thrust_data
    thrust_data = type_dict.get("ThrustMax")
    if isinstance(thrust_data, dict) and thrust_data:
        return thrust_data
    return {}


def engine_type_entries(fm) -> list[tuple[str, dict]]:
    """返回 ``[(key, EngineType dict), ...]``。

    依次扫描 ``EngineType0..EngineType15`` 与 ``EngineType``；只收 dict 且
    ``Main`` 为 dict 的项（WT 里存在占位 ``EngineTypeN: true`` 之类）。
    """
    entries: list[tuple[str, dict]] = []
    if not isinstance(fm, dict):
        return entries
    keys = [f"EngineType{i}" for i in range(ENGINE_SLOTS)] + ["EngineType"]
    for key in keys:
        eng = fm.get(key)
        if isinstance(eng, dict) and isinstance(eng.get("Main"), dict):
            entries.append((key, eng))
    return entries


def engine_instances(fm) -> list[dict]:
    """解析 ``Engine0..Engine15`` 实例列表（FIX_SPEC §3.2）。

    每项为 ``{"index", "name", "type_key", "type", "standalone", "pitch"}``：
    - 实例带整数 ``Type`` 且对应 ``EngineType{i}`` 存在 → 引用该类型；
    - 否则实例自带非空 ``Main`` → 老格式独立引擎（``standalone=True``）；
    - 否则（测试夹具的空 stub）→ 引用主类型 ``EngineType0``；
    - 都没有 → 实例自身即引擎定义（``standalone=True``）。
    """
    instances: list[dict] = []
    if not isinstance(fm, dict):
        return instances

    types = dict(engine_type_entries(fm))
    if "EngineType0" in types:
        primary_key: str | None = "EngineType0"
    elif types:
        primary_key = next(iter(types))
    else:
        primary_key = None
    primary = types[primary_key] if primary_key is not None else None

    for i in range(ENGINE_SLOTS):
        name = f"Engine{i}"
        inst = fm.get(name)
        if not isinstance(inst, dict):
            continue

        # 喷口俯仰角（度）：垂直升力发动机判定用
        pitch: float | None = None
        nozzle = inst.get("Nozzle0")
        if isinstance(nozzle, dict):
            direction = nozzle.get("Direction")
            if isinstance(direction, (list, tuple)) and len(direction) >= 2:
                pitch = abs(_as_float(direction[1]))

        # 新格式：实例只带整数 Type 索引，先于 Main 判断
        type_index = _type_index(inst.get("Type"))
        if type_index is not None:
            key = f"EngineType{type_index}"
            if key in types:
                instances.append({
                    "index": i,
                    "name": name,
                    "type_key": key,
                    "type": types[key],
                    "standalone": False,
                    "pitch": pitch,
                })
                continue

        # 老格式：实例本身就是一个完整引擎定义
        main = inst.get("Main")
        if isinstance(main, dict) and main:
            instances.append({
                "index": i,
                "name": name,
                "type_key": None,
                "type": inst,
                "standalone": True,
                "pitch": pitch,
            })
            continue

        # 测试夹具/精简数据里的空 stub：引用主类型
        if primary is not None:
            instances.append({
                "index": i,
                "name": name,
                "type_key": primary_key,
                "type": primary,
                "standalone": False,
                "pitch": pitch,
            })
        else:
            instances.append({
                "index": i,
                "name": name,
                "type_key": None,
                "type": inst,
                "standalone": True,
                "pitch": pitch,
            })

    return instances


def primary_entry(fm) -> dict | None:
    """返回主引擎实例项：优先 ``Engine0`` 对应实例，其次第一个类型条目，
    最后第一个实例；无引擎信息返回 None。
    """
    instances = engine_instances(fm)
    if instances and instances[0]["index"] == 0:
        return instances[0]
    for key, eng in engine_type_entries(fm):
        return {
            "index": -1,
            "name": key,
            "type_key": key,
            "type": eng,
            "standalone": False,
            "pitch": None,
        }
    return instances[0] if instances else None


def main_type(fm) -> str | None:
    """主引擎的 ``Main.Type`` 字符串（如 "Jet"/"Radial"）；未知返回 None。"""
    entry = primary_entry(fm)
    if entry is None:
        return None
    return _entry_main_type(entry)


# ============================================================
# 螺旋桨 / 喷气判定
# ============================================================
def _old_heuristic_is_prop(fm: dict) -> bool:
    """主引擎缺 ``Main.Type`` 时的旧启发式（FIX_SPEC §3.2）。

    有螺旋桨数据且 ThrustMaxCoeff 抽样节点全部缺失 → 螺旋桨；否则喷气。
    """
    if not has_propeller(fm):
        return False
    thrust_data = find_thrust_data(fm)
    for alt_idx, vel_idx in _HEURISTIC_COEFF_NODES:
        if f"ThrustMaxCoeff_{alt_idx}_{vel_idx}" in thrust_data:
            return False
    return True


def is_prop_aircraft(fm) -> bool:
    """按主引擎类型判定是否为螺旋桨飞机。

    ``Main.Type`` 属于 ``PROP_TYPES`` → True；属于 ``JET_TYPES`` → False；
    没有 Type 信息（老数据/精简夹具）→ 旧启发式（有螺旋桨且无推力网格）。
    """
    main = main_type(fm)
    if main in PROP_TYPES:
        return True
    if main in JET_TYPES:
        return False
    return _old_heuristic_is_prop(fm)


# ============================================================
# 发动机台数 / 总推力
# ============================================================
def prop_instances(fm) -> list[dict]:
    """参与推进的螺旋桨实例。

    主类型属于 ``PROP_TYPES`` 时只看 ``Main.Type`` 属于螺旋桨的实例；
    否则（无 Type 信息）返回全部实例。
    """
    instances = engine_instances(fm)
    main = main_type(fm)
    if main in PROP_TYPES:
        selected = [e for e in instances if _entry_main_type(e) in PROP_TYPES]
        return selected if selected else instances
    return instances


def jet_instances(fm) -> list[dict]:
    """参与推进的喷气实例（排除火箭助推与垂直升力发动机）。

    - 主类型属于 ``JET_TYPES``：只取同类型实例（主机 Jet 时排除 Rocket 助推）；
    - 无 Type 信息：全部实例计入；
    - 未知 Type 字符串：取非螺旋桨类型实例。
    最后排除俯仰角 >45° 的垂直升力发动机；若排除后为空则回退全部候选
    （Harrier 单发垂直起降机不能被清零）。
    """
    instances = engine_instances(fm)
    main = main_type(fm)
    if main in JET_TYPES:
        candidates = [e for e in instances if _entry_main_type(e) == main]
    elif main is None:
        candidates = instances
    else:
        candidates = [e for e in instances if _entry_main_type(e) not in PROP_TYPES]

    filtered = [
        e for e in candidates
        if e.get("pitch") is None or e["pitch"] <= VERTICAL_PITCH_DEG
    ]
    return filtered if filtered else candidates


def count_engines(fm) -> int:
    """发动机台数：螺旋桨数螺旋桨实例，喷气数喷气实例；至少 1。"""
    if is_prop_aircraft(fm):
        n_engines = len(prop_instances(fm))
    else:
        n_engines = len(jet_instances(fm))
    return max(1, n_engines)


def total_thrust0_kgf(fm) -> float:
    """喷气总静推力（kgf）：对每个喷气实例累加其自带类型的 ``ThrustMax0``。

    多 Jet 类型必须逐实例取各自 T0（如 ariete：1652+821=2473），不能
    主类型 T0 × 台数。累加为 0 时回退主推力数据的 T0 × 原始实例数。
    """
    total = 0.0
    for entry in jet_instances(fm):
        thrust_data = thrust_data_of(_entry_type(entry))
        total += _as_float(thrust_data.get("ThrustMax0"))
    if total == 0.0:
        thrust_data = find_thrust_data(fm)
        single_thrust = _as_float(thrust_data.get("ThrustMax0"))
        if single_thrust:
            total = single_thrust * max(1, _raw_engine_instance_count(fm))
    return total


# ============================================================
# 推力数据 / 引擎字典查找
# ============================================================
def find_thrust_data(fm) -> dict:
    """定位主推力数据 ``ThrustMax`` dict。

    顺序：主类型 → 第一个带推力数据的 EngineType → 老格式
    ``Engine{i}.Main.ThrustMax`` → ``{}``。
    """
    if not isinstance(fm, dict):
        return {}
    entry = primary_entry(fm)
    if entry is not None:
        thrust_data = thrust_data_of(_entry_type(entry))
        if thrust_data:
            return thrust_data
    for _, eng in engine_type_entries(fm):
        thrust_data = thrust_data_of(eng)
        if thrust_data:
            return thrust_data
    for i in range(ENGINE_SLOTS):
        inst = fm.get(f"Engine{i}")
        if not isinstance(inst, dict):
            continue
        main = inst.get("Main")
        if isinstance(main, dict):
            thrust_data = main.get("ThrustMax")
            if isinstance(thrust_data, dict) and thrust_data:
                return thrust_data
    return {}


def find_engine_dict(fm) -> dict:
    """定位引擎定义 dict（老格式返回整个 ``Engine{i}`` 实例）。

    顺序：主类型 → 第一个 EngineType 条目 → 第一个非空 ``Engine{i}`` → ``{}``。
    """
    if not isinstance(fm, dict):
        return {}
    entry = primary_entry(fm)
    if entry is not None:
        engine = _entry_type(entry)
        if engine:
            return engine
    for _, eng in engine_type_entries(fm):
        if eng:
            return eng
    for i in range(ENGINE_SLOTS):
        eng = fm.get(f"Engine{i}")
        if isinstance(eng, dict) and eng:
            return eng
    return {}


# ============================================================
# 汇总（schema / compute 共用的推力元数据）
# ============================================================
def thrust_summary(fm) -> dict:
    """返回推力汇总：``{"kind", "n_engines", "thrust_max0_kgf", "main_type"}``。

    螺旋桨飞机的 ``thrust_max0_kgf`` 恒为 0（其推力由轴功率模型给出）。
    """
    is_prop = is_prop_aircraft(fm)
    return {
        "kind": "prop" if is_prop else "jet",
        "n_engines": count_engines(fm),
        "thrust_max0_kgf": 0.0 if is_prop else round(total_thrust0_kgf(fm), 9),
        "main_type": main_type(fm),
    }
