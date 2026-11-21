# WarThunderFM 计算数据与《战争雷霆》数据符合性审计

- 审计日期：2026-11-20
- 审计对象：`data/raw/*.blkx` → `lib/compute.py` → `data/computed/*.json`，以及前端 `web/compute.js` 的同公式重算
- 对照基准：War Thunder Wiki 官方数据卡的 **RB 完全体（`show-char-rb-mod-ref`）** 极速
- 复核脚本：`scripts/audit_wiki.py`；明细表：`data/audit_wiki_43.csv`

## 1. 结论

**不完全符合。** 空重与原始飞模一致，但燃油有 7 条老格式键漏读；推力与极速存在成体系的解析、分类和计数错误。在 1,234 条数据中，约 **250 条（20%）** 至少受一项确定性缺陷影响。

| 核查项 | 结果 |
|---|---|
| 空重 `empty_mass_kg` | 1,233/1,233 与 `Mass.EmptyMass` 完全一致 |
| 燃油 `fuel_mass_kg` | 1,226 条 = 50% × `Mass.MaxFuelMass0`；7 条老格式只认 `MaxFuelMass0`，把 `MaxFuelMass` 当 0（质量少 6–8%） |
| 预计算文件是否为当前代码产物 | 1,233 条重算与存储值最大差 **7×10⁻¹¹**，不是“数据陈旧”问题 |
| 43 架 Wiki 极速对照 | 20/43 在 ±10% 内，31/43 在 ±20% 内；中位数 **-2.1%**，均值 **+3.6%** |
| 确定性缺陷影响面 | 老格式喷气/火箭 44 架、活塞/涡桨误判 134 架、多发动机重复计数 23 架、直升机 94 架、燃油键 7 架；去重后 **250 架** |
| 最严重单机偏差 | `b_66b` +192%（3,063 vs 1,048 km/h）、`a_4n` +90%、`yak_141` +62%、`a5m4` +92% |

结论分三层：

1. **能修的数据错误**：四类解析/计数 bug（老格式引擎、活塞机分类、多发动机计数、燃油键）导致约 250 架飞机的推力/功率出现数量级或大幅偏差，必须修。
2. **模型标定偏差**：即使避开上述 bug，螺旋桨极速系统性偏低 5–15%，加力喷气多数在 -19%～+12% 之间，但 `Mirage F1C` 低 44.5%（未用 `Mode5.ThrustMult`/`AfterburnerBoost`）。
3. **模型不适用范围**：94 架直升机用固定翼公式计算，结果无物理意义，应标注/排除。

因此，当前数据可以用于“同模型内部的相对比较”，**不能**作为“与游戏数据逐机一致”的权威数据对外发布。

## 2. 核查方法

### 2.1 数据流

```
data/raw/<name>.blkx  (飞模 JSON)
  └─ lib/compute.py: _build_thrust_model / _build_drag_model / compute_accel_grid
       └─ analyze.py: _mass_info → build_record → data/computed/<name>.json
            └─ web/compute.js: 浏览器端用同一套公式实时重算
```

- 质量：`empty_mass_kg = Mass.EmptyMass`，`fuel_mass_kg = fuel_pct × MaxFuelMass0`，默认 `fuel_pct = 0.5`，`flight_mass_kg = empty + fuel`。
- 网格：高度 0–15,000 m（每 1,000 m，16 层）× 马赫 0.1–2.5（步长 0.05，49 点），共 784 个样本。
- 极速取 `optimal.max_speed_per_alt` 中所有高度上 `accel > 0` 的最大 TAS。
- 加力：`metadata.afterburner` 为真时用 `thrust_ab_n`，否则用 `thrust_mil_n`。

### 2.2 Wiki 对照口径

Wiki 页面 `https://wiki.warthunder.com/unit/<name>` 的数据卡里，“Max speed”一行有四个数，按 span 的 class 区分：

| class | 含义 |
|---|---|
| `show-char-rb-mod-ref` | RB 完全体（本报告基准） |
| `show-char-rb-mod-basic` | RB 白板 |
| `show-char-ab-mod-ref` | AB 完全体 |
| `show-char-ab-mod-basic` | AB 白板 |

解析必须截到下一个 `game-unit_chars-block`；用固定字符窗口会把 “Rate of Climb” 的数值误当成速度（`a2d` 的速度块就没有四个 span）。本机 Python 的 SSL CA 不可用，脚本用 `curl` 抓取并缓存到 `/tmp/wt_wiki/`。

### 2.3 对照的局限

- 我们用 **50% 内油** 的质量；Wiki 的 RB 参考配置不一定相同。质量每差 5%，极速大约差 2–3%。
- Wiki 给的是“某高度下的最大速度”，我们取“全高度最大值”，两者本应接近，但升限/高空性能受 15 km 网格上限截断。
- 43 架是抽样，不是全量；但覆盖了活塞、涡桨、早期喷气、加力喷气、老格式、多发动机、直升机七类。

## 3. 与飞模一致的部分

- **空重**：1,233 条全部精确等于 `Mass.EmptyMass`，无一条偏差。
- **燃油（按代码所读的键）**：1,226 条精确等于 `0.5 × Mass.MaxFuelMass0`，飞行质量 = 空重 + 燃油，误差 < 1 g。
- **预计算与当前代码一致**：对 1,233 条逐样本重算，`accel_mps2` 最大差 6.9×10⁻¹¹，说明 `data/computed` 不是旧版本残留。
- **部分机型与 Wiki 吻合良好**（±3%）：`mig-15` +2.5%、`mig-17` +2.1%、`f-86a-5` +0.9%、`f-86f-25` +0.4%、`hunter_f1` -0.5%、`me-163b` +2.7%。
- 在 23 架“无已知解析 bug 的固定翼”子集中，15/23 在 ±10% 内，中位数 -5.1%——说明模型骨架可用，问题集中在分类、计数和标定。

## 4. 确定性缺陷

### 4.1 老格式喷气/火箭机被当成螺旋桨（44 架）

**根因**：`lib/compute.py:74 _get_thrust_data(fm)` 只查 `EngineType0` / `EngineType` / `EngineType1`；老格式飞模把引擎定义直接放在 `Engine0.Main` 下。读不到推力表后，`_is_prop_aircraft` 又看到 `Engine0.Propellor` 占位字典，于是走螺旋桨分支，用 `Power`（占位 1,200 hp）按 `P·η/V` 算推力。

**证据**：`data/raw/me-262a-1a.blkx` 的 `Engine0.Main` 为 `Type=Jet, ThrustMax0=910, Power=1200（占位）`，`ThrustMax` 有 56 个键（6 高度 × 7 速度）。当前 `data/computed/me-262a-1a.json` 在 Mach 0.1 的 `thrust_mil_n ≈ 34,501`，极速 740 km/h；Wiki RB 为 865 km/h。

把 `Engine0.Main` 提升为 `EngineType0` 后重算（原型，未同时排除助推）：

| 机型 | 当前极速 | 修正后 | Wiki RB | 修正后误差 |
|---|---:|---:|---:|---:|
| `me-262a-1a` | 740 | 935 | 865 | +8.1% |
| `f-80` | 690 | 919 | 903 | +1.8% |
| `f9f-2` | 797 | 980 | 926 | +5.8% |
| `he-162a-2` | 683 | 887 | 840 | +5.6% |
| `mig-9` | 740 | 923 | 909 | +1.5% |
| `vampire_fb5` | 850 | 923 | 855 | +8.0% |
| `f-84g_france` | 577 | 980 | — | — |
| `fj_4b` | 479 | 1,137 | — | — |

44 架中：

- **40 架**走螺旋桨模型（上表）；
- **3 架**（`fiat_g91_y`、`fiat_g91_ys`、`p_59a`）判为喷气但 `thrust_max0=0`，极速为 0；
- **1 架**（`fau-1`，PVRD）推力表结构不同（`ThrustOmegaMinCoeff`），提升后仍无系数网格，需要单独适配。

**完整名单**（44 架）：`arado-234_hockey`、`arado-234c-3`、`f-80`、`f-80a`、`f-84g_france`、`f2h-2`、`f3d_1`、`f9f-2`、`f9f-5`、`f9f-8`、`fau-1`、`fiat_g91_ps`、`fiat_g91_r1`、`fiat_g91_r3`、`fiat_g91_r4`、`fiat_g91_y`、`fiat_g91_ys`、`fj_4b`、`he-162a-2`、`j8m1`、`kitsuka`、`la_200_toriy`、`md_450b_barougan`、`md_450b_ouragan`、`md_452_mystere_2a`、`md_452_mystere_2c_preproduction`、`me-163b-1`、`me-262a-1a`（及 `_early`/`_u4`/`1b`/`2a`/`_1_u1`）、`me-262c-1a`、`me-262c-2b`、`mig-9`、`mig-9_ussr`、`p_59a`、`r2y2_kai`、`r2y2_v1`、`r2y2_v2`、`vampire_fb5`、`vampire_fb52a`、`yak-30d`。

### 4.2 活塞/涡桨机走喷气模型（134 架）

**根因**：这些飞模的 `ThrustMax0` 是统一占位值 **2,700 kgf**，并带 4×5 或 6×7 的 `ThrustMaxCoeff` 网格。`_is_prop_aircraft` 的判据是“抽样节点上有没有系数”，有网格就判为喷气，于是用 2,700 kgf × 系数当喷气推力。`lib/compute.py:144` 的 6 个抽样节点是 `(0,0),(0,6),(3,0),(3,6),(6,0),(6,11)`。

**影响**：134 架 Radial/Inline/TurboProp 中，26 架极速 >800 km/h，最高 `iar-81c` 1,041 km/h。强制走功率模型后，极速中位数 **673.8 → 421.4 km/h（-37%）**，>800 的 26 架归零。

| 机型 | 当前（jet 占位） | 功率模型 | Wiki RB |
|---|---:|---:|---:|
| `a5m4` | 858 | 479 | 447 |
| `iar-81c` | 1,041 | 643 | — |
| `ffvs_j22_a/b` | 980 | 479 | — |
| `mb_5` | 969 | 684 | — |
| `lagg-3-66` | 858 | 545 | — |
| `il_2m_1943` | 744 | 368 | — |
| `c-47` | 675 | 306 | — |

**注意**：功率模型本身对运输机/双发机偏低（`c-47` 306 km/h，实际约 360–370），所以“改判螺旋桨”是必要但不充分的修复；之后还要按机型标定功率/螺旋桨效率。反向异常 `a_109_eoa2`（266→683）和 `quing_6`（106→490）说明占位 `ThrustMax0` 不统一（550/150/2,700 都出现过），不能靠占位值反推。

### 4.3 多发动机重复计数（23 架）

**根因**：`lib/compute.py:120 _count_engines(fm)` 统计 `Engine0..Engine15` 的**全部实例**，而 `_build_thrust_model` 的喷气分支用 `t0_n = EngineType0.ThrustMax0 × n_engines`。当一台飞机有多个 `EngineType`（主机 + 助推火箭 + 垂直升力发动机）时，所有实例都乘上了**第一台发动机**的推力。

| 机型 | 当前 `thrust_max0` | 正确值 | 当前极速 | 修正后 | Wiki RB |
|---|---:|---:|---:|---:|---:|
| `b_66b` | 64,260 | 9,180 | 3,063 | 1,164 | 1,048 (+11%) |
| `yak_141` | 32,880 | 10,960 | 2,993 | 1,593 | 1,847 (-14%) |
| `yak-38` | 19,410 | 6,470 | 2,656 | 1,225 | — |
| `yak-38m` | 20,940 | 6,980 | 2,656 | 1,225 | — |
| `mirage_3s_c70_switzerland` | 16,840 | 4,210 | 2,848 | 1,367 | — |
| `tu_14t` | 15,300 | 5,100 | 980 | 875 | 856 (+2%) |
| `a_4n` | 15,222 | 5,074 | 2,102 | 1,137 | 1,105 (+3%) |
| `il_28` | 10,716 | 5,358 | 980 | 946 | 905 (+4.5%) |
| `mirage_3c` | 8,460 | 4,230 | 2,656 | 1,434 | 2,160 (-34%) |
| `a_4b` | 10,476 | 3,492 | 1,671 | 1,103 | — |
| `ariete` | 3,304 | 2,473 | 1,164 | 1,137 | — |

23 架中，21 架是喷气（主机 + 助推火箭/升力发动机），2 架是螺旋桨（`me_264` 的 4 台活塞 + 6 台火箭、`fr_1_fireball` 的 1 台活塞 + 1 台喷气）。

**正确计数规则**（已在原型中验证）：

1. 新格式：按 `Engine{j}.Type` 把实例归到 `EngineType{i}`；**没有被任何实例引用的孤儿 `EngineType` 必须忽略**（`ffa_p16` 的 `EngineType1` 无实例，若计入会把 1 台 4,800 kgf 算成 9,600）。
2. 老格式：每个带 `Main` 的 `Engine{j}` 算 1 台。
3. 主机为 `Jet` 时，排除 `Type=Rocket` 的助推类型（A-4、B-66B、Mirage III、Tu-14T）。
4. 所有实例中 `Nozzle0.Direction[1]` 俯仰角 > 45° 的垂直升力发动机排除（Yak-141 升力喷口 76°、Yak-38 90°，主机 0°）。
5. 螺旋桨模型只数 `Radial/Inline/TurboProp` 实例：`me_264` 的 4 台活塞 + 6 台火箭被算成 10 台，功率放大 2.5 倍（766→539，Wiki 519，+3.9%）；`fr_1_fireball` 的 1 台活塞 + 1 台喷气被算成 2 台（711→637，Wiki 652，-2.3%）。

**修正后仍偏低的原因**：`mirage_3c` 的 JATO 被去掉后，暴露加力推力不足（见 5.1）。所以 4.1 和 4.3 必须一起修，单独修一个会从“高估”翻到“低估”。

### 4.4 直升机（94 架）

用 `PropellerType0.Controls.HasCyclicPitchControl == True`（51 架，新格式）或 `Propeller0.Controls.HasCyclicPitchControl == True`（43 架，老格式）可精确识别，共 **94 架**；`MouseAim` 不行（391 架，含大量固定翼）。

当前结果：

| 机型 | 模型 | 当前极速 | Wiki RB |
|---|---|---:|---:|
| `ah_64d` | jet | **0**（全网格无正加速） | 295 |
| `mi_24a` | prop | 228 | 335 (-32%) |
| `ka_50` | jet | 319 | 310（但升限 15 km 荒谬） |

固定翼的升力/阻力/推力公式对旋翼机不适用。建议在 `metadata` 增加 `rotorcraft: true`，前端不显示极速/爬升曲线，或单独做旋翼模型；至少不能把 0 或 228 km/h 当成“计算结果”。

### 4.5 老格式燃油键漏读（7 架）

`analyze.py:_mass_info` 只读 `Mass.MaxFuelMass0`。以下 7 架只有 `Mass.MaxFuelMass`，于是 `fuel_mass_kg = 0`、`flight_mass_kg = empty_mass_kg`：

`fau-1`、`lagg-3-1`、`lagg-3-29`、`lagg_gu-37`、`mig_3_series_pod`、`night_fighter_mk_2`、`pandora_mk_1`。

质量少 6–8%（如 `night_fighter_mk_2` 7,265 vs 应为 7,915）。极速影响不一：`night_fighter_mk_2` 956→903（-5.5%），`lagg-3-1` 不变（诱导阻力占比小），`mig_3_series_pod` 不变（它同时是 134 架喷气占位表之一，推力主导）。修法是回退 `MaxFuelMass`。

## 5. 模型标定偏差（非解析 bug）

### 5.1 加力推力漏乘 `Mode5.ThrustMult`

引擎 `Main.Mode5`（加力模式）含 `ThrustMult`，实测 F-4E 1.40、MiG-21bis 1.49、J-10C 1.37、Su-27 1.35、MiG-29 1.35、FFA P-16 1.18。当前 `_thrust_from_model` 只用 `mil × ThrAftMaxCoeff`，**完全未乘这个 35–49% 的增益**。

直接乘上去：

| 机型 | 当前 | 乘 Mode5 | Wiki RB |
|---|---:|---:|---:|
| `mig-21_bis` | 1,806 | 2,549 | 2,240（反超 14%） |
| `j_10c` | 1,859 | 2,284 | 2,203（+3.7%） |
| `mig_29_9_12g` | 2,178 | 2,656 | 2,452（+8.3%） |
| `f-4e` | 2,390 | 2,773 | 2,140（+30%） |
| `su_27` | 2,656 | 2,773 | 2,498（+11%） |

对 MiG-21/J-10C 更准，对 F-4E/Su-27/MiG-29 反而过冲——说明各机 `ThrAftMaxCoeff` 表已经含了部分修正，简单相乘不是正确做法。需要按机型标定，或读 `AfterburnerBoost` 与 `Mode5` 的联合语义。

`mirage_f1c` 是反例：`Mode5 = {Throttle:1.0, ThrustMult:1.0}`（没有独立加力模式），`AfterburnerBoost=1.14` 也未被使用，当前 1,237 vs Wiki 2,228（**-44.5%**）。乘 1.14 后约 1,410，仍低 37%。

### 5.2 螺旋桨系统性偏低

在 6 km 高度，`bf-109f-4` 与 `fw-190a-5` 都恰好卡在 Mach 0.5：

| 机型 | 6 km 极速 | Wiki @6 km | 误差 |
|---|---:|---:|---:|
| `bf-109f-4` | 569.6 | 665 | -14.3% |
| `fw-190a-5` | 569.6 | 666 | -14.5% |

样本：bf-109 M0.5 推力 4,142 N / 阻力 3,429 N（净 +713）；M0.55 推力 3,765 / 阻力 4,017（净 -251）。越过 Mach 0.5 后推力下降快于阻力上升，功率模型在高马赫段衰减过强。整体上活塞机偏低 5–15%（`yak-3` -8.5%、`f4u-1a` -8.3%、`b-29` -7.5%、`p-51d` -6.4%）。

### 5.3 网格与质量假设

- 高度上限 15 km：705 条记录的“升限”正好是 15,000 m，所有 >15 km 的机型（Su-27/MiG-29 16 km、J-10C 16.5 km、Yak-141 24 km）被截断；`su_27` 还顶到 Mach 2.5 上限。
- 质量固定 50% 内油，不是游戏内满油/最小油；对外比较时应注明。
- 前端 `web/compute.js` 与 Python 是两份手工移植代码，本次审计只测了 Python；两边必须同步修改，否则网页结果与 JSON 不一致。

## 6. 数据集异常统计（1,234 条）

| 指标 | 数量 | 说明 |
|---|---:|---|
| 模型 kind = prop / jet | 716 / 518 | — |
| 极速 = 0 | 20 | 含 `ah_64d`、`fiat_g91_y/ys`、`p_59a`、`fau-1`、`i_180_event03` |
| 0 < 极速 < 200 km/h | 42 | 直升机、无人机、老格式故障机 |
| SEP > 200 m/s | 44 | 物理上不可能（约 20 g 当量） |
| SEP > 400 m/s | 6 | `yak_141` 941、`b_66b` 913、`mirage_3s_c70_switzerland` 747、`yak-38` 640、`yak-38m` 647、`a_4n` 419 |
| 极速 > 3,000 km/h | 1 | `b_66b` 3,063 |
| 升限 = 15,000 m | 705 | 网格截断，不是真实升限 |
| 质量 = 0 | 1 | `i_180_event03`（原始文件 2 字节 `{}`） |

## 7. 修复建议

> 本次审计只新增了报告与 `scripts/audit_wiki.py`，**没有改动 `lib/compute.py`、`web/compute.js` 或 `data/computed/`**。下面是建议的修复顺序。

### P0（数据错误，必须修）

1. **老格式引擎回退**：`_get_thrust_data` 在 `EngineType*` 缺失时读第一个带 `Main.ThrustMax` 的 `Engine{i}`；`fau-1` 的 PVRD 表单独适配。
2. **按 `Main.Type` 判推进类型**：`Radial/Inline/TurboProp` 走功率模型，`Jet/Rocket/PVRD` 走喷气模型；没有 `Type` 的测试 fixture 保留现有网格启发式作为回退。
3. **按类型 + 实例计数**：按 4.3 的五条规则重写 `_count_engines`，同时用于喷气 `t0_n` 和螺旋桨 `n_engines`。
4. **燃油键回退**：`Mass.MaxFuelMass0` 缺失时读 `Mass.MaxFuelMass`。
5. **同步 `web/compute.js`** 的 `isPropAircraft` / `getThrustData` / `countEngines` / `buildThrustModel`，跑 `tests/test_cross_js.py`。

预计效果（原型）：

- 40 架老喷气：740→935（me-262）、690→919（f-80）、526→1,103（f9f-8）；
- 134 架活塞：中位 674→421，>800 的 26 架清零；
- 23 架多发动机（21 喷气 + 2 螺旋桨）：b_66b 3,063→1,164、a_4n 2,102→1,137、il_28 980→946、tu_14t 980→875、me_264 766→539；
- 7 架燃油：质量 +6–8%。

修完后需要重算 `data/computed/*.json`（纯计算约 7 秒，含读写约 1–2 分钟），并重跑 108 个测试。

### P1（适用范围）

6. 直升机：`metadata` 增加 `rotorcraft: true`，前端隐藏固定翼极速/爬升结论，或单独做旋翼模型。
7. `Mode5.ThrustMult` / `AfterburnerBoost`：先按机型标定，再决定是否乘入；不要全局硬乘。
8. 输出中标注“50% 内油、15 km 高度上限、估算值”，避免被当成游戏内实测。

### P2（标定）

9. 螺旋桨功率模型在高马赫段的衰减、螺旋桨效率 η、运输机阻力面积；
10. 加力喷气的 `ThrAftMaxCoeff` 与 `Mode5` 联合标定；
11. 用更多 Wiki 样本（当前 43 架）做回归，目标是干净子集 ±10% 内 ≥80%。

## 8. 复现

```bash
# 测试基线（系统 Python 装不上 pytest，用 venv）
python3 -m venv --system-site-packages /tmp/wtvenv2
/tmp/wtvenv2/bin/pip install pytest
/tmp/wtvenv2/bin/python -m pytest tests -q          # 108 passed

# Wiki 对照（缓存已存在时可 --offline）
/tmp/wtvenv2/bin/python scripts/audit_wiki.py --offline \
    --cache /tmp/wt_wiki --out data/audit_wiki_43.csv

# 全量重算一致性检查（示例，逐条比对 samples）
python3 - <<'PY'
import json, glob, os, sys
sys.path.insert(0, '.')
import lib.compute as C
for p in glob.glob('data/computed/*.json'):
    name = os.path.basename(p)[:-5]
    d = json.load(open(p)); fm = json.load(open(f'data/raw/{name}.blkx'))
    md = d['metadata']
    if not md.get('flight_mass_kg'):
        continue
    s, _ = C.compute_accel_grid(fm, md['flight_mass_kg'], bool(md['afterburner']))
    stored = {(x['altitude_m'], round(x['mach'], 6)): x for x in d['samples']}
    for x in s:
        y = stored[(x['altitude_m'], round(x['mach'], 6))]
        assert abs(x['accel_mps2'] - y['accel_mps2']) < 1e-6
PY
```

## 附录 A：43 架 Wiki 对照

完整表见 `data/audit_wiki_43.csv`。按误差排序的关键行：

| 机型 | Wiki RB | 计算 | 误差 | 组 |
|---|---:|---:|---:|---|
| `b_66b` | 1,048 | 3,063 | +192.2% | 多发动机 |
| `a5m4` | 447 | 858 | +91.8% | 活塞误判 |
| `a_4n` | 1,105 | 2,102 | +90.2% | 多发动机 |
| `yak_141` | 1,847 | 2,993 | +62.0% | 多发动机 |
| `me_264` | 519 | 766 | +47.5% | 多发动机（功率） |
| `bi` | 799 | 1,115 | +39.6% | 火箭机 |
| `mirage_3c` | 2,160 | 2,656 | +22.9% | 多发动机 |
| `tu_14t` | 856 | 980 | +14.5% | 多发动机 |
| `f-4e` | 2,140 | 2,390 | +11.7% | 加力标定 |
| `fr_1_fireball` | 652 | 711 | +9.0% | 多发动机（功率） |
| `il_28` | 905 | 980 | +8.3% | 多发动机 |
| `a2d` | 796 | 858 | +7.7% | 功率标定 |
| `su_27` | 2,498 | 2,656 | +6.3% | 加力标定/网格上限 |
| `ka_50` | 310 | 319 | +2.8% | 直升机 |
| `me-163b` | 955 | 981 | +2.7% | 火箭机 |
| `mig-15` | 1,076 | 1,103 | +2.5% | 正常 |
| `mig-17` | 1,114 | 1,137 | +2.1% | 正常 |
| `f-86a-5` | 1,093 | 1,103 | +0.9% | 正常 |
| `f-86f-25` | 1,106 | 1,110 | +0.4% | 正常 |
| `hunter_f1` | 1,108 | 1,103 | -0.5% | 正常 |
| `vampire_fb5` | 855 | 850 | -0.6% | 老格式（巧合） |
| `me-262a-1a` | 865 | 740 | -14.4% | 老格式 |
| `mig-9` | 909 | 740 | -18.5% | 老格式 |
| `mig-21_bis` | 2,240 | 1,806 | -19.4% | 加力标定 |
| `f-80` | 903 | 690 | -23.5% | 老格式 |
| `mi_24a` | 335 | 228 | -32.0% | 直升机 |
| `mirage_f1c` | 2,228 | 1,237 | -44.5% | 加力标定 |
| `wyvern_s4` | 650 | 159 | -75.5% | 涡桨误判 |
| `ah_64d` | 295 | 0 | -100% | 直升机 |

## 附录 B：审计脚本说明

`scripts/audit_wiki.py`：

- 抓取/复用 Wiki HTML，按 `game-unit_chars-block` 解析四个数值；
- 从 `data/computed/<name>.json` 取全高度最大 TAS；
- 从 `data/raw/<name>.blkx` 取模型 kind、主引擎类型、`thrust_max0`；
- 输出 CSV，并打印 ≤10%/≤20%/中位数/均值。

`DEFAULT_NAMES` 是 43 个抽样机型；`--names` 可覆盖。`mig-19`、`iar-81c` 在 Wiki 无此 slug，未纳入。

## 9. 修复后回归

本节按 `FIX_SPEC.md` 完成 P0 修复（`lib/fmdata.py` 统一引擎/质量解析，Python 与 `web/compute.js` 同步）后，对全部 1,234 条数据重算并复跑回归。环境：系统 Python 3.14.0 + numpy 2.4.3，pytest 9.2.0（`/tmp/wtvenv2`），Node v24.11.1；全程离线（Wiki 缓存 `/tmp/wt_wiki`、raw 已缓存）。

### 9.1 测试与全量重算

| 项目 | 结果 |
|---|---|
| `node --check web/compute.js` | 通过 |
| `/tmp/wtvenv2/bin/python -m pytest tests -q` | **156 passed**（原有 108 + P0 修复 42 + 复审回归 6，0 failed / 0 skipped） |
| `python3 scripts/_compute_all.py --force` | 成功 **1,233** 条，失败 **1** 条：仅 `i_180_event03: no mass data`（原始文件为 2 字节空 FM，符合预期；其旧 JSON 未被覆盖） |
| `python3 -c "import analyze; analyze.update_manifest()"` | 完成 |
| 数据与当前代码一致性 | 1,233 条逐样本重算：966,672 个网格点 max\|Δaccel\| = **0.0**；`metadata.thrust_max0_kgf` / `flight_mass_kg` / `empty_mass_kg` 与 `thrust_summary` / `mass_info` 重算值全部 0 差异；全部 784 samples、无 NaN/缺样本 |

### 9.2 抽查（FIX_SPEC §9 表格）

| 机型 | kind | n_engines | thrust_max0_kgf | 全高度最大 TAS km/h | flight_mass_kg | FIX_SPEC 参考 |
|---|---|---:|---:|---:|---:|---|
| `me-262a-1a` | jet | 2 | 1,820 | 934.8 | 5,255 | jet/2/1,820/935 |
| `fiat_g91_y` | jet | 2 | 2,460 | 1,102.5 | 5,610 | jet/2/2,460/1,103 |
| `b_66b` | jet | 2 | 9,180 | 1,163.8 | 26,364.5 | jet/2/9,180/1,164 |
| `yak_141` | jet | 1 | 10,960 | 1,593.4 | 13,000 | jet/1/10,960/1,593 |
| `ariete` | jet | 2 | 2,473 | 1,137.2 | 2,907 | jet/2/2,473/1,137 |
| `a5m4` | prop | 1 | 0 | 478.8 | 1,440.4 | prop/1/0/479 |
| `me_264` | prop | 4 | 0 | 539.0 | 29,800 | prop/4/0/539 |
| `fr_1_fireball` | prop | 1 | 0 | 637.3 | 4,720 | prop/1/0/637 |
| `night_fighter_mk_2` | prop | 2 | 0 | 902.9 | **7,915** | prop/2/0/质量≈7,915 |

9 个机型 kind / 台数 / 推力与参考完全一致，极速偏差均 <0.1%，在 ±2% 容差内；`night_fighter_mk_2` 燃油回退 `MaxFuelMass` 后质量由 7,265 → 7,915 kg（+8.9%）。

### 9.3 异常计数：修复前 / 修复后

修复前取旧代码产物（1,234 条旧 `data/computed`）；分类计数用 `git show HEAD:lib/compute.py` 旧代码重放核对（精确 props-on-jet 134 / jets-on-prop 40）。

| 指标 | 修复前 | 修复后 | 说明 |
|---|---:|---:|---|
| 模型 kind = prop / jet | 716 / 518 | **810 / 424** | jet→prop 134 架、prop→jet 40 架；`i_180_event03` 为空 FM，两种代码都回退 jet |
| props-on-jet（螺旋桨走喷气模型） | 134 | **0** | — |
| jets-on-prop（喷气走螺旋桨模型） | 40¹ | **0** | ¹ AUDIT §4.1 的 44 架名单中实际走功率模型 40 架，另 3 架为零推力喷气、`fau-1` 为 PVRD 特例 |
| 极速 = 0 | 20 | **2** | 余 `i_180_event03`（空 FM）、`zeppelin`（飞艇，全网格无正加速） |
| 0 < 极速 < 200 km/h | 42 | **9** | 余低速机/无人机/直升机（`ah_56a`、`fokker_d7`、`po-2`、`uav_*` 等） |
| 极速 > 3,000 km/h | 1 | **0** | — |
| 最大极速 | 3,062.6（`b_66b`） | **2,884.8**（`mig_23mla`） | 仍顶 Mach 2.5 网格上限 |
| SEP > 200 m/s | 44 | **29** | 余 F-16 / MiG-23 / MiG-25 / MiG-29 / Yak-141 等加力机（标定问题，见 9.5） |
| SEP > 400 m/s | 6 | **0** | — |
| 最大 SEP | 941.0（`yak_141`） | **303.5**（`mig_23mla`） | 量级已恢复正常 |
| 质量 = 0 | 1 | 1 | `i_180_event03`（保留旧 JSON） |
| 燃油 = 0 | 8 | **1** | 7 架老格式燃油键（`fau-1`、`lagg-3-1` 等）已回退 `MaxFuelMass`；余 `i_180_event03` |
| 喷气 thrust_max0 = 0 | 44 | **0** | 老格式引擎回退后全部读到推力 |
| 全部 thrust_max0 = 0 | 240 | 811 | 修复后 = 810 架螺旋桨（按设计恒为 0）+ `i_180_event03` |

### 9.4 Wiki 43 机回归（修复前 → 修复后）

| 指标 | 修复前 | 修复后 |
|---|---:|---:|
| 样本数 | 43 | 43 |
| 误差 ≤10% | 20（46.5%） | **28（65.1%）** |
| 误差 ≤20% | 31（72.1%） | **36（83.7%）** |
| 中位数误差 | -2.14% | **+0.87%** |
| 均值误差 | +3.56% | **-3.56%** |
| 最大绝对误差 | +192.2%（`b_66b`） | **-62.3%**（`wyvern_s4`） |

明细见 `data/audit_wiki_43_before.csv` / `data/audit_wiki_43_after.csv`。主要改善（修复前 → 修复后误差）：

| 机型 | 修复前 | 修复后 | 机型 | 修复前 | 修复后 |
|---|---:|---:|---|---:|---:|
| `b_66b` | +192.2% | **+11.1%** | `me-262a-1a` | -14.4% | **+8.1%** |
| `a5m4` | +91.8% | **+7.1%** | `f-80` | -23.5% | **+1.8%** |
| `a_4n` | +90.2% | **+2.9%** | `mig-9` | -18.5% | **+1.6%** |
| `yak_141` | +62.0% | -13.7% | `f9f-2` | -14.0% | **+5.8%** |
| `me_264` | +47.5% | **+3.9%** | `he-162a-2` | -18.6% | **+5.6%** |
| `tu_14t` | +14.5% | **+2.2%** | `vampire_fb5` | -0.6% | +8.0% |
| `il_28` | +8.3% | **+4.6%** | `arado-234c-3` | -4.6% | +6.0% |
| `fr_1_fireball` | +9.0% | **-2.3%** | `mirage_3c` | +23.0% | -33.6%² |

² `mirage_3c` 去掉 JATO 重复计数后翻到低估，暴露加力推力不足（P1）；`ka_50` +2.8%→+31.9% 属直升机（模型不适用），`wyvern_s4` -75.5%→-62.3% 属涡桨功率标定（P1）。

### 9.5 遗留 P1 问题（本次未处理）

1. **加力标定（Mode5.ThrustMult / AfterburnerBoost）**：仍未接入。`mirage_f1c` -44.5%（1,236.6 vs Wiki 2,228）、`mirage_3c` -33.6%、`mig-21_bis` -19.4%、`j_10c` -15.6%、`yak_141` -13.7%；反例 `f-4e` +11.7%、`su_27` +6.3%，全局硬乘会过冲，需按机型标定（同 §5.1 结论）。
2. **螺旋桨 / 涡桨功率标定**：整体偏低 5–15% 的问题不变，如 `bf-109f-4` -12.1%、`fw-190a-5` -12.3%、`yak-3` -8.5%、`f4u-1a` -8.3%、`b-29` -7.5%；涡桨更严重（`wyvern_s4` -62.3%，`a2d` +7.7%）。
3. **直升机 / 旋翼机 94 架**：仍按固定翼公式计算，结果无物理意义。修复后 `ah_64d` 227.8（-22.8%）、`mi_24a` 227.8（-32.0%）、`ka_50` 409.0（+31.9%）、`ah_56a` <200。建议在 `metadata` 增加 `rotorcraft: true` 并隐藏固定翼结论，或单独做旋翼模型。
4. **`fau-1`（PVRD）**：老格式回退现在能读到 `Engine0.Main.ThrustMax.ThrustMax0 = 296 kgf`，极速由 0 → 673.8 km/h；但 PVRD 特殊推力语义未单独适配，保持已知例外，不纳入 Wiki 回归结论。
5. **网格与质量假设不变**：15 km 高度上限、Mach 2.5 上限、50% 内油；`mig_23mla` 等仍顶格，SEP>200 的 29 条与加力标定相关。

### 9.6 声明

**本次仅修复 P0 解析/计数缺陷（老格式引擎、推进类型判定、多类型发动机计数、老格式燃油键），未改物理模型标定**——推力/阻力公式、螺旋桨效率、加力增益、网格与质量假设均保持原状。修复后 `data/computed/` 已按新逻辑全量重算（1,233 条），Python 与 `web/compute.js` 结果一致；`data/audit_wiki_43.csv` 保留修复前快照，修复前后对比分别为 `data/audit_wiki_43_before.csv` / `data/audit_wiki_43_after.csv`。数据可用于“同模型内部相对比较”，绝对数值与游戏数据仍有 §9.5 所列系统性偏差。

### 9.7 复审后处置（前端 MachFactor 修复与 dist 重建）

独立复审（`FIX_REVIEW.md`）发现 1 个既有前端 P0：`web/compute.js` 的 `compileMachChannels` 对数组型 `Aerodynamics.MachFactor`（`b6n2`/`b6n2a` 为 `[3,3]`）调用 `float()` 得到 `0.0`，使 `Math.pow(t,0)=1` 直接取 `MultMachMax`，阻力高估、极速偏低 16.1%（`b6n2` JS 490.02 vs Python 584.24 km/h；HEAD 版本同样存在，非本次引入）。已按 `lib/compute.py` 的归一化语义修复脚本（仅改 `compileMachChannels`）：

| 处置 | 结果 |
|---|---|
| `compileMachChannels` 复刻 Python 归一化 | 数组/对象/布尔/非法值 → 不可转换；`MachFactor` 回退 3.0；五字段任一异常则跳过通道 |
| `b6n2` / `b6n2a` Python↔JS 全记录对拍 | 最大相对差 **7.58×10⁻¹⁴**（修复后 JS 极速 584.2386 km/h） |
| 既有真实机回归（me-262a-1a、b_66b、yak_141、ariete、a5m4） | 0 差异（浮点舍入级 ≤3.3×10⁻¹²） |
| 新增回归用例 | `tests/test_cross_js.py` 真实机参数化加入 `b6n2`/`b6n2a`（18 passed）；`tests/test_drag.py` 新增 MachFactor 数组归一化单测（26 passed） |
| 全量测试 | **156 passed**（0 failed / 0 skipped） |
| `bash build.sh` | 已重建 `dist/`：`dist/web/compute.js` 更新为新逻辑，`dist/web/index.html` 的 `compute.js?v=` 内容哈希同步；`dist/web/manifest.json` 内容不变，`dist/data/` 为 .gitignore 产物不入库 |

复审另提一处 P1（“§9.3 喷气 thrust0=0 修复前应为我 5 架”）经复核不成立：以 `git show HEAD` 旧 `data/computed` 的 `metadata.thrust_max0_kgf` 与 `lib/fmdata` 的主类型交叉统计，修复前主类型为 Jet/Rocket/PVRD 且 `thrust_max0=0` 的机型恰为 **44 架**（即 §4.1 老格式名单：40 架走功率模型 + 3 架零推力喷气 + `fau-1`），§9.3 数字无误。其余 P1（加力缺失、螺旋桨/涡桨标定、直升机、`fau-1`、网格上限、`i_180_event03` 旧记录）维持 §9.5 记录。
