# E2E Smoke Test

Comprehensive end-to-end testing for QuantStack system validation and CI pipeline verification.

## Overview

The E2E smoke test validates that all core components work together correctly, from data loading through backtesting execution and artifact generation. This ensures system integrity and provides confidence for releases.

## Quick Smoke Test

Fast validation using minimal data slice:

```bash
# Minimal data slice (1 symbol, 1 day)
export GOLD_ROOT="/home/jacobw/gcs-mount/gold"
export SYMBOLS="AAPL"
export DATES="2024-01-02"

# Run entry/exit policy (vwap_revert)
python -m qx_cli.cli entry-ab \
  --gold-root "$GOLD_ROOT" \
  --symbols "$SYMBOLS" \
  --dates "$DATES" \
  --policy vwap_revert \
  --policy-params '{"rvol_min": 1.0}' \
  --max-positions 1 \
  --seed 42

# Verify artifacts created
ls -la runs/
```

## Gold Slice Testing

### 1. Inspect and Create Sample Data

```bash
# Inspect a small AAPL partition and optionally write a tiny sample
python check_gold_and_make_smoke_sample.py \
  --gold-root /home/jacobw/gcs-mount/gold \
  --family bars_1m \
  --symbol AAPL \
  --year 2024 \
  --month 01 \
  --n-files 2 \
  --write-sample \
  --out-dir /tmp/e2e_smoke_from_gold
```

### 2. Run A/B Experiment and Validate Artifacts

```bash
# Run A/B experiment with policy variants
python -m qx_cli exp entry-ab \
  --cfg /tmp/e2e_smoke/config/strategy.yaml \
  --variants /tmp/e2e_smoke/overlays/policy_*.yaml \
  --name smoke_e2e_ab

# Validate experiment artifacts
python test_exp_artifacts.py --runs-root runs
```

## Comprehensive Smoke Test

Full system validation including reproducibility checks:

### Prerequisites

```bash
# Verify environment
python --version  # Should be 3.11 or 3.12
pip list | grep -E "(qx|pandas|pyarrow|duckdb)"
```

### Test Data Validation

```bash
# Test Gold data access
python -c "
import pandas as pd
from qx_data.gold_loader import GoldLoader

loader = GoldLoader('/home/jacobw/gcs-mount/gold')
df = loader.load_bars(['AAPL'], ['2024-01-02'])
print(f'Loaded {len(df)} bars')
print(df.head())
print(f'Data schema: {list(df.columns)}')
"
```

### Feature Engineering Test

```bash
# Test feature computation
python -c "
import pandas as pd
from qx_data.gold_loader import GoldLoader
from qx_features.registry import apply

loader = GoldLoader('/home/jacobw/gcs-mount/gold')
bars = loader.load_bars(['AAPL'], ['2024-01-02'])

features = apply(bars, [{
    'type': 'core_basics',
    'params': {'vwap_window_m': 30, 'rel_vol_window_m': 30}
}])

print(f'Feature columns: {[c for c in features.columns if c.startswith(\"f__\")]}')
print(f'VWAP range: {features[\"f__vwap\"].min():.2f} - {features[\"f__vwap\"].max():.2f}')
"
```

### Policy Execution Test

```bash
# Run test experiment with detailed validation
python -m qx_cli.cli entry-ab \
  --gold-root "/home/jacobw/gcs-mount/gold" \
  --symbols "AAPL,MSFT" \
  --dates "2024-01-02,2024-01-03" \
  --policy vwap_revert \
  --policy-params '{"rvol_min": 1.0, "max_position_bars": 50}' \
  --max-positions 2 \
  --position-size-pct 0.1 \
  --seed 42 \
  --debug
```

### Risk Management Test

```bash
# Test risk constraints
python -m qx_cli.cli entry-ab \
  --gold-root "/home/jacobw/gcs-mount/gold" \
  --symbols "AAPL" \
  --dates "2024-01-02" \
  --policy vwap_revert \
  --risk-params '{"max_risk_frac": 0.02, "atr_mult": 2.0}' \
  --seed 42
```

### Artifact Validation

```bash
# Verify run artifacts
RUN_DIR=$(ls -t runs/ | head -1)
echo "Latest run: $RUN_DIR"

# Check required artifacts
for artifact in signals.parquet trades.parquet metrics.json inputs_checksum.json; do
    if [ -f "runs/$RUN_DIR/$artifact" ]; then
        echo "✅ $artifact exists"
        # Validate schema
        if [[ $artifact == *.parquet ]]; then
            python -c "
import pandas as pd
df = pd.read_parquet('runs/$RUN_DIR/$artifact')
print(f'  Shape: {df.shape}')
print(f'  Columns: {list(df.columns)}')
"
        fi
    else
        echo "❌ $artifact missing"
    fi
done
```

### Reproducibility Test

```bash
# Test reproducibility by running identical experiments
echo "Running reproducibility test..."

# First run
python -m qx_cli.cli entry-ab \
  --gold-root "/home/jacobw/gcs-mount/gold" \
  --symbols "AAPL" \
  --dates "2024-01-02" \
  --policy vwap_revert \
  --seed 42

RUN1=$(ls -t runs/ | head -1)
cp "runs/$RUN1/inputs_checksum.json" /tmp/checksum1.json

# Second run
python -m qx_cli.cli entry-ab \
  --gold-root "/home/jacobw/gcs-mount/gold" \
  --symbols "AAPL" \
  --dates "2024-01-02" \
  --policy vwap_revert \
  --seed 42

RUN2=$(ls -t runs/ | head -1)
cp "runs/$RUN2/inputs_checksum.json" /tmp/checksum2.json

# Compare checksums
python -c "
import json
with open('/tmp/checksum1.json') as f1, open('/tmp/checksum2.json') as f2:
    c1, c2 = json.load(f1), json.load(f2)

for key in ['bars_norm_hash', 'features_hash', 'sip_hash', 'seed']:
    if c1[key] == c2[key]:
        print(f'✅ {key} matches')
    else:
        print(f'❌ {key} differs: {c1[key]} vs {c2[key]}')

print(f'Config hashes - Run1: {c1[\"config_hash\"]}, Run2: {c2[\"config_hash\"]}')
"
```

## Validation Gates

### Minimal Gates (Required)
- **Trade Count**: At least 10 trades generated
- **Data Quality**: No NaN values in `pnl` column
- **Equity Curve**: Equity curve present and continuous
- **Compare Report**: A/B comparison report rendered successfully
- **Checksum Rules**: Reproducibility checksums enforced

### Comprehensive Gates (Recommended)
- **Signal Quality**: Valid signals with proper timestamps
- **Order Execution**: Orders filled with realistic slippage
- **Risk Compliance**: All trades respect risk constraints
- **Performance Metrics**: Expected Sharpe ratio and drawdown bounds
- **Schema Compliance**: All artifacts match schema definitions

## Performance Benchmarks

Validate system performance meets expectations:

```bash
# Benchmark data loading
time python -c "
from qx_data.gold_loader import GoldLoader
loader = GoldLoader('/home/jacobw/gcs-mount/gold')
df = loader.load_bars(['AAPL', 'MSFT', 'GOOG'], ['2024-01-02', '2024-01-03'])
print(f'Loaded {len(df)} bars across {df[\"symbol\"].nunique()} symbols')
"

# Benchmark feature computation
time python -c "
from qx_data.gold_loader import GoldLoader
from qx_features.registry import apply
loader = GoldLoader('/home/jacobw/gcs-mount/gold')
bars = loader.load_bars(['AAPL'], ['2024-01-02'])
features = apply(bars, [{'type': 'core_basics', 'params': {'vwap_window_m': 30}}])
print(f'Computed {len([c for c in features.columns if c.startswith(\"f__\")])} features')
"

# Benchmark backtest execution
time python -m qx_cli.cli entry-ab \
  --gold-root "/home/jacobw/gcs-mount/gold" \
  --symbols "AAPL" \
  --dates "2024-01-02" \
  --policy vwap_revert \
  --seed 42
```

## Error Scenarios Test

Test system behavior under error conditions:

### Invalid Data Test

```bash
# Test with non-existent symbol
python -m qx_cli.cli entry-ab \
  --gold-root "/home/jacobw/gcs-mount/gold" \
  --symbols "INVALID_SYM" \
  --dates "2024-01-02" \
  --policy vwap_revert \
  --seed 42 2>&1 | grep -i error || echo "No error (unexpected)"
```

### Invalid Configuration Test

```bash
# Test with invalid policy parameters
python -m qx_cli.cli entry-ab \
  --gold-root "/home/jacobw/gcs-mount/gold" \
  --symbols "AAPL" \
  --dates "2024-01-02" \
  --policy vwap_revert \
  --policy-params '{"rvol_min": -1.0}' \
  --seed 42 2>&1 | grep -i error || echo "No error (unexpected)"
```

## CI/CD Integration Test

Test that local smoke test matches CI expectations:

```bash
# Run reproducibility tests (as in CI)
pytest tests/test_reproducibility.py -v

# Run code quality checks
flake8 qx-core/qx_core --count --select=E9,F63,F7,F82 --show-source --statistics
black --check qx-core/qx_core
mypy qx-core/qx_core --ignore-missing-imports

# Run full test suite (if available)
pytest -xvs --cov=qx_core --cov-report=term-missing || echo "Some tests may fail"
```

## Validation Criteria

A successful smoke test should meet these criteria:

### ✅ Data Loading
- Gold data loads without errors
- Expected columns present with correct types
- Data sorted by [symbol, ts]
- UTC timestamps in nanoseconds

### ✅ Feature Engineering
- Features compute successfully
- No NaN values in required features
- Feature columns follow naming convention (f__*)
- Warmup periods handled correctly

### ✅ Policy Execution
- Strategy runs without errors
- Signals generated when conditions met
- Orders created and executed
- Positions opened and closed

### ✅ Risk Management
- Risk constraints enforced
- Position sizing follows rules
- Stop losses calculated correctly

### ✅ Artifact Generation
- All required artifacts created
- Valid schema compliance
- Metrics computed correctly
- Checksums generated

### ✅ Reproducibility
- Identical inputs produce identical outputs
- Checksums match across runs
- Seeds control random behavior
- Fair comparison criteria met

## Troubleshooting

### Common Issues

**Data Loading Errors**
```bash
# Check Gold data mount
ls -la /home/jacobw/gcs-mount/gold/
# Verify data exists for requested symbols/dates
find /home/jacobw/gcs-mount/gold/ -name "*AAPL*" -type d
```

**Import Errors**
```bash
# Check package installation
pip install -e .[dev,testing]
# Verify imports work
python -c "from qx_core.schemas import validate_bars; print('OK')"
```

**Memory Issues**
```bash
# Monitor resource usage
python -c "
import psutil
print(f'Memory: {psutil.virtual_memory().percent}%')
print(f'CPU: {psutil.cpu_percent()}%')
"
```

**Permission Issues**
```bash
# Check write permissions for runs/
ls -la runs/
# Fix if needed
chmod 755 runs/
```

### Performance Issues

**Slow Data Loading**
- Reduce data slice size for testing
- Check Gold data cache configuration
- Verify network connectivity

**Slow Feature Computation**
- Reduce feature window sizes
- Check for unnecessary computations
- Optimize feature configuration

**Slow Backtest**
- Reduce simulation time period
- Simplify policy logic
- Check for inefficient loops

## Automation

For automated CI execution, use the comprehensive smoke test script:

```bash
#!/bin/bash
# scripts/run_smoke_test.sh

set -e

echo "🚀 QuantStack E2E Smoke Test"
echo "=========================="

# Run all smoke tests
python scripts/run_smoke_test.py --comprehensive

# Generate report
python scripts/generate_smoke_report.py

echo "✅ Smoke test completed successfully"
```

This smoke test provides confidence that the QuantStack system is functioning correctly and ready for production use.
