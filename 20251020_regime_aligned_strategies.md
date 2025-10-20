# Regime-Aligned Strategy Sprint Plan (2025-10-20)

## Preamble — Critical Quantitative Trading Rules
- **No Forward Look**: Feature generation, signal evaluation, and regime classification may only use information available at or before the signal bar’s close. Rolling windows must exclude the current bar when deriving statistics applied to that bar.
- **Signal Execution Timing**: Orders generated from bar `t` may be submitted no earlier than bar `t+1`. Policies must queue actions for execution on the first bar following signal creation.
- **Deterministic Processing**: Feature pipelines, detectors, and strategy policies must produce identical results for identical inputs. Avoid randomness; if unavoidable, seed via configuration.
- **Warmup Guardrails**: Trading logic must respect `f__regime__warmup_ok` and any feature-specific warmup flags. Ignore bars until all required features are fully primed.
- **Risk Integrity**: Position sizing, stops, and targets must route through `qx_risk.atr_stop` (or approved successor) to ensure consistency with firm-wide limits. Strategy overrides must stay within documented bounds.
- **Order Gating**: All policies must honor `BacktestEngine.is_strategy_allowed()` and regime-specific throttles (persistence, cooldown). No policy may bypass engine gating.
- **Data Lineage & Logging**: Extend structured logging to capture regime signals, feature diagnostics (e.g., AVWAP levels, value area status), and decision rationale per trade for downstream attribution and compliance.
- **Session Awareness**: Reset anchored indicators at session boundaries (09:30 ET) and handle premarket/after-hours data explicitly. No cross-session leakage.
- **Stress Handling**: Upon `RegimeType.STRESS`, block new orders unless explicitly whitelisted, tighten risk parameters, and escalate alerts.
- **Testing & Monitoring**: Every new feature and strategy must ship with unit tests, regression fixtures, and post-deploy monitoring hooks.

## Sprint Scope
Implement regime-aligned strategies leveraging enhanced AVWAP, volume profile, ICT, and order-flow features; integrate them into the existing regime detector, backtest engine, and risk stack with full test coverage and documentation.

## Feature & Strategy Specification Overview
- **Anchored VWAP Suite**: Session, premarket, first-hour, and prior-extreme AVWAPs computed per symbol/session via cumulative price–volume / volume, with deterministic resets aligned to trading hours.
- **Intraday Volume Profile**: Rolling histogram of traded volume producing POC/VAH/VAL plus acceptance/rejection flags after sustained closes outside value.
- **ICT Structure Toolkit**: Fair value gaps (three-bar pattern), displacement legs (range/ATR and volume filters), premium/discount arrays (62–79% retracement zones), and liquidity sweep detection (equal highs/lows cleared then rejected).
- **Order Flow & VPA Metrics**: Signed-volume order flow imbalance with EMA trend, absorption and climax detectors based on volume percentile, range compression, and wick ratios.
- **Stress Contraction Flag**: Identifies volatility cooling post stress spike to gate optional scalp logic.
- **Strategy Highlights**:
  - BULL/BEAR: AVWAP momentum (FVG continuation) and AVWAP pullback reclaim, symmetric long/short rules.
  - SIDEWAYS: Value rotation to POC and liquidity sweep VWAP/Band reversion.
  - STRESS: Default risk-off plus optional micro-scalp with strict controls.

## Workstream A — Feature Engineering (qx-features)
1. **Anchored VWAP Pack**
   - Implement `compute_avwap_features` producing `f__anchor__session_avwap`, `f__anchor__premarket_avwap`, `f__anchor__first_hour_avwap`, `f__anchor__prev_high_avwap`, `f__anchor__prev_low_avwap`.
   - Reset anchors per symbol/session; guard against missing premarket data with fallbacks.
   - Tests: deterministic AVWAP on synthetic OHLCV; verify resets and tolerance to sparse volume.
2. **Intraday Volume Profile Pack**
   - Build histogram-based POC/VAH/VAL, value acceptance flags, and expose columns under `f__profile__*` namespace.
   - Tests: compare against hand-computed profiles; ensure value area captures 70% of volume.
3. **ICT Structure Pack**
   - Add FVG detection, displacement leg tracking, PD arrays, and liquidity sweep flags with stateful handling per symbol.
   - Tests: fixtures covering bullish/bearish gaps, invalidation once filled, PD boundaries, sweep recognition.
4. **Order-Flow & VPA Enhancements**
   - Implement OFI proxy (`f__flow__ofi`, `f__flow__ofi_trend`) and refine absorption/climax metrics.
   - Tests: signed-volume sanity checks, EMA smoothing, VPA flag thresholds.
5. **Registry & Schema Updates**
   - Register new packs under `regime_enhanced`; document defaults and parameter validation in `docs/features`.

## Workstream B — Regime Detector Extensions (qx-core)
1. **Config Enhancements**
   - Add thresholds for AVWAP bias, value acceptance bars, and OFI confirmation to `RegimeDetectorConfig` + schema.
2. **Feature Aggregation**
   - Extend `_aggregate_features` to ingest new columns (median/any aggregation) with null safety.
3. **Stress Contraction Flag**
   - Surface `f__stress__contraction` for optional micro-scalp gating.
4. **Unit Tests**
   - Add targeted detector tests ensuring regimes respect new feature-based gating cues.

## Workstream C — Strategy Policies (qx-backtest)
1. **AVWAP Momentum Policy**
   - Regime gating: BULL (`vr>1.2`, `adx≥25`, `mod_vol∈[0.8,1.6]`, `stress==0`) or BEAR mirrored.
   - Entry (long): price above session & first-hour AVWAP, bullish displacement leg active, pullback tags active bullish FVG within discount PD (`62–79%` retrace), `ofi_trend>0`, no bearish sweep overhang; optional absorption confirmation.
   - Execution: queue order on bar `t+1`; stop at `max(fvg_upper, swing_low) − 0.1%` capped by `1.0*ATR`; partial take at `+0.8*ATR`, trail `1.0*ATR` after MFE ≥ `0.8*ATR`; hard timeout 60 bars; symmetrical rules for shorts.
2. **AVWAP Pullback Policy**
   - Entry (long): within last five bars low ≤ session AVWAP × `(1 − max(0.35%, 0.6×ATR%))`, current bar closes back above AVWAP, price remains in discount PD, no active bearish FVG ≤0.5 ATR overhead, optional absorption flag.
   - Risk: stop at recent swing − buffer or `1.0*ATR`; target `+0.8*ATR` with trailing after `+1.0*ATR`; timeout 60 bars; mirrored short entry for BEAR regime.
3. **Value Rotation Policy**
   - Regime gating: SIDEWAYS (`|vr-1|≤0.1` or `adx<22`, `mod_vol∈[0.7,1.4]`, `stress==0`).
   - Entry (long): price trades ≤0.25 ATR below `f__profile__val` and closes back inside value with `vpa_absorption` or `liq_sweep_low`, `close` within 0.5 ATR of session AVWAP.
   - Exit: TP at POC (optionally VAH), stop 0.25 ATR outside VAL or `1.0*ATR`, timeout 45 bars; mirrored short at VAH.
4. **Liquidity Sweep Reversion Policy**
   - Regime gating: SIDEWAYS with low ADX and `stress==0`.
   - Entry (long): `f__ict__liq_sweep_low==True`, `band_pos<0`, close above sweep level yet ≤ session AVWAP, `ofi_trend` turning positive.
   - Exit: TP at session AVWAP or POC (nearest), stop beyond sweep wick or `1.0*ATR`, timeout 45 bars, early exit if `vpa_climax` reverses; mirrored short for sweeps of highs.
5. **Stress Micro-Scalp Policy (Optional)**
   - Gating: `RegimeType.STRESS`, `f__stress__contraction==True`, whitelist membership, `rel_volume≥1.5`.
   - Entry (long): sweep low with distance to session AVWAP ≥ max(1.0%, 1.2×ATR%), `ofi_trend` crosses above 0, range contracts vs prior bar.
   - Risk: size ≤10% normal via overrides; stop `0.75*ATR`, target `0.5*ATR`, timeout 15 bars, disable after three losses or daily cap breach; symmetric short rules.
6. **Shared Infrastructure**
   - Implement parameter dataclasses, structured logging (feature snapshot, regime, rationale), and strict `t+1` execution scheduling.
7. **Unit Tests**
   - Construct fixtures covering warmup gating, valid/invalid entries, stop/target logic, and symmetry for long/short variants.

## Workstream D — Risk & Config Integration
1. **ATR Stop Overrides**
   - Extend `qx_risk.atr_stop` to accept strategy-specific overrides (max risk frac, ATR multiples, trailing triggers).
2. **Global Risk Guards**
   - Enforce per-symbol cooldowns and daily exposure caps in engine or dispatcher layer.
3. **Configuration Assets**
   - Provide reference YAML (`experiments/regime/enhanced_strategy.yaml`) wiring features, strategy_map, risk overrides.
4. **Tests**
   - Risk module unit tests verifying override precedence and regime-aware multipliers.

## Workstream E — Documentation & Telemetry
1. **Docs**
   - Author detailed feature references in `docs/features/regime_strategy_suite.md` & new `docs/features/avwap_pack.md`.
   - Update `README_regime_detection.md` with enhanced strategy map and setup instructions.
2. **Telemetry**
   - Extend strategy-level logging (JSON payload) capturing feature snapshot, regime, and decision rationale.
   - Provide sample dashboards/metrics for attribution by regime/strategy.

## Workstream F — Quality Assurance
1. **Static Analysis & Style**
   - `make lint`, `make format`.
2. **Unit & Integration Tests**
   - `pytest tests/test_features_*`, `pytest tests/test_regime_*`, `pytest tests/test_policies_*`.
3. **Scenario Backtests**
   - Run focused experiment on AAPL + top-30 HMM SIP symbols over 2024-01 to 2024-06; attribute by regime.
   - Validate stress handling via replay of known volatility events.
4. **Performance Benchmarks**
   - Measure feature computation throughput (`>40k bars/sec` target) and backtest latency.
5. **Sign-off Checklist**
   - Regression comparison vs current baseline, strategy attribution report, doc updates published.

## Appendix — Detailed Feature Logic
- **Session & Anchor VWAPs**
  ```python
  grouped = df.groupby(['symbol', 'session_start_ns'])
  pv_cum = grouped['close'].mul(grouped['volume']).cumsum()
  vol_cum = grouped['volume'].cumsum().replace(0, np.nan)
  df['f__anchor__session_avwap'] = pv_cum / vol_cum
  ```
  Anchor keys: session start (09:30 ET), premarket start, first-hour snapshot (10:30), previous-day high/low timestamps.
- **Intraday Volume Profile**
  ```python
  def compute_intraday_profile(group, price_step=0.1):
      price_min = np.floor(group['low'].min() / price_step) * price_step
      price_max = np.ceil(group['high'].max() / price_step) * price_step
      bins = np.arange(price_min, price_max + price_step, price_step)
      hist = np.zeros(len(bins) - 1)
      for hi, lo, vol in zip(group['high'], group['low'], group['volume']):
          idx_lo, idx_hi = np.searchsorted(bins, [lo, hi])
          width = max(idx_hi - idx_lo, 1)
          hist[idx_lo:idx_hi] += vol / width
      poc_idx = hist.argmax()
      cumulative = hist.cumsum() / hist.sum()
      vah = bins[np.searchsorted(cumulative, 0.85)]
      val = bins[np.searchsorted(cumulative, 0.15)]
      return bins[poc_idx], vah, val
  ```
- **Fair Value Gap Tracking**
  ```python
  bullish_fvg = (df['low'] > df['high'].shift(2)) & (df['close'].shift(1) > df['close'].shift(2))
  df['f__ict__fvg_bull_lower'] = np.where(bullish_fvg, df['low'], df['f__ict__fvg_bull_lower'].shift(1))
  df['f__ict__fvg_bull_upper'] = np.where(bullish_fvg, df['high'].shift(2), df['f__ict__fvg_bull_upper'].shift(1))
  df['f__ict__fvg_bull_active'] = (df['low'] >= df['f__ict__fvg_bull_upper'])
  df.loc[df['close'] <= df['f__ict__fvg_bull_upper'], 'f__ict__fvg_bull_active'] = False
  ```
- **Displacement Legs & PD Arrays**
  ```python
  disp_mask = ((df['high'] - df['low']) / df['f__vol__atr_14'] >= 1.2) & (df['volume'] / df['f__vol__rel_volume_30'] >= 1.3)
  df['f__ict__disp_high'] = np.where(disp_mask, df['high'], df['f__ict__disp_high'].shift(1))
  df['f__ict__disp_low'] = np.where(disp_mask, df['low'], df['f__ict__disp_low'].shift(1))
  leg_range = df['f__ict__disp_high'] - df['f__ict__disp_low']
  df['f__ict__pd_discount_top'] = df['f__ict__disp_low'] + 0.62 * leg_range
  df['f__ict__pd_discount_bottom'] = df['f__ict__disp_low'] + 0.79 * leg_range
  df['f__ict__pd_premium_bottom'] = df['f__ict__disp_high'] - 0.62 * leg_range
  df['f__ict__pd_premium_top'] = df['f__ict__disp_high'] - 0.79 * leg_range
  ```
- **Liquidity Sweeps**
  ```python
  window = 20
  rolling_high = df['high'].rolling(window)
  equal_high = (rolling_high.max() - rolling_high.min()) / rolling_high.max().clip(lower=1e-6) <= 0.0002
  sweep_high = (df['high'] > rolling_high.max().shift(1)) & (df['close'] < rolling_high.max().shift(1))
  df['f__ict__liq_sweep_high'] = equal_high & sweep_high
  df['f__ict__liq_sweep_high_level'] = np.where(df['f__ict__liq_sweep_high'], rolling_high.max().shift(1), np.nan)
  ```
- **Order Flow Imbalance & Trends**
  ```python
  tick = 0.01
  tr = (df['high'] - df['low']).replace(0, tick)
  df['f__flow__ofi'] = df['volume'] * (df['close'] - df['open']) / tr
  df['f__flow__ofi_trend'] = df.groupby('symbol')['f__flow__ofi'].transform(lambda s: s.ewm(span=8, adjust=False).mean())
  ```
- **VPA Absorption & Climax**
  ```python
  volume_avg = df['volume'].rolling(window=20, min_periods=10).mean()
  tr = df['high'] - df['low']
  body = (df['close'] - df['open']).abs()
  df['f__vpa__absorption'] = (df['volume'] > volume_avg) & (tr < 0.6 * df['f__vol__atr_14']) & (body < 0.25 * tr)
  volume_pct = df['volume'].rolling(window=50, min_periods=20).rank(pct=True)
  wick_ratio = ((df['high'] - df[['open', 'close']].max(axis=1)) + (df[['open', 'close']].min(axis=1) - df['low'])) / tr.replace(0, tick)
  df['f__vpa__climax'] = (volume_pct >= 0.95) & (tr >= 1.5 * df['f__vol__atr_14']) & (wick_ratio > 0.5)
  ```
- **Stress Contraction Flag**
  ```python
  stress = df['f__regime__stress_10_10']
  df['f__stress__contraction'] = (stress.shift(1) >= 1.0) & (stress < 1.0)
  ```

## Deliverables
- Enhanced feature pack implementations with tests.
- Updated regime detector and configuration schema.
- Four production-ready policies plus optional stress scalp policy.
- Risk override integration and reference experiment config.
- Documentation updates and telemetry extensions.
- Backtest reports demonstrating regime-aligned performance.

## Proposed Timeline (10 Working Days)
- **Day 1–3**: Workstream A (features) + initial tests.
- **Day 4–5**: Workstream B & C (detector + policies scaffold).
- **Day 6–7**: Workstream C completion + Workstream D (risk/config).
- **Day 8**: Documentation & telemetry (Workstream E).
- **Day 9–10**: QA, scenario backtests, review, sign-off (Workstream F).
