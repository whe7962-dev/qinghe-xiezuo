#!/usr/bin/env bash
# 一条命令启动：./run.sh（自动建 .venv、装依赖、起服务）
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3.12 -m venv .venv || python3 -m venv .venv
fi
.venv/bin/python -m pip install -q -r requirements.txt

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "已生成 .env，请先填入 ANTHROPIC_API_KEY 后重新运行。"
  exit 1
fi

echo "==> 启动服务：http://127.0.0.1:8000"
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
