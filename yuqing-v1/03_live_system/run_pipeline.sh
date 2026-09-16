#!/bin/bash
# 实时流水线：采集 → 清洗入事实表 → 重算 data.js
# 用法：
#   ./run_pipeline.sh                                # 需已设置 ATOMIC_XLSX
#   ./run_pipeline.sh "路径/Excel数据库改造示例.xlsx"
#   ATOMIC_XLSX=路径 DASH_OUT=路径 ./run_pipeline.sh
set -euo pipefail
cd "$(dirname "$0")"

PY="${LIVE_PYTHON:-python3}"
if ! "$PY" -c "import sys" >/dev/null 2>&1; then
  PY="/Users/Zhuanz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
fi

XLSX="${ATOMIC_XLSX:-}"
if [ -z "$XLSX" ] && [ -n "${1:-}" ]; then
  XLSX="$1"
fi
if [ -z "$XLSX" ]; then
  echo "未指定原子化工作簿：请设置 ATOMIC_XLSX 或传入路径参数" >&2
  exit 1
fi

mkdir -p logs
LOG="logs/pipeline.log"

# 防重入：上一次任务没结束就跳过本次（mkdir 锁，兼容 macOS / Linux）
LOCK_DIR="${TMPDIR:-/tmp}/yuqing-pipeline.lockdir"
if [ -d "$LOCK_DIR" ]; then
  if [ -n "$(find "$LOCK_DIR" -mmin +30 2>/dev/null)" ]; then
    # 超过 30 分钟的锁视为上次异常退出残留，清理后继续
    rmdir "$LOCK_DIR" 2>/dev/null || true
  else
    echo "$(date '+%F %T') 上一次任务未结束，跳过本次" >> "$LOG"
    exit 0
  fi
fi
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "$(date '+%F %T') 上一次任务未结束，跳过本次" >> "$LOG"
  exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

{
  echo "=== $(date '+%F %T') 开始（工作簿: ${XLSX}） ==="
  echo "[1/3] collect.py"
  "$PY" collect.py
  echo "[2/3] clean_and_append.py"
  "$PY" clean_and_append.py --xlsx "$XLSX"
  echo "[3/3] build_data.py --atomic"
  "$PY" "../01_code_docs/scripts/build_data.py" --atomic "$XLSX"
  echo "=== $(date '+%F %T') 完成 ==="
} 2>&1 | tee -a "$LOG"
