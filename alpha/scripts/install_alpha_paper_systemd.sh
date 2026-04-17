#!/bin/bash
# Install alpha ML paper/shadow user-systemd units.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
USER_SYSTEMD="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$USER_SYSTEMD"

units=(
    systemd/alpha-ml-paper-trading.service
    systemd/alpha-ml-paper-trading.timer
    systemd/alpha-ml-paper-trading-stop.service
    systemd/alpha-ml-paper-trading-stop.timer
)

for relpath in "${units[@]}"; do
    install -m 0644 "$ROOT/$relpath" "$USER_SYSTEMD/$(basename "$relpath")"
done

systemctl --user daemon-reload
systemctl --user enable --now alpha-ml-paper-trading.timer alpha-ml-paper-trading-stop.timer

echo "Installed alpha ML paper user-systemd units into $USER_SYSTEMD"
systemctl --user list-timers | grep -E "alpha-ml-paper" || true

