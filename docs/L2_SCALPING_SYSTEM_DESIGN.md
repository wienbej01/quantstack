# L2 Scalping Trading System Design (SIP + IBKR)

**Doc version**: 0.2  
**Date**: 2025-12-20  
**Scope**: Paper trading first (IBKR paper), NYSE L2 focus, 2 Hz decision cadence

This document specifies a scalping trading system design built on the L2 analysis in:
- `docs/L2_SCALPING_SYSTEM_FOUNDATION.md`
- `docs/L2_SCALPING_QUICK_REFERENCE.md`
- Signal prototypes: `data/l2_maximum/exports/l2_signals.py`
- Feature schema reference: `data/l2_maximum/features_v2/`

The system is **SIP-first** (daily Stock-In-Play universe) with **L2-driven**:
1) entry/exit decisions, 2) execution, 3) risk management.

Hard safety constraints for the initial paper pilot:
- **Max risk**: ≤ **1% of equity** per position (risk-at-stop).
- **Max size**: ≤ **100 shares** (testing cap).
- **No mock feeds in production code paths**. Mock data/code may be used only during
  development and must be removed before paper testing.

---

## 1. Strategic Thesis (What We’re Exploiting)

The analysis demonstrates exploitable microstructure structure at a 5–15 second horizon:

1) **OBI regime persistence** (high autocorrelation) supports regime-confirmed decisions.
2) **OBI → short-horizon momentum** (directional continuation) is the primary directional alpha.
3) **Hidden liquidity** is a strong adverse-selection indicator; it is primarily used as a
   **filter** (and optionally as a separate contrarian “do-not-enter” regime).
4) **Spread + depth dynamics** are primarily **execution alpha**, not direction alpha.

Practical target for the first system iteration:
- **Hold**: 5–15 seconds
- **Target**: ~15–20 bps gross (instrument-dependent; typically 1–2 ticks in many names)
- **Stop**: ~10 bps hard stop + “regime break” exit

---

## 2. Operating Constraints (Non-negotiable)

### 2.1 Connectivity and market data
- Broker/data: **IBKR via `ib_insync`** (existing modules under `qx-data/src/qx_data/live/`).
- L2: **IBKR Market Depth** (OpenBook/NYSE-only preferred; see `docs/PAPER_TRADING_GUIDE.md`).
- **Depth subscription caps** exist (see comments in `scripts/daily_sip_scheduler.py`).
  The design must function correctly with `max_l2_symbols` in the range **[1..6]** and
  degrade gracefully when the practical cap is 3.

### 2.2 Universe
- Daily SIP universe is produced by existing modules:
  - `scripts/daily_sip_scheduler.py` (Polygon-based SIP selection, persisted under
    `data/daily_sip/`)
  - `qx-data/src/qx_data/live/polygon_sip.py` (Polygon SIP selector)
- L2 scalping **only trades symbols with active L2 depth**. The “full SIP universe”
  may be used for monitoring/ranking, but the scalper trades the **L2 focus set**.

### 2.3 Risk and safety
- Max risk-at-stop per open position: **1% of account equity**.
- Max position size: **100 shares** (pilot cap).
- Kill switches:
  - Daily loss limit (recommend: **100 bps** of equity; configurable).
  - Data health degradation: stale L2, missing depth, repeated IBKR depth errors.
  - Connectivity loss: IBKR disconnect while positions exist ⇒ **flatten** (paper-safe).

### 2.4 Determinism and “no-mock” policy
- Production modules must not contain a “mock mode” or fall back to mock data.
- Any mock data/code used for early functional testing must be removed prior to paper test.
- Release checklist includes greps and runtime assertions (see §11.4).

---

## 3. Reference Data Model (Features v2)

The L2 decision engine consumes the feature set as defined in `features_v2` (36 columns):

- **Microstructure**: `mid`, `spread`, `microprice`, `micro_off`
- **Depth**: `depth_bid_k`, `depth_ask_k`, `depth_imb_k`, `pressure_k`
- **OBI levels**: `obi_1`, `obi_2`, `obi_3`, `obi_5`, `obi_10`
- **Dynamics** (deltas): `{mid, spread, obi_1, micro_off} × {5s, 15s, 30s, 60s}`

Live computation should be performed by the existing L2 feature pipeline (`qx-l2`) using:

```yaml
features:
  enabled: true
  obi_levels: [1, 2, 3, 5, 10]
  delta_windows_sec: [5, 15, 30, 60]
collection:
  snapshot_interval_ms: 500   # 2 Hz
```

---

## 4. System Architecture

### 4.1 Process topology (recommended)

Two-process design for safety and separation of concerns:

1) **Universe & L2 Data Service** (collector)
   - Universe selection (daily SIP + L2 focus set)
   - IBKR L2 subscriptions
   - Feature computation (features v2)
   - Journaling + storage

2) **Scalper Trading Service** (strategy/execution)
   - Consumes latest features (shared memory/event bus or in-process callback)
   - Runs decision engine at 2 Hz (or on-feature)
   - Runs risk checks + sizing
   - Submits/cancels orders via IBKR (paper account)
   - Full event logging and post-trade attribution

If latency or engineering time requires, the system can be a **single process** initially,
but must keep clean module boundaries so it can be split later.

### 4.2 Module-level architecture

```
          ┌──────────────────────────────────────────────────┐
          │                 Daily Universe                    │
          │  SIP selection (existing) + L2 focus selection    │
          └──────────────────────────────────────────────────┘
                               │
                               ▼
┌───────────────────────┐  ┌───────────────────────────────┐
│ L2 Collector (qx-l2)   │  │ IBKR L1 / account / orders     │
│ - reqMktDepth          │  │ (qx-data live modules)         │
│ - snapshot @ 2 Hz      │  └───────────────────────────────┘
│ - compute features_v2  │                 │
└───────────┬───────────┘                 │
            │ latest features             │
            ▼                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 L2 Decision Engine (pure)                   │
│ - signal generation (OBI, hidden liquidity, etc.)            │
│ - entry/exit state machine per symbol                        │
│ - produces TradeIntent (side, urgency, stop/target)          │
└───────────┬─────────────────────────────────────────────────┘
            │ intents
            ▼
┌─────────────────────────────────────────────────────────────┐
│                 L2 Risk Manager (stateful)                  │
│ - size() with 1% equity risk bound + 100 share cap           │
│ - kill switches + cooldowns                                  │
└───────────┬─────────────────────────────────────────────────┘
            │ approved orders
            ▼
┌─────────────────────────────────────────────────────────────┐
│                 L2 Execution Engine (IBKR)                  │
│ - order type selection from L2 context                       │
│ - bracket management OR manual stop/target                   │
│ - fill tracking + cancel/replace                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Universe Selection (SIP → Trade Set)

### 5.1 Inputs
- SIP universe: `data/daily_sip/sip_universe_YYYY-MM-DD.txt`
- L2 focus: `data/daily_sip/l2_symbols_YYYY-MM-DD.txt`
- Alternative: call `run_daily_sip_selection()` from `scripts/daily_sip_scheduler.py`

### 5.2 Trade universe policy
For the scalper, the **tradeable universe** is the **L2 focus set** (size `N_l2`).

Recommended default policy:
- `N_l2 = 3` (compatible with common IBKR depth limits)
- `N_trade = N_l2` (trade only depth-subscribed names)
- If `N_l2 > 3` is feasible, enable up to 6 symbols, but keep a hard cap.

### 5.3 Rotation policy (data vs trading)
Rotation is useful for data collection but harmful for scalping (it creates blind periods).

Policy:
- **No rotation for trade symbols** (continuous depth required).
- Optional: a separate rotating pool for **data collection only** (future ML).

Implementation hook:
- Use `qx-l2/src/qx_l2/symbols.py` in `external` mode and inject symbols from SIP outputs.

---

## 6. Macro Context Layer (Intraday)

This layer adds slower-timeframe context (1m–60m) to condition the 2 Hz L2 scalper.
It is used for gating, threshold modulation, and risk throttling (not as the entry trigger).

### 6.1 Data sources
- Per-symbol intraday bars: 1m OHLCV (+VWAP if available), RTH + optional premarket.
- Market ETFs: SPY, QQQ, IWM (risk regime + beta proxy).
- Sector ETFs: XLF, XLK, XLE, XLI, XLY, XLP, XLV, XLU, XLB, XLRE, XLC (optional).
- Daily SIP metadata (static day context): gap_pct, atr14, adv20, sip_score.

### 6.2 Feature families (recommended)

**A) Ticker technicals (1m/5m/15m)**
- Trend: EMA(9/21) slope, return_1m/5m/15m, regression_slope_5m.
- Mean-reversion anchor: distance_to_session_vwap, distance_to_open_vwap.
- Volatility: ATR_1m(14), realized_vol_5m/15m, range_pct_1m.
- Structure: opening_range_{5m,15m} high/low, session_high/low.

**B) Cross-sectional + cross-sector context**
- Reuse the existing cross-sectional concepts from the regime system where possible:
  `sector_momentum`, `cross_dispersion`, `market_breadth`, `up_down_ratio`.
- Market regime: SPY_ret_5m/15m, SPY_realized_vol_15m, breadth_SIP_5m (optional).
- Relative strength: sym_ret_5m - SPY_ret_5m, sym_ret_5m - sector_ret_5m.
- Dispersion: cross_dispersion_5m (universe or SIP-only).
- Sector momentum: sector_etf_ret_5m/15m and sector_rank among sectors.

**C) VPA (volume/price action)**
- Volume regime: vol_z_1m, vol_z_5m (rolling z-score vs last 30–60m).
- Effort vs result: volume_per_range_1m, close_location_value (CLV).
- Participation: cum_vol_ratio (cum vol vs baseline at same time-of-day), if available.

**D) ICT-style features (research-gated; objective definitions only)**
- Key levels: prev_day_high/low, premarket_high/low, opening_range_high/low.
- Liquidity sweeps: break_and_reclaim_{PDH,PDL,PMH,PML} within N bars.
- Displacement: body_zscore_1m, range_expansion_1m vs rolling baseline.
- Fair value gap proxy: 3-bar gap features on 1m/5m candles.

### 6.3 How context conditions the scalper
Default use is filters + parameter modulation:
- Directional gate: only take long scalps when 5m trend >= 0 and market regime not risk-off.
- Threshold modulation: in aligned context allow `obi_1` entry at 0.25–0.30; else 0.35+.
- Risk throttle: if realized vol is high or spread stress is elevated, reduce size and trades/day.
- Level-awareness: avoid entries into nearby resistance/support; use levels as take-profit magnets.

### 6.4 Update cadence and staleness rules
- Context updates on each completed 1m bar; multi-timeframe features roll up from 1m bars.
- L2 loop reads the latest context snapshot; if stale > 120s, treat as unknown context.
- Unknown context behavior: trade only high-conviction L2 signals with stricter thresholds.

### 6.5 Priority order (what to build first)
- v1 (high ROI): time-of-day, VWAP distance, 5m trend, realized vol, volume spike z-scores.
- v2 (next): sector ETF momentum + SIP breadth/dispersion + relative strength.
- v3 (research): ICT sweep/FVG/order-block heuristics behind strict feature toggles.

---

## 7. L2 Signal & Decision Engine

### 7.1 Signals (from `l2_signals.py`, generalized)

Core primitives:
- `obi_regime(obi_1) -> buy/sell/neutral`
- `detect_hidden_liquidity(obi_1, obi_5) -> hidden_buy/hidden_sell/none`
- `execution_window(obi_1, depth_bid_k, depth_ask_k) -> favorable_buy/favorable_sell/neutral`
- `composite_entry_score(obi_1, obi_5, pressure_k, pressure_mean, pressure_std) -> [0,1]`

### 7.2 Calibration (required for SIP-wide trading)

The analysis-derived per-symbol constants (pressure stats, thin-book thresholds) only
exist for a few symbols. To trade arbitrary SIP tickers, we need **online calibration**:

Per symbol, maintain rolling estimates:
- `median_spread` (rolling median over last 5–10 minutes)
- `p10_depth_bid`, `p10_depth_ask` (rolling 10th percentile over last 5–10 minutes)
- `pressure_mean`, `pressure_std` (rolling mean/std over last 5–10 minutes)

Warmup rules:
- No trades until a minimum warmup (e.g., 120 seconds of valid depth snapshots).
- If calibration cannot converge (depth missing), disable symbol for the session.

### 7.3 Entry logic (initial production candidate)

We implement two **entry archetypes**; the decision engine selects one per opportunity:

**A) OBI Momentum (primary)**
- Direction:
  - Long if `obi_1 >= +0.3`
  - Short if `obi_1 <= -0.3`
- Confirmation:
  - Require `confirm_k` consecutive snapshots with same sign regime (e.g., 2–3).
  - Require `spread <= 2.0 * median_spread` (avoid stressed microstructure).
  - Thin book filter: `depth_bid_k >= p10_depth_bid` and `depth_ask_k >= p10_depth_ask`.
- Hidden liquidity filter (adverse selection):
  - Longs: block if `hidden_buy` is active.
  - Shorts: block if `hidden_sell` is active.

**B) Extreme Reversal (optional, gated)**
- Trigger:
  - Long candidate if `obi_1 <= -0.6` AND `d_obi_1_15s > 0` (sell pressure easing)
  - Short candidate if `obi_1 >= +0.6` AND `d_obi_1_15s < 0`
- Must pass the same spread/depth filters.
- Optional: only enable after we have stable paper results on the momentum mode.

Entry output: `TradeIntent(direction, urgency, entry_style, stop_bps, target_bps, ttl_sec)`.

### 7.4 Exit logic (L2-native)

All exits are driven by a combination of:

1) **Hard stop**: `-10 bps` (configurable) from realized entry.
2) **Profit target**: `+15 bps` base; optional `+25 bps` if regime stays strong.
3) **Time stop**: default 5 seconds; extend to 15 seconds only if:
   - trade is in profit AND `obi_regime` remains aligned.
4) **Regime break**: exit when `obi_1` crosses 0 or flips regime for `break_k` snapshots.
5) **Data health stop**: if depth goes missing or stale, exit/flatten.

---

## 8. L2 Execution Engine (IBKR)

### 8.1 Execution objectives
- Minimize spread + adverse selection.
- Guarantee deterministic behavior under failure (no runaway order loops).
- Ensure every order is attributable (system tag + strategy tag; see `SYSTEM_SEPARATION_GUIDE.md`).

### 8.2 Order types (paper-safe baseline)

We treat “urgency” as the bridge from signals to execution:

- **Low urgency**: passive limit at bid/ask (join), short TTL (e.g., 1–2 seconds).
- **Medium urgency**: limit at mid (or one tick through), TTL 1 second.
- **High urgency**: marketable limit (cross spread), TTL 0.5 seconds.

The engine chooses urgency using:
- `micro_off` (microprice vs mid)
- `execution_window` (liquidity skew)
- spread multiple vs `median_spread`

### 8.3 Brackets vs manual exits

Initial safe approach:
- Use bracket orders for hard stop + take profit (see `qx-data/src/qx_data/live/order_manager.py`).
- Maintain an “active trade” supervisor that can **cancel/replace** brackets on regime-break
  exits (OBI flips) or time exits.

Key requirement:
- Bracket orders must be tagged with `{SYSTEM}_{CLIENT_ID}_{STRATEGY}_{SYMBOL}`.

### 8.4 Tick size and price rounding
- Retrieve `minTick` from IBKR contract details where possible.
- Always round limit/stop/target prices to valid ticks before submission.

### 8.5 Broker safety guards
- Max outstanding orders per symbol
- Cancel-on-timeout for any non-filled entry order
- Detect repeated IBKR depth/contract errors and disable symbol for session (reuse qx-l2 patterns)

---

## 9. L2 Risk Management Module

### 9.1 Sizing (risk-at-stop)

Sizing rule:

1) `risk_budget = equity * 0.01`
2) `stop_dist = max(stop_bps * mid_price, k_spread * spread, min_tick)`
3) `qty_risk = floor(risk_budget / stop_dist)`
4) `qty = min(qty_risk, max_shares=100)`

Notes:
- With the 100 share pilot cap, realized risk will usually be **well below** 1% of equity.
- `k_spread` is a guard (e.g., 2–3× spread) so we do not place stops inside the spread noise.

### 9.2 Portfolio-level limits (pilot defaults)
- `max_concurrent_positions`: 1–2 (start with 1)
- `max_positions_per_symbol`: 1
- `cooldown_sec_after_exit`: 30–60 seconds per symbol
- `max_trades_per_day`: small at first (e.g., 20) until stability is proven
- `daily_loss_limit`: recommend 100 bps of equity (configurable)

### 9.3 Kill switches
The risk manager triggers a system-wide “no new trades” state if:
- Daily loss limit reached
- IBKR disconnect / repeated order rejects
- L2 health check fails (stale snapshots beyond tolerance)

Flatten policy:
- If kill switch triggers while positions are open, flatten with marketable limits (paper-safe).

---

## 10. Data, Journaling, and Observability

### 10.1 What we must record (for every decision)
For each evaluated tick (2 Hz) and for each trade lifecycle event:
- Snapshot time, symbol, key features (OBI levels, depth, spread, micro_off, deltas)
- Derived signals (regime, hidden liquidity, execution window, composite score)
- Decision outcome (enter/hold/exit/skip + reason codes)
- Order intents and actual IBKR order IDs
- Fills (price, qty, timestamp), realized P&L, slippage vs mid

### 10.2 Storage
Reuse existing storage patterns:
- L2 raw/features parquet partitioning from `qx-l2/src/qx_l2/storage.py`
- Trade journal: SQLite or parquet under `data/l2_scalper/` with date partitioning

### 10.3 Live monitoring
Minimum viable observability:
- `logs/l2_scalper.log` (system lifecycle + errors)
- `data/l2*/journal.db` (collector errors and session stats)
- Metrics printed periodically:
  - depth availability rate
  - avg spread and “spread stress” percent
  - trade count, win rate proxy, average slippage

---

## 11. Testing and Validation Strategy

### 11.1 Unit tests (no IBKR required)
Targets:
- Feature engineering determinism (given a synthetic snapshot sequence)
- Signal functions (OBI regime, hidden liquidity, composite score)
- Decision logic state machine (entry/exit reason codes)
- Risk sizing math and limit enforcement

Principle:
- Tests should be pure, deterministic, and run under `pytest` without network access.

### 11.2 Integration tests (IBKR required, paper account)
Targets:
- Connectivity + subscriptions (market data + market depth)
- Order submission + tagging + cancellation
- Bracket lifecycle and fill callbacks

Policy:
- Mark these tests as opt-in (e.g., `pytest -m ibkr`) and skip by default.

### 11.3 Replay validation (offline, real captured data)
Goal:
- Verify the decision engine produces stable outputs when fed recorded `features_v2`.

Method:
- A “replay runner” reads `data/l2_maximum/features_v2/date=.../symbol=.../features.parquet`
  and feeds rows into the decision engine at accelerated time.
- This is not “mock data”; it is captured system output used for regression testing.

### 11.4 “No-mock before paper” release checklist
Before paper testing:
- `rg -n \"mock|fake|sample_data\" qx-* scripts | head -n 200` must show **no production-path mocks**.
- Ensure the scalper entrypoint imports only real data/broker modules.
- Run:
  - `make lint`
  - `make check-types`
  - `make test` (excluding IBKR-marked tests unless TWS is up)
- Explicitly delete any mock data files and mock connectors used during development.

---

## 12. Detailed Sprint Plan (with tests and acceptance criteria)

Sprint cadence: 1 week (adjust as needed). The goal is stable paper trading with strict safety
and full attribution before any parameter tuning.

### Sprint 0 — Interfaces + Config + “No-mock” guardrails
**Deliverables**
- Config schema for `l2_scalper` (YAML) with explicit toggles and safe defaults.
- Module skeletons and protocols (pure decision engine vs side-effectful execution).
- “No mock in production” checks documented and automated (pre-paper checklist).

**Engineering tasks**
- Define data contracts: `L2Features`, `TradeIntent`, `TradeState`, reason codes.
- Decide process topology (single vs two-process) and integration mechanism.
- Choose strategy tag name (e.g., `L2_SCALP_OBI`), client IDs, and orderRef format.

**Tests**
- Minimal unit tests for config parsing and default constraints.

**Acceptance criteria**
- Running the system with empty market data must refuse to trade (fail closed).

### Sprint 1 — Live L2 Feature Feed (features_v2 parity)
**Deliverables**
- L2 collector configured to compute `features_v2` exactly (OBI levels + delta windows).
- Access to latest per-symbol features for the trading engine (in-process callback or store).
- Health checks: snapshot freshness, depth availability, error disable list.

**Engineering tasks**
- Configure `qx-l2` to `snapshot_interval_ms=500`.
- Add per-symbol latest-feature cache (if not already present).
- Implement rolling calibrators (median spread, p10 depth, pressure stats).

**Tests**
- Unit test: feature engineer computes expected columns and delta logic.
- Unit test: calibrator converges on deterministic input stream.

**Acceptance criteria**
- For a live session window, collector writes features and reports:
  - depth rate ≥ 85% (symbol-dependent)
  - stable per-symbol calibration values after warmup

### Sprint 2 — L2 Decision Engine (entry/exit)
**Deliverables**
- Pure decision engine producing `TradeIntent` and `ExitIntent` with reason codes.
- Per-symbol state machine: idle → pending_entry → in_position → pending_exit → cooldown.
- Strategy modes: momentum (on by default), extreme reversal (off by default).

**Engineering tasks**
- Port signal logic from `data/l2_maximum/exports/l2_signals.py` into a domain module.
- Implement entry gating: confirm_k, hidden-liquidity filter, thin-book, spread stress.
- Implement exits: hard stop, profit target, time stop, regime break, data health stop.

**Tests**
- Table-driven unit tests for 20+ scenarios (entry allowed/blocked, exit reasons).
- Replay regression test on a small subset of `features_v2` (deterministic expectations).

**Acceptance criteria**
- Decision engine is deterministic: same input stream ⇒ same intents.
- All exit conditions fire with correct precedence and reason codes.

### Sprint 3 — Risk + Execution Integration (paper-safe)
**Deliverables**
- Risk manager enforcing 1% equity risk-at-stop and 100 share cap.
- Execution engine that maps intents to IBKR orders with proper tagging.
- Order lifecycle supervisor: TTL cancels, bracket management, regime-break forced exits.

**Engineering tasks**
- Integrate with `qx-data/src/qx_data/live/order_manager.py` (or add L2-specific executor).
- Implement tick rounding using IBKR contract metadata.
- Position reconciliation: confirm IBKR positions match internal state.

**Tests**
- Unit tests for sizing and caps, cooldowns, daily loss kill switch.
- Opt-in IBKR integration tests:
  - connect/disconnect
  - place/cancel limit orders (qty=1)
  - place bracket and verify orderRef tagging

**Acceptance criteria**
- In paper account, system can:
  - place/cancel orders safely
  - never exceed 100 shares
  - flatten on command and on kill switch

### Sprint 4 — Paper Trading Pilot + Metrics + Hardening
**Deliverables**
- Paper trading runbook and daily checklist.
- Post-trade report generation: signal quality vs execution quality attribution.
- Stability improvements based on pilot logs.

**Engineering tasks**
- Add metrics: fill rate, slippage vs mid, time-to-fill, realized bps per trade.
- Add “safe mode” toggles:
  - trade hours windows only
  - max trades/day
  - symbol disable list persisted daily
- Iterate on thresholds using pilot evidence (not guesswork).

**Tests**
- Regression tests for any tuning changes (decision engine outputs stable).

**Acceptance criteria**
- 3–5 consecutive paper sessions without crashes, runaway orders, or stale data trading.
- Clear, attributable logs for every trade decision and fill.

---

### Sprint 5 — Macro Context Layer (intraday)
**Deliverables**
- Context engine computing v1 macro features for trade symbols + SPY/QQQ/IWM.
- Context-gated decision engine with config toggles and staleness handling.
- Paper metrics to validate gating impact (trade count, slippage, realized bps, drawdown).

**Engineering tasks**
- Compute indicators from 1m bars: VWAP distance, EMA slopes, realized vol, volume z-scores.
- Add optional sector ETF momentum and relative strength features.
- Add key level distances (PDH/PDL/PMH/PML, opening range) as target/avoid inputs.

**Tests**
- Unit tests for indicator calculations on fixed small DataFrames.
- Replay test: verify context gating blocks trades near defined level/volatility conditions.

**Acceptance criteria**
- No stale-context trading; “unknown context” defaults are conservative and deterministic.
- Paper pilot shows reduced trades during risk-off windows without increasing error rates.

---

## 13. Implementation Notes (Repo Integration)

Recommended module placement (aligning with existing repo domains):
- **L2 collection + features**: `qx-l2/src/qx_l2/`
- **Live trading orchestration + IBKR execution**: `qx-data/src/qx_data/live/`
- **Pure decision logic**: keep free of IBKR imports; make it testable and replayable.

Key reuse points:
- Universe: `scripts/daily_sip_scheduler.py`, `qx-data/src/qx_data/live/polygon_sip.py`
- IBKR market data: `qx-data/src/qx_data/live/ibkr_data.py`
- Order tagging: `SYSTEM_SEPARATION_GUIDE.md`, `qx-data/src/qx_data/live/order_manager.py`
- L2 collection safety patterns: `docs/PAPER_TRADING_GUIDE.md`, `qx-l2` journaling

---

## 14. Paper-Test Readiness Checklist (Day-of-run)

1) Confirm IBKR Gateway/TWS paper is up (`127.0.0.1:7494`) and stable.
2) Run daily SIP selection and verify outputs in `data/daily_sip/`.
3) Confirm L2 symbols are NYSE depth-supported (no repeated depth errors in journal).
4) Confirm “no-mock” checks are clean (see §11.4).
5) Start services (collector + scalper) with unique client IDs and system tags.
6) Monitor logs for 10 minutes before enabling order submission.
