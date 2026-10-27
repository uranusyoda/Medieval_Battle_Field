#!/usr/bin/env bash
# 启动动作索引站（静态服务，根目录必须是仓库根，站点引用了 ../assets）
#   ./tools/serve_site.sh [port]
set -euo pipefail

PORT="${1:-8765}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT"
echo "圣殿骑士 · 动作索引"
echo "  http://127.0.0.1:${PORT}/site/anatomical.html  # 60 骨新版 · 8 套动画与绑定图鉴"
echo "  http://127.0.0.1:${PORT}/site/"
echo "  http://127.0.0.1:${PORT}/site/?grid=1     # 四联对比"
echo "  http://127.0.0.1:${PORT}/site/?clip=jump   # 直接打开某个动作"
echo "Ctrl-C 结束"

exec python3 -m http.server "$PORT" --bind 127.0.0.1
