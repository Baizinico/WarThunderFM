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

# 自动 cache-busting：把 index.html 中静态资源的 ?v=手动版本号替换为内容 hash
# （源码中的 ?v=N 仅作占位；构建时注入 md5，保证资源更新后浏览器必定重新拉取）
for asset in compute.js compare.js app.js style.css; do
  if [ -f "$ROOT_DIR/web/$asset" ]; then
    hash=$(md5sum "$ROOT_DIR/web/$asset" | cut -d' ' -f1 | cut -c1-10)
    sed -i "s/$asset?v=[0-9]*/$asset?v=$hash/g" "$DIST_DIR/web/index.html"
    echo "==> cache-busting: $asset?v=$hash"
  fi
done

# manifest.json 由 update_manifest 生成，构建时同样注入内容 hash（app.js 中引用）
if [ -f "$DIST_DIR/web/manifest.json" ]; then
  mhash=$(md5sum "$DIST_DIR/web/manifest.json" | cut -d' ' -f1 | cut -c1-10)
  sed -i "s/manifest.json?v=[0-9a-zA-Z]*/manifest.json?v=$mhash/" "$DIST_DIR/web/app.js"
  echo "==> cache-busting: manifest.json?v=$mhash"
fi

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
