#!/bin/bash
# L2 Scalping System - Setup and Run Script

set -e

echo "=========================================="
echo "L2 Scalping System Setup"
echo "=========================================="

# Create necessary directories
mkdir -p logs data

# Set up Python path
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Install pytz if not available
check_pytz() {
    python3 -c "import pytz" 2>/dev/null || {
        echo "Installing pytz..."
        pip3 install --user pytz
    }
}

# Function to check IBKR connection
check_ibkr() {
    echo "Checking IBKR connection..."
    python3 -c "
from ib_insync import IB
try:
    ib = IB()
    ib.connect('127.0.0.1', 7497, clientId=999, timeout=5)
    print('✓ IBKR Paper Trading connection OK')
    ib.disconnect()
except Exception as e:
    print('✗ IBKR connection failed:', e)
    print('Please ensure TWS/Gateway is running on port 7497')
    exit(1)
"
}

# Function to check SIP data
check_sip() {
    echo "Checking SIP data availability..."
    python3 -c "
from src.data.sip_integration import load_daily_sip_symbols
symbols = load_daily_sip_symbols()
if symbols:
    print(f'✓ SIP data available: {len(symbols)} symbols')
    print(f'  Top 3: {symbols[:3]}')
else:
    print('⚠ No SIP data found - will use fallback symbols')
"
}

# Function to run tests
run_tests() {
    echo "Running system tests..."
    cd tests
    python3 test_system.py
    cd ..
}

# Function to validate configuration
validate_config() {
    echo "Validating configuration..."
    
    # Check mock data is disabled for paper trading
    python3 - <<'PY'
from pathlib import Path

path = Path("config/strategy.yaml")
if not path.exists():
    raise SystemExit(0)

lines = path.read_text().splitlines()
mock_block = False
enabled_true = False
for line in lines:
    stripped = line.strip()
    if stripped.startswith("mock_data:"):
        mock_block = True
        continue
    if mock_block and stripped and not stripped.startswith("#") and ":" in stripped:
        key, value = [x.strip() for x in stripped.split(":", 1)]
        if key == "enabled" and value.lower() == "true":
            enabled_true = True
            break
        if key not in {"enabled", "update_frequency_hz", "symbols"}:
            break

if enabled_true:
    print("WARNING: Mock data is enabled in strategy.yaml")
    print("Set mock_data.enabled: false before paper trading")
PY
    
    # Check IBKR port is paper trading
    if grep -q "port: 7496" config/ibkr.yaml; then
        echo "WARNING: IBKR port is set to live trading (7496)"
        echo "Use port 7497 for paper trading"
    fi
    
    echo "✓ Configuration validation complete"
}

# Function to install systemd service
install_service() {
    echo "Installing systemd service..."
    sudo cp l2-scalping.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable l2-scalping
    echo "✓ Service installed. Use 'sudo systemctl start l2-scalping' to start"
}

# Main menu
case "${1:-menu}" in
    "test")
        echo "Running tests only..."
        check_pytz
        run_tests
        ;;
    "validate")
        echo "Validating system..."
        check_pytz
        validate_config
        check_sip
        check_ibkr
        run_tests
        ;;
    "run")
        echo "Starting trading system..."
        check_pytz
        validate_config
        check_sip
        check_ibkr
        echo "Starting L2 Scalping System..."
        python3 src/main.py --config config
        ;;
    "install")
        echo "Installing as system service..."
        install_service
        ;;
    "menu"|*)
        echo "L2 Scalping System Commands:"
        echo "  ./run.sh test      - Run tests only"
        echo "  ./run.sh validate  - Validate system and connections"
        echo "  ./run.sh run       - Start trading system"
        echo "  ./run.sh install   - Install as systemd service"
        echo ""
        echo "Systemd service commands:"
        echo "  sudo systemctl start l2-scalping    - Start service"
        echo "  sudo systemctl stop l2-scalping     - Stop service"
        echo "  sudo systemctl status l2-scalping   - Check status"
        echo "  journalctl -u l2-scalping -f        - View logs"
        echo ""
        echo "Before paper trading:"
        echo "1. Ensure TWS/Gateway is running on port 7497"
        echo "2. Set mock_data.enabled: false in config/strategy.yaml"
        echo "3. Run './run.sh validate' to check everything"
        echo "4. Run './run.sh run' to start trading"
        ;;
esac
