# Intraday SIP Integration Sprint Plan for `quantstack` (Codex CLI Prompt)

You are a head of quant trading system development and senior Python engineer in a hedgefund, working on the `quantstack` repository (`wienbej01/quantstack`).  
Your task is to integrate the existing **Stock‑In‑Play (SIP)** logic into the intraday ML pipeline so that:

- **Training and OOS backtests** can operate on a **SIP‑filtered universe** when configured to do so.
- SIP membership is **precomputed once** and stored efficiently, then **re‑used** by ML runs.
- The code is clean, tested, and backward‑compatible.

The repository contains an existing SIP implementation in **`qx-screener`** using a Hidden Markov Model (HMM) based selector:
- `qx-screener/src/qx_screener/hmm_sip.py`  
  - `HMMSIPConfig` – configuration object
  - `HMMSIPUniverseSelector` – main entry point for stock‑in‑play selection (supports “legacy” and “daily” modes)

You must **reuse this module** rather than coding SIP from scratch.  
When you modify a file, **print the entire updated file**, not just diffs.  
Do **not** run long‑running, full‑universe SIP jobs; only implement the tooling to run them later.
you are **prohibited** for changing any other code files without the explicit and direct authorization of the user. you **must** at all time prevent any data leakage / forward-look in the code as this is a **real-life** equity trading system.
you are **prohibited** from introducing mock/synth/dummy data into the system, except for strict functionality testing purpose. such test data and usage must be removed after use

Repo root is assumed to be the checked‑out `quantstack` repo. Intraday ML code lives mainly under:

- `extensions/intraday_ml`
- `extensions/intraday_ml_models`
- Phase‑A orchestration script: `run_phaseA_pipeline.py` at repo root.

---

## High‑Level Objective

Implement a **SIP‑aware intraday ML workflow** such that:

1. SIP membership is **precomputed** over a date range & universe using `HMMSIPUniverseSelector` and stored as partitioned parquet.
2. The **Phase‑A pipeline** can be configured to:
   - Train & validate using only SIP tickers (`sip_only`),
   - Use non‑SIP tickers (`no_sip`),
   - Or ignore SIP (`all`, i.e. legacy behavior).
3. Train/OOS symbol universes are **derived from SIP membership** when enabled, with **no change in behavior** when disabled.
4. A small set of tests verify correctness, and non‑SIP runs remain identical to current behavior.

You are not allowed to silently “simplify” the SIP algorithm: use `HMMSIPUniverseSelector` and/or its documented fallbacks.  
If something is ambiguous, make a reasonable assumption and document it in comments near the new code.

---

## Step 0 – Git hygiene & branch setup

**Goal:** Ensure the current code is checkpointed and all SIP work happens on a dedicated branch.

**Tasks:**

1. Show current status and branch:

   ```bash
   git status
   git branch
   ```

2. If there are uncommitted changes, stage and commit them:

   ```bash
   git add -A
   git commit -m "checkpoint: pre-SIP integration"
   ```

3. Push the current branch to `origin` (do not create a new remote here):

   ```bash
   git push
   ```

4. Create and switch to a new development branch for SIP integration:

   ```bash
   git checkout -b feature/intraday-sip-integration
   ```

You may assume `origin` is already configured.  
Do not attempt to rename branches or modify remote configuration.

---

## Step 1 – Discover and summarize existing SIP implementation

**Goal:** Identify and document the existing SIP module so further work reuses it.

**Tasks:**

1. Confirm SIP‑related modules via search (you can use `rg`/`grep` conceptually, but don’t actually run shell here):

   - `qx-screener/src/qx_screener/hmm_sip.py`
   - `qx-screener/src/qx_screener/daily_hmm_sip.py`
   - `qx-screener/src/qx_screener/sip.py`
   - Any relevant README / docs under `qx-screener` or `docs/features`

2. Open **`qx-screener/src/qx_screener/hmm_sip.py`** and note in code comments (no separate doc needed):

   - The purpose of `HMMSIPConfig` and `HMMSIPUniverseSelector`.
   - That `HMMSIPUniverseSelector` is the authoritative SIP universe selector to be used for precomputing membership.
   - That the `daily` mode is currently incomplete and we will **use `mode="legacy"` for now**, which already supports a fast cross‑sectional ranking fallback (e.g. using gap and pre‑market dollar volume).

3. Open `qx-screener/src/qx_screener/sip.py` and verify that it is a simpler relative‑volume SIP screener.  
   You do **not** need to integrate this module into the intraday ML pipeline in this sprint; just be aware it exists.

The output of this step is **comments in code** (e.g. in the new SIP membership module and/or CLI) making clear that:

- SIP selection is delegated to `HMMSIPUniverseSelector` (legacy mode),
- Full daily HMM scoring is out of scope for this sprint.

---

## Step 2 – Design & implement SIP membership I/O layer

**Goal:** Provide a reusable, efficient way to **store and load SIP membership** that training/OOS can consume.

**Design decisions:**

- SIP membership will be stored as **partitioned parquet** under the gold root.
- Partitioning key: `trade_date` (string or date, normalized to `YYYY-MM-DD`).
- Core schema:

  ```text
  trade_date : date or string YYYY-MM-DD
  symbol     : string
  is_sip     : bool/int (1 = SIP ticker, 0 = non-SIP ticker)
  sip_score  : float | optional (SIP score/rank); may be NaN if unknown
  sip_reason : string | optional (e.g. "legacy_gap_rvol")
  ```

- Directory layout example (adapt to existing conventions):

  ```text
  {gold_root}/intraday_ml/sip_membership/
    ├── trade_date=2023-01-02/part-0000.parquet
    ├── trade_date=2023-01-03/part-0000.parquet
    └── ...
  ```

**Tasks:**

1. Create a new module, e.g.:

   - `extensions/intraday_ml/sip_membership.py`

2. In this module, implement functions along these lines (adapt signatures as needed to match existing style):

   ```python
   from __future__ import annotations

   import pandas as pd
   from pathlib import Path
   from typing import Literal

   SIPMode = Literal["sip_only", "no_sip", "all"]

   def get_sip_membership_base_path(gold_root: str | Path) -> Path:
       # Return the base path for SIP membership parquet files under the gold root.
       # Example: {gold_root}/intraday_ml/sip_membership

   def save_sip_membership(df: pd.DataFrame, gold_root: str | Path) -> None:
       # Persist SIP membership rows as partitioned parquet under
       # {gold_root}/intraday_ml/sip_membership.
       #
       # Expected columns: trade_date, symbol, is_sip
       # Optional: sip_score, sip_reason.
       #
       # This function should:
       # - Normalize data types (trade_date as string YYYY-MM-DD, symbol as str).
       # - Write using partitioning by trade_date.
       # - Overwrite any existing partition for dates present in df (idempotent per date).

   def load_sip_membership_for_dates(
       gold_root: str | Path,
       start_date: str,
       end_date: str,
       mode: SIPMode = "sip_only",
   ) -> pd.DataFrame:
       # Load SIP membership for [start_date, end_date] (inclusive), filtered by mode.
       #
       # mode == "sip_only": return rows where is_sip is True/1.
       # mode == "no_sip" : return rows where is_sip is False/0.
       # mode == "all"    : return all rows.
       #
       # Raise a clear error if no data is found for the requested date range.
   ```

3. Implement filesystem logic using `pathlib` and `pandas`:

   - Use `pd.DataFrame.to_parquet` with appropriate partitioning.
   - When loading, filter by `trade_date` range and `mode`.
   - Ensure you handle the case where some dates are missing (raise or warn clearly).

4. Add minimal **input validation**:

   - Check for required columns in `save_sip_membership`.
   - In `load_sip_membership_for_dates`, validate that `start_date <= end_date` and that `mode` is one of the allowed values.

This module **does not compute SIP**; it only handles storage and retrieval.

---

## Step 3 – CLI to precompute SIP membership (using HMMSIPUniverseSelector)

**Goal:** Provide a command‑line tool that **precomputes daily SIP membership** over a date range & universe using the existing HMM SIP selector, then stores the results via `sip_membership.py`.

**Constraints:**

- You must **not** run long, overnight full‑universe jobs in this session.
- The CLI should be safe to run incrementally (e.g. re‑run for overlapping dates to overwrite partitions).
- SIP selection logic must come from `HMMSIPUniverseSelector` in `qx_screener.hmm_sip` (legacy mode for now).

**Tasks:**

1. Add a new CLI module, for example:

   - `extensions/intraday_ml/cli_build_sip_membership.py`

2. In this module:

   - Import:

     ```python
     from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector
     from extensions.intraday_ml.sip_membership import save_sip_membership
     ```

   - Implement an `argparse` CLI with arguments such as:

     - `--start-date YYYY-MM-DD` (required)
     - `--end-date YYYY-MM-DD` (required)
     - `--universe-config PATH` (path to existing universe config used by Phase A)
     - `--gold-root PATH` (defaults to current gold root if there is a canonical place)
     - `--top-k INT` (optional, default e.g. 40)
     - `--score-floor FLOAT` (optional, default 0.0)
     - `--mode {legacy}` (for now, restrict to `"legacy"`)
     - `--max-workers INT` (optional for future parallelization; can be unused initially)

   - Construct `HMMSIPConfig` from arguments, e.g.:

     ```python
     config = HMMSIPConfig(
         top_k=args.top_k,
         score_floor=args.score_floor,
         mode="legacy",
         # fill any other required fields with sensible defaults / config values
     )
     selector = HMMSIPUniverseSelector(config=config, ...)
     ```

   - For each date in `[start_date, end_date]`:

     - Load the relevant universe for that date (using existing universe/universe‑adapter machinery already used by your screener or intraday ML pipeline).
     - Call the selector’s method (e.g. `selector.select(date, universe, ...)` – adapt to actual API) to obtain the SIP selection:
       - This should give you a list or mapping of SIP symbols and possibly scores.
     - Build a DataFrame with columns:
       - `trade_date` (that date),
       - `symbol`,
       - `is_sip` (True for SIP symbols; you can choose not to emit non‑SIP rows at this stage),
       - `sip_score` (if available),
       - `sip_reason` (e.g. `"legacy_hmm_sip"` or `"legacy_gap_rvol"`).
     - Call `save_sip_membership(df_for_that_date, gold_root)`.

   - Print concise progress logs, e.g. “processed 2023‑01‑02: 40 SIP symbols”.

3. At the bottom of the file, add a docstring or comment with an example usage, e.g.:

   ```bash
   # Example usage (run manually from terminal, not by this CLI session):
   python -m extensions.intraday_ml.cli_build_sip_membership      --start-date 2023-01-01      --end-date 2023-12-31      --universe-config configs/intraday_ml/universe_sp500.yaml      --gold-root /home/jacobw/gcs-mount/gold      --top-k 40
   ```

Do **not** automatically run this command in the sprint; it is for the human user to execute, potentially overnight.

---

## Step 4 – Add SIP configuration to Phase‑A configs

**Goal:** Allow Phase‑A runs to optionally use SIP membership when building training and OOS universes.

**Tasks:**

1. Identify the Phase‑A config(s) used by `run_phaseA_pipeline.py`, typically under:

   - `configs/intraday_ml/` or similar.

2. Add a `sip_filter` block to the relevant YAML config(s). For example:

   ```yaml
   sip_filter:
     enabled: false            # default / legacy behavior
     mode: "sip_only"          # "sip_only" | "no_sip" | "all"
    membership_path: "/home/jacobw/quantstack/run/sip_membership"
   ```

3. Create at least:

   - One config where `sip_filter.enabled: false` (current behavior, no SIP).
   - One “SIP‑enabled” example config with:

     ```yaml
     sip_filter:
       enabled: true
       mode: "sip_only"
      membership_path: "/home/jacobw/quantstack/run/sip_membership"
     ```

Do not hardcode machine‑specific paths in the code; read them from config.

---

## Step 5 – Integrate SIP into Phase‑A pipeline (train & OOS)

**Goal:** Make `run_phaseA_pipeline.py` use precomputed SIP membership to choose the symbol universe for training and OOS when configured.

**Tasks:**

1. Open `run_phaseA_pipeline.py` and identify where:

   - The configs are loaded,
   - The universe/symbol list is derived,
   - The training/OOS datasets are built (likely via `DatasetManifestBuilder`, `create_training_dataset`, or similar in `extensions/intraday_ml/data_prep.py`).

2. Add a helper to centralize SIP‑aware symbol selection. For example, inside an appropriate module (either `run_phaseA_pipeline.py` or a small helper in `extensions/intraday_ml/sip_membership.py`):

   ```python
   from extensions.intraday_ml.sip_membership import load_sip_membership_for_dates

   def get_phase_symbols_with_sip(
       gold_root: str,
       splits_config: dict[str, Any],
       sip_config: dict[str, Any],
       phase: str,  # "train", "val", "test", "oos"
   ) -> list[str]:
       # Return the symbol universe for a given phase, optionally filtered by SIP.
       #
       # If sip_config["enabled"] is False, this should fall back to the
       # existing universe logic (no SIP filter).
   ```

3. Implement logic along these lines:

   - Determine date range for the given `phase` from existing splits logic.
   - If `sip_filter.enabled` is `False`:
     - Use existing universe logic to determine symbol list (no change).
   - If `sip_filter.enabled` is `True`:
     - Call `load_sip_membership_for_dates(...)` with:
       - `start_date`, `end_date` of the phase,
       - `mode` taken from `sip_filter.mode` (`"sip_only"`, `"no_sip"`, or `"all"`).
     - Derive symbol universe for that phase, e.g.:
       - Simple approach: use the **union** of SIP symbols over the phase date range.
       - More advanced approach (optional at this stage): phase/day‑specific symbol sets; for now union is acceptable.
     - Return this symbol list to the rest of the pipeline.

4. Wire this helper into `run_phaseA_pipeline.py`:

   - Wherever the code currently constructs a universe (list of symbols) for training / OOS:
     - Replace or augment that logic to call `get_phase_symbols_with_sip(...)` when SIP is enabled.
   - Pass these symbol lists into the downstream data prep / manifest builder functions instead of the original, SIP‑agnostic lists.

5. Ensure **no SIP computation** is performed inside Phase‑A:

   - Phase‑A must only **read** from the SIP membership parquet.
   - If membership files are missing for the requested date ranges, raise a clear exception telling the user to run the SIP membership CLI first.

6. Preserve default behavior:

   - When `sip_filter.enabled` is `False`, the symbol universe and behavior must be identical to pre‑sprint behavior (same symbols, same splits).

---

## Step 6 – Ensure data prep respects SIP decisions

**Goal:** Confirm that all phases of data prep honor the SIP‑filtered symbol sets when enabled.

**Tasks:**

1. Inspect `extensions/intraday_ml/data_prep.py` (or equivalent) and locate:

   - `create_training_dataset`,
   - Any functions that ingest symbol lists / universes,
   - Any custom loaders for OOS / backtest data.

2. Verify or adjust function signatures so that:

   - The **symbols** argument reflects the SIP‑filtered universe when SIP is enabled.
   - No internal code re‑expands to the full universe ignoring SIP.

3. If necessary, add internal assertions or logging, e.g.:

   - Log the number of symbols used for training vs OOS, indicating whether SIP filter is enabled and which `mode` is used.

4. Do **not** add SIP logic directly into `data_prep.py`; SIP filtering should be applied **before** data prep is called, by controlling the symbol universe passed into these functions.

---

## Step 7 – Tests and validation

**Goal:** Validate the new SIP membership I/O layer, the SIP integration, and ensure legacy behavior is intact.

**Tasks:**

1. **Unit tests for SIP membership I/O**

   - Add tests under `tests/extensions/intraday_ml/`, e.g. `test_sip_membership.py`.
   - Use a temporary directory (e.g. `tmp_path` fixture) as a fake gold root.
   - Create a small DataFrame:

     ```python
     data = pd.DataFrame(
         {
             "trade_date": ["2023-01-02", "2023-01-02", "2023-01-03"],
             "symbol": ["AAPL", "MSFT", "AAPL"],
             "is_sip": [1, 0, 1],
             "sip_score": [0.9, 0.1, 0.95],
         }
     )
     ```

   - Call `save_sip_membership(data, gold_root)`.
   - Then call `load_sip_membership_for_dates` for:
     - `mode="sip_only"` → expect only rows with `is_sip == 1`,
     - `mode="no_sip"` → only `is_sip == 0`,
     - `mode="all"` → all rows.
   - Assert expected row counts and symbol sets.

2. **Unit / small integration test for SIP‑aware Phase symbols**

   - Add tests for `get_phase_symbols_with_sip` (wherever you defined it).
   - Use a mocked or synthetic `splits_config` that defines train/test ranges over the dates in the test SIP membership.
   - Verify that:
     - With `sip_filter.enabled: true` and `mode: "sip_only"` → only SIP symbols appear.
     - With `mode: "no_sip"` → only non‑SIP symbols appear.
     - With `enabled: false` → symbol set matches the original (non‑SIP) logic.

3. **Smoke test config (documented, not executed here)**

   - Create a tiny Phase‑A config, e.g. `configs/intraday_ml/phaseA_sip_smoke.yaml`, with:
     - 2–3 symbols,
     - 5–10 days,
     - `sip_filter.enabled: true` and `mode: "sip_only"`,
     - `membership_path` pointing to a test location.
   - In comments (or docs), provide a sample command for the user:

     ```bash
     # After generating a tiny SIP membership file:
     python run_phaseA_pipeline.py        --config configs/intraday_ml/phaseA_sip_smoke.yaml
     ```

   - You do not need to run this smoke test in the sprint, but ensure the config parses and the code path is wired correctly.

4. **Regression: non‑SIP behavior**

   - If there is an existing test suite for Phase‑A, ensure all tests still pass with `sip_filter.enabled: false`.
   - If such tests don’t exist, at least:
     - Add a simple test that constructs a minimal config with SIP disabled and asserts that the symbol counts / date ranges match expected values (possibly via a small synthetic setup).

---

## Step 8 – Wrap‑up and Git actions

**Goal:** Finalize changes and prepare for review.

**Tasks:**

1. Run linters / formatters / tests (adapt to the project’s tooling):

   ```bash
   # examples (do not invent new tools; use what the repo uses)
   pytest
   ruff check .
   mypy .
   ```

2. Show the final `git status` so the user can see which files were touched.

3. Suggest commands to commit and push the SIP work (you do not have to execute them, but you may if appropriate):

   ```bash
   git add -A
   git commit -m "intraday ML: integrate precomputed SIP membership into Phase A training & OOS"
   git push -u origin feature/intraday-sip-integration
   ```

4. In your final message, summarize:

   - New modules added (e.g. `extensions/intraday_ml/sip_membership.py`, `extensions/intraday_ml/cli_build_sip_membership.py`),
   - Changes made to `run_phaseA_pipeline.py` and configs,
   - New tests created,
   - How the user should:
     - Run the SIP membership builder for a real universe/date range,
     - Run Phase‑A with SIP enabled,
     - Confirm results using the new tests / smoke config.

---

End of sprint plan. Implement everything above in the `quantstack` repo, printing full updated files as you change them. Do **not** launch any long‑running, full‑universe SIP membership jobs; just create the tooling and configs so the user can run them later from their terminal.
