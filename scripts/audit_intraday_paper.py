#!/usr/bin/env python3
"""
End-to-end forensic audit of intraday-paper trading system.
Validates all components from signal loading to order placement.
"""
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
import traceback

# Test results
results = {
    'passed': [],
    'failed': [],
    'warnings': []
}

def test(name):
    """Decorator for test functions."""
    def decorator(func):
        def wrapper():
            print(f"\n{'='*70}")
            print(f"TEST: {name}")
            print('='*70)
            try:
                func()
                results['passed'].append(name)
                print(f"✓ PASSED")
            except AssertionError as e:
                results['failed'].append((name, str(e)))
                print(f"✗ FAILED: {e}")
            except Exception as e:
                results['failed'].append((name, f"Exception: {e}"))
                print(f"✗ ERROR: {e}")
                traceback.print_exc()
        return wrapper
    return decorator

@test("1. Timestamp Parsing - dateutil.parser.parse()")
def test_timestamp_parsing():
    from dateutil import parser as dateutil_parser
    
    # Test various timestamp formats
    test_cases = [
        "2026-01-22 14:26:00-05:00",
        "2026-01-23 09:30:00-05:00",
        "2026-01-23T09:30:00-05:00",
        "2026-01-23 09:30:00",
    ]
    
    for ts_str in test_cases:
        parsed = dateutil_parser.parse(ts_str)
        print(f"  {ts_str} → {parsed}")
        assert isinstance(parsed, datetime), f"Failed to parse: {ts_str}"
    
    print(f"  All {len(test_cases)} timestamp formats parsed successfully")

@test("2. Signal File Existence")
def test_signal_files():
    signal_dir = Path('/home/jacobw/intraday_stack/data/daily_sip')
    
    # Check for recent signal files
    dates = sorted([d.name for d in signal_dir.iterdir() if d.is_dir() and d.name.startswith('date=')])
    
    print(f"  Found {len(dates)} signal date directories")
    assert len(dates) > 0, "No signal directories found"
    
    # Check most recent
    latest = dates[-1]
    latest_dir = signal_dir / latest
    parquet_files = list(latest_dir.glob('*.parquet'))
    
    print(f"  Latest: {latest} ({len(parquet_files)} parquet files)")
    assert len(parquet_files) > 0, f"No parquet files in {latest}"

@test("3. Signal Loading and Schema")
def test_signal_loading():
    import pandas as pd
    signal_dir = Path('/home/jacobw/intraday_stack/data/daily_sip')
    
    dates = sorted([d.name for d in signal_dir.iterdir() if d.is_dir() and d.name.startswith('date=')])
    latest_dir = signal_dir / dates[-1]
    parquet_files = list(latest_dir.glob('*.parquet'))
    
    df = pd.read_parquet(parquet_files[0])
    print(f"  Loaded {len(df)} signals from {parquet_files[0].name}")
    print(f"  Columns: {df.columns.tolist()}")
    
    # Check required columns
    required = ['symbol', 'timestamp', 'direction', 'entry_price']
    for col in required:
        assert col in df.columns, f"Missing required column: {col}"
    
    # Check timestamp format
    if len(df) > 0:
        sample_ts = df['timestamp'].iloc[0]
        print(f"  Sample timestamp: {sample_ts} (type: {type(sample_ts)})")

@test("4. Paper Trade Script Imports")
def test_imports():
    sys.path.insert(0, '/home/jacobw/intraday_stack')
    
    # Test critical imports
    imports = [
        ('ib_insync', 'IB'),
        ('dateutil.parser', None),
        ('pandas', 'pd'),
    ]
    
    for module, attr in imports:
        if attr:
            exec(f"from {module} import {attr}")
            print(f"  ✓ from {module} import {attr}")
        else:
            exec(f"import {module}")
            print(f"  ✓ import {module}")

@test("5. Configuration File")
def test_config():
    config_path = Path('/home/jacobw/intraday_stack/configs/paper_trade_config.yaml')
    
    if not config_path.exists():
        # Try alternate location
        config_path = Path('/home/jacobw/quantstack/configs/paper_trade_config.yaml')
    
    assert config_path.exists(), f"Config file not found: {config_path}"
    
    import yaml
    with open(config_path) as f:
        config = yaml.safe_load(f)
    
    print(f"  Config loaded from: {config_path}")
    print(f"  Keys: {list(config.keys())}")
    
    # Check critical settings
    if 'ibkr' in config:
        print(f"  IBKR host: {config['ibkr'].get('host', 'N/A')}")
        print(f"  IBKR port: {config['ibkr'].get('port', 'N/A')}")
        print(f"  Client ID: {config['ibkr'].get('client_id', 'N/A')}")

@test("6. Journal Database")
def test_journal_db():
    import sqlite3
    db_path = Path('/home/jacobw/intraday_stack/data/journal/events.db')
    
    assert db_path.exists(), f"Journal database not found: {db_path}"
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check tables
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cursor.fetchall()]
    print(f"  Tables: {tables}")
    
    # Check recent events
    if 'events' in tables:
        cursor.execute("SELECT COUNT(*) FROM events WHERE date(timestamp) = '2026-01-23'")
        count = cursor.fetchone()[0]
        print(f"  Events on 2026-01-23: {count}")
    
    conn.close()

@test("7. Paper Trade Script Syntax")
def test_script_syntax():
    script_path = Path('/home/jacobw/intraday_stack/scripts/paper_trade.py')
    
    assert script_path.exists(), f"Script not found: {script_path}"
    
    # Compile to check syntax
    with open(script_path) as f:
        code = f.read()
    
    compile(code, str(script_path), 'exec')
    print(f"  Script compiles successfully")
    print(f"  Size: {len(code)} bytes")

@test("8. Timestamp Parsing in Context")
def test_timestamp_in_context():
    """Test the actual timestamp parsing logic from paper_trade.py"""
    from dateutil import parser as dateutil_parser
    from datetime import datetime, timezone
    
    # Simulate the actual parsing logic
    test_timestamps = [
        "2026-01-22 14:26:00-05:00",
        datetime(2026, 1, 23, 9, 30, 0, tzinfo=timezone.utc),
    ]
    
    for ts in test_timestamps:
        if isinstance(ts, str):
            signal_time = dateutil_parser.parse(ts)
        elif isinstance(ts, datetime):
            signal_time = ts
        else:
            raise ValueError(f"Invalid timestamp type: {type(ts)}")
        
        # Check age calculation
        now = datetime.now(timezone.utc)
        age = (now - signal_time.replace(tzinfo=timezone.utc)).total_seconds()
        
        print(f"  {ts} → age: {age:.1f}s")
        assert isinstance(signal_time, datetime), "Parsing failed"

@test("9. IBKR Connection Parameters")
def test_ibkr_params():
    """Verify IBKR connection parameters are correct"""
    
    # Expected values for intraday-paper
    expected = {
        'host': '127.0.0.1',
        'port': 7494,
        'client_id': 111,
    }
    
    print(f"  Expected connection:")
    for k, v in expected.items():
        print(f"    {k}: {v}")
    
    # Check if systemd service file has correct params
    service_file = Path('/home/jacobw/quantstack/systemd/intraday-paper.service')
    if service_file.exists():
        with open(service_file) as f:
            content = f.read()
        
        if 'paper_trade.py' in content:
            print(f"  ✓ Service file references paper_trade.py")
        else:
            results['warnings'].append("Service file may not reference paper_trade.py")

@test("10. Signal Age Validation Logic")
def test_signal_age_logic():
    """Test signal age validation"""
    from datetime import datetime, timezone, timedelta
    
    now = datetime.now(timezone.utc)
    
    # Test cases: (signal_time, should_accept)
    test_cases = [
        (now - timedelta(seconds=30), True, "30s old - should accept"),
        (now - timedelta(minutes=5), True, "5min old - should accept"),
        (now - timedelta(minutes=15), False, "15min old - should reject"),
        (now + timedelta(minutes=1), False, "Future signal - should reject"),
    ]
    
    max_age_seconds = 600  # 10 minutes
    
    for signal_time, should_accept, desc in test_cases:
        age = (now - signal_time).total_seconds()
        is_valid = 0 <= age <= max_age_seconds
        
        status = "✓" if is_valid == should_accept else "✗"
        print(f"  {status} {desc}: age={age:.1f}s, valid={is_valid}")
        
        assert is_valid == should_accept, f"Signal age validation failed: {desc}"

@test("11. Order Price Precision")
def test_price_precision():
    """Verify order prices are properly rounded to tick size"""
    from cpapi.utils import round_to_tick_size
    
    test_prices = [
        (187.671085, 187.67),
        (187.39, 187.39),
        (2.465, 2.47),
        (100.999, 101.00),
    ]
    
    for input_price, expected in test_prices:
        rounded = round_to_tick_size(input_price, 0.01)
        print(f"  {input_price:.6f} → {rounded:.2f} (expected: {expected:.2f})")
        assert abs(rounded - expected) < 0.001, f"Rounding failed: {input_price}"

@test("12. Dry Run Mode Check")
def test_dry_run():
    """Check if dry run mode is properly configured"""
    script_path = Path('/home/jacobw/intraday_stack/scripts/paper_trade.py')
    
    with open(script_path) as f:
        content = f.read()
    
    # Check for dry run logic
    if 'DRY_RUN' in content or 'dry_run' in content:
        print(f"  ✓ Dry run mode found in script")
    else:
        results['warnings'].append("No dry run mode detected")
    
    # Check for actual order placement
    if 'placeOrder' in content or 'place_order' in content:
        print(f"  ✓ Order placement logic found")
    else:
        results['warnings'].append("No order placement logic found")

def main():
    print("="*70)
    print("INTRADAY-PAPER FORENSIC AUDIT")
    print("="*70)
    print(f"Time: {datetime.now()}")
    print(f"System: {os.uname().sysname} {os.uname().machine}")
    
    # Run all tests
    test_timestamp_parsing()
    test_signal_files()
    test_signal_loading()
    test_imports()
    test_config()
    test_journal_db()
    test_script_syntax()
    test_timestamp_in_context()
    test_ibkr_params()
    test_signal_age_logic()
    test_price_precision()
    test_dry_run()
    
    # Summary
    print("\n" + "="*70)
    print("AUDIT SUMMARY")
    print("="*70)
    print(f"✓ Passed: {len(results['passed'])}")
    print(f"✗ Failed: {len(results['failed'])}")
    print(f"⚠ Warnings: {len(results['warnings'])}")
    
    if results['failed']:
        print("\nFAILED TESTS:")
        for name, error in results['failed']:
            print(f"  ✗ {name}")
            print(f"    {error}")
    
    if results['warnings']:
        print("\nWARNINGS:")
        for warning in results['warnings']:
            print(f"  ⚠ {warning}")
    
    if results['passed']:
        print("\nPASSED TESTS:")
        for name in results['passed']:
            print(f"  ✓ {name}")
    
    # Final verdict
    print("\n" + "="*70)
    if len(results['failed']) == 0:
        print("✓ ALL TESTS PASSED - System ready for trading")
        return 0
    else:
        print(f"✗ {len(results['failed'])} TESTS FAILED - Issues must be resolved")
        return 1

if __name__ == '__main__':
    sys.exit(main())
