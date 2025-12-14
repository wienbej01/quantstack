# Triple‑Barrier Labeling — Optimal, Strategy‑Aligned Approach

This document outlines a practical “optimal” triple‑barrier labeling framework for an
intraday ML trading system, where **optimal** means:

- Barriers and horizon match the *real execution rules* you intend to trade.
- Parameters are tuned to maximize **out‑of‑sample net expectancy after costs**, not AUC.

## 1) Define Event Start Times (Don’t Label Every Minute)

Create an event at time `t0` only when you would genuinely consider entering.

Typical event filters:

- Symbol is in the daily SIP universe
- Time is within allowed trading window
- Liquidity/spread constraints are satisfied
- Strategy “setup” conditions are met

This reduces overlapping labels and makes the ML task trade-relevant.

## 2) Compute a Volatility Unit at `t0`

Compute a volatility scaler using only information available at `t0`:

- `vol = atr_pct(t0)` (or ATR in dollars, but be consistent across training/live)
- Optional clamping for extremes is acceptable, but must be consistent everywhere

## 3) Set the Three Barriers (PT, SL, Time)

Let:

- `p0` = entry price proxy (mid/last/open — choose one and keep it consistent)
- `side ∈ {+1 (long), -1 (short)}`
- `vol = atr_pct(t0)`

Define barrier distances:

- Profit distance: `pt = pt_mult * vol`
- Stop distance: `sl = sl_mult * vol`
- Vertical barrier time: `t1 = min(t0 + H minutes, session_end)`

Price levels (side-aware):

- `PT_price = p0 * (1 + side * pt)`
- `SL_price = p0 * (1 - side * sl)`

Recommended process:

1. Start with `pt_mult/sl_mult/H` that match your *current execution*
2. Tune only after the alignment baseline is verified

## 4) Determine Which Barrier Is Hit First (Using OHLC)

Scan bars from `t0` to `t1`:

- For **long**:
  - PT hit if `high >= PT_price`
  - SL hit if `low <= SL_price`
- For **short**:
  - PT hit if `low <= PT_price`
  - SL hit if `high >= SL_price`

If PT and SL touch in the same bar, choose a deterministic rule:

- Conservative realism: assume the adverse barrier hit first
- Alternative: drop these events, or use higher-resolution data

If neither PT nor SL hits by `t1`, the vertical barrier triggers (exit at `t1`).

## 5) Assign Labels (Pick One Scheme and Stay Consistent)

### A) 3‑Class Outcome (Directional + Timing)

- `y = +1` if PT is hit first
- `y = -1` if SL is hit first
- `y = 0` if time barrier triggers first

### B) Meta‑Labeling (Often Best for Live Trading)

- Use a base strategy/model to determine `side`
- Label: `y = 1` if PT hits before SL/time, else `0`

This trains the model to decide **“should we take this trade?”** rather than direction.

### C) EV Regression (Best for Ranking Trades)

- Label: `y = net_return_at_exit` (including realistic costs)
- Use predicted EV for top‑K selection / EV thresholding

## 6) Incorporate Costs Correctly

Key principle: barrier **triggering** should reflect how orders trigger on price, while
outcomes and optimization should be based on **net** results.

- Apply fees/spread/slippage to realized P&L at exit
- Ensure the PT barrier meaningfully clears expected round‑trip costs; otherwise “PT wins”
  can still be net losers

## 7) Prevent Leakage From Overlapping Events

Triple‑barrier events overlap, so standard CV will leak information. Use:

- **Purged** time-series CV (remove training samples whose event windows overlap the test)
- **Embargo** after each test fold
- Optional: uniqueness-based sample weights (downweight heavily overlapped periods)

## 8) Optimize `pt_mult`, `sl_mult`, and `H` on Validation (Not AUC)

Search over reasonable ranges and choose parameters that maximize **out‑of‑sample net
expectancy** subject to:

- drawdown limits
- turnover/cost limits
- minimum trade count (avoid “too few trades” overfit)

After optimization:

- Calibrate probabilities (Platt/isotonic) on a strict out-of-sample validation split
- Select trades using **EV margin** or daily **top‑K** ranking, not a fixed probability
  threshold

---
Not financial advice. This is a research/engineering approach for strategy-aligned ML.

