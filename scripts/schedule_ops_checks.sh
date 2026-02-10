#!/usr/bin/env bash
set -euo pipefail

ROOT="/home/jacobw/quantstack"
SCRIPT="$ROOT/scripts/ops_check_and_fix.sh"

if ! command -v systemd-run >/dev/null 2>&1; then
  echo "systemd-run not found; cannot schedule checks."
  exit 1
fi

cd "$ROOT"

for i in 1 2 3 4; do
  mins=$((30 * i))
  unit="ops-check-${mins}m"
  delay="${mins}m"
  echo "Scheduling ${unit} in ${delay}..."
  systemd-run \
    --user \
    --unit="${unit}" \
    --on-active="${delay}" \
    --property=Type=oneshot \
    --property=WorkingDirectory="${ROOT}" \
    "${SCRIPT}" "${i}"
done

echo ""
echo "Scheduled. View with:"
echo "  systemctl --user list-timers --all | rg 'ops-check-'"
