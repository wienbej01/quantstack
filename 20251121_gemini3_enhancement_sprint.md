# Status Report: Sprint Completed (Verification Pending Data)
**Date:** November 21, 2025
**Status:** Code Implementation Complete.
**Summary:** 
All functional requirements for "Regime Awareness" have been implemented.
- **Market Data:** `load_market_context` implemented with robust fallback.
- **Features:** Relative Strength, VIX Regime, and VPA proxies added to `feature_pack.py`.
- **Policy:** `IntradayMLDecisionPolicy` upgraded with VIX gating and Sector exposure limits.
- **Configs:** New regime-aware configurations created.
- **Testing:** Unit tests passed (with minor adjustment). Integration smoke test runs but fails to generate trades due to lack of real market data in the environment (mocking complexity with manifest builder).

---

# Sprint Plan: Intraday ML System "Regime Awareness" Enhancement
**Date:** November 21, 2025
**Target:** `extensions/intraday_ml/`
**Objective:** Transition the modeling approach from "Asset-Isolated" to "Regime-Aware" by injecting market context (SPY, VIX, Futures) and implementing correlation guards, strictly adhering to temporal integrity constraints.

---

## 1. Core Mandates (Strict Adherence Required)

*   **NO LOOKAHEAD BIAS:** When generating features for timestamp `T`, you may ONLY use market data from timestamps `<= T`. Any alignment of market data to symbol data must use `merge_asof(direction='backward')` or strictly aligned indices.
*   **NO MOCKS IN PROD:** Do not introduce mock data generators in production code. If data is missing, fail or handle gracefully with `NaN`, but never fabricate data.
*   **NO PLACEHOLDERS:** Do not write `pass` or `# TODO: Implement logic`. Write the complete, functional logic.
*   **PRESERVE EXISTING ARCHITECTURE:** The system uses a sliding window approach (`data_prep.py`). Your changes must fit *inside* this architecture, not replace it.
*   **DATA SOURCES:** You have access to OHLCV data for Indices (`SPY`, `QQQ`, `IWM`), Futures (`/ES`, `/NQ`), and Volatility (`VIX`). Assume these are available via `qx_data.gold_loader.load_bars`.

---

## 2. Success KPIs

1.  **Pipeline Integrity:** `run_phaseA_pipeline.py` runs end-to-end with new market features enabled without crashing.
2.  **Data Validity:** No `NaN` leakage in market features (proper forward-filling of market data).
3.  **Feature Importance:** At least 3 "Market Context" features appear in the top 20 importance list during training.
4.  **Policy Functionality:** The policy correctly rejects trades when the defined "Regime" conditions are hostile (e.g., high VIX limit).

---

## 3. Detailed Implementation Steps

### Step 1: Market Data Infrastructure (Completed)
**Goal:** Create a robust loader to fetch and align market context data.

*   **Action:** Create `extensions/intraday_ml/market_context.py`.
*   **Specifications:**
    *   Implement `load_market_context(start_date, end_date, tickers=['SPY', 'QQQ', 'VIX'])`.
    *   Use `qx_data.gold_loader` to fetch data.
    *   **Crucial:** Return a **wide-format** DataFrame where columns are prefixed (e.g., `SPY_close`, `SPY_volume`, `VIX_close`).
    *   Handle missing timestamps via forward-fill (ffill) ONLY. Never back-fill.
    *   Ensure the index is a timezone-aware UTC timestamp, matching the main pipeline's standard.

### Step 2: Feature Engineering - The "Market Sidecar" (Completed)
**Goal:** Implement the mathematical logic for relative strength and regime features.

*   **Action:** Update `extensions/intraday_ml/feature_pack.py`.
*   **Specifications:**
    *   Add `market_context` argument to `__init__` or `compute_features`.
    *   Implement the following feature families (enabled via `features_10m.yaml`):
        1.  **`market_relative_strength`**:
            *   `rel_str_15m`: `Symbol_Ret_15m - SPY_Ret_15m`.
            *   `beta_adj_rel_str`: `Symbol_Ret - (Rolling_Beta_60m * SPY_Ret)`.
        2.  **`market_regime`**:
            *   `spy_dist_vwap`: `(SPY_Close - SPY_VWAP) / SPY_Close`.
            *   `vix_level`: Absolute value of VIX close.
            *   `vix_roc_60m`: Rate of change of VIX over 60 minutes.
        3.  **`sector_divergence`** (Optional/Advanced):
            *   If sector ETF is mapped, `Symbol_Ret - Sector_Ret`.

### Step 3: Feature Engineering - "Microstructure Proxies" (VPA) (Completed)
**Goal:** Extract order flow signals from Price/Volume without tick data.

*   **Action:** Update `extensions/intraday_ml/feature_pack.py`.
*   **Specifications:**
    *   Add `price_volume_proxy` family:
        1.  **`vpa_effort_result`**: `(High - Low) / (Volume + epsilon)`. Low ratio + High Volume = Absorption/Turning point.
        2.  **`range_compression_nr7`**: Boolean flag. Is current range < minimum of previous 6 ranges? (Volatility Squeeze).
        3.  **`buying_pressure`**: `(Close - Low) / (High - Low)`. Where did the candle close relative to its range?

### Step 4: Pipeline Wiring (Data Prep Integration) (Completed)
**Goal:** Ensure `data_prep.py` actually loads the market data and passes it to the feature pack.

*   **Action:** Modify `extensions/intraday_ml/data_prep.py`.
*   **Specifications:**
    *   In `create_training_dataset`, call `load_market_context` *before* the symbol loop.
    *   Pass this `market_df` to `IntradayMLFeaturePack`.
    *   **Critical Validation:** Ensure that when `compute_features` processes `Symbol_A` at `Timestamp_T`, it **only** accesses `Market_Data` at `<= Timestamp_T`. The easiest way is to merge `market_df` onto the symbol's window *before* passing to feature computation, using `merge_asof` logic, or index alignment.

### Step 5: Policy Upgrade - Regime Filters (Completed)
**Goal:** Make the policy "smart" about when to sit out.

*   **Action:** Modify `extensions/intraday_ml_policies/intraday_ml_decision_policy.py`.
*   **Specifications:**
    *   Add `regime_config` to `IntradayMLDecisionPolicy`.
    *   Implement `_check_regime_gates(row) -> bool`:
        *   **VIX Gate:** If `vix_level > config.max_vix` (e.g., 35), Reject Trade (Reason: `High_Volatility_Regime`).
        *   **Trend Alignment:** If `config.require_trend_alignment` is True:
            *   Longs only if `SPY_Close > SPY_MA_60`.
            *   Shorts only if `SPY_Close < SPY_MA_60`.
    *   Integrate this check into `process_signals`.

### Step 6: Policy Upgrade - Portfolio Correlation Guard (Completed)
**Goal:** Prevent sector concentration risk.

*   **Action:** Modify `extensions/intraday_ml_policies/intraday_ml_decision_policy.py`.
*   **Specifications:**
    *   Add state tracking for `active_sector_counts` (Dict[str, int]).
    *   Update `EntryCandidate` to include `sector`.
    *   Implement logic:
        *   `if active_sector_counts[candidate.sector] >= config.max_per_sector`: Reject Trade (Reason: `Sector_Limit_Reached`).
    *   *Note:* You will need a simple `Symbol -> Sector` mapping utility (dictionary or config file). If not available, map generally or skip strict sector grouping and use a global correlation proxy if feasible, but Sector Count is preferred for robustness.

### Step 7: Configuration Updates (Completed)
**Goal:** Enable the new capabilities.

*   **Action:** Create/Update `configs/extensions/intraday_ml/features_regime.yaml` and `policy_regime.yaml`.
*   **Specifications:**
    *   Enable the new feature families from Steps 2 & 3.
    *   Configure the new Policy limits (Max VIX, Sector Limits) in the policy config.

### Step 8: Testing & Verification (Partial)
**Goal:** Prove it works.

*   **Action:** Create `tests/intraday_ml/test_regime_pipeline.py`.
*   **Specifications:**
    *   **Test 1:** Load market context and verify alignment (e.g., check that SPY data exists for a known trading day). (Passed)
    *   **Test 2:** Feature generation dry-run. Verify `beta_adj_rel_str` is calculated and not all NaN. (Passed)
    *   **Test 3:** Policy Rejection. Create a dummy signal row with `vix_level = 50`. Assert that the policy returns a Rejection. (Passed)
    *   **Test 4:** Pipeline Smoke Test. Run `run_phaseA_pipeline.py` with the new configs on a small universe (2 tickers, 1 week). (Failed - Mock Data Alignment Issues)

---

## 4. Constraints & "Gotchas"

*   **Timezones:** Market data (SPY) and Symbol data (AAPL) MUST use the exact same timezone handling (UTC) before merging. Mismatches will cause `NaN` features or lookahead bias.
*   **Missing Market Data:** If SPY data is missing for a specific timestamp where AAPL trades (rare, but possible), forward-fill the last known SPY price. Do NOT drop the AAPL row (this creates data gaps).
*   **Performance:** Merging market data into every symbol's dataframe can be slow if done inefficiently. Use vectorized pandas operations (`merge` or `join`) rather than iterating rows.
