# HMM SIP CLI Recipes

**Command-line interface recipes for HMM SIP Universe Selector testing and deployment.**

## Prerequisites

```bash
cd /home/jacobw/quantstack
# Ensure all dependencies are installed
pip install -e qx-*
pip install -e .
```

## Quick Validation Commands

### Unit Tests
```bash
# Run all HMM SIP tests
pytest tests/test_hmm_sip_selector_mvp.py tests/test_hmm_sip_performance.py tests/test_hmm_sip_p_hat_simple.py -v

# Performance benchmark (1000 symbols)
python -m pytest tests/test_hmm_sip_performance.py -v -s
```

### Functionality Tests
```bash
# Test basic selector functionality
python -c "
from qx_screener.hmm_sip import HMMSIPUniverseSelector, HMMSIPConfig
import pandas as pd

# Simple smoke test
config = HMMSIPConfig(top_k=5, enable_gold_fallback=True)
selector = HMMSIPUniverseSelector(config)
print('✅ HMM SIP selector initialized successfully')
"
```

## One-Day Pilot A/B Tests

### Basic A/B Test (Legacy vs HMM SIP)
```bash
# Configure experiment
python -m qx_cli exp entry-ab \
  --cfg experiments/vwap_revert/strategy.yaml \
  --variants experiments/vwap_revert/overlays/sip_legacy.yaml,experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml \
  --name vwap_hmmsip_ab_2024_01_03 \
  --dates 2024-01-03

# Monitor progress
tail -f runs/*/logs/*.log

# Compare results
python -m qx_cli exp compare --exp experiments/vwap_hmmsip_ab_2024_01_03
jq '.' experiments/vwap_hmmsip_ab_2024_01_03/compare.json
```

### With Minute-level p̂ Gating
```bash
# Create p̂ gating overlay
cat > experiments/vwap_revert/overlays/sip_hmmsip_with_phate.yaml << EOF
sip:
  selector:
    type: hmm_sip
    params:
      top_k: 30
      score_floor: 0.3
      enable_gold_fallback: true
      p_hat_threshold: 0.7
      min_minutes_in_state: 3
EOF

# Run comparison
python -m qx_cli exp entry-ab \
  --cfg experiments/vwap_revert/strategy.yaml \
  --variants experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml,experiments/vwap_revert/overlays/sip_hmmsip_with_phate.yaml \
  --name vwap_phate_ab_2024_01_03 \
  --dates 2024-01-03
```

## Two-Week Production Pilot

```bash
# Extended two-week test
python -m qx_cli exp entry-ab \
  --cfg experiments/vwap_revert/strategy.yaml \
  --variants experiments/vwap_revert/overlays/sip_legacy.yaml,experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml \
  --name vwap_hmmsip_ab_2w \
  --dates 2024-01-03..2024-01-16

# Generate comprehensive report
python -m qx_cli exp compare --exp experiments/vwap_hmmsip_ab_2w
python -m qx_report generate --exp experiments/vwap_hmmsip_ab_2w --output reports/
```

## Performance Benchmarking

### Synthetic Data Benchmark
```bash
# Run 1000-symbol performance test
python -m pytest tests/test_hmm_sip_performance.py::test_performance_1000_symbols_external_file -v -s

# Gold fallback performance
python -m pytest tests/test_hmm_sip_performance.py::test_performance_1000_symbols_gold_fallback -v -s
```

### Cache Performance Analysis
```bash
# First run (cache miss)
python -c "
import time, tempfile, os
from qx_screener.hmm_sip import HMMSIPUniverseSelector, HMMSIPConfig
from tests.test_hmm_sip_p_hat_simple import create_simple_test

start = time.time()
create_simple_test()
print(f'Cold run: {time.time() - start:.2f}s')
"

# Second run (cache hit)
python -c "
import time, tempfile, os
from qx_screener.hmm_sip import HMMSIPUniverseSelector, HMMSIPConfig
from tests.test_hmm_sip_p_hat_simple import create_simple_test

start = time.time()
create_simple_test()
print(f'Hot run: {time.time() - start:.2f}s')
"
```

## Validation and QA

### Hash Stability Validation
```bash
# Verify deterministic hashing
python -c "
from qx_screener.hmm_sip import HMMSIPUniverseSelector, HMMSIPConfig
from tests.test_hmm_sip_selector_mvp import create_sample_bars
import pandas as pd

bars_df = create_sample_bars()
config = HMMSIPConfig(top_k=3, enable_gold_fallback=True)
selector = HMMSIPUniverseSelector(config)

# Multiple runs should produce identical results
results = []
for i in range(3):
    result = selector.select(bars_df, {'target_date': '2024-01-03'})
    results.append(len(result))

print(f'Result consistency: {results}')
assert len(set(results)) == 1, 'Hash stability test failed!'
print('✅ Hash stability validated')
"
```

### Configuration Validation
```bash
# Test all configuration combinations
python -c "
from qx_screener.hmm_sip import HMMSIPUniverseSelector, HMMSIPConfig
from tests.test_hmm_sip_selector_mvp import create_sample_bars
import pandas as pd

bars_df = create_sample_bars()
configs = [
    HMMSIPConfig(top_k=5),
    HMMSIPConfig(top_k=5, score_floor=0.5),
    HMMSIPConfig(top_k=5, p_hat_threshold=0.7),
    HMMSIPConfig(top_k=5, p_hat_threshold=0.7, min_minutes_in_state=3),
]

for i, config in enumerate(configs):
    selector = HMMSIPUniverseSelector(config)
    result = selector.select(bars_df, {'target_date': '2024-01-03'})
    print(f'Config {i+1}: {len(result)} timestamps')

print('✅ All configurations validated')
"
```

## Troubleshooting Commands

### Check External File Structure
```bash
# Verify hybrid-local structure
echo "Checking hybrid-local structure..."
ls -la ~/hybrid-local/signals/sip/universe/pre/ || echo "No premarket files found"
find ~/hybrid-local/signals/sip/1m/ -name "*.parquet" 2>/dev/null | head -5 || echo "No p̂ files found"
```

### Validate Input Checksums
```bash
# Check sip_hash in recent experiments
find experiments/ -name "inputs_checksum.json" -exec sh -c '
    echo "=== $1 ==="
    jq -r ".sip_hash // \"No sip_hash\"" "$1"
' _ {} \; | head -10
```

### Monitor Resource Usage
```bash
# Memory and CPU during selector run
/usr/bin/time -v python -c "
from qx_screener.hmm_sip import HMMSIPUniverseSelector, HMMSIPConfig
from tests.test_hmm_sip_performance import create_large_synthetic_dataset
import pandas as pd

bars_df = create_large_synthetic_dataset(1000)
config = HMMSIPConfig(top_k=50, p_hat_threshold=0.6)
selector = HMMSIPUniverseSelector(config)
result = selector.select(bars_df, {'target_date': '2024-01-09'})
print(f'Processed {len(bars_df)} bars, {len(result)} timestamps')
"
```

## Production Deployment

### Environment Validation
```bash
# Verify production environment
python -c "
import sys
print(f'Python: {sys.version}')
import pandas as pd
print(f'Pandas: {pd.__version__}')
from qx_screener.hmm_sip import HMMSIPUniverseSelector
print('✅ HMM SIP module imported successfully')

# Test basic functionality
config = HMMSIPConfig()
selector = HMMSIPUniverseSelector(config)
print('✅ Basic initialization successful')
"
```

### Smoke Test Suite
```bash
# Complete smoke test suite
echo "Running HMM SIP smoke test suite..."

# 1. Unit tests
pytest tests/test_hmm_sip_selector_mvp.py -q

# 2. Performance tests
pytest tests/test_hmm_sip_performance.py -q

# 3. Integration tests
pytest tests/test_hmm_sip_p_hat_simple.py -q

# 4. End-to-end test
python -m qx_cli exp entry-ab \
  --cfg experiments/vwap_revert/strategy.yaml \
  --variants experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml \
  --name smoke_test_$(date +%Y%m%d_%H%M%S) \
  --dates 2024-01-03

echo "✅ All smoke tests passed"
```

## Monitoring and Maintenance

### Log Analysis
```bash
# Extract HMM SIP logs from recent runs
find runs/ -name "*.log" -exec grep -l "HMM\|P_HAT" {} \; | head -3 | xargs grep -h "P_HAT\|CACHE"

# Check cache performance
grep "CACHE" runs/*/logs/*.log | tail -10
```

### Health Check
```bash
# Daily health check script
cat > tools/hmm_sip_health_check.sh << 'EOF'
#!/bin/bash
echo "=== HMM SIP Health Check $(date) ==="

# Check module imports
python -c "from qx_screener.hmm_sip import HMMSIPUniverseSelector; print('✅ Module OK')" || echo "❌ Module import failed"

# Check recent experiments
recent_exp=$(find experiments/ -name "*hmmsip*" -type d | head -1)
if [ -n "$recent_exp" ]; then
    echo "✅ Recent experiment found: $recent_exp"
else
    echo "❌ No recent HMM SIP experiments found"
fi

# Check external data availability
if [ -d "$HOME/hybrid-local/signals/sip" ]; then
    echo "✅ External data directory exists"
    ls -1 "$HOME/hybrid-local/signals/sip/universe/pre/" | wc -l | xargs echo "  Premarket files:"
else
    echo "⚠️  No external data directory (using Gold fallback)"
fi

echo "=== Health Check Complete ==="
EOF

chmod +x tools/hmm_sip_health_check.sh
./tools/hmm_sip_health_check.sh
```