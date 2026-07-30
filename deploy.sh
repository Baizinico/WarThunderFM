#!/usr/bin/env bash
# 部署 WT 飞行模型分析器到 Cloudflare Pages
# 用法: bash deploy.sh [project-name]
set -euo pipefail

PROJECT_NAME="${1:-wt-fm-analyzer}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIST_DIR="$ROOT_DIR/dist"

echo "==> 项目: $PROJECT_NAME"
echo "==> 准备部署目录 dist/"

# 重建 dist 目录，保持相对路径结构:
#   dist/index.html        根跳转页 → /web/
#   dist/web/*             应用静态文件 (index.html 从此处获取 manifest.json 与 ../data/raw/*.blkx)
#   dist/data/raw/*.blkx   飞行模型原始数据
rm -rf "$DIST_DIR"
mkdir -p "$DIST_DIR/web" "$DIST_DIR/data/raw"

cp "$ROOT_DIR/web/"* "$DIST_DIR/web/"
cp "$ROOT_DIR/data/raw/"*.blkx "$DIST_DIR/data/raw/" 2>/dev/null || true

# 根跳转页
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

echo "==> dist/ 内容:"
( cd "$DIST_DIR" && find . -type f | sort )

# 确认 wrangler 可用
if ! command -v npx >/dev/null 2>&1; then
  echo "错误: 未找到 npx，请先安装 Node.js (>=18)" >&2
  exit 1
fi

echo "==> 使用 wrangler 部署到 Cloudflare Pages (分支: main)"
cd "$ROOT_DIR"
npx -y wrangler@latest pages deploy "$DIST_DIR" \
  --project-name="$PROJECT_NAME" \
  --branch=main \
  --commit-dirty

echo "==> 部署完成"
echo "    生产地址: https://$PROJECT_NAME.pages.dev/web/"
echo "    (首次部署后可在 Cloudflare 控制台绑定自定义域名)"
