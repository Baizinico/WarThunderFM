# War Thunder 飞行模型 3D 加速度分析

基于 [gszabi99/War-Thunder-Datamine](https://github.com/gszabi99/War-Thunder-Datamine) 拆包数据的
War Thunder 飞机加速度分析工具：

- 后端（Python）解析 `.blkx` 飞行模型，计算高度 × 马赫加速度网格、最优飞行剖面、最佳爬升路线
- 前端（浏览器端）实时加载原始数据并重算，Plotly 3D 曲面可视化
- 多机对比：关键指标对比表 + 曲线叠加 + 归一化雷达图（前后端算法一致，交叉验证）
- 部署为 Cloudflare Workers 静态站点

> 数据由网络拆包计算获得，并不一定 100% 准确。

## 目录结构

```
analyze.py             CLI 主入口（download / compute / compare / run / serve / list）
lib/
  compute.py           物理引擎：ISA 大气、推力插值、阻力模型、加速度网格
  compare.py           多机对比：指标提取、对比数据构建、校验、终端对比表
  downloader.py        .blkx 下载（jsdelivr CDN，含缓存与重试）
  schema.py            JSON Schema 校验、record 构建与读写
web/                   前端（index.html + compute.js + compare.js + app.js + style.css）
  compute.js           lib/compute.py 的浏览器端移植（与后端共享公式）
  compare.js           lib/compare.py 的浏览器端移植（与后端共享对比口径）
data/
  raw/                 原始 .blkx 数据
  computed/            预计算 JSON（legacy，前端实际在浏览器端实时计算）
scripts/               一次性探索/校验脚本（需在项目根目录运行）
tests/                 pytest 单元测试 + JS/Python 交叉验证
```

## 快速开始

```bash
pip install -r requirements.txt

# 下载飞行模型
python analyze.py download j_10c mig-21

# 计算加速度网格
python analyze.py compute j_10c
python analyze.py compute bf-109f-4 --no-afterburner --fuel-pct 0.3
python analyze.py compute f-16a --mass 12000

# 下载 + 计算（并发，默认 4 线程）
python analyze.py run --workers 8 j_10c su-27

# 多机对比（关键指标表 + 曲线叠加 + 雷达图数据）
python analyze.py compare j_10c su_27 mig-21_bis
python analyze.py compare j_10c su_27 --fuel-pct 0.3 --payload 2000
python analyze.py compare j_10c su_27 --no-save      # 只打印对比表

# 启动本地预览
python analyze.py serve

# 列出数据集
python analyze.py list
```

### 多机对比

对比既可在命令行完成，也可在网页里交互完成：

- **CLI**：`python analyze.py compare <机型1> <机型2> [机型...]` 会按统一参数（燃油 / 挂载 / 加力）
  现场计算每架飞机，打印等宽对比表（`*` 标记每行最优值），并把完整对比数据写入
  `data/computed/compare_<机型>.json`。缺少原始数据时会退回使用 `data/computed/<机型>.json`
  预计算结果（`--from-computed` 可强制只读预计算结果）。
- **网页**：当前飞机的燃油 / 挂载参数会随「加入对比」一起入队（最多 4 架），
  队列满 2 架后自动生成三块对比视图：
  1. **关键指标对比表** —— 飞行质量、静推力、推重比、最大加速度、最大爬升率、实用升限、
     极速（Mach / TAS），每行最优值高亮；
  2. **曲线叠加** —— 可切换「最佳爬升路线（高度→马赫）」「爬升率（高度→SEP）」
     「定高加速（马赫→加速度，可选高度层）」；
  3. **综合能力雷达** —— 关键指标在本次对比集合内归一化到 0-100，表示相对强弱。
  「同步参数」按钮会把当前燃油 / 挂载参数套用到队列中所有飞机并重算，保证对比公平。

对比口径与推导逻辑在 `lib/compare.py` 与 `web/compare.js` 中逐字段保持一致，
由 `tests/test_compare_cross_js.py` 用 Node.js 交叉验证。

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

`tests/test_cross_js.py` 使用 Node.js 验证 `web/compute.js` 与 `lib/compute.py`
输出一致（含真实 `.blkx` 数据端到端对比），防止双端算法失同步。Node.js 缺失时该模块自动跳过。

`tests/test_compare.py` 覆盖对比指标口径、最优值方向、雷达归一化与 `compare` 子命令；
`tests/test_compare_cross_js.py` 验证 `web/compare.js` 与 `lib/compare.py` 的对比数据逐字段一致。

## 构建与部署

```bash
bash build.sh                     # 生成 dist/（自动注入静态资源内容 hash 防缓存）
bash deploy.sh [project-name]     # 部署到 Cloudflare Pages
# 或
npx wrangler deploy               # 部署为 Cloudflare Workers（_worker.js + assets）
```
