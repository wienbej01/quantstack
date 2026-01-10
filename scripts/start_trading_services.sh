#!/bin/bash
# Start trading services sequentially, confirming each connection before proceeding

set -e

GATEWAY_PORT=7497
TIMEOUT=45

check_client_connected() {
    local client_id=$1
    local timeout=$2
    local elapsed=0
    
    while [ $elapsed -lt $timeout ]; do
        if ss -an | grep ":$GATEWAY_PORT" | grep ESTAB | grep -q .; then
            # Check Gateway UI would be better, but we check if new ESTAB appeared
            sleep 2
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

wait_for_service() {
    local service=$1
    local expected_clients=$2
    local timeout=$3
    
    echo "Starting $service..."
    systemctl start "$service"
    
    echo "Waiting for connection (up to ${timeout}s)..."
    sleep 5  # Initial wait for service startup
    
    local elapsed=5
    while [ $elapsed -lt $timeout ]; do
        local current=$(ss -an | grep ":$GATEWAY_PORT" | grep ESTAB | wc -l)
        current=$((current / 2))  # Each connection shows twice (client + server side)
        
        if [ "$current" -ge "$expected_clients" ]; then
            echo "✓ $service connected ($current clients total)"
            return 0
        fi
        sleep 2
        elapsed=$((elapsed + 2))
    done
    
    echo "✗ $service failed to connect within ${timeout}s"
    return 1
}

echo "=========================================="
echo "Starting Trading Services Sequentially"
echo "=========================================="

# Check Gateway is running
if ! ss -an | grep -q ":$GATEWAY_PORT.*LISTEN"; then
    echo "ERROR: Gateway not listening on port $GATEWAY_PORT"
    echo "Start Gateway first and login"
    exit 1
fi

echo "✓ Gateway listening on port $GATEWAY_PORT"
echo ""

# Count initial connections
INITIAL=$(ss -an | grep ":$GATEWAY_PORT" | grep ESTAB | wc -l)
INITIAL=$((INITIAL / 2))
echo "Initial connected clients: $INITIAL"
echo ""

# Start l2-scalping first (2 connections: client 20 + 21)
if ! systemctl is-active --quiet l2-scalping; then
    wait_for_service "l2-scalping" $((INITIAL + 2)) $TIMEOUT || exit 1
else
    echo "l2-scalping already running"
fi
echo ""

# Update count
CURRENT=$(ss -an | grep ":$GATEWAY_PORT" | grep ESTAB | wc -l)
CURRENT=$((CURRENT / 2))

# Start l2-collector (1 connection: client 521)
if ! systemctl is-active --quiet l2-collector; then
    wait_for_service "l2-collector" $((CURRENT + 1)) $TIMEOUT || exit 1
else
    echo "l2-collector already running"
fi
echo ""

# Update count
CURRENT=$(ss -an | grep ":$GATEWAY_PORT" | grep ESTAB | wc -l)
CURRENT=$((CURRENT / 2))

# Start intraday-paper (2 connections: client 998 preflight + 11 trading)
if ! systemctl is-active --quiet intraday-paper; then
    wait_for_service "intraday-paper" $((CURRENT + 2)) $TIMEOUT || exit 1
else
    echo "intraday-paper already running"
fi
echo ""

# Final status
echo "=========================================="
echo "Final Status"
echo "=========================================="
FINAL=$(ss -an | grep ":$GATEWAY_PORT" | grep ESTAB | wc -l)
FINAL=$((FINAL / 2))
ZOMBIES=$(ss -an | grep ":$GATEWAY_PORT" | grep CLOSE-WAIT | wc -l)

echo "Connected clients: $FINAL"
echo "Zombie connections: $ZOMBIES"
echo ""

systemctl is-active l2-scalping l2-collector intraday-paper

echo ""
echo "✓ All services started successfully"
