#!/bin/bash
# Monitor the full improved features rebuild

LOG_FILE="/tmp/build_improved_features.log"
PROCESS_NAME="build_intraday_features_improved"

echo "=== MONITORING FULL IMPROVED FEATURES REBUILD ==="
echo "Started: $(date)"
echo "Process: $(pgrep -f $PROCESS_NAME | head -1)"
echo "Log: $LOG_FILE"
echo ""

# Function to show progress
show_progress() {
    echo "=== PROGRESS UPDATE $(date) ==="
    
    # Check if process is running
    PID=$(pgrep -f $PROCESS_NAME | head -1)
    if [ -z "$PID" ]; then
        echo "❌ Process not running"
        return 1
    else
        echo "✅ Process running (PID: $PID)"
    fi
    
    # Show last 10 lines of log
    echo ""
    echo "--- Last 10 log lines ---"
    tail -10 $LOG_FILE 2>/dev/null || echo "Log file not found"
    
    # Check for completion indicators
    if grep -q "IMPROVED FEATURES COMPLETE" $LOG_FILE 2>/dev/null; then
        echo ""
        echo "🎉 BUILD COMPLETE!"
        return 0
    fi
    
    # Check for errors
    if grep -q "Error\|Failed\|Exception" $LOG_FILE 2>/dev/null; then
        echo ""
        echo "⚠️  Errors detected in log"
    fi
    
    echo ""
    echo "--- Memory usage ---"
    ps -p $PID -o pid,ppid,cmd,%mem,%cpu 2>/dev/null || echo "Process info not available"
    
    echo ""
    return 2
}

# Monitor every 5 minutes
while true; do
    show_progress
    STATUS=$?
    
    if [ $STATUS -eq 0 ]; then
        echo "Build completed successfully!"
        break
    elif [ $STATUS -eq 1 ]; then
        echo "Process stopped. Checking final status..."
        if grep -q "IMPROVED FEATURES COMPLETE" $LOG_FILE 2>/dev/null; then
            echo "✅ Build completed successfully!"
        else
            echo "❌ Build failed or was interrupted"
        fi
        break
    fi
    
    echo "Sleeping 5 minutes..."
    sleep 300
done

echo ""
echo "=== FINAL STATUS ==="
echo "End time: $(date)"

# Show final results if available
if [ -f "$LOG_FILE" ]; then
    echo ""
    echo "--- Final log summary ---"
    grep -E "(COMPLETE|ERROR|rows|symbols|Features)" $LOG_FILE | tail -10
fi
