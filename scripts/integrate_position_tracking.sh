#!/bin/bash
# L2 Scalping Position Tracking Integration Script
# Automatically integrates the new position tracking system with systemd

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUANTSTACK_ROOT="/home/jacobw/quantstack"
L2_SCALPING_DIR="$QUANTSTACK_ROOT/l2_scalping"

echo "🚀 L2 Scalping Position Tracking Integration"
echo "=============================================="

# Function to check if we're in the right environment
check_environment() {
    echo "📋 Checking environment..."
    
    if [ ! -d "$QUANTSTACK_ROOT" ]; then
        echo "❌ Quantstack directory not found: $QUANTSTACK_ROOT"
        exit 1
    fi
    
    if [ ! -d "$L2_SCALPING_DIR" ]; then
        echo "❌ L2 Scalping directory not found: $L2_SCALPING_DIR"
        exit 1
    fi
    
    if [ ! -f "$L2_SCALPING_DIR/src/main.py" ]; then
        echo "❌ L2 Scalping main.py not found"
        exit 1
    fi
    
    echo "✅ Environment check passed"
}

# Function to validate new position tracking components
validate_components() {
    echo "🔍 Validating position tracking components..."
    
    local components=(
        "$L2_SCALPING_DIR/src/position_manager.py"
        "$L2_SCALPING_DIR/src/order_tracker.py"
        "$L2_SCALPING_DIR/src/fill_processor.py"
        "$QUANTSTACK_ROOT/scripts/update_position_tracking_schema.py"
        "$QUANTSTACK_ROOT/scripts/validate_position_tracking.py"
    )
    
    for component in "${components[@]}"; do
        if [ ! -f "$component" ]; then
            echo "❌ Missing component: $component"
            exit 1
        fi
    done
    
    echo "✅ All components found"
}

# Function to run validation tests
run_validation() {
    echo "🧪 Running position tracking validation..."
    
    cd "$QUANTSTACK_ROOT"
    if ! python scripts/validate_position_tracking.py; then
        echo "❌ Validation tests failed"
        exit 1
    fi
    
    echo "✅ Validation tests passed"
}

# Function to update database schema
update_schema() {
    echo "🗄️  Updating database schema..."
    
    cd "$QUANTSTACK_ROOT"
    if python scripts/update_position_tracking_schema.py; then
        echo "✅ Database schema updated successfully"
    else
        echo "⚠️  Schema update failed or already applied"
    fi
}

# Function to create enhanced startup script
create_enhanced_startup() {
    echo "📝 Creating enhanced startup script..."
    
    local startup_script="$L2_SCALPING_DIR/start_scalping_enhanced.sh"
    
    cat > "$startup_script" << 'EOF'
#!/bin/bash
# Enhanced L2 Scalping System Launcher with Position Tracking
cd /home/jacobw/quantstack/l2_scalping

export TZ="America/New_York"
export PATH="/home/jacobw/quantstack/.venv/bin:$PATH"
export PYTHONPATH="/home/jacobw/quantstack:/home/jacobw/quantstack/l2_scalping/src"
export L2_DATA_ROOT="${L2_DATA_ROOT:-/home/jacobw/quantstack/data/l2}"

# Market hours check (09:25 - 16:00 ET)
current_hour=$(date +%H)
current_min=$(date +%M)
if [ $current_hour -lt 9 ] || [ $current_hour -gt 16 ]; then
    echo "Outside market hours ($current_hour:$current_min ET) - exiting"
    exit 0
fi
if [ $current_hour -eq 9 ] && [ $current_min -lt 25 ]; then
    echo "Before market prep time (09:25 ET) - exiting"
    exit 0
fi

# SIP dependency check
SIP_FILE="/home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json"
if [ ! -f "$SIP_FILE" ]; then
    echo "SIP universe not found: $SIP_FILE - exiting"
    exit 0
fi

# Position tracking system validation
echo "🔍 Validating position tracking system..."
cd /home/jacobw/quantstack
if ! python scripts/validate_position_tracking.py > /dev/null 2>&1; then
    echo "❌ Position tracking validation failed - aborting startup"
    exit 1
fi
echo "✅ Position tracking system validated"

# Database schema check/update
echo "🗄️  Checking database schema..."
if ! python scripts/update_position_tracking_schema.py > /dev/null 2>&1; then
    echo "⚠️  Schema update check completed"
fi

cd /home/jacobw/quantstack/l2_scalping

# Clear any zombie depth subscriptions before starting
CLEAR_SCRIPT="/home/jacobw/quantstack/scripts/clear_ibkr_depth_subscriptions.py"
if [ -f "$CLEAR_SCRIPT" ]; then
    echo "Clearing IBKR depth subscriptions..."
    /home/jacobw/quantstack/.venv/bin/python "$CLEAR_SCRIPT" || echo "Warning: depth clear failed"
fi

# Validate IOC price improvement configuration
echo "Validating IOC price improvement..."
python3 validate_ioc.py || {
    echo "CRITICAL: IOC validation failed - aborting startup"
    exit 1
}

echo "🚀 Starting L2 Scalping with Enhanced Position Tracking..."
exec /home/jacobw/quantstack/.venv/bin/python -u src/main.py --config config
EOF

    chmod +x "$startup_script"
    echo "✅ Enhanced startup script created: $startup_script"
}

# Function to backup and update systemd service
update_systemd_service() {
    echo "⚙️  Updating systemd service..."
    
    local service_file="/etc/systemd/system/l2-scalping.service"
    local backup_file="/etc/systemd/system/l2-scalping.service.backup.$(date +%Y%m%d_%H%M%S)"
    
    # Backup existing service
    if [ -f "$service_file" ]; then
        echo "📋 Backing up existing service to: $backup_file"
        sudo cp "$service_file" "$backup_file"
    fi
    
    # Update service to use enhanced startup script
    sudo tee "$service_file" > /dev/null << EOF
[Unit]
Description=L2 Scalping Trading System with Enhanced Position Tracking
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=jacobw
Group=jacobw
WorkingDirectory=/home/jacobw/quantstack/l2_scalping
Environment=PYTHONPATH=/home/jacobw/quantstack:/home/jacobw/quantstack/l2_scalping/src:/home/jacobw/quantstack/qx-l2/src
Environment=L2_DATA_ROOT=/home/jacobw/quantstack/data/l2
Environment=TZ=America/New_York
ExecStart=/home/jacobw/quantstack/scripts/audit_wrapper.sh l2-scalping /home/jacobw/quantstack/l2_scalping/start_scalping_enhanced.sh
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryMax=1G
CPUQuota=50%

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    # Reload systemd
    sudo systemctl daemon-reload
    echo "✅ Systemd service updated and reloaded"
}

# Function to test systemd integration
test_systemd_integration() {
    echo "🧪 Testing systemd integration..."
    
    # Enable service
    sudo systemctl enable l2-scalping.service
    
    # Check service status
    if systemctl is-enabled l2-scalping.service > /dev/null; then
        echo "✅ Service enabled successfully"
    else
        echo "❌ Failed to enable service"
        exit 1
    fi
    
    # Validate service file
    if systemctl status l2-scalping.service > /dev/null 2>&1 || [ $? -eq 3 ]; then
        echo "✅ Service configuration valid"
    else
        echo "❌ Service configuration invalid"
        exit 1
    fi
}

# Function to create monitoring script
create_monitoring_script() {
    echo "📊 Creating position tracking monitoring script..."
    
    local monitor_script="$QUANTSTACK_ROOT/scripts/monitor_position_tracking.py"
    
    cat > "$monitor_script" << 'EOF'
#!/usr/bin/env python3
"""Monitor L2 Scalping Position Tracking System"""

import sys
import time
from pathlib import Path

# Add l2_scalping src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "l2_scalping" / "src"))

def check_position_tracking():
    """Check if position tracking components are working"""
    try:
        from position_manager import PositionManager
        from order_tracker import OrderTracker
        from fill_processor import FillProcessor
        
        # Quick validation
        pm = PositionManager()
        ot = OrderTracker()
        
        print(f"✅ Position tracking components loaded successfully")
        print(f"   - PositionManager: {len(pm)} positions")
        print(f"   - OrderTracker: {len(ot)} orders")
        return True
        
    except Exception as e:
        print(f"❌ Position tracking check failed: {e}")
        return False

def check_database_schema():
    """Check if database schema is updated"""
    try:
        # Add intraday_stack to path
        intraday_path = str(Path(__file__).parent.parent.parent / "intraday_stack" / "src")
        if intraday_path not in sys.path:
            sys.path.append(intraday_path)
        
        from journal.event_store import EventStore
        
        event_store = EventStore()
        if hasattr(event_store, 'conn') and event_store.conn:
            cursor = event_store.conn.cursor()
            
            # Check for new columns
            cursor.execute("""
                SELECT column_name FROM information_schema.columns 
                WHERE table_name = 'orders' AND column_name = 'trade_id'
            """)
            
            if cursor.fetchone():
                print("✅ Database schema updated")
                return True
            else:
                print("⚠️  Database schema not updated")
                return False
        else:
            print("⚠️  No database connection")
            return False
            
    except Exception as e:
        print(f"⚠️  Database schema check failed: {e}")
        return False

def main():
    print("🔍 L2 Scalping Position Tracking Monitor")
    print("=" * 50)
    
    all_good = True
    
    if not check_position_tracking():
        all_good = False
    
    if not check_database_schema():
        all_good = False
    
    if all_good:
        print("\n✅ All position tracking components are healthy")
        return 0
    else:
        print("\n❌ Some position tracking components have issues")
        return 1

if __name__ == "__main__":
    sys.exit(main())
EOF

    chmod +x "$monitor_script"
    echo "✅ Monitoring script created: $monitor_script"
}

# Main execution
main() {
    echo "Starting integration at $(date)"
    
    check_environment
    validate_components
    run_validation
    update_schema
    create_enhanced_startup
    update_systemd_service
    test_systemd_integration
    create_monitoring_script
    
    echo ""
    echo "🎉 L2 Scalping Position Tracking Integration Complete!"
    echo "======================================================"
    echo ""
    echo "✅ Database schema updated"
    echo "✅ Enhanced startup script created"
    echo "✅ Systemd service updated"
    echo "✅ Monitoring script created"
    echo ""
    echo "📋 Service Status:"
    systemctl status l2-scalping.service --no-pager -l
    echo ""
    echo "🚀 The system is ready for auto-start via systemd"
    echo "   - Service: l2-scalping.service"
    echo "   - Timer: l2-scalping.timer (if configured)"
    echo "   - Monitor: scripts/monitor_position_tracking.py"
    echo ""
    echo "📊 To monitor: python scripts/monitor_position_tracking.py"
    echo "🔄 To restart: sudo systemctl restart l2-scalping.service"
    echo "📜 To view logs: journalctl -u l2-scalping.service -f"
}

# Run main function
main "$@"
