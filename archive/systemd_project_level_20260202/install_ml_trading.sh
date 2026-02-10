#!/bin/bash
# Install ML Paper Trading systemd services

set -e

SYSTEMD_DIR="/home/jacobw/quantstack/systemd"
USER_SYSTEMD="$HOME/.config/systemd/user"

mkdir -p "$USER_SYSTEMD"
mkdir -p /home/jacobw/quantstack/logs

# Copy service files
cp "$SYSTEMD_DIR/ml-paper-trading.service" "$USER_SYSTEMD/"
cp "$SYSTEMD_DIR/ml-paper-trading.timer" "$USER_SYSTEMD/"

# Reload systemd
systemctl --user daemon-reload

# Enable and start timer
systemctl --user enable ml-paper-trading.timer
systemctl --user start ml-paper-trading.timer

echo "✅ ML Paper Trading timer installed and started"
echo ""
echo "Commands:"
echo "  systemctl --user status ml-paper-trading.timer  # Check timer status"
echo "  systemctl --user status ml-paper-trading        # Check service status"
echo "  systemctl --user start ml-paper-trading         # Start manually"
echo "  systemctl --user stop ml-paper-trading          # Stop"
echo "  journalctl --user -u ml-paper-trading -f        # View logs"
echo ""
echo "Timer will start trading at 9:25 AM ET on market days"
