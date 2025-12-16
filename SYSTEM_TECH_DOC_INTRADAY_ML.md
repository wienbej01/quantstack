# Intraday ML System – Technical (Canonical)

## High-level architecture
- **Historical data**: 1m OHLCV parquet from `/home/jacobw/gcs-mount/gold/stocks/1m/`.
- **Live SIP selection**: Delayed Polygon prev-bar endpoint, scored by `qx_data.live.polygon_sip.PolygonSIPSelector`; outputs `data/daily_sip/sip_universe_<date>.txt` and `l2_symbols_<date>.txt`.
- **Live execution**: `scripts/live_trading_system.py` loads the SIP universe, checks IBKR availability, collects L2 (opening + power hour) via `QuantstackL2Collector`, and paper-trades all SIP names through `PaperTrader` (IBKR).
- **Models**: Regime-aware predictors loaded from `./models/regime_aware/*_model.pkl` via `qx_data.live.ml_predictor.RegimeAwarePredictor`. Predictions feed a simple long/short policy (0.65/0.35 thresholds) in the live loop.
- **Features**: Engineered by `qx-features` (core_basics, regime_enhanced, VPA). Registry lives in `qx-features/src/qx_features/registry.py`.

## Data flows
1) **Training/backtest** (offline)
   - Source: gold 1m parquet → feature packs (see `qx-features/src/qx_features/core_basics.py` and `regime_enhanced.py`).
   - Targets/configs: stored under `configs/` (intraday ML variants).
   - Models saved to `./models/regime_aware/` and consumed by live predictor.
2) **Daily SIP (live)**
   - Script: `scripts/daily_sip_scheduler.py`
   - Selector: `qx_data.live.polygon_sip.PolygonSIPSelector.get_sip_universe(top_k=40)`
   - Outputs: `data/daily_sip/sip_universe_<date>.txt`, `data/daily_sip/l2_symbols_<date>.txt`
3) **Live loop**
   - Entry: `./start_live_system.sh` → `scripts/live_trading_system.py`
   - Checks: Polygon key, IBKR reachability (non-blocking), loads/creates SIP files.
   - L2 windows: 09:30–10:30 ET and 15:00–16:00 ET (NY only, top 6 SIP).
   - Trading: Paper orders on all SIP symbols when `RegimeAwarePredictor.predict` crosses >0.65 (BUY) or <0.35 (SELL). Logs to `logs/live_trading.log`.

## Key modules
- `qx_data/live/polygon_sip.py`: Polygon prev-bar fetch, HMM-style SIP scoring (price $5–50, vol ≥100k, gap/premarket-$ DV z-scores), NYSE filtering when needed.
- `qx_data/live/ml_predictor.py`: Loads regime models (`*_model.pkl`), extracts feature vector, returns probability for live policy.
- `qx_data/live/l2_collector.py`: Thin wrapper around `transalpha/l2` `MultiL2Collector` for IBKR Level 2 snapshots.
- `scripts/daily_sip_scheduler.py`: Batch SIP run + persistence.
- `scripts/live_trading_system.py`: Main orchestrator (SIP load/generate, IBKR connect, L2 polling, trading loop).
- `scripts/validate_data_integrations.py`: Sanity checks for gold mount, SIP artifacts, and optional Polygon/IBKR reachability.

## Operations and commands
- **Validate environment**: `python scripts/validate_data_integrations.py --check-polygon --check-ibkr`
- **Generate SIP**: `python scripts/daily_sip_scheduler.py`
- **Start live system**: `./start_live_system.sh` (runs `scripts/live_trading_system.py`)
- **Inspect logs**: `tail -f logs/live_trading.log`
- **L2 outputs**: `data/live_l2/run_id=live_<yyyymmdd>/`
- **SIP outputs**: `data/daily_sip/sip_universe_<date>.txt`, `data/daily_sip/l2_symbols_<date>.txt`

## Safety and constraints
- No synthetic/mocked data in production paths; use fixtures only in tests.
- Enforce time ordering: features/labels must not leak future information.
- IBKR checks are non-blocking: live loop continues SIP-only if IBKR is down.
- Polygon rate limiting is handled inside the selector; failures surface as errors.

## Dependencies
- Python 3.11, `ib_insync` for IBKR, `requests`/`pandas`/`pyarrow` for data handling, `qx-features` for feature packs.
- External services: Polygon (delayed prev-bar), IBKR Gateway/TWS on `127.0.0.1:7497` (paper).

## File map (intraday ML)
- Project mgmt: `quantstack_intraday_execution_plan.md`
- Technical (this file): `SYSTEM_TECH_DOC_INTRADAY_ML.md`
- Live scripts: `scripts/daily_sip_scheduler.py`, `scripts/live_trading_system.py`, `start_live_system.sh`
- SIP/L2 data: `data/daily_sip/`, `data/live_l2/`
- Models: `./models/regime_aware/`
- Features: `qx-features/src/qx_features/*`
