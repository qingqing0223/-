#!/bin/bash
# 启动实时动态态势感知系统（自动选择可用 Python）
cd "$(dirname "$0")"
PY="${LIVE_PYTHON:-python3}"
if ! "$PY" -c "import sys" >/dev/null 2>&1; then
  PY="/Users/Zhuanz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi
echo "使用 Python: $PY"
exec "$PY" server.py "$@"
