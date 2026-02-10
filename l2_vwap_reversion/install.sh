#!/bin/bash
# Install L2 VWAP Mean Reversion systemd service and timer

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/l2-vwap-reversion.service"
TIMER_FILE="$SCRIPT_DIR/l2-vwap-reversion.timer"

echo "Installing L2 VWAP Mean Reversion service..."

# Copy service and timer files
sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo cp "$TIMER_FILE" /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable timer (auto-start before market open)
sudo systemctl enable l2-vwap-reversion.timer

# Start timer
sudo systemctl start l2-vwap-reversion.timer

echo ""
echo "Installation complete!"
echo ""
echo "Timer status:"
systemctl status l2-vwap-reversion.timer --no-pager || true
echo ""
echo "Next trigger:"
systemctl list-timers l2-vwap-reversion.timer --no-pager || true
echo ""
echo "Commands:"
echo "  Start now:     sudo systemctl start l2-vwap-reversion"
echo "  Stop:          sudo systemctl stop l2-vwap-reversion"
echo "  View logs:     journalctl -u l2-vwap-reversion -f"
echo "  Timer status:  systemctl list-timers l2-vwap-reversion.timer"
