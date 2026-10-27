#!/bin/bash
# 双击即可打开本地动画展厅；已有项目服务时直接复用。
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
SHOW_PORT=8765
for candidate in 8765 8766 8767 8768; do
  SHOW_URL="http://127.0.0.1:${candidate}/site/anatomical.html"
  if curl -fsS --max-time 2 -o /dev/null "$SHOW_URL" 2>/dev/null; then
    open "$SHOW_URL"
    exit 0
  fi
  if python3 -c 'import socket,sys;s=socket.socket();s.bind(("127.0.0.1",int(sys.argv[1])));s.close()' "$candidate" 2>/dev/null; then
    SHOW_PORT="$candidate"
    break
  fi
done
SHOW_URL="http://127.0.0.1:${SHOW_PORT}/site/anatomical.html"
python3 -m http.server "$SHOW_PORT" --bind 127.0.0.1 &
SHOW_PID=$!
trap 'kill "$SHOW_PID" 2>/dev/null || true' EXIT INT TERM
for attempt in {1..30}; do
  if curl -fsS --max-time 1 -o /dev/null "$SHOW_URL" 2>/dev/null; then
    open "$SHOW_URL"
    echo "动画展厅已打开：$SHOW_URL"
    echo '关闭此窗口或按 Ctrl-C 可停止本次启动的服务。'
    wait "$SHOW_PID"
    exit 0
  fi
  sleep .2
done
echo '服务未能启动，请检查端口，或运行 ./tools/serve_site.sh 9000。'
exit 1
