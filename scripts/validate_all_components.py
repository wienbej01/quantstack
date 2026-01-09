#!/usr/bin/env python3
"""
Comprehensive Pre-Market Validation Suite

Run this before market hours to catch ALL potential failures.
Usage: python scripts/validate_all_components.py
"""

import subprocess
import sys
from pathlib import Path


def run_test(name: str, cmd: str, timeout: int = 30) -> tuple[bool, str]:
    """Run a test command and return (passed, output)"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stderr or result.stdout
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


def main():
    print("=" * 70)
    print("COMPREHENSIVE PRE-MARKET VALIDATION SUITE")
    print("=" * 70)

    tests = []

    # 1. Systemd service tests
    print("\n[1/6] SYSTEMD SERVICES")
    for svc in ["l2-collector", "l2-scalping", "l2-watchdog"]:
        passed, out = run_test(f"{svc} active", f"systemctl is-active {svc}")
        status = "🟢" if passed and "active" in out else "🔴"
        print(f"  {status} {svc}: {out.strip()}")
        tests.append((f"svc_{svc}", passed and "active" in out))

    # 2. Timer tests
    print("\n[2/6] SYSTEMD TIMERS")
    for timer in ["trading-orchestrator", "l2-collector", "intraday-paper"]:
        passed, out = run_test(f"{timer} timer", f"systemctl is-active {timer}.timer")
        status = "🟢" if passed and "active" in out else "⚪"
        print(f"  {status} {timer}.timer: {out.strip()}")
        tests.append((f"timer_{timer}", passed))

    # 3. Python import tests
    print("\n[3/6] PYTHON IMPORTS (l2_scalping)")
    import_test = """
cd /home/jacobw/quantstack/l2_scalping && PYTHONPATH=src python3 -c "
from data.l2_feed import L2DataFeed, L2Snapshot
from data.sip_integration import load_daily_sip_symbols
from execution.order_manager import IBKROrderManager, OrderRequest, OrderSide, OrderType
from signals.l2_signals import L2SignalGenerator
from risk.risk_manager import RiskManager
from reporting.trade_journal import TradeJournal
from scheduler import MarketScheduler
print('OK')
"
"""
    passed, out = run_test("l2_scalping imports", import_test)
    status = "🟢" if passed and "OK" in out else "🔴"
    print(f"  {status} All l2_scalping modules: {'OK' if passed else out[:50]}")
    tests.append(("imports_l2_scalping", passed and "OK" in out))

    # 4. SIP data test
    print("\n[4/6] SIP UNIVERSE DATA")
    sip_test = """
python3 -c "
import json
from pathlib import Path
sip_dir = Path('/home/jacobw/intraday_stack/data/daily_sip')
latest = sorted(sip_dir.glob('date=*'))[-1] if list(sip_dir.glob('date=*')) else None
if latest:
    with open(latest / 'sip_universe.json') as f:
        data = json.load(f)
    symbols = data.get('symbols', [])
    print(f'{len(symbols)} symbols')
else:
    print('NO SIP FILE')
"
"""
    passed, out = run_test("SIP universe", sip_test)
    has_symbols = passed and "symbols" in out and "NO SIP" not in out
    status = "🟢" if has_symbols else "🔴"
    print(f"  {status} SIP universe: {out.strip()}")
    tests.append(("sip_universe", has_symbols))

    # 5. API connectivity
    print("\n[5/6] API CONNECTIVITY")
    
    # Polygon
    polygon_test = 'curl -s "https://api.polygon.io/v2/aggs/ticker/AAPL/prev?apiKey=ZBxeJYOn0_e0UcPgEYLA90CQ9S28_EfU" | grep -q "OK" && echo "OK"'
    passed, out = run_test("Polygon API", polygon_test)
    status = "🟢" if passed and "OK" in out else "🔴"
    print(f"  {status} Polygon API: {'Connected' if passed else 'FAILED'}")
    tests.append(("api_polygon", passed and "OK" in out))

    # IBKR Gateway
    ibkr_test = "nc -zv 127.0.0.1 7497 2>&1"
    passed, out = run_test("IBKR Gateway", ibkr_test)
    is_open = "succeeded" in out or "open" in out.lower()
    status = "🟢" if is_open else "⚠️ "
    print(f"  {status} IBKR Gateway: {'Connected' if is_open else 'Offline (start before market)'}")
    tests.append(("api_ibkr", is_open))  # Warning, not failure

    # NTFY
    ntfy_test = 'curl -s -X POST "https://ntfy.sh/jacobw-trading-status" -d "validation test" | grep -q "id" && echo "OK"'
    passed, out = run_test("NTFY", ntfy_test)
    status = "🟢" if passed else "🔴"
    print(f"  {status} NTFY notifications: {'Working' if passed else 'FAILED'}")
    tests.append(("api_ntfy", passed))

    # 6. Component interaction test
    print("\n[6/6] COMPONENT INTERACTIONS")
    interaction_test = """
cd /home/jacobw/quantstack/l2_scalping && PYTHONPATH=src python3 -c "
from data.l2_feed import L2Snapshot
from signals.l2_signals import L2SignalGenerator
from risk.risk_manager import RiskManager
from reporting.trade_journal import TradeJournal

sg = L2SignalGenerator({})
rm = RiskManager({})
tj = TradeJournal('/tmp/test.jsonl')

snap = L2Snapshot('TEST', 0, 10, 10.02, 10.01, 0.02, 1000, 800, 0.1, 0.1, 5000, 4000, 0.2, 0, 0)
signal = sg.generate_signal(snap)
rm.account_value = 100000
allowed, _ = rm.check_pre_trade_risk('TEST', 50, 10.01, 100000)
tj.record_signal('TEST', 'BUY', 0.8)
print('OK')
"
"""
    passed, out = run_test("Component interactions", interaction_test)
    status = "🟢" if passed and "OK" in out else "🔴"
    print(f"  {status} Signal→Risk→Journal flow: {'OK' if passed else out[:50]}")
    tests.append(("interactions", passed and "OK" in out))

    # Summary
    print("\n" + "=" * 70)
    print("VALIDATION SUMMARY")
    print("=" * 70)

    passed_count = sum(1 for _, p in tests if p)
    failed_count = len(tests) - passed_count
    
    critical_failures = [name for name, passed in tests 
                        if not passed and not name.startswith("api_ibkr")]

    if critical_failures:
        print(f"🔴 CRITICAL FAILURES ({len(critical_failures)}):")
        for name in critical_failures:
            print(f"   - {name}")
        print("\n⚠️  DO NOT START TRADING until failures are resolved!")
        return 1
    else:
        print(f"✅ All critical tests passed ({passed_count}/{len(tests)})")
        if not any(p for n, p in tests if n == "api_ibkr"):
            print("⚠️  IBKR Gateway offline - start before market open")
        print("\n🟢 System ready for trading")
        return 0


if __name__ == "__main__":
    sys.exit(main())
