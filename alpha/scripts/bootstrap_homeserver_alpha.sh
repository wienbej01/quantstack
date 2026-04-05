#!/usr/bin/env bash
set -euo pipefail

ROOT="${HOME}/trading/repos/quantstack"
BRANCH="${1:-alpha-homeserver-dev}"
VENV="${ROOT}/.venv"
PYTHON_BIN="${VENV}/bin/python"
PIP_BIN="${VENV}/bin/pip"

cd "${ROOT}"

echo "[1/6] Sync branch ${BRANCH}"
git fetch origin
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

echo "[2/6] Ensure virtualenv"
if [[ ! -d "${VENV}" ]]; then
  python3 -m venv "${VENV}"
fi
"${PYTHON_BIN}" -m pip install -U pip setuptools wheel >/dev/null
"${PIP_BIN}" install -r requirements.txt >/dev/null

echo "[3/6] Verify alpha runtime assets"
test -d "${HOME}/quantstack/data/l2/l2_maximum/raw"
test -d "${HOME}/quantstack-v2/data/l2/l2_maximum/raw"
test -d "${HOME}/intraday_stack/data/daily_sip"
test -d "${ROOT}/alpha/output/polygon_ohlcv_cache"
test -d "${ROOT}/alpha/models"

echo "[4/6] Asset summary"
printf "legacy_l2_raw_dates="
find "${HOME}/quantstack/data/l2/l2_maximum/raw" -maxdepth 1 -type d -name 'date=*' | wc -l
printf "v2_l2_raw_dates="
find "${HOME}/quantstack-v2/data/l2/l2_maximum/raw" -maxdepth 1 -type d -name 'date=*' | wc -l
printf "sip_dates="
find "${HOME}/intraday_stack/data/daily_sip" -maxdepth 1 -type d -name 'date=*' | wc -l
printf "polygon_cache_files="
find "${ROOT}/alpha/output/polygon_ohlcv_cache" -maxdepth 1 -type f | wc -l
printf "alpha_model_files="
find "${ROOT}/alpha/models" -maxdepth 1 -type f | wc -l

echo "[5/6] Smoke test alpha CLI"
"${PYTHON_BIN}" alpha/scripts/run_hypothesis_test.py --help >/dev/null

echo "[6/6] Branch status"
git status --short --branch

cat <<'EOF'

Homeserver alpha workspace is ready.

Suggested next commands:
  cd ~/trading/repos/quantstack
  source .venv/bin/activate
  python alpha/scripts/run_hypothesis_test.py --hypothesis ml --start 2026-03-09 --end 2026-03-20 --bar-source polygon
EOF
