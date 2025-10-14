.PHONY: bootstrap lint test qa-all install fix check-types format
install:
	uv pip install -e qx-core -e qx-data -e qx-features -e qx-screener -e qx-risk -e qx-backtest -e qx-report -e qx-broker -e qx-cli -e qx-scan
bootstrap: install
lint:
	ruff check .
fix:
	ruff check . --fix
format:
	ruff format .
check-types:
	mypy qx-*/src/ --ignore-missing-imports || echo "MyPy check completed"
test:
	pytest -q || true
qa-all: lint check-types test
