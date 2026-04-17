#!/bin/bash
# Alpha ML paper trading launcher for homeserver user-systemd.
set -euo pipefail

ROOT="/home/jacobw/trading/repos/quantstack"
cd "$ROOT"

RUNTIME_ENV="/home/jacobw/.config/quantstack/runtime.env"
if [ -f "$RUNTIME_ENV" ]; then
    # shellcheck disable=SC1090
    source "$RUNTIME_ENV"
fi

export TZ="America/New_York"
export PATH="$ROOT/.venv/bin:$PATH"
export PYTHONPATH="$ROOT/alpha:$ROOT:${PYTHONPATH:-}"
export SIP_DAILY_ROOT="${SIP_DAILY_ROOT:-/home/jacobw/quantstack-v2/data/daily_sip}"

current_hour=$(date +%H)
current_min=$(date +%M)
if [ "$current_hour" -lt 9 ] || [ "$current_hour" -gt 16 ]; then
    echo "Outside market hours ($current_hour:$current_min ET) - exiting"
    exit 0
fi
if [ "$current_hour" -eq 9 ] && [ "$current_min" -lt 31 ]; then
    echo "Before alpha paper start time (09:31 ET) - exiting"
    exit 0
fi

SIP_FILE="$SIP_DAILY_ROOT/date=$(date +%F)/sip_universe.json"
if [ ! -f "$SIP_FILE" ]; then
    echo "SIP universe not found: $SIP_FILE - exiting"
    exit 0
fi

mkdir -p "$ROOT/alpha/output/paper_trading/action_ranker/logs"

LOG_FILE="$ROOT/alpha/output/paper_trading/action_ranker/logs/alpha_ml_paper_trade.log"

echo "Starting alpha ML paper trading for $(date +%F)"
exec "$ROOT/.venv/bin/python" -u "$ROOT/alpha/scripts/run_alpha_ml_paper_trading.py" \
    --date "$(date +%F)" \
    --loop \
    --interval-seconds "${ALPHA_PAPER_INTERVAL_SECONDS:-60}" \
    --max-symbols "${ALPHA_PAPER_MAX_SYMBOLS:-3}" \
    --daily-top-k "${ALPHA_PAPER_DAILY_TOP_K:-4}" \
    --max-longs-per-day "${ALPHA_PAPER_MAX_LONGS_PER_DAY:-2}" \
    --min-score "${ALPHA_PAPER_MIN_SCORE:-0.5}" \
    --execution-mode "${ALPHA_PAPER_EXECUTION_MODE:-ibkr_paper}" \
    --exit-mode "${ALPHA_PAPER_EXIT_MODE:-time_only}" \
    --execution-quantity "${ALPHA_PAPER_EXECUTION_QUANTITY:-10}" \
    --execution-stop-bps "${ALPHA_PAPER_EXECUTION_STOP_BPS:-50}" \
    --execution-target-bps "${ALPHA_PAPER_EXECUTION_TARGET_BPS:-5000}" \
    --execution-max-action-age-seconds "${ALPHA_PAPER_MAX_ACTION_AGE_SECONDS:-180}" \
    --ibkr-host "${IBKR_HOST:-127.0.0.1}" \
    --ibkr-port "${IBKR_PORT:-7494}" \
    --ibkr-client-id "${ALPHA_PAPER_IBKR_CLIENT_ID:-410}" \
    --ibkr-account-id "${ALPHA_PAPER_IBKR_ACCOUNT_ID:-}" \
    --order-ref-prefix "${ALPHA_PAPER_ORDER_REF_PREFIX:-ALPHA_ML}" \
    --sip-root "$SIP_DAILY_ROOT" \
    --bar-source polygon
