# Quantstack Intraday ML Integration Build Plan (20251024)
**Status:** Integration-ready  
**Scope:** Intraday ML forecasting pipeline integrated with `quantstack` without modifying existing modules unless explicitly approved.

---

## 🔒 Modification Policy (Hard Stop Rules)
These apply to every task, PR, and script. They are non-negotiable.

1) **DO NOT MODIFY EXISTING FILES** anywhere in `quantstack` without **explicit written permission** from Jacob.  
   - If a change is believed necessary, open a PR that only contains a doc note under `docs/PROPOSED_CHANGES/` and a single `CHANGE_REQUEST.md` describing the delta. No code changes allowed in that PR.
2) **ONLY CREATE NEW FILES** under the following extension namespaces. Reuse imports from existing modules wherever possible.  
   - `extensions/intraday_ml/` (new feature pack, labeling, configs, CLI wrappers)  
   - `extensions/intraday_ml_policies/` (new model-driven backtest policy)  
   - `extensions/intraday_ml_models/` (trainers, model IO, eval)  
   - `docs/extensions/intraday_ml/` (docs)  
   - `configs/extensions/intraday_ml/` (YAML configs)  
   - `tests/extensions/intraday_ml/` (tests)
3) **NEVER DUPLICATE EXISTING METHODS.** Always import and use existing utilities from `qx-core`, `qx-data`, `qx-features`, `qx-backtest`, `qx-cli` before writing helpers.  
   - If an existing function is “almost right,” write a **thin adapter** in `extensions/` that calls it; do not re-implement.
4) **FAIL CI if any existing file is edited** (pre-commit hook provided below).  
5) **All new public APIs must be prefixed** with `intraday_ml_` to avoid name collisions.

---

## Process Flow (Integrated)
```mermaid
flowchart TD
A[Start] --> B[Gold bars (1m) written per quantstack contract]
B --> C[extensions/intraday_ml/features: compute ≤150 features]
C --> D[extensions/intraday_ml/labels: ATR tri-class labels]
D --> E[extensions/intraday_ml_models: train LightGBM; optional N-HiTS]
E --> F[extensions/intraday_ml_policies: model-driven policy]
F --> G[qx-backtest engine + risk + costs]
G --> H[qx-cli exp run -> artefacts + qx-report]
H --> I[Compare vs baselines; iterate]
```
Notes:
- **Data source:** Use `qx-data` loader only. No new loaders.  
- **Universe:** Use existing screener module where possible; adapters live under `extensions/`.  
- **Finalization:** Treat your one-off normalization as pre-integrated; only **read Gold** here.

---

## Wireframe (Integration Surfaces)
- **Use**: `qx-data` to load 1m bars (UTC-ns, schema-checked).  
- **Extend via new files** only:  
  - `extensions/intraday_ml/feature_pack.py` → registers `f__intraday_ml__*` computed columns using `qx-features` primitives where available.  
  - `extensions/intraday_ml/labeling.py` → breakout tri-class labels with strict no-peek windows.  
  - `extensions/intraday_ml_models/train_lgbm.py` → LightGBM tri-class trainer that consumes `DatasetBuilder` outputs.  
  - `extensions/intraday_ml_models/io.py` → versioned model save/load.  
  - `extensions/intraday_ml_policies/policy_intraday_breakout.py` → policy wrapper that loads model, computes features at cut times, enforces first-bar-after execution and flat EOD.  
  - `configs/extensions/intraday_ml/*.yaml` → thresholds, cuts, paths.  
  - `docs/extensions/intraday_ml/*` → how-to, diagrams.  
  - `tests/extensions/intraday_ml/*` → unit, property, integration tests.  
- **Do NOT** modify existing packs/policies/loaders.

---

## Sprints (Integrated; ultra-explicit; new files only)

### Sprint 0 — Repo Guardrails and Scaffolding (1–2 days)
**Objective:** Set up enforcement that blocks any edits outside `extensions/`, `configs/extensions/`, `docs/extensions/`, `tests/extensions/`.

**Create new files:**
- `.pre-commit-config.yaml` (hook to block edits to non-extension paths)
- `.github/pull_request_template.md`
- `extensions/intraday_ml/README.md`
- `docs/extensions/intraday_ml/00_OVERVIEW.md`
- `configs/extensions/intraday_ml/config.yaml` (template only)
- `tests/extensions/intraday_ml/test_path_guards.py`

**Pre-commit hooks (add the following):**
- **Path guard:** reject any change that touches files outside allowed extension and docs/configs/tests extension paths.  
- **Duplicate method detector:** grep for function names that already exist in `qx-core`, `qx-data`, `qx-features`, `qx-backtest`, `qx-cli`; fail if duplicates found.  
- **Synthetic data sentinel:** block `faker|make_classification|random.*` in prod modules.

**CI checks (new):**
- `make precommit`
- `pytest -q tests/extensions/intraday_ml/test_path_guards.py`
- A dry-run that imports every new module to assert no accidental imports from `/scripts` or direct file IO.

**Definition of Done (DoD):**
- Any PR that adds/modifies files outside extension paths **fails** locally and in CI.  
- PR template present and enforced.

---

### Sprint 1 — Config and Contracts (1–2 days)
**Objective:** Define all config knobs and data contracts without coding core logic.

**Create new files:**
- `configs/extensions/intraday_ml/cuts.yaml` → `["09:35","11:00","13:30","14:30"]` ET
- `configs/extensions/intraday_ml/targets.yaml` → `horizons=[30,60,90]; k_atr=0.40`
- `configs/extensions/intraday_ml/universe.yaml` → use existing screener ids; no new screener code
- `docs/extensions/intraday_ml/CONTRACTS.md` → schemas, naming (`f__intraday_ml__*`), no-peek rules
- `tests/extensions/intraday_ml/test_contracts.py`

**Use existing modules:** `qx-data`, `qx-features.registry`, `qx-features.DatasetBuilder`

**Tests:**
- Ensure configs load and validate against JSON schema (write a new schema under `extensions/intraday_ml/_schemas/`).  
- Ensure **no** imports from vendor clients; only `qx-data` allowed.

**DoD:**
- Configs parse; contracts documented; tests green; zero edits to existing files.

---

### Sprint 2 — Feature Pack (≤150 features; 3–4 days)
**Objective:** Implement `intraday_ml` pack using only existing primitives when available.

**Create new files:**
- `extensions/intraday_ml/feature_pack.py`
- `extensions/intraday_ml/feature_registry.py` (register pack into local registry that the policy will import)
- `tests/extensions/intraday_ml/test_feature_pack_unit.py`
- `docs/extensions/intraday_ml/FEATURE_CATALOG.md`

**Rules:**
- **Always** attempt to import from `qx-features` first (e.g., returns, ATR, RV, VWAP distance).  
- If a primitive does not exist, write a **thin helper** here; log in `FEATURE_CATALOG.md` why it was needed.  
- Feature names: `f__intraday_ml__{family}__{signal}`.

**Tests:**
- Unit: deterministic outputs for selected windows; dtype checks.  
- Property: **max dependency timestamp ≤ ts_cut** for all features.  
- Registry: generated columns match registry list exactly (no rogue names).

**DoD:**
- ≤150 features; all from existing primitives where possible; unit/property tests pass.

---

### Sprint 3 — Labels (2–3 days)
**Objective:** Tri-class breakout labels with first-hit logic and no-peek guarantees.

**Create new files:**
- `extensions/intraday_ml/labeling.py`
- `tests/extensions/intraday_ml/test_labels_unit.py`
- `tests/extensions/intraday_ml/test_labels_no_peek.py`
- `docs/extensions/intraday_ml/LABELS.md`

**Rules:**  
- Horizons: 30/60/90 min from `ts_cut`.  
- ATR(14) precomputed from bars up to `ts_cut`.  
- First-hit sequence decides up/down/none.  
- Labels live in DataFrame column `y_class` with values `{-1,0,+1}`.

**Tests:**  
- Verify forward window starts at `ts_cut + 1min`.  
- Verify ATR window ends at `≤ ts_cut`.  
- Random sample of 1k cuts passes **no-peek** assertions.

**DoD:** Labels computed solely from `qx-data` inputs; tests green.

---

### Sprint 4 — Dataset Builder Integration (2–3 days)
**Objective:** Use `qx-features.DatasetBuilder` to assemble ML datasets; **no changes** to the builder itself.

**Create new files:**
- `extensions/intraday_ml/build_dataset.py` (wrapper that calls the existing builder)
- `configs/extensions/intraday_ml/dataset.yaml`
- `tests/extensions/intraday_ml/test_dataset_build.py`
- `docs/extensions/intraday_ml/DATASET.md`

**Rules:**  
- Call existing `DatasetBuilder` APIs; if a missing option is required, write an issue and a `PROPOSED_CHANGES/CHANGE_REQUEST.md`.  
- Output manifests to `artefacts/extensions/intraday_ml/datasets/` with hashes.

**Tests:**  
- Split integrity (no overlap; embargo respected).  
- Manifest present; hashes stable across runs.

**DoD:** Reproducible datasets produced via existing API.

---

### Sprint 5 — Model Training (LightGBM; optional N-HiTS) (3–4 days)
**Objective:** Train tri-class classifier using the dataset. **Only new files** under models.

**Create new files:**
- `extensions/intraday_ml_models/train_lgbm.py`
- `extensions/intraday_ml_models/io.py`
- `configs/extensions/intraday_ml/model_lgbm.yaml`
- `tests/extensions/intraday_ml/test_train_lgbm_smoke.py`
- `docs/extensions/intraday_ml/MODELING.md`

**Rules:**  
- No data loaders besides `qx-data` and dataset artefacts.  
- Calibrate probabilities (Platt or isotonic).  
- Version models with semantic tags; write `model_card.json` alongside binaries.

**Tests:**  
- Smoke train on small split; artifact written; calibration monotonic.  
- Determinism: fixed seeds → identical metrics within epsilon.

**DoD:** Model artifacts produced under `artefacts/extensions/intraday_ml/models/`.

---

### Sprint 6 — Policy & Backtest Integration (3–4 days)
**Objective:** Add a new policy that consumes features at cut times and issues orders according to intraday rules.

**Create new files:**
- `extensions/intraday_ml_policies/policy_intraday_breakout.py`
- `configs/extensions/intraday_ml/policy.yaml`
- `tests/extensions/intraday_ml/test_policy_exec_rules.py`
- `docs/extensions/intraday_ml/POLICY.md`

**Rules:**  
- **Execution only on the first bar AFTER the signal bar.**  
- **Flat by 15:59:59 ET** (no overnight positions).  
- Respect spread/slippage models from existing backtest engine.  
- Load models via `extensions/intraday_ml_models/io.py`.  
- Use existing risk sizing; if a new risk rule is needed, propose via `PROPOSED_CHANGES/` doc only.

**Tests:**  
- Reject same-bar fills.  
- Assert EOD flatness across a week.  
- R:R enforcement (1:2) honored in simulated fills.

**DoD:** Backtests run via `qx-cli exp` using the new policy; artefacts logged.

---

### Sprint 7 — Experiments & Reporting (2–3 days)
**Objective:** Run experiments using `qx-cli` and compare against baselines.

**Create new files:**
- `configs/extensions/intraday_ml/exp.yaml`
- `docs/extensions/intraday_ml/EXPERIMENTS.md`
- `tests/extensions/intraday_ml/test_exp_smoke.py`

**Rules:**  
- Use existing comparators; no new report code.  
- Store results under `artefacts/extensions/intraday_ml/experiments/`.

**Tests:**  
- Smoke experiment completes; artefacts present; summary stats parsable.

**DoD:** A/B comparisons plotted by existing reporting tools.

---

### Sprint 8 — Ops, Runbooks, and Handover (1–2 days)
**Objective:** Document everything and lock in run commands.

**Create new files:**
- `docs/extensions/intraday_ml/RUNBOOK.md`
- `docs/extensions/intraday_ml/COMPLIANCE.md`
- `extensions/intraday_ml/Makefile` (phony targets below)
- `tests/extensions/intraday_ml/test_runbook_commands.py`

**Make targets (extensions only):**
```
make intraday-setup
make intraday-features
make intraday-labels
make intraday-dataset
make intraday-train
make intraday-policy-check
make intraday-exp
make intraday-qa
```
**DoD:** A competent dev can run the pipeline via Make and `qx-cli` without editing core modules.

---

## Compliance & Anti-Leakage (Always On)
- **No forward look**: features must depend on data `≤ ts_cut`; labels start at `ts_cut+1min`.
- **Signal-to-execution**: fills at the **open of next bar only**.
- **No synthetic data** in prod. Test fixtures are isolated under `tests/`.
- **Universe eligibility**: join to daily eligibility table; no survivorship bias.
- **ET time discipline**: cuts in ET; conversions validated with DST tests.
- **Determinism**: fixed seeds; content hashes stable.

---

## Pre-commit & CI (Strict)
**Pre-commit hooks (new or extended):**
1) **path_guard.py**: fail if any staged path is outside `extensions/`, `configs/extensions/`, `docs/extensions/`, `tests/extensions/`.  
2) **duplicate_api_guard.py**: parse AST of new files; fail if function/class names duplicate public APIs in core modules.  
3) **synthetic_guard.py**: block `faker|make_classification|random.*` in prod code.  
4) **io_guard.py**: block direct network/file IO in features/labels/policies; must go through `qx-data` or provided IO helpers.

**CI stages (must pass):**
- `make precommit`  
- `pytest tests/extensions/intraday_ml -q --maxfail=1`  
- E2E day replay using `qx-cli exp` on a tiny date range  
- Coverage ≥ 80% on `extensions/` packages

---

## Tests (Checklist)
- **Feature pack**: determinism, dtype, registry exactness, dependency window ≤ `ts_cut`.  
- **Labels**: first-hit logic, no-peek, ATR window bound.  
- **Dataset**: embargo and split integrity; manifest hashes.  
- **Model**: calibration, determinism, artifact versioning.  
- **Policy**: next-bar execution, EOD flatness, R:R enforcement.  
- **Experiments**: artefacts present; parsers read them.  
- **Guards**: path guard, duplicate guard, synthetic guard.

---

## Paths & Naming (New Files Only)
- Code: `extensions/intraday_ml/*`, `extensions/intraday_ml_models/*`, `extensions/intraday_ml_policies/*`  
- Configs: `configs/extensions/intraday_ml/*.yaml`  
- Docs: `docs/extensions/intraday_ml/*.md`  
- Tests: `tests/extensions/intraday_ml/*.py`  
- Artefacts: `artefacts/extensions/intraday_ml/{datasets,models,experiments}/`  
- Feature names: `f__intraday_ml__{family}__{signal}`  
- Label column: `y_class` in dataset frames

---

## LLM Coder Operating Frame (Pin this to every task)
```
SYSTEM GOALS
- Implement tasks strictly under “Modification Policy” and “Compliance & Anti-Leakage”.
- Use existing quantstack modules; do not duplicate methods.
- Create new files only under the allowed extension paths.

CONSTRAINTS
- No edits to existing files without written permission.
- No synthetic data in prod paths.
- No network/file IO in feature/label/policy code beyond qx-data loaders.
- All thresholds/cuts come from configs.

FILES TO READ (examples)
- qx-data loader API, qx-features registry, DatasetBuilder docs
- configs/extensions/intraday_ml/*.yaml

FILES TO WRITE (authoritative)
- Only the files listed per sprint under extensions/configs/docs/tests.

DEFINITION OF DONE
- Pre-commit and CI green.
- Tests under tests/extensions/intraday_ml pass.
- No modified files outside allowed paths.
- Artefacts written to artefacts/extensions/intraday_ml/*.
```
---

## Definition of Done (Global)
- Zero deltas to core modules.  
- All new modules live under `extensions/…` namespaces.  
- Full test matrix green; coverage threshold met.  
- Runbook reproducible on a fresh checkout.

---

## Appendix A — Template: CHANGE_REQUEST.md (for any core edit proposal)
```
# CHANGE REQUEST — <short title>
## Problem
Describe why existing API cannot be used via adapter.

## Proposed Delta (no code included)
File(s) to change:
- qx-<module>/<path>.py

API before/after (signatures only):
- before: foo(a: int) -> int
- after: foo(a: int, *, mode: str = "strict") -> int

## Alternatives
- Adapter pattern attempted: <link to adapter PR>

## Impact
Backwards compatibility, tests to add, docs to update.

## Approval
<Jacob sign-off here>
```

---

## Appendix B — Minimal Makefile (extensions only)
```
.PHONY: intraday-setup intraday-features intraday-labels intraday-dataset \
        intraday-train intraday-policy-check intraday-exp intraday-qa

intraday-setup:
\tpre-commit install

intraday-features:
\tpython -m extensions.intraday_ml.feature_pack --smoke

intraday-labels:
\tpython -m extensions.intraday_ml.labeling --smoke

intraday-dataset:
\tpython -m extensions.intraday_ml.build_dataset --config configs/extensions/intraday_ml/dataset.yaml

intraday-train:
\tpython -m extensions.intraday_ml_models.train_lgbm --config configs/extensions/intraday_ml/model_lgbm.yaml

intraday-policy-check:
\tpytest tests/extensions/intraday_ml/test_policy_exec_rules.py -q

intraday-exp:
\tqx-cli exp run --config configs/extensions/intraday_ml/exp.yaml

intraday-qa:
\tpytest tests/extensions/intraday_ml -q
```
