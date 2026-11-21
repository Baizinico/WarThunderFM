# FIX_REVIEW.md — WarThunderFM 引擎/质量解析修复 · 独立复审

复审者：reviewer（独立重跑，不信任其他 agent 报告；只读审查，未改任何业务代码/数据，不 git commit）。
环境：`/tmp/wtvenv2/bin/python` (Python 3.14.0, pytest 9.2.0, numpy 2.4.3)、Node v24.11.1；cwd 仓库根。

## 结论：需修（P0 1 个，属既有网页端缺陷；Python/数据侧可接受）

- **Python/数据侧修复通过全部独立复核**：`lib/fmdata.py` 纯标准库；`_build_thrust_model` 用逐实例 T0 求和；`schema/analyze/_compute_all` 质量与推力口径一致；1,233 条 `data/computed` 与当前代码逐样本 0 差；测试真绿无 skip。
- **网页侧 `web/compute.js` 与 Python 在 2 架真实机型上偏差 16.1%**（b6n2/b6n2a，>1e-6 P0 阈值）。根因为既有 drag/mach 代码对数组型 `MachFactor` 的处理差异，**非本次修复引入**（HEAD 版本同样存在），但违反 FIX_SPEC §7「JS/Python 逐条对应」验收，须修或明确记录。未自行改代码，交 root 决策。

## 独立验证命令与关键数字

1. `git status --short` = 1242 M（1233 `data/computed/*.json` + 9 个源码/测试文件）+ 9 ??（AUDIT.md、FIX_SPEC.md、lib/fmdata.py、scripts/audit_wiki.py、tests/test_fmdata.py、3 个 audit CSV、.claude/）；无意外文件；`git diff --stat` 1242 files。
2. `grep -n numpy lib/fmdata.py` → 仅第 1 行 docstring，无第三方 import（452 行）。
3. `lib/compute.py`：jet 分支 `"t0_n": total_thrust0_kgf(fm) * G`（逐实例累加各自 ThrustMax0，仅总和 0 时回退），prop 分支 `n_engines=count_engines(fm)`；模型键名未变；`git diff -U0` 无 drag/optimal/climb hunk。
4. `lib/schema.py` build_record 用 `mass_info` + `thrust_summary`；`analyze.py:134-140 _mass_info` 委托 fmdata，调用点 208/305 全覆盖；`scripts/_compute_all.py:44` 同源。
5. `node --check web/compute.js` → 通过。
6. `/tmp/wtvenv2/bin/python -m pytest tests -q` → **150 passed in 1.35s**（0 fail 0 skip）；`pytest tests/test_cross_js.py -v` → **14 passed 全 PASSED 无 skip**（含 5 架真实机全记录对拍）。
7. 1,233 条全量重算（`compute_accel_grid(fm, empty+0.5*max_fuel, afterburner)`）：966,672 网格点 **max|Δaccel|=0.0**；metadata empty/fuel/flight/thrust_max0 与 fmdata **0 差**；全部 samples=784、无 NaN；喷气 thrust0=0 共 **0** 个（fau-1=296，PVRD 例外）；props_on_jet=**0**、jets_on_prop=**0**。
8. Node↔Python 5 机对拍（me-262a-1a、b_66b、yak_141、ariete、a5m4）：全部一致，最大相对差 3.3e-12；极速 934.8 / 1163.8 / 1593.4 / 1137.2 / 478.8 km/h。
9. FIX_SPEC §9 表 9 机与 AUDIT §9.2 数值一致（另 4 机：fiat_g91_y 1102.5、me_264 539.0、fr_1_fireball 637.3、night_fighter_mk_2 902.9）。
10. 老燃油键 7 架全部回退 `Mass.MaxFuelMass`（`MaxFuelMass0=None`）：night_fighter_mk_2 = **7,915 kg**（原 7,265，+8.9%）；fau-1 1,860；lagg-3-1/29、lagg_gu-37 2,814；mig_3_series_pod 3,101.5。
11. AUDIT §9.3 复算（新数据）：kind 810/424、极速=0 **2**、0<v<200 **9**、SEP>200 **29**、SEP>400 **0**、最大极速 2,884.75、最大 SEP 303.55、全部 thrust0=0 **811**——与文档一致；HEAD 旧数据重放 716/518、20/42/44/6、3,062.63、940.96 亦一致。
12. AUDIT §9.4 Wiki CSV 复算：before ≤10% 20/31、中位 -2.15、均值 +3.56、最大 +192.2；after 28/36（65.1%/83.7%）、中位 +0.87、均值 -3.56、最大 -62.3——与文档一致。
13. `scripts/audit_wiki.py --offline` 可用：重建 43 行，与 `data/audit_wiki_43_after.csv` 逐字段 0 差异。

## 问题分级

**P0（必须修，未自行改动）**
- **b6n2 / b6n2a：`web/compute.js` 与 `lib/compute.py` 极速 490.02 vs 584.24 km/h（16.1%）**。根因：`data/raw/b6n2.blkx` 的 `Aerodynamics.MachFactor=[3,3]`；`lib/compute.py:481-489` 遇 list 取 3.0；`web/compute.js:619` `float([3,3])` → `Number([3,3])||0` = 0.0，阻力倍率在 MachCrit 处直接跳到 MultMachMax。补丁实验（Array.isArray→3.0）后 JS=584.2385766277334 与 Python 完全相同。HEAD 旧版 JS/Python 对 b6n2 为 618.3 vs 817.9，**同一既有缺陷**；`tests/test_cross_js.py` 真实机用例未覆盖「老格式平坦气动 + 数组 MachFactor」。建议：修 JS 并由 root 决定是否补 cross-js 用例；本次仅记录。

**P1（记录）**
- AUDIT §9.3「喷气 thrust0=0：44→0」有误：修复前实际 **5** 架（fau-1、fiat_g91_y、fiat_g91_ys、i_180_event03、p_59a；44 是 §4.1 老格式机数）；修复后按 1,233 条为 0，含 i_180 的 1,234 条为 1。
- 数值归因：最大极速 mig_23ml 与 mig_23mla 同为 2,884.7501（AUDIT 归因 mig_23mla 可接受）；舍入级：fr_1_fireball -2.2 vs -2.3、mirage_3c +22.9 vs +23.0、Wiki 中位 -2.15 vs -2.14。
- `dist/`（git 跟踪的部署产物）未重建：`dist/web/compute.js` 仍是 HEAD 旧逻辑（无 totalThrust0Kgf/engineInstances），`dist/data/computed` 为旧 1,234 条；`build.sh`/`deploy.sh` 会重建，CI 不构建 dist；**直接 wrangler deploy 会发布旧前端**，部署前必须 `bash build.sh` 并提交/更新 dist。
- AUDIT §9.5 已列口径类 P1（加力未接、螺旋桨偏低、直升机 94 架、fau-1 例外、15km/Mach2.5/50% 内油假设），本次修复范围外，维持。

## 未覆盖风险
- 1,234 架 JS 全量对拍仅 b6n2/b6n2a 不一致，但其他 aero 数组字段（MachCrit/Mult* 等）未逐一穷举类型差异，残留风险低。
- `tests/test_cross_js.py` 真实机仅 5 架，未覆盖每类真实机（老格式/多类型/垂直升力）；建议后续扩充真实机回归集。
- dist 发布链路无 CI 校验，存在旧产物上线风险。
- `data/computed/i_180_event03.json` 为既有旧零质量记录（metadata 全 0、784 samples），AUDIT §9.1/§9.3 已注明，`data/_compute_failures.txt` 记录失败原因；未覆盖，符合规格。

## 复审后处置（root，2026-11-20）

- **P0 已修复**：`web/compute.js` 的 `compileMachChannels` 已按 `lib/compute.py` 语义归一化（数组/对象/布尔/非法值 → 不可转换；`MachFactor` 回退 3.0；通道五字段任一异常则跳过）。`b6n2`/`b6n2a` Python↔JS 全记录最大相对差 **7.58×10⁻¹⁴**，修复后 JS 极速 584.2386 km/h（Python 584.2386）；既有 5 架真实机回归 0 差异。
- **回归用例已补**：`tests/test_cross_js.py` 真实机参数化加入 `b6n2`/`b6n2a`（18 passed）；`tests/test_drag.py` 新增 MachFactor 数组归一化单测（26 passed）。全量 **156 passed**（0 fail / 0 skip）。
- **P1「dist 未重建」已处置**：`bash build.sh` 重建，`dist/web/compute.js` 与 `dist/web/index.html` 缓存哈希已更新，`dist/data/` 为 .gitignore 产物。
- **P1「§9.3 喷气 thrust0=0 应为 5 架」经复核不成立**：以 `git show HEAD` 旧数据 + `lib/fmdata` 主类型交叉统计，修复前 Jet/Rocket/PVRD 且 `thrust_max0=0` 恰为 **44 架**（即 §4.1 老格式名单），AUDIT §9.3 维持原值。
- 其余 P1（加力标定、螺旋桨/涡桨、直升机 94 架、`fau-1`、15 km/Mach 2.5/50% 内油假设、`i_180_event03` 旧记录）维持记录，不在本次 P0 范围。
