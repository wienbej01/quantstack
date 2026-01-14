#!/bin/bash
#
# Audit wrapper for systemd services
# Tracks service lifecycle, resource usage, and exit codes
#
# Usage: audit_wrapper.sh <service-name> <command> [args...]
#

set -euo pipefail

SERVICE_NAME="${1:-unknown}"
shift

AUDIT_DIR="$HOME/quantstack/logs/audit"
mkdir -p "$AUDIT_DIR"

# Get current date in Manila timezone
DATE=$(TZ=Asia/Manila date +%Y-%m-%d)
AUDIT_LOG="$AUDIT_DIR/audit_${DATE}.jsonl"
HUMAN_LOG="$AUDIT_DIR/audit_${DATE}.log"

# Timestamp function (all three timezones)
log_audit() {
    local event_type="$1"
    local message="$2"
    local severity="${3:-INFO}"
    local context="${4:-null}"
    local metrics="${5:-null}"
    
    local ts_utc=$(date -u +"%Y-%m-%dT%H:%M:%S+00:00")
    local ts_mnl=$(TZ=Asia/Manila date +"%Y-%m-%dT%H:%M:%S%:z")
    local ts_et=$(TZ=America/New_York date +"%Y-%m-%dT%H:%M:%S%:z")
    
    # Build JSON manually to avoid escaping issues
    local json_event="{\"timestamp_utc\":\"$ts_utc\",\"timestamp_mnl\":\"$ts_mnl\",\"timestamp_et\":\"$ts_et\",\"event_type\":\"$event_type\",\"service\":\"$SERVICE_NAME\",\"severity\":\"$severity\",\"message\":\"$message\""
    
    if [ "$context" != "null" ]; then
        json_event="$json_event,\"context\":$context"
    fi
    
    if [ "$metrics" != "null" ]; then
        json_event="$json_event,\"metrics\":$metrics"
    fi
    
    json_event="$json_event}"
    echo "$json_event" >> "$AUDIT_LOG"
    
    # Human-readable format
    local mnl_time=$(TZ=Asia/Manila date +"%Y-%m-%d %H:%M:%S")
    local et_time=$(TZ=America/New_York date +"%H:%M:%S")
    local human_line="[$mnl_time MNL / $et_time ET] [$severity] [$SERVICE_NAME] $event_type: $message"
    
    if [ "$context" != "null" ]; then
        human_line="$human_line | Context: $context"
    fi
    
    if [ "$metrics" != "null" ]; then
        human_line="$human_line | Metrics: $metrics"
    fi
    
    echo "$human_line" >> "$HUMAN_LOG"
}

# Get process metrics
get_metrics() {
    local pid=$1
    
    if [ ! -d "/proc/$pid" ]; then
        echo "null"
        return
    fi
    
    # Memory in MB
    local mem_kb=$(awk '/VmRSS/ {print $2}' /proc/$pid/status 2>/dev/null || echo "0")
    local mem_mb=$(echo "scale=1; $mem_kb / 1024" | bc 2>/dev/null || echo "0")
    
    # CPU usage (approximate)
    local cpu_percent=$(ps -p $pid -o %cpu= 2>/dev/null | tr -d ' ' || echo "0")
    
    echo "{\"memory_mb\":$mem_mb,\"cpu_percent\":$cpu_percent}"
}

# Trap exit
cleanup() {
    local exit_code=$?
    local end_time=$(date +%s)
    local duration=$((end_time - START_TIME))
    
    local context="{\"exit_code\":$exit_code,\"duration_sec\":$duration}"
    
    if [ $exit_code -eq 0 ]; then
        log_audit "SERVICE_STOP" "$SERVICE_NAME stopped successfully" "INFO" "$context"
    else
        log_audit "SERVICE_STOP" "$SERVICE_NAME stopped with error (exit=$exit_code)" "ERROR" "$context"
    fi
    
    exit $exit_code
}

trap cleanup EXIT INT TERM

# Log service start
START_TIME=$(date +%s)
CMD_ESCAPED=$(printf '%s' "$*" | sed 's/"/\\"/g')
START_CONTEXT="{\"command\":\"$CMD_ESCAPED\",\"user\":\"$USER\",\"pwd\":\"$PWD\"}"
log_audit "SERVICE_START" "$SERVICE_NAME starting" "INFO" "$START_CONTEXT"

# Execute command and capture PID
"$@" &
SERVICE_PID=$!

# Log service ready with initial metrics
sleep 1
READY_METRICS=$(get_metrics $SERVICE_PID)
log_audit "SERVICE_READY" "$SERVICE_NAME running (PID=$SERVICE_PID)" "INFO" "null" "$READY_METRICS"

# Wait for process
wait $SERVICE_PID
