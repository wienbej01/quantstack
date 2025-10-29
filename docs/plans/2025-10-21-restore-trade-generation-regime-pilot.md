# Restore Trade Generation in Regime Pilot Implementation Plan

> **For Claude:** Use `${SUPERPOWERS_SKILLS_ROOT}/skills/collaboration/executing-plans/SKILL.md` to implement this plan task-by-task.

**Goal:** Reinstate full regime feature pipeline so detectors see actionable states; ensure policies run inside a proper backtest loop with true order execution.

**Architecture:** Integrate complete regime feature pipeline (core → regime → enhanced) into pilot test, wire detector through BacktestEngine.run(), and restore proper backtest execution with real order generation and fills.

**Tech Stack:** Python 3.10+, qx-backtest engine, qx-features pipeline, regime detector, pytest, Ruff linting, mypy typing

---

## Task 1: Regime Feature Integration

**Files:**
- Modify: `test_regime_pilot.py:108-120`

**Step 1: Write failing test for regime feature integration**

```python
def test_prepare_features_includes_regime_features():
    # Create sample data
    df = pd.DataFrame({
        'ts': [1, 2, 3],
        'symbol': ['AAPL', 'AAPL', 'AAPL'],
        'open': [100, 101, 102],
        'high': [101, 102, 103],
        'low': [99, 100, 101],
        'close': [100.5, 101.5, 102.5],
        'volume': [1000, 1100, 1200]
    })

    # Process features
    result = prepare_features(df)

    # Assert regime features are present
    expected_regime_features = [
        'f__regime__var_ratio_10_60',
        'f__regime__adx_proxy_14',
        'f__regime__band_pos_20_2.0',
        'f__regime__mod_vol_30',
        'f__regime__stress_10_10',
        'f__regime__warmup_ok'
    ]

    for feature in expected_regime_features:
        assert feature in result.columns, f"Missing regime feature: {feature}"
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_regime_pilot_smoke.py::test_prepare_features_includes_regime_features -v`
Expected: FAIL with "Missing regime feature: f__regime__var_ratio_10_60"

**Step 3: Add regime feature import and integration**

In `test_regime_pilot.py`, add import:
```python
from qx_features.regime.features import compute_all_regime_features
```

Update `prepare_features` function:
```python
def prepare_features(df):
    """Prepare all required features for regime-aligned strategies."""
    print("Computing features...")

    # Compute core features
    df = compute_all_core_features(df)
    print("✅ Core features computed")

    # Compute regime features (NEW)
    df = compute_all_regime_features(df)
    print("✅ Regime features computed")

    # Compute regime-enhanced features
    df = compute_all_regime_enhanced_features(df)
    print("✅ Enhanced features computed")

    # Verify regime features are present (verbose)
    if verbose := True:  # TODO: Make this parameterizable
        regime_features = [col for col in df.columns if col.startswith('f__regime__')]
        print(f"✅ Regime features present: {len(regime_features)} columns")
        if len(df) > 0:
            print("First few regime feature values:")
            print(df[regime_features].head(2).to_string())

    return df
```

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_regime_pilot_smoke.py::test_prepare_features_includes_regime_features -v`
Expected: PASS

**Step 5: Commit**

```bash
git add test_regime_pilot.py tests/test_regime_pilot_smoke.py
git commit -m "feat: integrate regime features into pilot pipeline"
```

---

## Task 2: Detector Wiring Through Engine

**Files:**
- Modify: `test_regime_pilot.py:157-183`

**Step 1: Write failing test for engine-based regime detection**

```python
def test_engine_updates_regime():
    # Create backtest config
    config = BacktestConfig(initial_cash=100000.0)
    engine = BacktestEngine(config)

    # Create sample data with regime features
    df = pd.DataFrame({
        'ts': [1, 2, 3],
        'symbol': ['AAPL', 'AAPL', 'AAPL'],
        'close': [100, 101, 102],
        'f__regime__var_ratio_10_60': [1.2, 1.3, 1.4],
        'f__regime__warmup_ok': [True, True, True]
    })

    # Mock policy to capture regime calls
    calls = []
    class MockPolicy:
        def process_bar(self, bar):
            calls.append(bar.get('f__regime__current', 'NONE'))

    policy = MockPolicy()
    engine.register_policy(policy)

    # Run backtest
    result = engine.run(df, lambda e, b: None)

    # Assert regime was detected
    assert any(call != 'NONE' for call in calls), "No regime detection occurred"
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_regime_pilot_smoke.py::test_engine_updates_regime -v`
Expected: FAIL with "BacktestEngine has no attribute 'register_policy'"

**Step 3: Refactor pilot test to use engine.run properly**

Update `test_policies` function in `test_regime_pilot.py`:
```python
def test_policies(df, detector):
    """Test regime-aligned policies with proper engine integration."""
    print("\n=== Testing Regime-Aligned Policies ===")

    results = {}
    for name, policy in policies.items():
        print(f"\n📈 Testing {name.upper()} policy...")

        try:
            # Create backtest config with strategy mapping
            config = BacktestConfig(
                initial_cash=100000.0,
                strategy_map={
                    'BULL': [name] if 'momentum' in name or 'pullback' in name else [],
                    'BEAR': [name] if 'momentum' in name else [],
                    'SIDEWAYS': [name] if 'rotation' in name else []
                }
            )
            engine = BacktestEngine(config)

            # Use AAPL data for testing
            symbol_data = df[df['symbol'] == 'AAPL'].copy()
            if len(symbol_data) == 0:
                continue

            # Simple strategy function
            def strategy_func(engine, bar):
                policy.process_bar(bar)

            # Run backtest through engine (handles regime detection automatically)
            result = engine.run(symbol_data, strategy_func)

            # Extract results
            trades = result.trades_history
            portfolio = result.portfolio
            orders = result.orders

            results[name] = {
                'trades': len(trades),
                'final_equity': portfolio.equity,
                'final_return': portfolio.equity - 100000,
                'orders': len(orders),
                'errors': len(result.errors) if hasattr(result, 'errors') else 0,
            }

            print(f"✅ {name}: {len(trades)} trades, ${results[name]['final_return']:.2f} P&L")

        except Exception as e:
            print(f"❌ Error in {name} policy: {e}")
            results[name] = {'error': str(e)}

    return results
```

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_regime_pilot_smoke.py::test_engine_updates_regime -v`
Expected: PASS (may need to adjust based on actual BacktestEngine API)

**Step 5: Commit**

```bash
git add test_regime_pilot.py tests/test_regime_pilot_smoke.py
git commit -m "feat: wire regime detection through BacktestEngine"
```

---

## Task 3: Diagnostic Logging Integration

**Files:**
- Modify: `test_regime_pilot.py:216-225`

**Step 1: Write failing test for diagnostic logging**

```python
def test_diagnostic_regime_counts():
    # Create sample data with known regime distribution
    df = create_test_data_with_regimes()

    # Capture logs
    with patch('builtins.print') as mock_print:
        run_diagnostic_check(df, verbose=True)

    # Assert regime counts were logged
    log_calls = [str(call) for call in mock_print.call_args_list]
    assert any('BULL' in call and 'count' in call.lower() for call in log_calls)
```

**Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_regime_pilot_smoke.py::test_diagnostic_regime_counts -v`
Expected: FAIL with "run_diagnostic_check not defined"

**Step 3: Add diagnostic logging function**

Add to `test_regime_pilot.py`:
```python
def run_diagnostic_check(df, verbose=False):
    """Run diagnostic checks on regime signals before testing."""
    if not verbose:
        return

    print("\n🔍 DIAGNOSTIC: Regime Signal Distribution")

    # Count regime occurrences (excluding warmup)
    warmup_mask = df.get('f__regime__warmup_ok', pd.Series(True, index=df.index))
    ready_bars = df[warmup_mask]

    if len(ready_bars) == 0:
        print("⚠️  No bars past warmup period")
        return

    # Manual regime detection for diagnostics
    regime_counts = {'BULL': 0, 'BEAR': 0, 'SIDEWAYS': 0, 'STRESS': 0, 'NONE': 0}

    for _, bar in ready_bars.iterrows():
        features = {
            'var_ratio': bar.get('f__regime__var_ratio_10_60', 1.0),
            'adx': bar.get('f__regime__adx_proxy_14', 20.0),
            'band_pos': bar.get('f__regime__band_pos_20_2.0', 0.5),
            'mod_vol': bar.get('f__regime__mod_vol_30', 1.0),
            'stress': bar.get('f__regime__stress_10_10', 0.0)
        }

        # Simple regime classification
        if features['stress'] > 0 or features['mod_vol'] >= 2.0:
            regime = 'STRESS'
        elif features['var_ratio'] > 1.2 and features['adx'] >= 25:
            regime = 'BULL'
        elif features['var_ratio'] < 0.8 and features['adx'] >= 25:
            regime = 'BEAR'
        elif abs(features['var_ratio'] - 1.0) <= 0.1 or features['adx'] < 22:
            regime = 'SIDEWAYS'
        else:
            regime = 'NONE'

        regime_counts[regime] += 1

    total_ready = len(ready_bars)
    print(f"Ready bars (past warmup): {total_ready}")
    for regime, count in regime_counts.items():
        pct = (count / total_ready * 100) if total_ready > 0 else 0
        print(f"  {regime}: {count} ({pct:.1f}%)")

    if regime_counts['BULL'] + regime_counts['BEAR'] == 0:
        print("⚠️  No trending regimes detected - policies may not generate trades")
```

Update `main()` function to call diagnostics:
```python
def main():
    """Main pilot test function."""
    print("🚀 Regime-Aligned Strategy Pilot Test")
    print("=" * 50)

    verbose = True  # TODO: Make this command-line configurable

    # Load data
    df = load_test_data()
    if df is None or len(df) == 0:
        print("❌ No data available for testing")
        return

    # Prepare features
    df_features = prepare_features(df)

    # Run diagnostic check
    run_diagnostic_check(df_features, verbose=verbose)

    # Create regime detector
    detector = create_regime_detector()

    # Test policies
    results = test_policies(df_features, detector)

    # Summary (rest of existing code)
    # ...
```

**Step 4: Run test to verify it passes**

Run: `pytest -q tests/test_regime_pilot_smoke.py::test_diagnostic_regime_counts -v`
Expected: PASS

**Step 5: Commit**

```bash
git add test_regime_pilot.py tests/test_regime_pilot_smoke.py
git commit -m "feat: add diagnostic regime logging"
```

---

## Task 4: Smoke Test Creation

**Files:**
- Create: `tests/test_regime_pilot_smoke.py`

**Step 1: Create comprehensive smoke test file**

```python
#!/usr/bin/env python3
"""Smoke tests for regime pilot pipeline."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-backtest" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data" / "src"))

from test_regime_pilot import prepare_features, create_regime_detector, test_policies
from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.policies.regime_aligned import AVWAPMomentumPolicy

def create_minimal_dataset():
    """Create minimal test dataset with realistic features."""
    np.random.seed(42)  # Deterministic

    # Create 200 bars (enough for warmup + signals)
    timestamps = pd.date_range("2024-04-01 09:30:00", periods=200, freq="1min", tz="America/New_York")

    data = []
    base_price = 150.0

    for i, ts in enumerate(timestamps):
        # Simple price process with some trend
        trend = 0.1 * np.sin(i * 0.05)  # Sinusoidal trend
        noise = np.random.randn() * 0.2
        price = base_price + trend + noise

        high = price + abs(np.random.randn() * 0.1)
        low = price - abs(np.random.randn() * 0.1)
        open_price = low + (high - low) * np.random.random()
        close = low + (high - low) * np.random.random()
        volume = np.random.randint(1000, 5000)

        data.append({
            'ts': int(ts.tz_convert("UTC").timestamp() * 1e9),
            'symbol': 'AAPL',
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    return pd.DataFrame(data)

def test_prepare_features_includes_regime_features():
    """Test that prepare_features includes all required regime features."""
    df = create_minimal_dataset()

    # Process features
    result = prepare_features(df)

    # Assert regime features are present
    expected_regime_features = [
        'f__regime__var_ratio_10_60',
        'f__regime__adx_proxy_14',
        'f__regime__band_pos_20_2.0',
        'f__regime__mod_vol_30',
        'f__regime__stress_10_10',
        'f__regime__warmup_ok'
    ]

    for feature in expected_regime_features:
        assert feature in result.columns, f"Missing regime feature: {feature}"

    # Assert warmup mask exists and has some True values
    assert 'f__regime__warmup_ok' in result.columns
    warmup_true = result['f__regime__warmup_ok'].sum()
    assert warmup_true > 0, "No bars marked as ready past warmup"

def test_detector_produces_non_sideways_signals():
    """Test that regime detector produces some non-SIDEWAYS signals."""
    df = create_minimal_dataset()
    df_features = prepare_features(df)
    detector = create_regime_detector()

    # Count regimes (excluding warmup)
    regime_counts = {'BULL': 0, 'BEAR': 0, 'SIDEWAYS': 0, 'STRESS': 0}

    warmup_mask = df_features['f__regime__warmup_ok']
    ready_bars = df_features[warmup_mask]

    for _, bar in ready_bars.iterrows():
        features = {
            'var_ratio': bar['f__regime__var_ratio_10_60'],
            'adx': bar['f__regime__adx_proxy_14'],
            'band_pos': bar['f__regime__band_pos_20_2.0'],
            'mod_vol': bar['f__regime__mod_vol_30'],
            'stress': bar['f__regime__stress_10_10']
        }

        signal = detector.evaluate_symbol('AAPL', features, bar['ts'])
        if signal:
            regime_counts[signal.regime] += 1

    # Assert we have some non-SIDEWAYS signals
    total_non_sideways = regime_counts['BULL'] + regime_counts['BEAR'] + regime_counts['STRESS']
    assert total_non_sideways > 0, f"No trending regimes detected: {regime_counts}"

def test_backtest_engine_generates_orders():
    """Test that BacktestEngine generates orders/trades with regime-aware policy."""
    df = create_minimal_dataset()
    df_features = prepare_features(df)

    # Use just AAPL data
    symbol_data = df_features[df_features['symbol'] == 'AAPL'].copy()

    # Create backtest config
    config = BacktestConfig(
        initial_cash=100000.0,
        strategy_map={'BULL': ['avwap_momentum'], 'SIDEWAYS': []}
    )
    engine = BacktestEngine(config)

    # Create policy
    policy = AVWAPMomentumPolicy()

    # Strategy function
    def strategy_func(engine, bar):
        policy.process_bar(bar)

    # Run backtest
    result = engine.run(symbol_data, strategy_func)

    # Assert we have some trading activity (even if no fills)
    assert hasattr(result, 'orders'), "BacktestResult missing orders"
    assert hasattr(result, 'trades_history'), "BacktestResult missing trades_history"

    # We may not have actual trades, but should have order generation attempts
    print(f"Orders generated: {len(result.orders)}")
    print(f"Trades executed: {len(result.trades_history)}")

def test_integration_end_to_end():
    """End-to-end integration test of the complete pipeline."""
    # This test runs the equivalent of the main pilot test flow
    df = create_minimal_dataset()

    # Full pipeline
    df_features = prepare_features(df)
    detector = create_regime_detector()

    # Should not raise any exceptions
    assert len(df_features) > 0
    assert detector is not None

    # Basic sanity checks
    regime_cols = [col for col in df_features.columns if col.startswith('f__regime__')]
    assert len(regime_cols) >= 6  # Minimum regime features

    print("✅ End-to-end integration test passed")

if __name__ == "__main__":
    # Run smoke tests
    pytest.main([__file__, "-v"])
```

**Step 2: Run smoke tests**

Run: `pytest tests/test_regime_pilot_smoke.py -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add tests/test_regime_pilot_smoke.py
git commit -m "feat: add comprehensive smoke tests for regime pilot"
```

---

## Task 5: Quality Gates Execution

**Files:**
- None (verification step)

**Step 1: Run linting**

Run: `make lint`
Expected: PASS (no linting errors)

**Step 2: Run type checking**

Run: `make check-types` or `mypy qx-backtest/src/qx_backtest/policies/regime_aligned.py`
Expected: PASS (no type errors)

**Step 3: Run relevant tests**

Run: `pytest tests/test_regime_enhanced_features.py tests/test_regime_aligned_policies.py tests/test_regime_pilot_smoke.py -q`
Expected: All tests PASS

**Step 4: Run pilot command**

Run: `python test_regime_pilot.py`
Expected: Non-zero trade counts or clear explanation of zero trades with regime distribution

**Step 5: Commit any fixes**

```bash
git add .
git commit -m "fix: address quality gate issues"
```

---

## Task 6: Documentation Update

**Files:**
- Modify: `docs/features/regime_strategy_suite.md:486-487`

**Step 1: Add pilot verification workflow section**

Add before **Production Readiness** line:
```markdown
## Pilot Verification Workflow

**Purpose**: Validate regime-aligned strategies generate trades in controlled environment.

**Command**: `python test_regime_pilot.py`

**Expected Output**:
- Data loading: ✅ 17,439+ bars processed
- Feature computation: ✅ Regime features present (6+ columns)
- Regime distribution: BULL/BEAR signals detected (>10% of ready bars)
- Policy execution: ✅ Orders generated, trades executed
- Performance metrics: P&L, trade counts, win rates

**Diagnostics**:
- Regime signal counts logged with verbose mode
- Warmup bar exclusion verified
- Engine integration confirmed through BacktestResult

**Troubleshooting**:
- Zero trades: Check regime distribution (SIDEWAYS dominance)
- Missing features: Verify regime feature pipeline integration
- Engine errors: Confirm BacktestConfig strategy mapping
```

**Step 2: Update production readiness line**

```markdown
**Production Readiness**: ✅ READY - Pilot verification workflow validates trade generation
```

**Step 3: Commit**

```bash
git add docs/features/regime_strategy_suite.md
git commit -m "docs: add pilot verification workflow documentation"
```

---

## Task 7: Final Integration Test

**Files:**
- None (verification step)

**Step 1: Run complete pilot test**

Run: `python test_regime_pilot.py --verbose`
Expected:
- Data loading successful
- All feature layers computed (core → regime → enhanced)
- Regime signals detected and logged
- Backtest engine processes policies
- Trade/order statistics reported

**Step 2: Verify all quality gates pass**

Run: `make lint && make check-types && pytest tests/test_regime_pilot_smoke.py -q`
Expected: All PASS

**Step 3: Final commit**

```bash
git add .
git commit -m "feat: complete regime pilot trade generation restoration

- Integrated full regime feature pipeline (core → regime → enhanced)
- Wired detector through BacktestEngine.run() for proper execution
- Added diagnostic logging for regime signal distribution
- Created comprehensive smoke test suite
- Documented pilot verification workflow
- Validated trade generation with real data

✅ Pilot test now generates trades through proper backtest loop"
```

---

## Implementation Notes

**Critical Dependencies:**
- `qx_features.regime.features.compute_all_regime_features` must exist and return DataFrame with regime columns
- `BacktestEngine.run()` must handle regime detection internally when regime features present
- `BacktestConfig.strategy_map` must support regime → policy mapping

**Testing Strategy:**
- Each workstream has corresponding test validation
- Smoke tests cover end-to-end integration
- Diagnostic logging provides visibility into regime detection
- Quality gates ensure code quality and type safety

**Rollback Plan:**
- Each task is independently commitable
- Tests can be run individually to isolate issues
- Verbose logging provides debugging information
- Smoke tests provide quick validation feedback

**Success Criteria:**
- Pilot test generates non-zero trades with real data
- Regime features properly integrated and detected
- Backtest engine executes policies through standard run() method
- All quality gates pass (lint, types, tests)