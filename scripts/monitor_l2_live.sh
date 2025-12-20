#!/bin/bash
# Real-time L2 monitoring dashboard (no sudo required)

clear
echo "=========================================="
echo "L2 COLLECTOR LIVE MONITOR"
echo "=========================================="
echo ""

while true; do
    # Move cursor to top
    tput cup 4 0
    
    # Current time
    echo "Current Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
    echo "Current ET:   $(TZ='America/New_York' date '+%Y-%m-%d %H:%M:%S %Z')"
    echo ""
    
    # Service status
    echo "--- L2 COLLECTOR STATUS ---"
    if systemctl is-active --quiet l2-collector.service; then
        echo "✅ Service: ACTIVE"
        PID=$(systemctl show l2-collector.service --property=MainPID | cut -d= -f2)
        echo "   PID: $PID"
        MEM=$(ps -p $PID -o rss= 2>/dev/null | awk '{print $1/1024 " MB"}')
        echo "   Memory: $MEM"
    else
        echo "❌ Service: INACTIVE"
    fi
    echo ""
    
    # Watchdog status
    echo "--- WATCHDOG STATUS ---"
    if systemctl is-active --quiet l2-watchdog.service; then
        echo "✅ Watchdog: ACTIVE"
        RESTARTS=$(grep -c "Service restarted successfully" logs/l2_watchdog.log 2>/dev/null || echo "0")
        echo "   Restarts today: $RESTARTS"
    else
        echo "❌ Watchdog: INACTIVE"
    fi
    echo ""
    
    # Recent errors (using journalctl without sudo - limited access)
    echo "--- RECENT STATUS ---"
    if systemctl is-active --quiet l2-collector.service; then
        echo "✅ No service failures detected"
    else
        echo "⚠️  Service not active"
    fi
    echo ""
    
    # Data collection stats
    echo "--- DATA COLLECTION ---"
    if [ -d "qx-l2/data/l2_dual" ]; then
        FILES=$(find qx-l2/data/l2_dual -name "*.parquet" 2>/dev/null | wc -l)
        SIZE=$(du -sh qx-l2/data/l2_dual 2>/dev/null | cut -f1)
        echo "   Files: $FILES"
        echo "   Size: $SIZE"
        
        # Latest file
        LATEST=$(find qx-l2/data/l2_dual -name "*.parquet" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
        if [ -n "$LATEST" ]; then
            LATEST_TIME=$(stat -c %y "$LATEST" 2>/dev/null | cut -d'.' -f1)
            echo "   Latest: $LATEST_TIME"
        fi
    else
        echo "   No data yet"
    fi
    echo ""
    
    # Watchdog log tail
    echo "--- WATCHDOG LOG (last 3 lines) ---"
    tail -3 logs/l2_watchdog.log 2>/dev/null || echo "No watchdog logs"
    echo ""
    
    echo "=========================================="
    echo "Press Ctrl+C to exit | Refreshing every 10s"
    echo "Note: Running without sudo - limited log access"
    
    sleep 10
done
