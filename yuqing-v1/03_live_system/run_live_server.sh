#!/bin/bash
# 启动实时大屏服务端（路线 B：SSE 秒级推送 + 真实平台自动调度）
# 等价于：LIVE_PLATFORM_ENABLED=1 ./start.sh
cd "$(dirname "$0")"
export LIVE_PLATFORM_ENABLED="${LIVE_PLATFORM_ENABLED:-1}"
PY="${LIVE_PYTHON:-python3}"
if ! "$PY" -c "import sys" >/dev/null 2>&1; then
  PY="/Users/Zhuanz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
echo "使用 Python: $PY（LIVE_PLATFORM_ENABLED=1）"
exec "$PY" server.py "$@"
