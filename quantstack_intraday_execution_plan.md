# Quantstack Intraday ML – Project Management (Canonical)

## ✅ PHASE 1 COMPLETE (2025-12-16)

**Real IBKR data integration implemented and ready for testing.**

**Status**: Mock data issue resolved  
**Testing**: Run `python scripts/test_phase1_real_data.py`  
**See**: [LIVE_TRADING_UPGRADE_PLAN.md](LIVE_TRADING_UPGRADE_PLAN.md)

### Implementation Summary
- ✅ Created `IBKRMarketDataManager` for real-time streaming
- ✅ Updated ML predictor with proper cross-sectional features
- ✅ Removed mock data from live trading system
- ✅ Integrated historical bars for lookback features

## What the system does today
- **Historical training**: pulls 1m parquet bars from `/home/jacobw/gcs-mount/gold/stocks/1m/` for any symbol/date range; feature packs live in `qx-features`.
- **Daily SIP (live)**: `scripts/daily_sip_scheduler.py` fetches delayed Polygon data, applies the SIP scorer (`qx_data.live.polygon_sip.PolygonSIPSelector`), and writes `data/daily_sip/sip_universe_<date>.txt` and `l2_symbols_<date>.txt`.
- **Paper trading + L2**: `scripts/live_trading_system.py` loads the daily SIP universe, connects to IBKR for paper trading, and records L2 for top NYSE SIP names during opening/power hour via `QuantstackL2Collector`.

## Daily runbook (market days)
1) **Pre-flight**  
   - `python scripts/validate_data_integrations.py --check-polygon --check-ibkr` (requires Polygon key + IBKR Gateway).
   - Confirm gold mount is present if training/backfills are planned.
2) **Generate SIP**  
   - `python scripts/daily_sip_scheduler.py` → produces `data/daily_sip/sip_universe_<today>.txt` and `l2_symbols_<today>.txt`.
3) **Start live loop**  
   - `./start_live_system.sh` (checks Polygon/IBKR, then runs `scripts/live_trading_system.py`).
   - Monitor `logs/live_trading.log` for status: SIP size, IBKR status, L2 window transitions, trade attempts.
4) **Close-of-day**  
   - Collect logs and L2 snapshots (`data/live_l2/run_id=live_<yyyymmdd>`).  
   - Persist trade decisions from IBKR paper account if needed for PnL review.

## Training/backtest quick pilot (5-day concept proof)
```bash
. .venv/bin/activate
python - <<'PY'
import pandas as pd
from pathlib import Path
p = Path('/home/jacobw/gcs-mount/gold/stocks/1m/AAPL/2024/2024-01.parquet')
df = pd.read_parquet(p, columns=['ts','open','high','low','close','volume']).head(5*390)
print(df.head())
print(df.tail())
print('rows', len(df))
PY
```
Use the resulting slice to exercise feature pipelines (`qx-features`) or model training as needed.

## Ownership and artifacts
- **Canonical PM doc**: this file. No parallel PM docs exist.
- **Canonical tech doc**: `SYSTEM_TECH_DOC_INTRADAY_ML.md`.
- **Live outputs**: `data/daily_sip/*`, `data/live_l2/*`, `logs/live_trading.log`.
- **Code entrypoints**: `scripts/daily_sip_scheduler.py`, `scripts/live_trading_system.py`, `start_live_system.sh`.

## Open tasks (ordered)
1) Add a minimal smoke test for `PolygonSIPSelector.get_sip_universe` using a recorded response fixture.
2) Add a thin IBKR availability mock test for `LiveTradingSystem.check_ibkr_connection` to avoid live dependency in CI.
3) Wire an automated archive of daily SIP/L2 outputs to a dated folder for reproducibility.
4) Refresh model artifacts in `./models/regime_aware/` (current code loads them; ensure they are present/dated).

## Non-negotiables
- No mock/synthetic data in production paths (only in isolated tests with fixtures).
- No forward-looking leakage; maintain strict time ordering in all data/feature/label flows.
- Keep SIP/live behavior configuration-driven; avoid hard-coded symbol lists outside archived docs.
