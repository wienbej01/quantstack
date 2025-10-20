# Regime-Aware Intraday Strategy Suite (Detailed)

## Executive Summary

Objective: Deliver a profitable, regime-robust intraday equity system using symmetric long/short strategies tailored to BULL, BEAR, SIDEWAYS, and STRESS regimes. Designs leverage existing features (VWAP, ATR, RVOL, variance-ratio, ADX proxy, band position, stress metrics, VPA) and the rule-based regime detector with persistence/cooldown. Each strategy below specifies features, precise entry/exit rules, parameter defaults/ranges, and risk controls with long/short symmetry.

Evidence base: This suite follows widely studied intraday phenomena—trend continuation under strong order-imbalance (momentum), reversion within constrained volatility (mean reversion), and volatility-shock microstructure (stress), consistent with mainstream academic and practitioner insights (variance-ratio tests, ADX for trend strength, Bollinger-based reversions, volume-price action patterns, ATR-based risk sizing).

## Regime Definitions and Gating Signals

- Regimes: `BULL`, `BEAR`, `SIDEWAYS`, `STRESS`, `OFF` (detector caches daily).
- Detector features (from `regime_basics`):
  - `vr = f__regime__var_ratio_10_60` (trend vs range)
  - `adx = f__regime__adx_proxy_14` (trend strength)
  - `modv = f__regime__mod_vol_30` (seasonality-adjusted vol)
  - `bpos = f__regime__band_pos_20_2.0` (position in bands)
  - `stress = f__regime__stress_10_10` (vol/volume spikes)
- Trade features (from `core_basics`):
  - `vw = f__ta__vwap_30`, `atr = f__vol__atr_14`, `rvol = f__vol__rel_volume_30`
  - Optional: `p__vpa__*` (price breakout, climax, absorption)

Baseline regime thresholds (tune per universe):
- BULL: `vr > 1.2`, `adx >= 25`, `modv ∈ [0.8, 1.6]`, `stress == 0`
- BEAR: `vr < 0.8`, `adx >= 25`, `modv ∈ [0.8, 1.7]`, `stress == 0`
- SIDEWAYS: `|vr-1| <= 0.1` or `adx < 22`; `bpos ∈ [0.3, 0.7]`; `modv ∈ [0.7, 1.4]`; `stress == 0`
- STRESS: `modv >= 2.0` or `stress > 0`

Global trading constraints:
- Bar frequency: 1-minute; warmup: respect `f__regime__warmup_ok` before entries.
- Session filters: avoid first 2 minutes; block new entries last 10 minutes.
- Timeout: 60 bars (unless noted); one open position per symbol per strategy.
- Universe: prefer daily HMM_SIP selection (top-k, score_floor) to focus liquidity/flow.

## Parameter Heuristics

- Vol-adaptive deviation minimum: `dev_pct_min = max(0.35, 0.6 * (atr/px)*100)` bps
- Breakout threshold: `bo_bps ∈ [10, 35]` (default 20 bps)
- Stop/Target multiples: `k_stop, k_tp ∈ [0.8, 1.5]` ATR
- Trailing activation: after +0.8 ATR in favor, trail `1.0*ATR` (momentum)
- Size: `qty = floor( (max_risk_frac * equity) / (atr * atr_mult) )`

## BULL Regime Strategies

Strategy 1: Trend Continuation via VWAP Breakout (long/short symmetric)
- Intent: Exploit sustained directional moves when trend is strong.
- Gating: `vr > 1.2`, `adx >= 25`, `modv ∈ [0.8,1.6]`, `stress == 0`.
- Long Entry (mirror short with inequalities flipped):
  - Breakout: `px > vw * (1 + bo_bps/10000)` with `bo_bps=20`.
  - Confirmation: either (a) 10-bar retest holds above VWAP or (b) `bpos` rising and `< 0.9`.
  - Optional filters: `rvol >= 1.2` OR `p__vpa__price_breakout == 1`.
- Exit (long):
  - Stop: `entry - 1.0*atr`; Target: `entry + 1.0*atr`.
  - Trailing: after MFE ≥ `0.8*atr`, maintain `1.0*atr` trail; timeout 60 bars.
- Risk: `max_risk_frac=0.02`, `atr_mult=1.0`; regime multipliers per `qx_risk`.
- Short side symmetry: if allowed in mapping for BULL (default off); otherwise active in BEAR.

Strategy 2: Trend Pullback to VWAP (long/short symmetric)
- Intent: Enter on shallow pullbacks to VWAP in an established uptrend.
- Gating: same as Strategy 1.
- Long Entry:
  - Pullback: any of last 10 bars had `px <= vw*(1 - dev_pct_min/100)`; current bar reclaims VWAP (`cross_up` condition: `px[t-1]<=vw[t-1]`, `px[t]>vw[t]`).
  - Optional: `bpos ∈ [0.35, 0.85]`.
- Exit (long):
  - Stop: `entry - 1.0*atr`; TP: `entry + 1.0*atr` or trail `1.0*atr` after +1.0 ATR; timeout 60 bars.
- Risk: `max_risk_frac=0.02`, `atr_mult=1.0`.
- Short symmetry: bounce-to-VWAP then `cross_down` in BEAR.

## BEAR Regime Strategies (Mirrored)

Strategy 1: Trend Continuation via VWAP Breakdown (short focus)
- Gating: `vr < 0.8`, `adx >= 25`, `modv ∈ [0.8,1.7]`, `stress == 0`.
- Short Entry (mirror of BULL breakout): `px < vw*(1 - bo_bps/10000)`; confirm via retest-and-fail or falling `bpos` (> 0.1).
- Exit (short): stop `entry + 1.0*atr`; TP `entry - 1.0*atr`; trail after +0.8 ATR; timeout 60.
- Risk: `max_risk_frac=0.02`, `atr_mult=1.0` (regime multiplier increases ATR mult to 1.2 by default).
- Long symmetry: only if mapping allows longs in BEAR (optional).

Strategy 2: Trend Pullback to VWAP (short)
- Gating: same as above.
- Short Entry: bounce to VWAP then `cross_down` (`px[t-1]>=vw[t-1]`, `px[t]<vw[t]`) with recent deviation ≥ `dev_pct_min`.
- Exits/Risk: mirror of BULL pullback.

## SIDEWAYS Regime Strategies

Strategy 1: VWAP Mean Reversion (long/short symmetric)
- Intent: Fade deviations that tend to revert to VWAP within constrained volatility.
- Gating: `|vr-1|<=0.1` or `adx < 22`; `bpos ∈ [0.3,0.7]`; `modv ∈ [0.7,1.4]`; `stress == 0`.
- Long Entry:
  - Deviation: `px <= vw*(1 - dev_pct_min/100)` where `dev_pct_min = max(0.40, 0.6*atr% )`.
  - Optional: `rvol ∈ [0.6,1.5]`; avoid VPA breakout (`p__vpa__price_breakout == 0`).
- Exit (long):
  - Primary: TP at VWAP touch (`px >= vw`) OR fixed `+0.8*atr`.
  - Stop: `entry - 1.0*atr`; timeout 45–60 bars.
- Short symmetry: `px >= vw*(1 + dev_pct_min/100)`; TP at VWAP or `-0.8*atr`; stop `+1.0*atr`.
- Risk: `max_risk_frac=0.015`, `atr_mult=1.0`.

Strategy 2: Bollinger Band Reversion (long/short symmetric)
- Intent: Fade excursions outside 2σ bands back to mid-band/VWAP.
- Gating: `adx < 22`, `|vr-1|<=0.1`, `stress == 0`.
- Long Entry: `bpos < 0.0` AND (`px < vw` OR `rvol <= 1.5`); boost size if `p__vpa__climax == 1`.
- Exit (long): to mid-band or VWAP (nearest), stop `entry - 1.0*atr`, timeout 45 bars.
- Short symmetry: `bpos > 1.0` AND (`px > vw` OR `rvol <= 1.5`).
- Risk: `max_risk_frac=0.015`, `atr_mult=1.0`.

## STRESS Regime Strategies

Default: No new entries (risk-off)
- Detector: `modv >= 2.0` or `stress > 0`.
- Action: manage open risk—tighten trails by +0.5 ATR; prefer flattening.

Optional Strategy: Volatility Shock Micro-Scalp (long/short symmetric; off by default)
- Intent: Capture immediate mean-reversion after extreme spikes with tiny size and strict exits.
- Gating: `stress > 0`, `modv >= 2.0`, two-bar volatility contraction; ensure distance to VWAP > `max(1.0%, 1.2*atr%)`.
- Long Entry: `bpos < -0.1` with contraction; Short Entry: `bpos > 1.1` (mirror).
- Exit: TP `0.5*atr`; Stop `0.75*atr`; timeout 15 bars; size ≤ 10% of normal.
- Risk: override multipliers to `risk_multiplier=0.1`, `atr_multiplier=1.5`.

## Risk Management

Sizing and stops
- Base sizing: `qty = floor( (max_risk_frac * equity) / (atr * atr_mult) )`.
- Suggested base: momentum/pullback `max_risk_frac=2%`; reversion `1.5%`.
- Default regime multipliers (from `qx_risk/atr_stop.py`):
  - BULL: (1.0, 1.0), BEAR: (0.8, 1.2), SIDEWAYS: (0.9, 1.1), STRESS: (0.3, 1.5).
- Portfolio constraints: max open risk 6% equity; per-symbol 2 entries/session; 10-bar cooldown post stop-out.

Slippage and liquidity
- Use HMM_SIP daily universe to cap tail risk and improve fills.
- Optional: block entries when `rvol < 0.4` or dollar-volume below threshold.

## Calibration and Tuning

Procedure
- Start with defaults; AB-test `bo_bps`, `dev_pct_min`, `k_stop/k_tp`, trail activation, and timeout.
- Bucket symbols by intraday volatility (ATR%) and adjust `dev_pct_min` scaling per bucket.
- Use regime attribution to tune per regime rather than global optimization.

Diagnostics
- Monitor regime flips/day, avg time between flips, cache hit rate.
- Segment P&L by (regime, strategy, side). Target profile: momentum wins fewer but larger; reversion frequent smaller gains; stress near-zero entries if disabled.

## Implementation Mapping (Current Codebase)

- Momentum strategies: model via `qx_backtest/policies/vwap_momentum.py` with parameters `breakout_threshold_bps`, retest confirmation, ATR trailing, and timeouts.
- Pullback strategies: either parameterize momentum enhanced policy to require `cross_up/down` after deviation or add a small wrapper.
- Mean reversion: use `qx_backtest/policies/vwap_revert.py` with entry deviations; add pre-entry gating using regime features.
- Band reversion: lightweight policy leveraging `bpos` and ATR stops.
- Risk and gating already integrated: `engine.is_strategy_allowed()`, `qx_risk.atr_stop` regime multipliers, `reject_order_for_regime`.

## Example Config Snippets

Regime detector and mapping
```yaml
regime:
  enabled: true
  persistence_bars: 5
  cooldown_minutes: 15
  detector_params:
    variance_ratio_bull: 1.2
    variance_ratio_bear: 0.8
    adx_trend_threshold: 25.0
    volatility_stress_threshold: 2.0
    sideways_band_min: 0.3
    sideways_band_max: 0.7
  strategy_map:
    BULL: ["vwap_mom_trend", "vwap_pullback"]
    BEAR: ["vwap_mom_trend", "vwap_pullback"]
    SIDEWAYS: ["vwap_revert", "band_revert"]
    STRESS: []
```

Features
```yaml
features:
  - type: "regime_basics"
  - type: "core_basics"
  # - type: "vpa"  # optional
```

Universe selection (daily HMM_SIP)
```yaml
sip:
  method: "hmm"
  config:
    mode: "daily"
    score_floor: 0.01
    top_k: 20
```

## References (Conceptual Guide)

- Variance-ratio (trend vs random walk), ADX (trend strength), Bollinger reversions, volume-price action (breakouts, climaxes), and ATR risk sizing are standard components in both academic and practitioner literature for intraday strategy design.

## Roadmap

1) Parameterize momentum/pullback in configs; expose `cross_up/down` confirmation in momentum-enhanced policy.
2) Add `band_revert` lightweight policy; include gating by `adx` and `stress`.
3) Add symbol-bucket calibration for `dev_pct_min` scaling vs ATR%.
4) Validate on ≥ 3 months per regime; publish regime-attributed performance and risk.
