#!/usr/bin/env bash
# 重启恢复检查钩子（verify.sh 调用；退出码 0=通过，非 0=不通过）。
# 固定步骤：起服务 → 写入带唯一标记的记录 → 杀进程并确认退出 → 再起 → 按标记读回比对。
# 约束：不碰真实数据（QINGHE_DATA_DIR 指向临时目录）；不调真实模型（只用 /api/load，不需要 Key）；收尾清干净。
set -uo pipefail

cd "$(dirname "$0")/../backend"
PY=".venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
PORT="${QINGHE_RC_PORT:-8099}"
BASE="http://127.0.0.1:$PORT"
TMP_DATA="$(mktemp -d)"
MARK="RESTART-CHECK-$RANDOM-$RANDOM"
PID=""

log() { printf '%s\n' "$*"; }
fail() { log "不通过：$*"; exit 1; }

cleanup() {
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null
    wait "$PID" 2>/dev/null
  fi
  rm -rf "$TMP_DATA"
}
trap cleanup EXIT

if command -v lsof >/dev/null 2>&1 && lsof -i ":${PORT}" >/dev/null 2>&1; then
  fail "端口 ${PORT} 已被占用，不杀他人进程。"
fi

start_server() {
  QINGHE_DATA_DIR="$TMP_DATA" "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
    >"$TMP_DATA/uvicorn.log" 2>&1 &
  PID=$!
  local i
  for i in $(seq 1 40); do
    if curl -sf "$BASE/api/state" >/dev/null 2>&1; then return 0; fi
    if ! kill -0 "$PID" 2>/dev/null; then fail "服务未能启动，日志见 $TMP_DATA/uvicorn.log"; fi
    sleep 0.3
  done
  fail "服务启动超时。"
}

stop_server() {
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    kill "$PID" 2>/dev/null
    wait "$PID" 2>/dev/null
  fi
  PID=""
}

# 1) 起服务
log "1) 启动服务（临时数据目录：${TMP_DATA}）"
start_server
log "   服务已就绪。"

# 2) 写入带唯一标记的记录（载入任务表 + 聊天，不调模型）
TASK_FILE="$TMP_DATA/task.csv"
CHAT_FILE="$TMP_DATA/chat.csv"
printf '编号,工作项,责任人,当前安排,截止日,验收条件\n%s,重启检查任务,林川,开发中,9 月 20 日,可恢复\n' "$MARK" > "$TASK_FILE"
printf '编号,时间,来源,内容\nC-01,9 月 20 日 10:00,项目负责人,重启检查\n' > "$CHAT_FILE"
log "2) 写入带标记记录（${MARK}）"
LOAD_RESP="$(curl -sf -F "task_csv=@$TASK_FILE" -F "chat_csv=@$CHAT_FILE" "$BASE/api/load")" \
  || fail "载入接口失败。"
log "   载入响应：$LOAD_RESP"

# 3) 杀进程并确认退出
log "3) 停止服务进程。"
stop_server
sleep 0.6
if curl -sf "$BASE/api/state" >/dev/null 2>&1; then fail "服务进程未退出。"; fi
log "   已退出。"

# 4) 再起服务
log "4) 再次启动服务。"
start_server

# 5) 读回比对
log "5) 按标记读回。"
STATE="$(curl -sf "$BASE/api/state")" || fail "读状态接口失败。"
printf '%s' "${STATE}" | grep -q "${MARK}" || fail "重启后未读到标记 ${MARK}。"
log "   读到标记，恢复成功。"

log "通过：写入的记录在进程重启后仍可读回。"
exit 0
