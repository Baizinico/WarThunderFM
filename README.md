# War Thunder 飞行模型 3D 加速度分析

基于 [gszabi99/War-Thunder-Datamine](https://github.com/gszabi99/War-Thunder-Datamine) 拆包数据的
War Thunder 飞机加速度分析工具：

- 后端（Python）解析 `.blkx` 飞行模型，计算高度 × 马赫加速度网格、最优飞行剖面、最佳爬升路线
- 前端（浏览器端）实时加载原始数据并重算，Plotly 3D 曲面可视化
- 部署为 Cloudflare Workers 静态站点

> 数据由网络拆包计算获得，并不一定 100% 准确。

## 目录结构

```
analyze.py             CLI 主入口（download / compute / run / serve / list）
lib/
  compute.py           物理引擎：ISA 大气、推力插值、阻力模型、加速度网格
  downloader.py        .blkx 下载（jsdelivr CDN，含缓存与重试）
  schema.py            JSON Schema 校验、record 构建与读写
web/                   前端（index.html + compute.js + app.js + style.css）
  compute.js           lib/compute.py 的浏览器端移植（与后端共享公式）
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

# 启动本地预览
python analyze.py serve

# 列出数据集
python analyze.py list
```

## 测试

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

`tests/test_cross_js.py` 使用 Node.js 验证 `web/compute.js` 与 `lib/compute.py`
输出一致（含真实 `.blkx` 数据端到端对比），防止双端算法失同步。Node.js 缺失时该模块自动跳过。

## 构建与部署

```bash
bash build.sh                     # 生成 dist/（自动注入静态资源内容 hash 防缓存）
bash deploy.sh [project-name]     # 部署到 Cloudflare Pages
# 或
npx wrangler deploy               # 部署为 Cloudflare Workers（_worker.js + assets）
```
