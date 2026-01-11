#!/bin/bash
# Wait until IBKR Gateway is listening before allowing dependent services.

set -euo pipefail

HOST="${IBKR_GATEWAY_HOST:-127.0.0.1}"
PORT="${IBKR_GATEWAY_PORT:-7497}"
TIMEOUT="${IBKR_GATEWAY_WAIT_TIMEOUT:-300}"
STABLE_SLEEP="${IBKR_GATEWAY_STABLE_SLEEP:-15}"

start_ts="$(date +%s)"

while true; do
    if ss -ltn 2>/dev/null | grep -q ":${PORT}"; then
        sleep "$STABLE_SLEEP"
        echo "Gateway listening on ${HOST}:${PORT}"
        exit 0
    fi

    now_ts="$(date +%s)"
    elapsed=$((now_ts - start_ts))
    if [ "$elapsed" -ge "$TIMEOUT" ]; then
        echo "Timeout waiting for gateway on ${HOST}:${PORT}"
        exit 1
    fi
    sleep 2
done
