#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/jacobw/quantstack"
STATE_DIR="$HOME/.quantstack/ops_checks"
STATE_FILE="$STATE_DIR/state.json"

ROUND="${1:-0}"

export TZ="America/New_York"
NOW_ET="$(date '+%Y-%m-%d %H:%M:%S ET')"

mkdir -p "$STATE_DIR" >/dev/null 2>&1 || true

ensure_user_bus_env() {
  if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
  fi
  if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
  fi
}

ib_gateway_check() {
  local host="${IBKR_GATEWAY_HOST:-127.0.0.1}"
  local port="${IBKR_GATEWAY_PORT:-7494}"
  if command -v ss >/dev/null 2>&1; then
    if ss -ltn "( sport = :${port} )" 2>/dev/null | grep -q ":${port}"; then
      echo "✅ IB Gateway: listening ${host}:${port}"
      return 0
    fi
  fi
  if command -v nc >/dev/null 2>&1; then
    if nc -z -w 1 "$host" "$port" >/dev/null 2>&1; then
      echo "✅ IB Gateway: tcp ok ${host}:${port}"
      return 0
    fi
  fi
  echo "❌ IB Gateway: not listening ${host}:${port}"
  return 1
}

check_and_fix_unit() {
  local scope="$1" unit="$2" pattern="$3"

  local cmd=(systemctl)
  if [[ "$scope" == "user" ]]; then
    ensure_user_bus_env
    cmd+=(--user)
  fi

  local st
  st="$("${cmd[@]}" is-active "$unit" 2>/dev/null || true)"

  if [[ "$st" == "active" ]]; then
    if pgrep -f "$pattern" >/dev/null 2>&1; then
      echo "✅ ${unit}: running"
      return 0
    fi
    echo "❌ ${unit}: active but process missing (${pattern})"
    return 1
  fi

  # Fix: restart only when clearly not active.
  if "${cmd[@]}" restart "$unit" >/dev/null 2>&1; then
    local st2
    st2="$("${cmd[@]}" is-active "$unit" 2>/dev/null || true)"
    if [[ "$st2" == "active" ]] && pgrep -f "$pattern" >/dev/null 2>&1; then
      echo "✅ ${unit}: was ${st}; fixed via restart"
      return 0
    fi
    echo "❌ ${unit}: restart issued but now ${st2}"
    return 1
  fi

  echo "❌ ${unit}: ${st:-inactive}; restart failed"
  return 1
}

db_activity_check() {
  # Use ET date for trades; executions for the last 15 minutes (ibkr_time).
  if ! command -v psql >/dev/null 2>&1; then
    echo "❌ DB Activity: psql not found"
    return 1
  fi

  local et_date="((now() at time zone 'America/New_York')::date)"
  local trades
  trades="$(psql -d trading -U jacobw -t -A -F '|' -c \
    "SELECT COALESCE(system,'unknown')||':'||COUNT(*)::int
     FROM trades
     WHERE (entry_time::timestamptz AT TIME ZONE 'America/New_York')::date = ${et_date}
     GROUP BY 1 ORDER BY 1;" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g' || true)"

  local execs
  execs="$(psql -d trading -U jacobw -t -A -F '|' -c \
    "SELECT COALESCE(system,'unknown')||':'||COUNT(*)::int
     FROM executions
     WHERE ibkr_time > now() - interval '15 minutes'
     GROUP BY 1 ORDER BY 2 DESC LIMIT 5;" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\\+/ /g' || true)"

  if [[ -z "$trades" ]] && [[ -z "$execs" ]]; then
    echo "❌ DB Activity: query failed (no output)"
    return 1
  fi

  echo "✅ DB Activity: trades(${trades:-0}) exec15m(${execs:-0})"
  return 0
}

wal_growth_check() {
  local wal="$ROOT/logs/wal/fills_$(date -u '+%Y%m%d').jsonl"
  if [[ ! -f "$wal" ]]; then
    echo "✅ WAL Growth: no WAL file yet"
    return 0
  fi

  local n
  n="$(wc -l "$wal" | awk '{print $1}' 2>/dev/null || echo 0)"

  local last_n=0
  local has_state=0
  if [[ -f "$STATE_FILE" ]]; then
    has_state=1
    last_n="$(python3 -c "import json;print(json.load(open('$STATE_FILE')).get('wal_lines',0))" 2>/dev/null || echo 0)"
  fi
  local delta=$((n - last_n))

  python3 - <<PY 2>/dev/null || true
import json, os
os.makedirs("${STATE_DIR}", exist_ok=True)
with open("${STATE_FILE}", "w") as f:
    json.dump({"wal_lines": ${n}}, f, indent=2, sort_keys=True)
PY

  if (( has_state == 0 )); then
    echo "✅ WAL Growth: baseline recorded (lines=${n})"
    return 0
  fi

  if (( delta <= 0 )); then
    echo "✅ WAL Growth: stable (lines=${n}, delta=${delta})"
    return 0
  fi
  if (( delta > 5000 )); then
    echo "❌ WAL Growth: growing fast (lines=${n}, +${delta})"
    return 1
  fi
  echo "✅ WAL Growth: ok (lines=${n}, +${delta})"
  return 0
}

send_ntfy() {
  local title="$1" priority="$2" tags="$3" body="$4"
  if ! command -v curl >/dev/null 2>&1; then
    return 0
  fi
  curl -sS --max-time 6 \
    -H "Title: ${title}" \
    -H "Priority: ${priority}" \
    ${tags:+-H "Tags: ${tags}"} \
    -d "$body" \
    "ntfy.sh/jacobw-trading-alerts" >/dev/null 2>&1 || true
}

msg="Ops Check ${ROUND} @ ${NOW_ET}\n"
fail=0
report_lines=()

run_check() {
  local out rc
  out="$("$@")"
  rc=$?
  report_lines+=("$out")
  echo "$out"
  return "$rc"
}

if ! run_check ib_gateway_check; then
  fail=$((fail + 1))
fi

if ! run_check check_and_fix_unit system "l2-scalping.service" "l2_scalping/src/main.py"; then
  fail=$((fail + 1))
fi
if ! run_check check_and_fix_unit system "intraday-paper.service" "paper_trade.py"; then
  fail=$((fail + 1))
fi
if ! run_check check_and_fix_unit user "l2-vwap-reversion.service" "l2_vwap_reversion/src/main.py"; then
  fail=$((fail + 1))
fi

if ! run_check db_activity_check; then
  fail=$((fail + 1))
fi
if ! run_check wal_growth_check; then
  fail=$((fail + 1))
fi

title="✅ Ops Check OK"
priority="default"
tags="white_check_mark"
if (( fail > 0 )); then
  title="⚠️ Ops Check Issues (${fail})"
  priority="high"
  tags="warning,rotating_light"
fi

body="$(printf '%s\n\n%s\n' "$msg" "$(printf '%s\n' "${report_lines[@]}")")"
send_ntfy "$title" "$priority" "$tags" "$body"

if (( fail > 0 )); then
  exit 1
fi
exit 0
