#!/usr/bin/env bash
# 本机阶段 2 走查：生成隔离演示数据并在 8000 启动后端（托管 frontend/dist）。
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/outputs/phase2"
mkdir -p "$OUT"
cd "$ROOT"
if command -v cygpath >/dev/null 2>&1; then
  DB="$(cygpath -w "$OUT/demo.db")"
else
  DB="$OUT/demo.db"
fi
DATABASE_PATH="$DB" PYTHONUTF8=1 python scripts/seed_phase2_demo.py
exec python "$OUT/serve_backend.py"