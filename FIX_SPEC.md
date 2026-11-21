# WarThunderFM P0 修复规格（Fix Spec）

本文件是 Agent Teams 修复阶段的**唯一实现基准**。所有改动必须符合本规格；与 `AUDIT.md`
（审计报告）冲突时以本文件为准。**不要 git commit / git add / git push。**

## 0. 目标

修复 `AUDIT.md` 第 4 节列出的四类确定性数据缺陷，并同步浏览器端与重算数据：

1. **老格式引擎读不到推力**：234 架 FM 没有 `EngineType*`，引擎定义在 `Engine{i}.Main`
   （44 架喷气/火箭被当螺旋桨，`thrust_max0=0` 或严重偏低）。
2. **推进类型判错**：`_is_prop_aircraft` 用“有无 ThrustMaxCoeff 网格”判断，导致 134 架
   活塞/涡桨（占位 `ThrustMax0=2700`）走喷气模型。
3. **多类型发动机重复计数**：`_count_engines` 数所有 `Engine{i}` 实例，喷气把火箭助推/
   垂直升力发动机也算进去（b_66b 64,260 vs 9,180 kgf；yak_141 32,880 vs 10,960）。
4. **老格式燃油键**：7 架只有 `Mass.MaxFuelMass` 而 `< 0` 的 `MaxFuelMass0`，质量少 6–8%。

产出要求：`lib/compute.py` 与 `web/compute.js` 同步、全部测试通过、`data/computed/`
按新逻辑重算 1,233 条、Wiki 43 机回归对比改善、`AUDIT.md` 追加修复后章节。

## 1. 非目标（P1/P2，不要动）

- 不实现 `Mode5.ThrustMult` / `AfterburnerBoost` 加力增益（b3/b5 已证明单独乘会过冲）。
- 不改螺旋桨功率模型标定（整体偏低 5–15%）。
- 不为直升机/旋翼机单独建模（仍按固定翼公式算，只在报告里标注）。
- 不改 15 km 高度网格、Mach 2.5 网格上限、50% 内油假设。
- 不改 JSON schema 字段名/结构（只改字段值），不改 `data/raw/`，不改 `web/` 其它文件。
- 不修 `fau-1`（PVRD 特殊推力表，`Engine0.Main` 无 `ThrustMax`），允许其保持现状并在报告注明。

## 2. 全量数据事实（已扫描 1,234 个 `data/raw/*.blkx`）

- `Main.Type` 取值：`Radial` 460、`Jet` 404、`Inline` 322、`TurboProp` 55、`Rocket` 30（无 PVRD）。
- 1,000 架有 `EngineType{i}`；234 架没有（老格式，引擎定义在 `Engine{i}.Main`）。
- `Engine{i}.Type` **是整数索引**（如 `0`、`1`），指向 `EngineType0/EngineType1/...`；
  共 1,586 个实例。353 个实例没有 `Type` 但有非空 `Main`（老格式独立引擎）。
- **不存在**“有 EngineType 又有独立 Main 引擎”的混合布局，也不存在 `Engine{i}.Type`
  指向缺失 `EngineType{i}` 的情况。
- 典型布局（用于测试夹具）：
  - `b_66b`：`EngineType0` Jet T0=4590 + `EngineType1` Rocket T0=453；实例 Engine0/1 Type=0、
    Engine2–13 Type=1，Nozzle 俯仰 0°。正确总推力 9,180 kgf。
  - `yak_141`：两个 Jet 类型（主机 10,960 / 升力 4,260）；Engine0 Type=0 俯仰 0°，
    Engine1/2 Type=1 俯仰 **76°**。正确只计 1 台主机。
  - `yak-38`：同上，升力喷口俯仰 **90°**。
  - `il_28`：4 个类型（Jet、Jet、Rocket、Rocket），实例 Type=0..3；Rocket 俯仰 12°。
  - `ffa_p16`：只有 `Engine0` Type=0，`EngineType1` 是**孤儿类型**（无实例引用），必须忽略。
  - `me_264`：Inline 1730 HP + Rocket；4 个活塞实例 + 6 个火箭实例；螺旋桨只计 4 台。
  - `fr_1_fireball`：Radial 1210 + Jet 735；各 1 个实例，按螺旋桨只计 1 台。
  - `ariete`：两个 Jet 类型 T0=1652 / 821，各 1 个实例；总推力应为 2,473（不是 1,652×2）。
  - `me-262a-1a`（老格式）：`Engine0/1` 各带 `Main`（Type=Jet，`Main.ThrustMax.ThrustMax0=910`，
    `Main.Power=1200` 为占位），并有占位 `Propellor` 字典；必须判为喷气、2 发、总 1,820 kgf。
  - `a2d`（老格式）：`Engine0/1.Main` Type=TurboProp、T0=256（占位），有 `Propeller0`；
    必须判为螺旋桨、2 发。
  - `a5m4`：`EngineType0.Main.Type=Radial`、Power=619，有占位 `ThrustMax0=2700` + 系数网格；
    必须判为螺旋桨（不是喷气）。

## 3. 新模块 `lib/fmdata.py`（**纯标准库**，禁止 import numpy）

`lib/schema.py` 的模块注释承诺“仅依赖标准库”，因此引擎/质量解析必须放在本模块，
由 `compute.py`、`schema.py`、`analyze.py`、`scripts/_compute_all.py` 共用。

常量：

```python
PROP_TYPES = {"Radial", "Inline", "TurboProp"}
JET_TYPES = {"Jet", "Rocket", "PVRD"}
ENGINE_SLOTS = 16
VERTICAL_PITCH_DEG = 45.0
```

### 3.1 必需 API（函数名与签名固定，测试会直接导入）

```python
def mass_info(fm) -> tuple[float, float]
    # (empty_mass, max_fuel_mass)
    # empty = float(Mass.EmptyMass or 0)
    # max_fuel = Mass.MaxFuelMass0 if > 0 else Mass.MaxFuelMass if > 0 else 0.0

def has_propeller(fm) -> bool
    # PropellerType0 / Propeller0 非空 dict，或任一 Engine{i}.Propellor 非空 dict

def thrust_data_of(type_dict) -> dict
    # type_dict["Main"]["ThrustMax"]（dict）优先；否则 type_dict["ThrustMax"]（dict）；否则 {}

def engine_type_entries(fm) -> list[tuple[str, dict]]
    # 依次扫描 EngineType0..EngineType15、EngineType；只收 dict 且 Main 为 dict 的项

def engine_instances(fm) -> list[dict]
    # 每项：{"index": int, "name": "Engine0", "type_key": str|None,
    #        "type": dict, "standalone": bool, "pitch": float|None}
    # 规则见 3.2

def primary_entry(fm) -> dict | None
    # 优先 Engine0 对应实例；否则 engine_type_entries 第一项；否则 engine_instances 第一项

def main_type(fm) -> str | None
    # 主引擎 type 的 Main.Type（字符串）；无则 None

def is_prop_aircraft(fm) -> bool
    # 主类型属于 PROP_TYPES → True；属于 JET_TYPES → False；
    # 无 Type 信息时走旧启发式（见 3.2 第 4 条）

def count_engines(fm) -> int
    # 螺旋桨：prop_instances 数量；喷气：jet_instances 数量；至少 1

def total_thrust0_kgf(fm) -> float
    # 对 jet_instances 中每个实例，累加其 type 的 ThrustMax0（不是“主类型 T0 × 台数”）
    # 若累加为 0：回退 find_thrust_data(fm)["ThrustMax0"] × max(1, 原始 Engine{i} 个数)

def find_thrust_data(fm) -> dict
    # 主类型 thrust_data_of 非空则返回；否则 engine_type_entries 顺序第一个非空；
    # 否则老格式：Engine0..15 的 Main.ThrustMax 第一个非空；否则 {}

def find_engine_dict(fm) -> dict
    # 主类型 dict 非空则返回；否则 engine_type_entries 第一项；否则第一个非空 Engine{i}；否则 {}

def thrust_summary(fm) -> dict
    # {"kind": "prop"|"jet", "n_engines": int,
    #  "thrust_max0_kgf": float, "main_type": str|None}
    # prop 的 thrust_max0_kgf 恒为 0.0；jet 用 total_thrust0_kgf 并 round 到 1e-9？

def jet_instances(fm) -> list[dict]
def prop_instances(fm) -> list[dict]
```

### 3.2 核心算法

**实例解析**（`engine_instances`）：

```python
types = {key: eng for key, eng in engine_type_entries(fm)}
primary = types.get("EngineType0") or (first type) or None
entries = []
for i in range(16):
    inst = fm.get(f"Engine{i}")
    if not isinstance(inst, dict):
        continue
    pitch = None
    nozzle = inst.get("Nozzle0")
    if isinstance(nozzle, dict):
        d = nozzle.get("Direction")
        if isinstance(d, (list, tuple)) and len(d) >= 2:
            pitch = abs(float(d[1]))   # 俯仰角绝对值，度
    t = inst.get("Type")
    if isinstance(t, (int, float)) or (isinstance(t, str) and t.isdigit()):
        key = f"EngineType{int(t)}"
        if key in types:
            entries.append({..., "type_key": key, "type": types[key], "standalone": False, "pitch": pitch})
            continue
    main = inst.get("Main")
    if isinstance(main, dict) and main:
        # 老格式：实例本身就是一个完整引擎类型（保留 Compressor 等）
        entries.append({..., "type_key": None, "type": inst, "standalone": True, "pitch": pitch})
        continue
    if primary is not None:
        # 测试夹具里的空 stub：引用主类型
        entries.append({..., "type_key": "EngineType0"?, "type": primary, "standalone": False, "pitch": pitch})
    else:
        entries.append({..., "type": inst, "standalone": True, "pitch": pitch})
return entries
```

**主类型**：`primary_entry(fm)` 的 `type`；`main_type` 取 `type.get("Main", {}).get("Type")`。

**螺旋桨实例**（`prop_instances`）：若 `main_type` 属于 `PROP_TYPES`，返回
`[e for e in entries if e.type.Main.Type in PROP_TYPES]`；如果为空，返回全部实例。

**喷气实例**（`jet_instances`）：

```python
mtype = main_type(fm)
if mtype in JET_TYPES:
    allowed = {mtype}
    cands = [e for e in entries if e.type.Main.Type in allowed]
elif mtype is None:
    cands = entries                     # 无 Type 的测试夹具/老数据，全部计入
else:                                    # 未知 Type 字符串
    cands = [e for e in entries if e.type.Main.Type not in PROP_TYPES]

# 垂直升力发动机排除（Yak-141/38）：仅当排除后仍有候选时才排除
filtered = [e for e in cands if e.pitch is None or e.pitch <= 45.0]
return filtered if filtered else cands
```

注意：**Harrier 这类单发垂直起降机**如果唯一实例被垂直喷口排除，`filtered` 为空 →
回退到 `cands`，仍计 1 台，避免推力归零。

**旧启发式（只在 `main_type` 为 None 时使用）**：
`has_propeller(fm)` 为真且 `find_thrust_data(fm)` 在抽样节点
`(0,0),(0,6),(3,0),(3,6),(6,0),(6,11)` 都没有 `ThrustMaxCoeff_{a}_{v}` → 螺旋桨，否则喷气。

**总推力**：`sum(float(thrust_data_of(e.type).get("ThrustMax0", 0.0)) for e in jet_instances(fm))`。
必须逐实例取各自类型的 T0（`ariete` 两个 Jet 类型不同 T0 时不能乘主类型 T0）。
若结果为 0，回退 `find_thrust_data` 的 `ThrustMax0 × max(1, 原始 Engine{i} 实例数)`。

## 4. `lib/compute.py` 改动

- 顶部 `from lib.fmdata import (...)`（绝对导入，与 `analyze.py` 风格一致）。
- `_get_thrust_data(fm)` → `return fmdata.find_thrust_data(fm)`（保留函数名，测试可能导入）。
- `_find_engine_dict(fm)` → `return fmdata.find_engine_dict(fm)`。
- `_count_engines(fm)` → `return fmdata.count_engines(fm)`。
- `_is_prop_aircraft(fm)` → `return fmdata.is_prop_aircraft(fm)`。
- `_build_thrust_model(fm)`：
  - prop 分支：`n_engines = fmdata.count_engines(fm)`（其余不变）。
  - jet 分支：`t0_kgf = fmdata.total_thrust0_kgf(fm)`，`"t0_n": t0_kgf * G`；
    `table = _build_thrust_table(fm) if fmdata.find_thrust_data(fm) else None`。
  - **模型 dict 的键保持不变**：prop `{"kind","n_engines","prop_area","stages","base_power"}`，
    jet `{"kind","t0_n","table"}`（`tests/test_prepared_equivalence.py`、`scripts/audit_wiki.py` 依赖）。
- 不改 `_thrust_from_model` / `interpolate_thrust` / 阻力 / 网格逻辑。
- 函数 docstring 按新语义更新（老格式回退、按类型计数）。

## 5. `lib/schema.py` 改动

- 顶部 `from lib.fmdata import mass_info, thrust_summary`（`fmdata` 是纯标准库，不破坏模块承诺）。
- `build_record`：
  - `empty_mass, max_fuel_mass = mass_info(fm)`；
  - `thrust_max0_kgf = float(thrust_summary(fm)["thrust_max0_kgf"])`；
  - 删除原先重复的 16 槽遍历与 EngineType 循环；
  - `fuel_mass_kg = fuel_pct * max_fuel_mass`、`flight_mass_kg = empty + fuel` 不变；
  - docstring 同步更新（“兼容老格式与多发动机类型”）。
- 其余 schema 校验逻辑不动。

## 6. `analyze.py` 与 `scripts/_compute_all.py`

- `analyze.py: _mass_info` → `return fmdata.mass_info(fm)`（顶部导入）。
- `scripts/_compute_all.py`：质量提取改为 `fmdata.mass_info(fm)`，其余不变。
- 不新增 CLI 参数。

## 7. `web/compute.js` 改动（必须与 Python 逐条对应）

保持现有纯脚本风格（无 import/export）。新增/改写以下函数，命名用 camelCase：

- `getThrustData`、`findEngineDict`、`countEngines`、`isPropAircraft`：按 Python 同规则重写。
- 新增：`engineTypeEntries`、`thrustDataOf`、`engineInstances`、`primaryEntry`、`mainTypeOf`、
  `massInfo`、`jetInstances`、`propInstances`、`totalThrust0Kgf`、`thrustSummary`。
- `buildThrustModel`：prop 用 `countEngines`；jet 用 `t0N = totalThrust0Kgf(fm) * G`。
- `analyzeAircraft`（约 830 行起）：
  - `maxFuelMass = MaxFuelMass0 > 0 ? MaxFuelMass0 : (MaxFuelMass > 0 ? MaxFuelMass : 0)`；
  - `thrustMax0Kgf = thrustSummary(fm).thrust_max0_kgf`。
- JS 的 `Engine{i}.Type` 是 number：`const t = inst.Type; if (t != null && isFinite(Number(t))) key = 'EngineType' + Math.trunc(Number(t))`。
- 不要改动 drag/optimal/climb 等其它函数。

## 8. 测试要求（`tests/`）

### 8.1 `tests/fixtures.py` 新增夹具

| 函数 | 内容 |
| --- | --- |
| `make_old_format_jet_fm()` | 老格式：`Engine0/1` 各 `Main{Type:"Jet", Power:1200, ThrustMax:{ThrustMax0:910, 6×7 系数}}` + 占位 `Propellor`；无 EngineType |
| `make_multi_type_jet_fm()` | `EngineType0` Jet T0=4590、`EngineType1` Rocket T0=453；2 个 Type=0、12 个 Type=1 实例 |
| `make_vertical_lift_fm()` | `EngineType0` Jet T0=10960、`EngineType1` Jet T0=4260；Engine0 Type0 俯仰 0°、Engine1/2 Type1 俯仰 76° |
| `make_typed_prop_fm()` | `EngineType0.Main.Type="Radial"`、Power=619、占位 `ThrustMax0=2700` + 4×5 系数；`PropellerType0`；1 实例 Type=0 |
| `make_old_format_prop_fm()` | `Engine0/1.Main.Type="TurboProp"`、Power=256、T0=256；`Propeller0` |
| `make_multi_jet_type_fm()` | `EngineType0` Jet T0=1652、`EngineType1` Jet T0=821；各 1 实例 |
| `make_orphan_type_jet_fm()` | 仅 `Engine0` Type=0；多一个未被引用的 `EngineType1` Jet T0=9999 |

保留现有夹具不动（其 `Engine0` 为空 stub，依赖新规则“stub 引用主类型”）。

### 8.2 新测试文件 `tests/test_fmdata.py`

至少覆盖：
- `mass_info`：`MaxFuelMass0` 正常；`MaxFuelMass0=0` 时回退 `MaxFuelMass`；两者都缺失返回 0。
- 老格式喷气：`is_prop_aircraft` False、`count_engines` 2、`total_thrust0_kgf` 1820、`find_thrust_data` 非空。
- 老格式螺旋桨：prop True、count 2。
- 带 Type 的螺旋桨（占位网格）：prop True、count 1。
- 多类型喷气：count 2、T0 9180（Rocket 被排除）。
- 垂直升力：count 1、T0 10960。
- 两个 Jet 类型：T0 2473。
- 孤儿类型：count 1、T0 1200（示例值）。
- `thrust_summary` 的 kind/count/thrust 字段。

### 8.3 更新/新增既有测试

- `tests/test_thrust.py`：加老格式喷气插值测试（`interpolate_thrust` = 2×910×G）、带 Type 螺旋桨判定测试。
- `tests/test_cross_js.py`：`py_analyze` 的 `max_fuel` 改为与 `fmdata.mass_info` 一致；
  新增参数化用例，对 `make_old_format_jet_fm`、`make_multi_type_jet_fm`、`make_vertical_lift_fm`、
  `make_typed_prop_fm`、`make_orphan_type_jet_fm` 做 Python/JS 全记录比较。
- `tests/test_schema.py`：新增“`MaxFuelMass0=0` 时 `fuel_mass_kg` 用 `MaxFuelMass`”用例；
  现有 `test_thrust_max0_with_engine_count` 期望值不变（10,000）。
- 现有 108 个测试必须全部继续通过。

## 9. 重算与回归验收

环境：`/tmp/wtvenv2/bin/python`（pytest 9.2.0 + 系统 numpy 2.4.3）；Node v24.11.1。

1. `node --check web/compute.js`
2. `/tmp/wtvenv2/bin/python -m pytest tests -q` → 全绿（108 + 新增）。
3. 全量重算：
   ```bash
   python scripts/_compute_all.py --force
   python -c "import analyze; analyze.update_manifest()"
   ```
   期望 1,233 条成功；仅 `i_180_event03` 因无质量数据失败；不联网（raw 已缓存）。
4. 抽查（允许 ±2% 的数值差，与原型实验对比）：

   | 机型 | kind | n_engines | thrust_max0_kgf | 极速 km/h（约） |
   | --- | --- | --- | --- | --- |
   | `me-262a-1a` | jet | 2 | 1820 | 935 |
   | `fiat_g91_y` | jet | 2 | 2460 | 1103 |
   | `b_66b` | jet | 2 | 9180 | 1164 |
   | `yak_141` | jet | 1 | 10960 | 1593 |
   | `ariete` | jet | 2 | 2473 | 1137 |
   | `a5m4` | prop | 1 | 0 | 479 |
   | `me_264` | prop | 4 | 0 | 539 |
   | `fr_1_fireball` | prop | 1 | 0 | 637 |
   | `night_fighter_mk_2` | prop | 2 | 0 | 质量 7,915 kg 左右 |

5. Wiki 回归：
   ```bash
   cp data/audit_wiki_43.csv data/audit_wiki_43_before.csv
   python scripts/audit_wiki.py --offline --out data/audit_wiki_43_after.csv
   ```
   记录修复前后 ≤10%/≤20%/中位数/均值对比；在 `AUDIT.md` 末尾追加 `## 9. 修复后回归`
   一节（含表格与异常计数变化：props-on-jet 应为 0，jets-on-prop 应为 0）。
6. 其它异常计数复核：极速=0、0<极速<200、SEP>200/400、极速>3000 的数量与修复前对比。
7. 最终 `git status` 只应出现预期文件（`AUDIT.md`、`FIX_SPEC.md`、`data/audit_wiki_43*`、
   `data/computed/*`、`lib/`、`web/compute.js`、`analyze.py`、`scripts/`、`tests/`）。

## 10. 汇报格式

完成后向 root 报告：改动文件清单、测试结果（总数/通过数）、重算成功数、关键抽查
（表格）、Wiki 前后统计、遗留 P1 问题、`git status` 摘要。不要 git commit。
