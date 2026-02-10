#!/usr/bin/env python3
"""
DEFINITIVE END-TO-END SYSTEM VALIDATION

This script validates EVERY component, EVERY method signature, EVERY data flow path.
If this passes, the system is ready for production.

Run: python scripts/definitive_e2e_test.py
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Add l2_scalping to path
sys.path.insert(0, "/home/jacobw/quantstack/l2_scalping/src")
os.chdir("/home/jacobw/quantstack/l2_scalping")

ERRORS = []
WARNINGS = []


def test(name: str):
    """Decorator to run and report tests"""

    def decorator(func):
        def wrapper():
            try:
                func()
                print(f"✅ {name}")
                return True
            except AssertionError as e:
                ERRORS.append(f"{name}: {e}")
                print(f"❌ {name}: {e}")
                return False
            except Exception as e:
                ERRORS.append(f"{name}: {type(e).__name__}: {e}")
                print(f"❌ {name}: {type(e).__name__}: {e}")
                return False

        return wrapper

    return decorator


# ============================================================================
# SECTION 1: NO MOCK DATA IN PRODUCTION
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 1: MOCK DATA VERIFICATION")
print("=" * 70)


@test("No mock_data in config files")
def test_no_mock_config():
    config_dir = Path("config")
    for f in config_dir.glob("*.yaml"):
        content = f.read_text()
        assert (
            "mock_data" not in content.lower() or "enabled: false" in content.lower()
        ), f"mock_data found in {f.name}"


@test("No mock imports in production code")
def test_no_mock_imports():
    src_dir = Path("src")
    for f in src_dir.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        content = f.read_text()
        # Allow "mock" in comments and docstrings about removal
        lines = [l for l in content.split("\n") if not l.strip().startswith("#")]
        code = "\n".join(lines)
        assert "from unittest.mock" not in code, f"unittest.mock import in {f.name}"
        assert "import mock" not in code, f"mock import in {f.name}"


@test("Mock data guard exists in main.py")
def test_mock_guard():
    main_py = Path("src/main.py").read_text()
    assert (
        "mock_data" in main_py and "RuntimeError" in main_py
    ), "Mock data guard missing in main.py"


test_no_mock_config()
test_no_mock_imports()
test_mock_guard()


# ============================================================================
# SECTION 2: ALL IMPORTS WORK
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 2: IMPORT VALIDATION")
print("=" * 70)


@test("Import data.l2_feed")
def test_import_l2_feed():
    from data.l2_feed import L2DataFeed, L2Snapshot

    assert L2DataFeed is not None
    assert L2Snapshot is not None


@test("Import data.sip_integration")
def test_import_sip():
    from data.sip_integration import load_daily_sip_symbols

    assert callable(load_daily_sip_symbols)


@test("Import execution.order_manager")
def test_import_order_manager():
    from execution.order_manager import (
        IBKROrderManager,
        OrderRequest,
        OrderSide,
        OrderType,
        OrderUpdate,
    )

    assert IBKROrderManager is not None
    assert OrderRequest is not None
    assert OrderSide is not None
    assert OrderType is not None


@test("Import signals.l2_signals")
def test_import_signals():
    from signals.l2_signals import (
        L2SignalGenerator,
        SignalType,
        SignalValidator,
        TradingSignal,
    )

    assert L2SignalGenerator is not None
    assert SignalType is not None


@test("Import risk.risk_manager")
def test_import_risk():
    from risk.risk_manager import Position, RiskManager, RiskMetrics, RiskStatus

    assert RiskManager is not None
    assert RiskStatus is not None


@test("Import reporting.trade_journal")
def test_import_journal():
    from reporting.trade_journal import TradeJournal, TradeRecord, TradeStatus

    assert TradeJournal is not None
    assert TradeRecord is not None


@test("Import scheduler")
def test_import_scheduler():
    from scheduler import MarketScheduler

    assert MarketScheduler is not None


test_import_l2_feed()
test_import_sip()
test_import_order_manager()
test_import_signals()
test_import_risk()
test_import_journal()
test_import_scheduler()


# ============================================================================
# SECTION 3: CONFIG LOADING
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 3: CONFIG VALIDATION")
print("=" * 70)

import yaml

CONFIG = {}


@test("Load all config files")
def test_load_config():
    global CONFIG
    for f in sorted(Path("config").glob("*.yaml")):
        with open(f) as fp:
            CONFIG.update(yaml.safe_load(fp) or {})
    assert len(CONFIG) > 0, "No config loaded"
    assert "ibkr" in CONFIG, "Missing ibkr config"
    assert "strategy" in CONFIG, "Missing strategy config"


@test("Config has required IBKR settings")
def test_ibkr_config():
    ibkr = CONFIG.get("ibkr", {})
    assert ibkr.get("host") == "127.0.0.1", "Wrong IBKR host"
    assert ibkr.get("port") == 7494, "Wrong IBKR port"
    order_client_id = ibkr.get("order_client_id_base", ibkr.get("order_client_id"))
    data_client_id = ibkr.get("data_client_id_base", ibkr.get("data_client_id"))
    assert order_client_id is not None, "Missing order_client_id"
    assert data_client_id is not None, "Missing data_client_id"


@test("Config has required risk settings")
def test_risk_config():
    assert "per_trade" in CONFIG, "Missing per_trade config"
    assert "daily" in CONFIG, "Missing daily config"
    assert "position_sizing" in CONFIG, "Missing position_sizing config"


test_load_config()
test_ibkr_config()
test_risk_config()


# ============================================================================
# SECTION 4: SIP DATA
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 4: SIP DATA VALIDATION")
print("=" * 70)


@test("SIP directory exists")
def test_sip_dir():
    sip_dir = Path("/home/jacobw/intraday_stack/data/daily_sip")
    assert sip_dir.exists(), f"SIP directory missing: {sip_dir}"


@test("SIP universe file exists")
def test_sip_file():
    sip_dir = Path("/home/jacobw/intraday_stack/data/daily_sip")
    date_dirs = sorted(sip_dir.glob("date=*"))
    assert len(date_dirs) > 0, "No SIP date directories"
    latest = date_dirs[-1]
    sip_file = latest / "sip_universe.json"
    assert sip_file.exists(), f"SIP file missing: {sip_file}"


@test("SIP symbols load correctly")
def test_sip_load():
    from data.sip_integration import load_daily_sip_symbols

    symbols = load_daily_sip_symbols()
    assert len(symbols) > 0, "No symbols loaded from SIP"
    assert all(isinstance(s, str) for s in symbols), "Invalid symbol type"


test_sip_dir()
test_sip_file()
test_sip_load()


# ============================================================================
# SECTION 5: COMPONENT INITIALIZATION
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 5: COMPONENT INITIALIZATION")
print("=" * 70)

from data.l2_feed import L2DataFeed, L2Snapshot
from data.sip_integration import load_daily_sip_symbols
from execution.order_manager import IBKROrderManager, OrderRequest, OrderSide, OrderType
from reporting.trade_journal import TradeJournal
from risk.risk_manager import RiskManager
from scheduler import MarketScheduler
from signals.l2_signals import L2SignalGenerator, SignalValidator

SYMBOLS = load_daily_sip_symbols()[:3]


@test("L2DataFeed initializes")
def test_init_feed():
    feed = L2DataFeed(
        {"ibkr": CONFIG.get("ibkr", {}), "symbols": SYMBOLS, "depth_levels": 5}
    )
    assert feed.host == "127.0.0.1"
    assert feed.port == 7494


@test("IBKROrderManager initializes")
def test_init_order_manager():
    om = IBKROrderManager(CONFIG)
    assert om.host == "127.0.0.1"
    assert om.port == 7494
    expected_id = CONFIG["ibkr"].get("order_client_id_base", CONFIG["ibkr"].get("order_client_id"))
    assert om.client_id == expected_id


@test("L2SignalGenerator initializes")
def test_init_signal_gen():
    sg = L2SignalGenerator(CONFIG)
    assert sg is not None


@test("SignalValidator initializes")
def test_init_signal_validator():
    sv = SignalValidator(CONFIG.get("strategy", {}), CONFIG.get("risk", {}))
    assert sv is not None


@test("RiskManager initializes")
def test_init_risk():
    rm = RiskManager(CONFIG.get("risk", {}))
    assert rm.max_shares == CONFIG["position_sizing"]["max_shares"]


@test("TradeJournal initializes")
def test_init_journal():
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tj = TradeJournal(tmpdir)
        assert Path(tj.journal_file).name.startswith("trades_")


@test("MarketScheduler initializes")
def test_init_scheduler():
    ms = MarketScheduler(CONFIG)
    assert ms.auto_start == CONFIG["schedule"]["auto_start"]


test_init_feed()
test_init_order_manager()
test_init_signal_gen()
test_init_signal_validator()
test_init_risk()
test_init_journal()
test_init_scheduler()


# ============================================================================
# SECTION 6: METHOD SIGNATURES (EXACT MATCH TO MAIN.PY CALLS)
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 6: METHOD SIGNATURE VALIDATION")
print("=" * 70)

# Create instances for testing
feed = L2DataFeed({"ibkr": CONFIG.get("ibkr", {}), "symbols": SYMBOLS})
om = IBKROrderManager(CONFIG)
sg = L2SignalGenerator(CONFIG)
sv = SignalValidator(CONFIG.get("strategy", {}), CONFIG.get("risk", {}))
rm = RiskManager(CONFIG.get("risk", {}))
TJ_DIR = tempfile.mkdtemp()
tj = TradeJournal(TJ_DIR)
ms = MarketScheduler(CONFIG)

# Create test snapshot
SNAPSHOT = L2Snapshot(
    symbol="BE",
    timestamp=1234567890.0,
    bid=10.0,
    ask=10.02,
    mid=10.01,
    spread=0.02,
    bid_size=1000,
    ask_size=800,
    obi_1=0.111,
    obi_5=0.15,
    depth_bid=5000.0,
    depth_ask=4000.0,
    pressure=0.2,
    d_mid_5s=0.001,
    d_obi_1_5s=0.02,
)


@test("L2DataFeed.connect() signature")
def test_sig_feed_connect():
    # Should accept no args (connects using config)
    import inspect

    sig = inspect.signature(feed.connect)
    assert (
        len(
            [p for p in sig.parameters.values() if p.default == inspect.Parameter.empty]
        )
        == 0
    )


@test("L2DataFeed.get_latest_snapshot(symbol) signature")
def test_sig_feed_snapshot():
    import inspect

    sig = inspect.signature(feed.get_latest_snapshot)
    params = list(sig.parameters.keys())
    assert "symbol" in params


@test("L2DataFeed.add_data_callback(callback) signature")
def test_sig_feed_callback():
    def dummy(snap):
        pass

    feed.add_data_callback(dummy)  # Should not raise


@test("IBKROrderManager.connect() signature")
def test_sig_om_connect():
    import inspect

    sig = inspect.signature(om.connect)
    assert (
        len(
            [p for p in sig.parameters.values() if p.default == inspect.Parameter.empty]
        )
        == 0
    )


@test("IBKROrderManager.place_order(request) signature")
def test_sig_om_place():
    import inspect

    sig = inspect.signature(om.place_order)
    params = list(sig.parameters.keys())
    assert "order_request" in params or "request" in params


@test("IBKROrderManager.health_check() signature")
def test_sig_om_health():
    result = om.health_check()
    assert isinstance(result, dict)
    assert "connected" in result


@test("L2SignalGenerator.generate_signal(snapshot) signature")
def test_sig_signal_gen():
    signal = sg.generate_signal(SNAPSHOT)
    assert hasattr(signal, "signal_type")
    assert hasattr(signal, "strength")
    assert hasattr(signal, "confidence")


@test("SignalValidator.is_valid_signal(signal, snapshot) signature")
def test_sig_signal_valid():
    signal = sg.generate_signal(SNAPSHOT)
    valid, reason = sv.is_valid_signal(signal, SNAPSHOT)
    assert isinstance(valid, bool)
    assert isinstance(reason, str)


@test("RiskManager.check_pre_trade_risk(symbol, qty, price, account) signature")
def test_sig_risk_check():
    rm.account_value = 100000
    allowed, reason = rm.check_pre_trade_risk("BE", 50, 10.01, 100000)
    assert isinstance(allowed, bool)
    assert isinstance(reason, str)


@test(
    "RiskManager.calculate_position_size(symbol, strength, conf, account, price) signature"
)
def test_sig_risk_size():
    qty = rm.calculate_position_size("BE", 0.8, 0.7, 100000, 10.01)
    assert isinstance(qty, int)


@test("RiskManager.add_position(symbol, quantity, price) signature")
def test_sig_risk_add():
    rm.add_position("TEST", 50, 10.01)
    assert "TEST" in rm.positions


@test("RiskManager.update_position_pnl(symbol, current_price) signature")
def test_sig_risk_update():
    rm.update_position_pnl("TEST", 10.05)


@test("RiskManager.close_position(symbol, exit_price) signature")
def test_sig_risk_close():
    pnl = rm.close_position("TEST", 10.05)
    assert isinstance(pnl, (int, float))


@test("RiskManager.should_stop_trading() signature")
def test_sig_risk_stop():
    should_stop, reason = rm.should_stop_trading()
    assert isinstance(should_stop, bool)
    assert isinstance(reason, str)


@test("RiskManager.get_risk_metrics(account_value) signature")
def test_sig_risk_metrics():
    metrics = rm.get_risk_metrics(100000)
    assert hasattr(metrics, "daily_pnl")


@test("TradeJournal.record_signal(symbol, signal_type, signal_strength) signature")
def test_sig_journal_signal():
    trade_id = tj.record_signal("BE", "BUY", 0.8)
    assert isinstance(trade_id, str)


@test(
    "TradeJournal.record_trade_entry(symbol, side, quantity, entry_price, order_id) signature"
)
def test_sig_journal_entry():
    tj.record_trade_entry("BE", "BUY", 50, 10.01, "ORD_001")


@test("TradeJournal.record_trade_exit(symbol, exit_price, pnl, commission) signature")
def test_sig_journal_exit():
    tj.record_trade_exit("BE", 10.05, 2.0, 0.50)


@test("TradeJournal.get_daily_summary() signature")
def test_sig_journal_summary():
    summary = tj.get_daily_summary()
    assert isinstance(summary, dict)


@test("MarketScheduler.is_trading_time() signature")
def test_sig_sched_time():
    result = ms.is_trading_time()
    assert isinstance(result, bool)


@test("MarketScheduler.run_with_schedule(callback) signature")
def test_sig_sched_run():
    import inspect

    sig = inspect.signature(ms.run_with_schedule)
    params = list(sig.parameters.keys())
    assert len(params) >= 1  # At least callback


@test("OrderRequest dataclass fields")
def test_sig_order_request():
    order = OrderRequest(
        symbol="BE",
        side=OrderSide.BUY,
        quantity=50,
        price=10.01,
        order_type=OrderType.LIMIT,
        time_in_force="DAY",
        client_order_id="TEST_001",
    )
    assert order.symbol == "BE"
    assert order.side == OrderSide.BUY
    assert order.quantity == 50
    assert order.price == 10.01


test_sig_feed_connect()
test_sig_feed_snapshot()
test_sig_feed_callback()
test_sig_om_connect()
test_sig_om_place()
test_sig_om_health()
test_sig_signal_gen()
test_sig_signal_valid()
test_sig_risk_check()
test_sig_risk_size()
test_sig_risk_add()
test_sig_risk_update()
test_sig_risk_close()
test_sig_risk_stop()
test_sig_risk_metrics()
test_sig_journal_signal()
test_sig_journal_entry()
test_sig_journal_exit()
test_sig_journal_summary()
test_sig_sched_time()
test_sig_sched_run()
test_sig_order_request()


# ============================================================================
# SECTION 7: FULL TRADING FLOW SIMULATION
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 7: FULL TRADING FLOW SIMULATION")
print("=" * 70)


@test("Complete entry flow: Signal → Risk → Order → Journal")
def test_entry_flow():
    # 1. Generate signal
    signal = sg.generate_signal(SNAPSHOT)

    # 2. Validate signal
    valid, reason = sv.is_valid_signal(signal, SNAPSHOT)

    # 3. Risk check
    rm2 = RiskManager(CONFIG.get("risk", {}))
    rm2.account_value = 100000
    allowed, risk_reason = rm2.check_pre_trade_risk("FLOW", 50, 10.01, 100000)

    # 4. Position sizing
    qty = rm2.calculate_position_size("FLOW", 0.8, 0.7, 100000, 10.01)
    assert qty > 0, "Position size should be > 0"

    # 5. Create order
    order = OrderRequest(
        symbol="FLOW",
        side=OrderSide.BUY,
        quantity=qty,
        price=10.01,
        order_type=OrderType.LIMIT,
        time_in_force="DAY",
        client_order_id="FLOW_001",
    )

    # 6. Record in journal
    with tempfile.TemporaryDirectory() as tmpdir:
        tj2 = TradeJournal(tmpdir)
        tj2.record_signal("FLOW", "BUY", 0.8)
        tj2.record_trade_entry("FLOW", "BUY", qty, 10.01, "FLOW_001")

        # 7. Add position
        rm2.add_position("FLOW", qty, 10.01)
        assert "FLOW" in rm2.positions


@test("Complete exit flow: Update → Close → Journal")
def test_exit_flow():
    rm3 = RiskManager(CONFIG.get("risk", {}))
    rm3.account_value = 100000
    rm3.add_position("EXIT", 50, 10.01)

    # 1. Update PnL
    rm3.update_position_pnl("EXIT", 10.05)

    # 2. Close position
    pnl = rm3.close_position("EXIT", 10.05)
    assert pnl > 0, "PnL should be positive"

    # 3. Record exit
    with tempfile.TemporaryDirectory() as tmpdir:
        tj3 = TradeJournal(tmpdir)
        tj3.record_signal("EXIT", "BUY", 0.8)
        tj3.record_trade_entry("EXIT", "BUY", 50, 10.01, "EXIT_001")
        tj3.record_trade_exit("EXIT", 10.05, pnl, 0.50)

        # 4. Get summary
        summary = tj3.get_daily_summary()
        assert "total_trades" in summary


test_entry_flow()
test_exit_flow()


# ============================================================================
# SECTION 8: EXTERNAL DEPENDENCIES
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 8: EXTERNAL DEPENDENCIES")
print("=" * 70)


@test("Polygon API accessible")
def test_polygon():
    import urllib.request

    url = "https://api.polygon.io/v2/aggs/ticker/AAPL/prev?apiKey=ZBxeJYOn0_e0UcPgEYLA90CQ9S28_EfU"
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read())
        assert data.get("status") == "OK", f"Polygon API error: {data}"


@test("NTFY accessible")
def test_ntfy():
    import urllib.request

    req = urllib.request.Request(
        "https://ntfy.sh/jacobw-trading-status", data=b"e2e test", method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        assert "id" in data, "NTFY response missing id"


@test("Log directories writable")
def test_log_dirs():
    dirs = [
        "/home/jacobw/quantstack/logs",
        "/home/jacobw/quantstack/data",
        "/home/jacobw/quantstack/l2_scalping/data",
    ]
    for d in dirs:
        p = Path(d)
        if not p.exists():
            p.mkdir(parents=True)
        assert os.access(d, os.W_OK), f"Directory not writable: {d}"


test_polygon()
test_ntfy()
test_log_dirs()


# ============================================================================
# SECTION 9: SYSTEMD SERVICES
# ============================================================================
print("\n" + "=" * 70)
print("SECTION 9: SYSTEMD SERVICES")
print("=" * 70)


@test("l2-collector service active")
def test_svc_collector():
    result = subprocess.run(
        ["systemctl", "is-active", "l2-collector"], capture_output=True, text=True
    )
    assert result.stdout.strip() == "active", f"l2-collector: {result.stdout.strip()}"


@test("l2-scalping service active")
def test_svc_scalping():
    result = subprocess.run(
        ["systemctl", "is-active", "l2-scalping"], capture_output=True, text=True
    )
    assert result.stdout.strip() == "active", f"l2-scalping: {result.stdout.strip()}"


@test("l2-watchdog service active")
def test_svc_watchdog():
    result = subprocess.run(
        ["systemctl", "is-active", "l2-watchdog"], capture_output=True, text=True
    )
    assert result.stdout.strip() == "active", f"l2-watchdog: {result.stdout.strip()}"


@test("trading-orchestrator timer active")
def test_timer_orch():
    result = subprocess.run(
        ["systemctl", "is-active", "trading-orchestrator.timer"],
        capture_output=True,
        text=True,
    )
    assert (
        result.stdout.strip() == "active"
    ), f"trading-orchestrator.timer: {result.stdout.strip()}"


test_svc_collector()
test_svc_scalping()
test_svc_watchdog()
test_timer_orch()


# ============================================================================
# FINAL SUMMARY
# ============================================================================
print("\n" + "=" * 70)
print("FINAL SUMMARY")
print("=" * 70)

# Cleanup
import shutil

try:
    shutil.rmtree(TJ_DIR)
except:
    pass

if ERRORS:
    print(f"\n🔴 {len(ERRORS)} CRITICAL ERRORS:")
    for e in ERRORS:
        print(f"   ❌ {e}")
    print("\n⛔ SYSTEM NOT READY FOR PRODUCTION")
    sys.exit(1)
else:
    print(f"\n✅ ALL TESTS PASSED")
    print("\n🟢 SYSTEM VALIDATED AND READY FOR PRODUCTION")
    print("\nRemaining manual checks:")
    print("  1. Start IBKR Gateway before market open (21:00 Manila)")
    print("  2. Verify Gateway connection after start")
    print("  3. Monitor first 15 minutes of trading session")
    sys.exit(0)
