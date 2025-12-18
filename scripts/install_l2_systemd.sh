#!/bin/bash
set -e

echo "Installing L2 Collector systemd service and timer (Daily Daemon Mode)..."

# Copy service files
sudo cp systemd/l2-collector.service /etc/systemd/system/
sudo cp systemd/l2-collector.timer /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start timer
sudo systemctl enable l2-collector.timer
sudo systemctl start l2-collector.timer

echo "L2 Collector systemd setup complete!"
echo ""
echo "Commands:"
echo "  Status:    sudo systemctl status l2-collector.timer"
echo "  Logs:      sudo journalctl -u l2-collector.service -f"
echo "  Stop:      sudo systemctl stop l2-collector.timer"
echo "  Restart:   sudo systemctl restart l2-collector.timer"
echo "  Manual:    sudo systemctl start l2-collector.service"
echo ""
echo "Schedule: Daily at 9:25 AM ET (Mon-Fri)"
echo "Mode: Daemon - runs all day, collects during 7 windows"
