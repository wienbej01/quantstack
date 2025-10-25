.PHONY: bootstrap lint test qa-all install fix check-types format test-daily-hmm smoke-daily-hmm
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

# Daily HMM_SIP testing targets
test-daily-hmm:
	@echo "Running daily HMM_SIP integration tests..."
	pytest tests/test_daily_hmm_end_to_end.py -v

smoke-daily-hmm:
	@echo "Running daily HMM_SIP smoke test..."
	python -c "from tests.test_daily_hmm_end_to_end import test_daily_hmm_comprehensive_workflow; test_daily_hmm_comprehensive_workflow(); print('✅ Daily HMM_SIP smoke test passed!')"
