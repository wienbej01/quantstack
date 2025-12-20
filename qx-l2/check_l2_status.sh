#!/bin/bash
echo "=== L2 Collector Status ==="
echo "Process: $(ps aux | grep 'run_collector.py --daemon' | grep -v grep | wc -l) running"
echo "PID: $(ps aux | grep 'run_collector.py --daemon' | grep -v grep | awk '{print $2}')"
echo ""
echo "=== Latest Logs ==="
tail -5 l2_daemon.log
echo ""
echo "=== Data Directory ==="
ls -la data/l2/ 2>/dev/null || echo "No data directory yet"
echo ""
echo "=== Next Collection Window ==="
python3 -c "
from qx_l2 import L2Scheduler, load_config
import sys
sys.path.insert(0, 'src')
config = load_config('configs/default.yaml')
scheduler = L2Scheduler(config)
next_window = scheduler.next_window_start()
if next_window:
    print(f'Next: {next_window.strftime(\"%Y-%m-%d %H:%M:%S %Z\")}')
    import datetime
    now = scheduler.now_local()
    delta = next_window - now
    hours = int(delta.total_seconds() // 3600)
    minutes = int((delta.total_seconds() % 3600) // 60)
    print(f'Time until next window: {hours}h {minutes}m')
"
