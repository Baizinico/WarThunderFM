#!/usr/bin/env bash
# 构建脚本：生成 Cloudflare Worker 可托管的 dist/ 静态资源目录
# 用法: bash build.sh
# 结构:
#   dist/index.html        根跳转页 → 302 到 /web/
#   dist/web/*            应用静态文件（入口 web/index.html）
#   dist/data/raw/*.blkx  飞行模型原始数据（前端通过 ../data/raw/ 加载）
#   dist/data/computed/*.json  预计算加速度数据
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR/web" "$DIST_DIR/data/raw" "$DIST_DIR/data/computed"

# 复制应用静态文件
cp "$ROOT_DIR/web/"* "$DIST_DIR/web/"

# 复制飞行模型原始数据（.blkx）
shopt -s nullglob
blkx_files=("$ROOT_DIR/data/raw/"*.blkx)
if [ ${#blkx_files[@]} -gt 0 ]; then
  cp "${blkx_files[@]}" "$DIST_DIR/data/raw/"
fi

# 复制预计算加速度数据（.json）
json_files=("$ROOT_DIR/data/computed/"*.json)
if [ ${#json_files[@]} -gt 0 ]; then
  cp "${json_files[@]}" "$DIST_DIR/data/computed/"
fi

# 根路径占位页（Worker 的 _worker.js 会对 / 做 302 重定向，
# 这里仍放一份 index.html 作为无 Worker 环境下的降级）
cat > "$DIST_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url=web/">
  <title>WT 飞行模型分析器</title>
</head>
<body>
  正在跳转至 <a href="web/">应用首页</a>...
</body>
</html>
EOF

echo "==> 构建完成: $DIST_DIR"
echo "==> 文件清单:"
( cd "$DIST_DIR" && find . -type f | sort )
