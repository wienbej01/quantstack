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
    if grep -q "enabled: true" config/strategy.yaml | grep -A1 "mock_data"; then
        echo "WARNING: Mock data is enabled in strategy.yaml"
        echo "Set mock_data.enabled: false before paper trading"
    fi
    
    # Check IBKR port is paper trading
    if grep -q "port: 7496" config/ibkr.yaml; then
        echo "WARNING: IBKR port is set to live trading (7496)"
        echo "Use port 7497 for paper trading"
    fi
    
    echo "✓ Configuration validation complete"
}

# Main menu
case "${1:-menu}" in
    "test")
        echo "Running tests only..."
        run_tests
        ;;
    "validate")
        echo "Validating system..."
        validate_config
        check_ibkr
        run_tests
        ;;
    "run")
        echo "Starting trading system..."
        validate_config
        check_ibkr
        echo "Starting L2 Scalping System..."
        python3 src/main.py --config config
        ;;
    "menu"|*)
        echo "L2 Scalping System Commands:"
        echo "  ./run.sh test      - Run tests only"
        echo "  ./run.sh validate  - Validate system and connections"
        echo "  ./run.sh run       - Start trading system"
        echo ""
        echo "Before paper trading:"
        echo "1. Ensure TWS/Gateway is running on port 7497"
        echo "2. Set mock_data.enabled: false in config/strategy.yaml"
        echo "3. Run './run.sh validate' to check everything"
        echo "4. Run './run.sh run' to start trading"
        ;;
esac
