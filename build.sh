#!/usr/bin/env bash
# 构建脚本：将源文件整理为 Cloudflare Pages 可部署的 dist/ 目录
# 结构:
#   dist/index.html        根跳转页 → /web/
#   dist/web/*             应用静态文件 (index.html 入口，引用 ../data/raw/*.blkx)
#   dist/data/raw/*.blkx   飞行模型原始数据
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"

rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR/web" "$DIST_DIR/data/raw"

# 复制应用静态文件
cp "$ROOT_DIR/web/"* "$DIST_DIR/web/"

# 复制飞行模型原始数据 (.blkx)
cp "$ROOT_DIR/data/raw/"*.blkx "$DIST_DIR/data/raw/" 2>/dev/null || true

# 根路径跳转页（访问 / 时自动跳转到 /web/）
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

echo "构建完成: $DIST_DIR"
