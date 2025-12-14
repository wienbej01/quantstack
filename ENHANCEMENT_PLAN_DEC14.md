# Intraday ML Trading System — Enhancement Plan (Dec 14, 2025)

This plan translates the findings in `TECHNICAL_DOCUMENTATION_UPDATED_DEC14.md` into
prioritized, testable engineering and research work to close the model→trading P&L gap.

## Target Outcome (For a $10k Account)

- Positive net expectancy **after** realistic costs/slippage.
- Stable performance across months (no single-regime dependence).
- Bounded drawdowns with automated risk controls and operational safety.

## Current Diagnosis (Condensed)

- **Objective mismatch**: labels target “move ±1.5× ATR within day” while exits are
  time/EOD + 1.5× ATR stop + 2.0× ATR TP (rare hits), so “correct” predictions do not
  reliably convert into realized P&L.
- **Metric mismatch**: optimizing AUC + trading fixed probability threshold is not an
  economic objective and tends to be unstable across regimes.
- **Sizing/cost consistency risk**: sizing and backtest normalization use `100.0`-style
  constants; the documented min/max share clamps are not inherently compatible with a
  $10k account across $10–$500 symbols.
- **Sparse trades**: excellent per-bar metrics can coexist with weak edge on the subset
  of traded moments; diagnostics must be trade-centric.

## Phase 0 (P0): Stop-The-Line Alignment & Correctness

Goal: Ensure the ML target, signal selection, execution, sizing, and costs are all
economically consistent so backtests are meaningful.

- [ ] **Align labels to executed exits (triple-barrier + costs)**
  - Change supervised target to match the *actual* stop, profit target, and time-out.
  - Include transaction costs/slippage in label outcomes (or in EV computation used for
    selection).
  - **Success**: probability buckets show monotonic improvement in *net* returns (higher
    score → higher realized net P&L / R-multiple).

- [ ] **Replace fixed threshold selection with EV / ranking**
  - Select trades via expected value after costs (or daily top‑K ranking), not a static
    `p>0.30` rule.
  - Tune selection logic on the validation window for *net* P&L subject to drawdown and
    turnover limits.
  - **Success**: improved trade-level expectancy and reduced variance across months.

- [ ] **Probability calibration (and use calibrated outputs)**
  - Apply Platt scaling or isotonic regression on a strict out-of-sample validation
    split.
  - Gate trades using calibrated EV margins (trade only when edge clears costs by a
    buffer).
  - **Success**: predicted win-rate and realized win-rate are directionally consistent.

- [ ] **Make sizing, notional limits, and cost model “real dollars”**
  - Shares must be derived from actual price and stop distance; enforce notional caps
    consistent with $10k equity (and broker constraints).
  - Validate bid/ask spread + slippage assumptions vs liquidity/volatility buckets.
  - **Success**: backtest position sizes are feasible live and P&L sensitivity to costs
    is explicitly measured.

- [ ] **Trade-level diagnostics (required before any live)**
  - Probability-decile chart vs realized net returns.
  - Confusion matrix and calibration curve at the *trade* horizon.
  - Breakdown by time-of-day, symbol liquidity, volatility regime, and market trend.
  - **Success**: the “why” of wins/losses is explainable and stable.

## Phase 1 (P1): Improve Profit Capture & Robustness

Goal: Increase realized payoff when the model is correct and avoid known bad regimes.

- [ ] **Exit redesign to realize edge**
  - If 2× ATR TP is rarely hit, adopt partial take-profit, closer targets, time-based
    exits, and/or trailing logic aligned to mean reversion behavior.
  - **Success**: average win size increases (or loss size decreases) without exploding
    turnover/costs.

- [ ] **Explicit regime gating**
  - Add market-state filters (trend vs chop, volatility regime, open/close behavior).
  - Avoid or separate catalyst-driven days (earnings/news) if not modeled explicitly.
  - **Success**: drawdowns concentrate less in single periods; “bad months” are reduced.

- [ ] **Universe segmentation**
  - Split SIP universe into strategy-appropriate buckets (e.g., gap-fade vs
    continuation) rather than forcing one mean-reversion policy on all gappers.
  - **Success**: per-bucket expectancy is positive and less correlated.

- [ ] **Cross-sectional trade budget**
  - Daily trade budget + top‑K selection by EV with liquidity/spread constraints.
  - **Success**: fewer, higher-quality trades; reduced cost drag.

## Phase 2 (P2): Structural Upgrades (If Edge Still Weak)

Goal: Upgrade the learning problem and reduce microstructure noise sensitivity.

- [ ] **Predict economically meaningful targets**
  - Regression for expected net return, probability TP-before-SL, or quantile forecasts.
  - **Success**: improved EV ranking and stability vs classification-only approach.

- [ ] **Multi-timeframe context / lower noise execution**
  - Use 3–5 minute execution bars with multi-timeframe features while keeping risk
    controls intraday.
  - **Success**: lower slippage, fewer false positives, improved live feasibility.

- [ ] **Multi-alpha + regime selector**
  - Combine multiple independent intraday alphas (reversion, momentum, volatility)
    with a selector/gating model.
  - **Success**: reduced dependence on one market regime and smoother equity curve.

## Live Readiness Checklist (Non-Negotiable)

- [ ] **Operational constraints confirmed**
  - PDT/cash-settlement constraints, short availability/borrow, order type support,
    and realistic fills.
- [ ] **Portfolio-level risk controls**
  - Max daily loss, max trades/day, max concurrent positions, and an automated kill
    switch on abnormal slippage/model drift.
- [ ] **Paper-trade validation**
  - Log: signal score, intended entry/exit, fills, slippage, realized R-multiple, and
    reason codes for each trade.
- [ ] **Go/No-Go criteria**
  - Positive net expectancy after costs, acceptable drawdown, and stable performance
    across multiple market regimes before increasing size.

---
Not financial advice. This is an engineering/research enhancement plan based on the
system description in `TECHNICAL_DOCUMENTATION_UPDATED_DEC14.md`.

