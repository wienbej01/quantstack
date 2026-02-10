#!/bin/bash
# Install Position Monitor systemd services

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Installing position monitor services..."

# Copy service files
sudo cp "$SCRIPT_DIR/position-monitor.service" /etc/systemd/system/
sudo cp "$SCRIPT_DIR/conky-position.service" /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable position-monitor.service
sudo systemctl enable conky-position.service

# Start services
sudo systemctl start position-monitor.service
sudo systemctl start conky-position.service

echo "Services installed. Checking status..."
sleep 2
systemctl status position-monitor.service --no-pager
echo "---"
systemctl status conky-position.service --no-pager
