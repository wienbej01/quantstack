#!/bin/bash
# Disable zombie l2-watchdog service
# This service is trying to monitor l2-collector which has been retired

set -e

echo "=== Disabling Zombie l2-watchdog Service ==="
echo ""
echo "Background: l2-watchdog monitored l2-collector service."
echo "l2-collector was retired (L2 collection moved into l2-scalping)."
echo "l2-watchdog script was moved to archive but service not disabled."
echo "Result: Service restarting infinitely (5700+ times)."
echo ""

# Check current status
echo "Current status:"
systemctl status l2-watchdog.service --no-pager || true
echo ""

# Stop the service
echo "Stopping l2-watchdog.service..."
sudo systemctl stop l2-watchdog.service
echo "✓ Stopped"
echo ""

# Disable the service
echo "Disabling l2-watchdog.service..."
sudo systemctl disable l2-watchdog.service
echo "✓ Disabled"
echo ""

# Remove the unit file
echo "Removing systemd unit file..."
sudo rm -f /etc/systemd/system/l2-watchdog.service
echo "✓ Removed /etc/systemd/system/l2-watchdog.service"
echo ""

# Reload systemd
echo "Reloading systemd daemon..."
sudo systemctl daemon-reload
echo "✓ Reloaded"
echo ""

# Verify
echo "Verification:"
systemctl list-units --all | grep l2-watchdog || echo "✓ l2-watchdog no longer in systemd"
echo ""

echo "=== Cleanup Complete ==="
echo ""
echo "l2-watchdog service has been disabled and removed."
echo "This service is no longer needed as l2-collector has been retired."
