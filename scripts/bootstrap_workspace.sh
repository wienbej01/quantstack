#!/usr/bin/env bash
set -euo pipefail
ROOT="$HOME/quantstack"
mkdir -p "$ROOT"
cd "$ROOT"

# venv
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip wheel

# core dev deps
pip install uv duckdb pyarrow pandas pydantic pyyaml typer rich jsonschema jinja2 nbconvert matplotlib ruff mypy pytest pytest-cov pre-commit

# packages (dirs only for now)
for pkg in qx-core qx-data qx-features qx-screener qx-risk qx-backtest qx-report qx-broker qx-cli qx-scan; do
  mkdir -p "$ROOT/$pkg/src/${pkg//-/_}"
  touch "$ROOT/$pkg/src/${pkg//-/_}/__init__.py"
done

# shared config
cat > "$ROOT/.editorconfig" <<'EC'
root = true
[*]
end_of_line = lf
insert_final_newline = true
charset = utf-8
indent_style = space
indent_size = 2
EC

cat > "$ROOT/.gitignore" <<'GI'
.venv/
__pycache__/
*.pyc
runs/
reports/
GI

cat > "$ROOT/.env.example" <<'ENV'
# Example environment variables
QX_DATA_ROOT=/home/jacobw/gcs-mount/gold
ENV

cat > "$ROOT/ruff.toml" <<'RUFF'
line-length = 100
target-version = "py311"
[lint]
select = ["E","F","I","UP","B","C4","SIM","PL"]
ignore = []
RUFF

cat > "$ROOT/mypy.ini" <<'MYPY'
[mypy]
python_version = 3.11
warn_return_any = True
warn_unused_ignores = True
warn_redundant_casts = True
disallow_untyped_defs = True
ignore_missing_imports = True
MYPY

cat > "$ROOT/pytest.ini" <<'PYT'
[pytest]
testpaths = tests
addopts = -q
PYT

cat > "$ROOT/.pre-commit-config.yaml" <<'PC'
repos:
  - repo: https://github.com/psf/black
    rev: 24.8.0
    hooks: [{id: black}]
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.2
    hooks: [{id: ruff}]
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks: [{id: mypy}]
PC

cat > "$ROOT/Makefile" <<'MK'
.PHONY: bootstrap lint test qa-all install
install:
	uv pip install -e qx-core -e qx-data -e qx-features -e qx-screener -e qx-risk -e qx-backtest -e qx-report -e qx-broker -e qx-cli -e qx-scan
bootstrap: install
lint:
	ruff check .
test:
	pytest -q || true
qa-all: lint test
MK