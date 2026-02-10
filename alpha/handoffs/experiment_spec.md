# Experiment Spec: Deep L2 Liquidity → 300s Price Movement

## Objective (Falsifiable)
Test whether **unusual deep L2 liquidity events** predict subsequent **300-second (5-minute) price movement**. The experiment is falsified if (a) the pooled effect is not distinguishable from zero within confidence intervals and (b) placebo/shuffle tests show effects of comparable magnitude.

## Assumptions & Defaults
- Universe: US equities with L2 coverage; regular session only (09:30–16:00 ET).
- L2 is aggregated to 1-second snapshots; Polygon 1-minute OHLCV is available.
- All timestamps converted to America/New_York.
- Use log returns for outcomes.

## Event Definitions (Unusual Deep Liquidity)
All definitions use **depth band levels 5–20** on both sides of the book (i.e., excluding top 4 levels). Define per-second deep size as:
- `deep_bid_size_t = sum(size_bid_levels_5_to_20)`
- `deep_ask_size_t = sum(size_ask_levels_5_to_20)`
- `deep_total_t = deep_bid_size_t + deep_ask_size_t`

### Definition A: High-Percentile Deep Size (Absolute)
- **Baseline window:** trailing 60 minutes of 1s snapshots per symbol.
- **Unusual criterion:** `deep_total_t >= P99(deep_total)` within the baseline window (or robust z-score ≥ 3 using median/MAD if percentiles are sparse).
- **Persistence:** condition must hold for **≥ 30 consecutive seconds**.
- **Event time:** first second of the persistence run.
- **Cooldown:** enforce a **5-minute no-overlap** window after an event (ignore new events whose forward window would overlap).

### Definition B: Deep/Top Ratio Spike (Relative)
- **Near-book size:** `near_total_t = sum(size_levels_1_to_4 on both sides)`.
- **Ratio:** `ratio_t = deep_total_t / max(near_total_t, 1)`.
- **Baseline window:** trailing 60 minutes.
- **Unusual criterion:** `ratio_t >= P99(ratio)` within baseline, **and** `deep_total_t >= P90(deep_total)` to avoid ratio spikes from near-book collapse.
- **Persistence:** **≥ 20 consecutive seconds**.
- **Event time:** first second of the persistence run.
- **Cooldown:** same 5-minute no-overlap window.

*(Either definition is acceptable; report results for both separately.)*

## Time Alignment Rules
### L2 (1s) to OHLCV (1m)
1. Convert event timestamp to ET.
2. **Assign event to minute bucket** `m = floor(event_ts to minute)`.
3. **Use the next minute’s open** as the event-aligned price to avoid using data from the same minute after the event:
   - `t0_price = open_{m+1}`
4. If `open_{m+1}` is missing (e.g., gap), drop the event.

### Forward 300s (5-minute) Return Using 1m Bars
- **Forward price:** `t1_price = close_{m+5}` (minute `m+5` is the 5th minute after `m+1`).
- **Outcome:** `ret_300s = log(t1_price / t0_price)`.
- **Pre-trend (lead) check:** `ret_pre_300s = log(close_{m} / open_{m-4})` using the 5 minutes prior to the event window (strictly before event minute).

*(If any required bars are missing, drop the event.)*

## Controls & Normalization
Minimum controls:
1. **Time-of-day bucket normalization:** 30-minute buckets (13 buckets over regular session). Compute within-bucket z-scores for `ret_300s` and control variables, or include bucket fixed effects.
2. **Trailing volatility control:** `vol_30m` = rolling std of 1m log returns over prior 30 minutes (per symbol).

Optional additional controls (use at least one if available):
- **Trailing volume:** 30-minute rolling mean of 1m volume.
- **Bid-ask spread proxy:** (ask_1 - bid_1) from L1 in same second; or 1m high-low range.

## Estimation Approach
### Baseline Comparison
- Compare distribution of `ret_300s` for event minutes vs non-event minutes within the same symbol and time-of-day bucket.

### Pooled Effect (Primary)
- Regression or difference-in-means with controls:
  - `ret_300s ~ event_indicator + time_bucket_FE + vol_30m + symbol_FE`.
- Report coefficient on `event_indicator` with CI.

### Per-Symbol Effect (Secondary)
- For each symbol, estimate the event effect with same controls (drop symbol FE), and summarize cross-sectional distribution of effects.

### Confidence Intervals
- **Bootstrap** with fixed seed (e.g., 42): resample **days within symbol** to preserve intraday structure.
- 1,000 bootstrap reps (or as feasible), report 95% CIs.
- Record seeds in metadata.

## Falsification & Robustness
1. **Placebo test (mandatory):**
   - Shuffle event times **within each day and time-of-day bucket** for each symbol, preserving event counts.
   - Recompute effects; expect near-zero and statistically insignificant.
2. **Lead/lag pre-trend check (mandatory):**
   - Estimate effect on `ret_pre_300s` (−300s..0). Expect no effect.
3. **Time-shift falsification (mandatory):**
   - Shift event timestamps by +30 minutes (within session) and re-run. Expect no effect.
4. **Regime stratification (suggested):**
   - Split by high vs low `vol_30m` (median split per symbol/day) and report effects.

## Event De-duplication & Filtering
- Enforce **5-minute cooldown** after each event to prevent overlapping forward windows.
- Exclude events within the first 5 minutes and last 6 minutes of the session (insufficient history/forward bars).

## Expected Output Tables in RESULTS.md
Engineering should generate these tables (with both Definition A and B sections):
1. **Event Counts:** rows by symbol and total; columns = `n_events`, `n_placebo`, `n_days`, `avg_events_per_day`.
2. **Pooled Effect (Primary):** columns = `definition`, `coef_event`, `ci_low`, `ci_high`, `p_value`, `n_events`, `n_controls`.
3. **Per-Symbol Effects:** columns = `symbol`, `definition`, `coef_event`, `ci_low`, `ci_high`, `n_events`.
4. **Placebo Results:** columns = `definition`, `coef_event`, `ci_low`, `ci_high`, `p_value`, `n_placebo`.
5. **Pre-Trend Check:** columns = `definition`, `coef_event_pre`, `ci_low`, `ci_high`, `p_value`, `n_events`.
6. **Regime Stratification:** columns = `definition`, `regime` (high/low vol), `coef_event`, `ci_low`, `ci_high`, `n_events`.
7. **Threshold Sensitivity (if run):** columns = `definition`, `threshold` (e.g., P97/P99/P99.5), `coef_event`, `ci_low`, `ci_high`, `n_events`.

## Notes
- Keep definitions and thresholds consistent across symbols unless coverage is too sparse; if sparse, relax to P97 but report it in sensitivity table.
- Record all filtering rules, seed, and dropped-event counts in metadata.
