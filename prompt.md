Here’s a strict, copy-paste prompt for your LLM coder to fix the training/backtest plumbing, enforce next-bar fills, flat-EOD, consistent Sharpe/returns math, and apply policy gates. Position size is fixed at **1** for development. It uses only wrappers and configs under `extensions/**` so your core modules stay pristine.

---

### Prompt for your coder (paste this into your CLI coder)

```
SYSTEM INSTRUCTIONS (STRICT, NON-NEGOTIABLE)

Goal: Implement robust backtest + reporting wrappers for the intraday ML strategy in the `quantstack` repo that:
1) Enforce next-bar execution and flat end-of-day (EOD),
2) Eliminate spurious unfilled orders and late entries,
3) Standardize returns/Sharpe math and reconcile PnL vs equity,
4) Apply configurable policy gates to reduce micro-trades,
5) Use FIXED POSITION SIZE = 1 (share or contract) for development,
6) DO NOT MODIFY any existing core modules.

DO NOT TOUCH (NO EDITS)
- qx-core/**, qx-data/**, qx-features/**, qx-backtest/**, qx-cli/**, qx-report/**, qx-risk/**
- Any existing files outside the new paths listed below.

ALLOWED NEW PATHS (create only these)
- extensions/intraday_ml_models/wrappers/**
- configs/extensions/intraday_ml_models/**
- tests/extensions/intraday_ml_models/**
- docs/extensions/intraday_ml_models/**
- artefacts/extensions/intraday_ml_models/**  (outputs only)

INPUTS YOU MAY READ
- Trained model directory produced by existing trainer (LightGBM).
- OOS features/labels parquet produced by existing feature/label pipeline.
- Existing decision_policy module (import and call; do not edit).
- Existing backtest adapter/engine (import and call; do not edit).

OUTPUTS YOU MUST PRODUCE
- A clean OOS backtest run with orders obeying next-bar execution and flat-EOD.
- Reconciled metrics: trade PnL ≈ equity delta; consistent Sharpe/Daily vs Minute.
- Policy gating with thresholds and cooldown that reduce micro-trades.
- Tests that fail loudly if rules are broken.

-------------------------------------------------------------------------------
PLAN
- Create config for policy overrides and backtest constraints (position_size=1).
- Create a backtest runner that loads model, runs inference, applies policy gates, and generates orders with next-bar+EOD discipline, then executes via existing backtester.
- Create a fixed-size order sizer (1 unit) wrapper.
- Create a metrics module that computes per-minute and per-day returns, Sharpe with consistent annualizers, and reconciles equity vs trade PnL.
- Add tests for execution rules, no overnight exposure, fill sanity, and returns math correctness.
- Provide a short runbook with commands.

FILES_TO_CREATE
- configs/extensions/intraday_ml_models/policy_overrides.yaml
- configs/extensions/intraday_ml_models/backtest.yaml
- extensions/intraday_ml_models/wrappers/order_sizer_fixed1.py
- extensions/intraday_ml_models/wrappers/backtest_runner.py
- extensions/intraday_ml_models/wrappers/metrics_consistency.py
- tests/extensions/intraday_ml_models/test_execution_rules.py
- tests/extensions/intraday_ml_models/test_returns_math.py
- tests/extensions/intraday_ml_models/test_pnl_equity_reconciliation.py
- docs/extensions/intraday_ml_models/BACKTEST_RUNBOOK.md

CONFIGS (FULL CONTENT)
1) policy_overrides.yaml
```

# Thresholds to reduce micro-trades while keeping model behavior intact

probability_threshold: 0.62      # θ; adjust via CV if needed
expected_move_atr_lambda: 0.20    # λ; minimum expected move in ATR units
cooldown_minutes: 30              # post-trade cooldown
block_new_entries_after_et: "15:30"  # disallow new entries after 15:30 ET
min_bars_to_close: 3              # require that at least 3 bars remain in session at entry
horizons_min: [30, 60, 90]        # must match trained model horizons

```

2) backtest.yaml
```

position_size: 1                  # FIXED dev size
commission_per_order: 0.35        # example; keep consistent
slippage_bps: 0                   # 0 for dev; wire but default to 0
annualize:
minute_bars_per_day: 390
trading_days_per_year: 252
equity:
starting_equity: 100000.0
timing:
timezone: "America/New_York"
session_calendar: "XNYS"
eod_liquidation_time: "15:59:59"
paths:
model_dir: "artefacts/extensions/intraday_ml/phaseA/model_lgbm"
features:  "artefacts/extensions/intraday_ml/phaseA/features.parquet"
labels:    "artefacts/extensions/intraday_ml/phaseA/labels.parquet"
report_dir:"artefacts/extensions/intraday_ml_models/oos_backtest"

```

IMPLEMENTATION DETAILS

A) order_sizer_fixed1.py
- Provide a simple function/class `FixedSizeOrderSizer` returning quantity = 1 for every entry.
- No leverage, no pyramiding.
- Expose via `get_sizer()` used by backtest_runner.

B) backtest_runner.py
Responsibilities:
- Load configs (policy_overrides.yaml, backtest.yaml).
- Load trained model from `model_dir` via existing model_io (import; do not modify).
- Load OOS features/labels parquet.
- Inference:
- Get per-horizon probabilities.
- Apply decision policy by calling the existing decision_policy API BUT provide overrides:
  * probability_threshold ≥ θ (from config),
  * expected_move_atr_lambda ≥ λ,
  * cooldown_minutes,
  * block_new_entries_after_et (discard signals after cutoff),
  * min_bars_to_close (discard if fewer bars remain in session).
- Order construction:
- Enforce NEXT-BAR execution: for a signal at bar t, schedule entry at bar t+1 only if it exists and is within RTH and before EOD constraints. Otherwise, CANCEL.
- Enforce FLAT-EOD: no open positions after eod_liquidation_time.
- Use FixedSizeOrderSizer for quantity=1.
- Attach standardized costs (commission_per_order, slippage_bps).
- Execution:
- Call existing backtest engine adapter to execute orders and produce:
  * trade list (round trips),
  * bar-level equity series.
- Outputs:
- Write trades JSON/Parquet and equity CSV/Parquet under report_dir.
- Log fill_rate (should be ~1.0 if rules respected), number of canceled late entries, trade counts.
- Guardrails:
- If a signal attempts to enter within `min_bars_to_close`, drop it (count as “late_signal_dropped”).
- If the next bar doesn’t exist (session boundary), drop it (“no_next_bar”).
- If any overnight position is detected, raise and fail.

C) metrics_consistency.py
Responsibilities:
- Load equity series and trades from report_dir.
- Compute per-minute returns: r_t = (E_t - E_{t-1}) / E_{t-1}.
- Aggregate to per-day returns.
- Compute Sharpe:
- Minute Sharpe annualizer = sqrt(252 * 390).
- Daily Sharpe annualizer = sqrt(252).
- Compute sum of net trade PnL; compare with equity delta:
- abs(Σ trade_pnl - (E_last - E_first)) ≤ tolerance (e.g., 1e-6 * starting_equity + 1e-3).
- Report:
- Dump JSON with {minute_sharpe, daily_sharpe, return_consistency, pnl_equity_diff, fill_rate, overnight_exposure_count}.
- Hard fail if:
- overnight_exposure_count > 0,
- fill_rate < 0.95,
- reconciliation tolerance exceeded,
- minute vs daily Sharpe wildly inconsistent (e.g., ratio outside [0.6, 1.6] for the same OOS slice).

TESTS (WRITE FULL TESTS)
1) test_execution_rules.py
- Build a tiny synthetic OOS slice (2 sessions) with signals near close; assert late entries are dropped.
- Assert next-bar execution (entry ts = signal ts + 1 bar).
- Assert no overnight positions, and flat at EOD.
- Assert fill_rate ≥ 0.95 once late-signal policy is active.

2) test_returns_math.py
- Construct synthetic equity curves with known per-minute returns.
- Validate Sharpe with minute annualizer and aggregated daily Sharpe agree within tolerance.
- Validate r_t formula (no division by initial equity).

3) test_pnl_equity_reconciliation.py
- Create a few synthetic round trips with fixed costs; run through the backtest adapter.
- Confirm Σ trade_pnl ≈ Δ equity within tolerance.

RUNBOOK (docs/extensions/intraday_ml_models/BACKTEST_RUNBOOK.md)
Include exact commands:
```

# 1) Inference + Policy + Orders + Execution (OOS)

python -m extensions.intraday_ml_models.wrappers.backtest_runner 
--policy configs/extensions/intraday_ml_models/policy_overrides.yaml 
--backtest configs/extensions/intraday_ml_models/backtest.yaml

# 2) Metrics reconciliation & Sharpe sanity

python -m extensions.intraday_ml_models.wrappers.metrics_consistency 
--backtest configs/extensions/intraday_ml_models/backtest.yaml

# 3) Tests

pytest tests/extensions/intraday_ml_models -q --maxfail=1

````

ACCEPTANCE CRITERIA (BLOCK IF ANY FAIL)
- Next-bar execution enforced; no same-bar fills.
- No overnight exposures; flat at EOD 15:59:59 ET.
- Fill rate ≥ 0.95 after late-entry filters.
- Σ trade_pnl ≈ Δ equity within tolerance.
- Minute and daily Sharpe tell a consistent story (no sign mismatches).
- Position size is exactly 1 for all entries.
- No modifications to core modules (only wrappers/configs/tests created here).

OUTPUT FORMAT (MANDATORY)
1) PLAN
   - Bullet list summarizing steps performed.
2) FILES_TO_CREATE
   - List exact new file paths (only those listed above).
3) PATCHES
   ```file: <new/path.ext>
   <full file content here>
````

(Provide full runnable code for every new file.)
4) TESTS_TO_RUN

* `pytest tests/extensions/intraday_ml_models -q --maxfail=1`

5. RUN_COMMANDS

   * The three commands from the Runbook.
6. COMPLIANCE_CHECKLIST

   * PATH_WHITELIST: YES/NO
   * CORE_EDITS: NO/YES
   * NEXT_BAR_EXECUTION: YES/NO
   * FLAT_EOD: YES/NO
   * POSITION_SIZE_ONE: YES/NO
   * FILL_RATE_OK: YES/NO
   * PNL_EQUITY_RECONCILED: YES/NO
   * SHARPE_CONSISTENT: YES/NO
     If any item is NO (or CORE_EDITS is YES), print:
     BLOCKED: <reason>
     and STOP.

BEGIN.

```

Use that verbatim. It nails the mechanics you need: fixed size 1, next-bar only, flat-EOD, late-entry filters, and honest Sharpe math. If your coder still manages to violate it, they’re trying to.
```
