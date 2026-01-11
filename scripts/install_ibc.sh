#!/bin/bash
# Install IBC (IBController) into ./ibc for automated IBKR Gateway login.

set -euo pipefail

DEST_DIR="/home/jacobw/quantstack/ibc"
API_URL="https://api.github.com/repos/IbcAlpha/IBC/releases/latest"
LOCAL_ZIP="${IBC_ZIP_PATH:-$DEST_DIR/IBCLinux.zip}"

mkdir -p "$DEST_DIR"

if ! command -v unzip >/dev/null 2>&1; then
    echo "ERROR: unzip not installed."
    exit 1
fi

TMP_ZIP="$(mktemp)"
if [ -f "$LOCAL_ZIP" ]; then
    cp "$LOCAL_ZIP" "$TMP_ZIP"
else
    API_JSON="$(mktemp)"
    if ! curl -fSL -o "$API_JSON" "$API_URL"; then
        echo "ERROR: failed to fetch release metadata from $API_URL"
        echo "Option: download manually to $LOCAL_ZIP and re-run."
        exit 1
    fi

    DOWNLOAD_URL="$(python3 - <<'PY' "$API_JSON"
import json
import sys

with open(sys.argv[1], "r") as handle:
    data = json.load(handle)

for asset in data.get("assets", []):
    name = asset.get("name", "")
    if name.startswith("IBCLinux-") and name.endswith(".zip"):
        print(asset.get("browser_download_url", ""))
        raise SystemExit(0)
raise SystemExit(1)
PY
)"
    rm -f "$API_JSON"

    if [ -z "$DOWNLOAD_URL" ]; then
        echo "ERROR: failed to resolve IBCLinux download URL from $API_URL"
        echo "Option: download manually to $LOCAL_ZIP and re-run."
        exit 1
    fi

    if ! curl -fSL -o "$TMP_ZIP" "$DOWNLOAD_URL"; then
        echo "ERROR: failed to download IBC from $DOWNLOAD_URL"
        echo "Option: download manually to $LOCAL_ZIP and re-run."
        exit 1
    fi
fi

unzip -o "$TMP_ZIP" -d "$DEST_DIR"
rm -f "$TMP_ZIP"

chmod +x "$DEST_DIR"/*.sh "$DEST_DIR"/*/*.sh

echo "IBC installed in $DEST_DIR"
echo "Next: create $DEST_DIR/IBController.ini with your credentials."
