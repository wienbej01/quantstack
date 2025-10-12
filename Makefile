.PHONY: bootstrap lint test qa-all install
install:
	uv pip install -e qx-core -e qx-data -e qx-features -e qx-screener -e qx-risk -e qx-backtest -e qx-report -e qx-broker -e qx-cli -e qx-scan
bootstrap: install
lint:
	ruff check .
test:
	pytest -q || true
qa-all: lint test
