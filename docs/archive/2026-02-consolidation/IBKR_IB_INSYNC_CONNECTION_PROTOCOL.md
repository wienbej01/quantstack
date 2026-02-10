# IBKR ib_insync Connection Protocol (qx-broker)

This document defines the connection protocol and operating process for the
new ib_insync-based IBKR integration under `qx_broker.ibkr`. It replaces the
old CPAPI platform workflow and is the authoritative guide for connecting,
monitoring, and shutting down IBKR sessions across all services.

## Scope

Applies to all services using the IBKR gateway directly, with priority for:
- l2-collect
- l2-scalping
- intraday-paper
- monitoring and tooling (health checks, alerts)

## Goals

- Prevent client ID collisions and orphaned connections.
- Enforce a single event loop per service with deterministic threading rules.
- Maintain reliable L1/L2 data flow and order connectivity.
- Provide repeatable, production-safe startup/shutdown procedures.

## Components

- IBKR Gateway (TWS API) listening on `127.0.0.1:7494` (paper by default).
- `qx_broker.ibkr` modules:
  - `connection.py`: event loop + session lifecycle
  - `market_data.py`: L1 market data
  - `market_depth.py`: L2 depth
  - `orders.py`: order placement and tracking
  - `account.py`: positions, account summary, PnL
  - `health.py`: data freshness + connectivity checks

## Client ID Policy

Every service uses a dedicated client ID range to avoid cached conflicts.
Example ranges (update per environment):
- l2-collector: 1-99
- intraday-paper: 100-199
- l2-scalping: 200-299
- monitoring/health: 900-999

Rules:
- Each service starts at its base ID and may increment within its range on
  reconnect if the ID is in use.
- Never reuse the same client ID concurrently across services.
- When troubleshooting, confirm active IDs using the Gateway UI or logs.

## Connection Lifecycle

### 1) Gateway readiness
The IBKR Gateway must be running and authenticated before services connect.
Use the `ibkr-gateway-ready.service` systemd unit to block dependent services
until the gateway port is reachable.

Health signal examples:
- `systemctl status ibkr-gateway-ready.service`
- `nc -zv 127.0.0.1 7494`

### 2) Session creation
Each service creates an `IBKRSession` with a single event loop thread.
The event loop owns all IBKR calls. No IBKR API calls are allowed from
non-loop threads.

Minimal session setup:
- `IBKRConnectionConfig(host, port, client_id, timeouts)`
- `IBKRSessionConfig(system_name, connection)`
- `IBKRSession.start()` then `IBKRSession.connect()`

### 3) IBKR calls
All calls must be executed via:
- `session.call(...)` for blocking calls
- `session.call_soon(...)` for non-blocking work

Do not call `ib_insync.IB` methods directly from worker threads.

### 4) Request timeouts and error policy
- Set `IB.RequestTimeout` and `IB.RaiseRequestErrors=True`.
- Handle connection and client ID errors explicitly.
- On reconnect, allow ID fallback within the configured range.

### 5) Market data subscriptions
- L1: `IBKRMarketData.subscribe(contract, snapshot=False)`
- L2: `IBKRMarketDepth.subscribe(contract)`
- Enforce `num_rows <= 5` and `max_symbols <= 3` for L2 depth (IBKR limit).

### 6) Orders
- Use `IBKROrderManager` for order placement and lifecycle tracking.
- All orders must include `orderRef` tags:
  `system_name_client_id_prefix_strategy_symbol`
- For IOC orders, set TIF to `IOC` explicitly.

### 7) Account and PnL
- Use `IBKRAccount.positions()`, `accountSummary()`, and `reqPnL`.
- Subscribe to PnL once per account; reuse the subscription for monitoring.

### 8) Health checks
- `IBKRHealthChecker.check(max_age_sec=5)` validates:
  - connection
  - `reqCurrentTime` responsiveness
  - L1/L2 data freshness

### 9) Shutdown
- Cancel L2 depth and L1 subscriptions.
- Cancel open orders if needed.
- `session.disconnect()` and stop the event loop thread.

## Operational Runbook (systemd + manual gateway)

This system uses systemd timers for all services but requires a manual
IBKR Gateway/Portal startup and authentication each day.

### 1) Start IBKR Gateway/Portal and authenticate (manual UI)

- Launch IBKR Gateway (or TWS if configured).
- Log in to the paper account.
- In API settings, ensure:
  - "Enable ActiveX and Socket Clients" is enabled.
  - Socket port is `7494`.
  - Trusted IPs include `127.0.0.1`.
- Keep the UI session open for the trading day.

Confirm the port is reachable:

```bash
ss -ltn | rg ":7494"
nc -zv 127.0.0.1 7494
```

### 2) Run a preflight check (recommended)

```bash
python /home/jacobw/quantstack/scripts/preflight_check.py
```

Notes:
- Uses `IBKR_GATEWAY_HOST` (default `127.0.0.1`) and `IBKR_GATEWAY_PORT` (default `7494`).
- The default preflight client ID is `998` (utilities range). If that ID is in use, preflight will attempt a small fallback within the utilities range to avoid false failures.

### 3) Choose run mode

Production (systemd timers already enabled):

```bash
systemctl list-timers --all --no-pager | rg -n \
  "intraday-sip|preflight|l2-collector|l2-scalping|intraday-paper|system-health|daily-trade-report"
```

Manual start (debug/validation only; uses audit wrapper and clears old PIDs):

```bash
bash /home/jacobw/quantstack/scripts/start_new_platform_manual.sh
```

Manual logs:

```bash
tail -n 40 /home/jacobw/quantstack/logs/manual/l2_collect.log
tail -n 40 /home/jacobw/quantstack/logs/manual/l2_scalping.log
tail -n 40 /home/jacobw/intraday_stack/logs/paper_trade_manual.log
```

### 4) Validate L1 + L2 flow with a single symbol (paper only)

```bash
python - <<'PY'
from qx_broker.ibkr import (
    ContractFactory,
    IBKRConnectionConfig,
    IBKRDepthConfig,
    IBKRMarketData,
    IBKRMarketDataConfig,
    IBKRMarketDepth,
    IBKRSession,
    IBKRSessionConfig,
)

connection = IBKRConnectionConfig(host="127.0.0.1", port=7494, client_id=905)
session = IBKRSession(IBKRSessionConfig(system_name="MANUAL_TEST", connection=connection))
if not session.connect():
    raise RuntimeError("IBKR gateway not reachable")

factory = ContractFactory(session)
contract = factory.qualify(factory.stock("AAPL", exchange="SMART"))

market_data = IBKRMarketData(session, IBKRMarketDataConfig(snapshot=True))
market_data.subscribe(contract)
session.ib.sleep(2)
print("L1:", market_data.snapshot("AAPL"))

market_depth = IBKRMarketDepth(session, IBKRDepthConfig(num_rows=5, max_symbols=1))
market_depth.subscribe(contract)
session.ib.sleep(2)
print("L2:", market_depth.snapshot("AAPL"))

session.disconnect()
PY
```

### 5) Validate order connectivity (paper only)

```bash
python - <<'PY'
from ib_insync import MarketOrder
from qx_broker.ibkr import (
    ContractFactory,
    IBKRConnectionConfig,
    IBKROrderConfig,
    IBKROrderManager,
    IBKRSession,
    IBKRSessionConfig,
)

connection = IBKRConnectionConfig(host="127.0.0.1", port=7494, client_id=906)
session = IBKRSession(IBKRSessionConfig(system_name="MANUAL_TEST", connection=connection))
if not session.connect():
    raise RuntimeError("IBKR gateway not reachable")

factory = ContractFactory(session)
contract = factory.qualify(factory.stock("AAPL", exchange="SMART"))

orders = IBKROrderManager(session, IBKROrderConfig(order_ref_prefix="MANUAL"))
result = orders.place_order(contract, MarketOrder("BUY", 1, tif="IOC"), strategy="MANUAL")
session.ib.sleep(2)
print("Order status:", result.trade.orderStatus.status)

session.disconnect()
PY
```

### 6) L2 collector (manual run, debug only)

```bash
cd /home/jacobw/quantstack
l2-collect --once --symbols AAPL --log-level INFO
```

### 7) L2 scalping (manual validation, debug only)

Generate the daily SIP universe if not already present:

```bash
python /home/jacobw/intraday_stack/scripts/generate_daily_sip_universe.py \
  --date "$(date +%Y-%m-%d)"
```

Run the validation flow:

```bash
cd /home/jacobw/quantstack/l2_scalping
./run.sh validate
```

### 8) intraday-paper (manual run, debug only)

```bash
cd /home/jacobw/intraday_stack
python scripts/paper_trade.py --paper --once
```

### 9) Monitoring while running

```bash
ps aux | rg "l2-collect|l2-scalping|paper_trade"
tail -f /home/jacobw/quantstack/logs/l2_collector.log
tail -f /home/jacobw/intraday_stack/logs/paper_trade.log
```

### 10) Shutdown (emergency only)

Use Ctrl+C in each terminal. If a process is stuck:

```bash
pkill -f "/home/jacobw/.local/bin/l2-collect"
pkill -f "/home/jacobw/quantstack/l2_scalping/src/main.py"
pkill -f "/home/jacobw/intraday_stack/scripts/paper_trade.py"
pkill -f "audit_wrapper.sh l2-collect"
pkill -f "audit_wrapper.sh l2-scalping"
pkill -f "audit_wrapper.sh intraday-paper"
```

## Service Start Order (systemd)

1. Manually start and authenticate IBKR Gateway/Portal
2. `ibkr-gateway-ready.service` (port readiness gate)
3. Timers start: `intraday-sip`, `preflight-check`, `l2-collector`,
   `l2-scalping`, `intraday-paper` (see `docs/COMPLETE_SYSTEM_GUIDE.md`)
4. Monitoring services: `l2-watchdog`, `system-health-monitor`,
   `position-monitor` + `conky`

## Environment Variables

Common overrides:
- `IBKR_GATEWAY_HOST` (default `127.0.0.1`)
- `IBKR_GATEWAY_PORT` (default `7494`)
- `IBKR_HEALTH_CLIENT_ID` (default `998`)
- `IBKR_POSITION_CLIENT_ID` (default `900`)
- `IBKR_ACCOUNT_ID` (optional, for explicit account selection)

## Failure Modes and Actions

- Client ID in use:
  - Allow fallback to next ID within range, log the selected ID.
- Gateway down:
  - Services fail fast; systemd restarts after gateway-ready.
- No market data:
  - Treat as non-fatal during closed hours unless explicitly required.
- L2 depth errors (Error 309):
  - Reduce active symbols to 3 or fewer, log and disable extra symbols.

## Validation Checklist

Before market open:
- Gateway is running and authenticated.
- Preflight script passes (`scripts/preflight_check.py`).
- Health monitor shows gateway healthy.
- L1/L2 data can be received via `pytest -m ibkr` (opt-in).
- Manual tests completed before enabling systemd units.

## Example Usage

Create and connect a session:

```python
from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig

connection = IBKRConnectionConfig(host="127.0.0.1", port=7494, client_id=201)
session_cfg = IBKRSessionConfig(system_name="L2_SCALPING", connection=connection)
session = IBKRSession(session_cfg)

if not session.connect():
    raise RuntimeError("IBKR gateway not reachable")
```

Subscribe to L2 depth:

```python
from qx_broker.ibkr import ContractFactory, IBKRDepthConfig, IBKRMarketDepth

factory = ContractFactory(session)
contract = factory.stock("AAPL", exchange="NYSE")
contract = factory.qualify(contract)

market_depth = IBKRMarketDepth(session, IBKRDepthConfig(num_rows=5, max_symbols=3))
market_depth.subscribe(contract)
```

Place an IOC order:

```python
from ib_insync import LimitOrder
from qx_broker.ibkr import IBKROrderConfig, IBKROrderManager

orders = IBKROrderManager(session, IBKROrderConfig(order_ref_prefix="L2SCALP"))
order = LimitOrder("BUY", 10, 150.25, tif="IOC")
orders.place_order(contract, order)
```

## References

- ib_insync API docs: https://ib-insync.readthedocs.io/api.html
- Gateway readiness script: `scripts/wait_for_ibkr_gateway.sh`
- Health monitor: `system_health_monitor.py`
- Preflight checks: `scripts/preflight_check.py`
