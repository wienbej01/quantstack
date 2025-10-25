# CLAUDE.md — Project Contract (quantstack)

> Location: `/home/jacobw/quantstack/CLAUDE.md`  
> Purpose: Standardized framework to build modular, interchangeable trading system components across sibling repos.

---

## 0) Scope, repos, and data

**Project root:** `/home/jacobw/quantstack`

**Sibling repos available to this project (read/write unless marked read-only):**
- `/home/jacobw/intraday_stack`
- `/home/jacobw/hybrid_fourier`
- `/home/jacobw/hybrid-local`
- `/home/jacobw/HMM_SIP`
- `/home/jacobw/Cor_trading`
- `/home/jacobw/RL_trading`
- `/home/jacobw/timegpt_v2`
- `/home/jacobw/transalpha`
- `/home/jacobw/volume_price_trade`

**Data mounts (read-only):**
- `/home/jacobw/gcs-mount`

**Prohibited globs (never read or write):**
- `**/*.parquet`
- `**/data/**`
- `**/.venv/**`
- `**/__pycache__/**`
- `**/.mypy_cache/**`
- `**/.pytest_cache/**`
- `**/run/**` (generated artifacts)
- `**/secrets/**`

**Python path and packaging:**
- Treat each repo’s `src/` as a package root. Avoid relative-path hacks.

---

## 1) Non-negotiable data policy (echo of global)
- **No synthetic/mock data outside unit dev tests.** Mocks live only under `tests/fixtures/` and are never used for backtests or performance reporting.
- **All backtests use real, provenance-tracked market data** from `/home/jacobw/gcs-mount` with manifests, CA-adjustments, and delisting-safe universes.

---

## 2) MCP & tools contract
- Use **Context7 MCP** for code search, cross-repo inventory, and log grep. Start read-only.
- Shell and Git are read-only until explicitly granted write/commit.
- **Session Step 0 (mandatory):**
  1. List available MCP tools + one-line capability.
  2. Propose tool usage per step with rationale.
  3. Print exact search patterns/globs before running them.

---

## 3) Quantstack modular architecture (qx-* modules)

### Core Module Structure
The system uses a layered modular architecture with qx-* packages:

```
qx-core/                 # Foundation: schemas, contracts, validators, hashers
├── src/qx_core/
│   ├── schemas.py      # Pydantic models: Bar, Signal, Order, Trade, etc.
│   ├── contracts.py    # Protocol interfaces: DataClient, Policy, RiskManager
│   ├── validators.py   # DataFrame validation functions
│   ├── hashers.py      # Reproducibility hashing utilities
│   └── utils.py        # Time, session, bar utilities

qx-data/                 # Data loading and normalization
├── src/qx_data/
│   └── gold_loader.py  # Gold data access with provenance tracking

qx-features/            # Feature engineering (pure functions)
├── src/qx_features/
│   ├── core_basics.py  # VWAP, relative volume, ATR features
│   ├── vpa.py         # Volume-price analysis patterns
│   └── registry.py    # Feature pack registration system

qx-screener/            # Universe selection (SIP + HMM methods)
├── src/qx_screener/
│   ├── sip.py         # Original SIP implementation
│   └── hmm_sip.py     # HMM-based universe selector

qx-backtest/            # Order → fill → position → P&L pipeline
├── src/qx_backtest/
│   ├── engine.py      # Backtest orchestration engine
│   ├── policies/      # Trading policy implementations
│   │   ├── base.py    # Policy protocol interface
│   │   └── vwap_revert.py  # VWAP reversion strategy
│   ├── portfolio.py   # Position and equity tracking
│   ├── order.py       # Order management
│   ├── fill.py        # Fill simulation
│   └── risk.py        # Risk management integration

qx-risk/                # Risk management (sizing, stops, limits)
├── src/qx_risk/
│   └── atr_stop.py    # ATR-based stop loss implementation

qx-report/              # Comparative analysis and reporting
├── src/qx_report/
│   ├── readers.py     # Artifact readers for run data
│   ├── summaries.py   # Statistical analysis and summaries
│   └── main.py        # Report generation interface

qx-cli/                 # Typer/Rich CLI surface and experiment orchestration
├── src/qx_cli/
│   ├── commands/      # CLI command implementations
│   ├── exp/          # Experiment framework (entry-ab, risk-grid, etc.)
│   └── main.py       # Main CLI entry point
```

### Data Flow Pipeline
```
Gold bars (qx-data)
    ↓ Optional SIP screen (qx-screener)
    ↓ Feature enrichment (qx-features)
    ↓ Model policy (qx-backtest/policies)
    ↓ Risk & sizing (qx-risk)
    ↓ Backtest execution (qx-backtest)
    ↓ Portfolio allocation (qx-backtest/portfolio)
    ↓ Run artifacts (parquet + json)
    ↓ Reports/compare (qx-report)
```

### Experiment Framework (qx-cli)
Seven experiment types with reproducible hash validation:
1. **Entry/Exit A/B Testing** (`entry-ab`): Policy variations
2. **Risk Grid Analysis** (`risk-grid`): Systematic risk optimization
3. **Cost Analysis Sweep** (`cost-sweep`): Performance under cost assumptions
4. **Workflow Orchestration** (`wf`): Multi-stage experiment pipelines
5. **Regime Analysis** (`regime-slice`): Performance across market conditions
6. **Portfolio Testing** (`portfolio`): Multi-asset strategy validation
7. **Comparison Analysis** (`compare`): Statistical variant comparisons

### Key Architecture Principles
- **Pure Functions**: Features and signals are side-effect free
- **Hash-based Reproducibility**: Every input/output hashed for validation
- **Protocol Interfaces**: Duck typing for flexible implementations
- **Configuration-driven**: YAML configs with overlay system
- **Feature Registry**: Extensible feature engineering packs
- **Multi-method Universe Selection**: Support for SIP and HMM approaches

---

## 4) Cross-repo wiring rules
- Treat sibling repos as libraries; import only public interfaces from their `src/` packages.
- If you must reach across repos, first propose an adapter in `quantstack/src/adapters/` and get approval.
- Do not couple on internal file paths of other repos; prefer config-driven handoffs (JSONL, Parquet schema contracts, or function APIs).

---

## 5) Gate-by-gate diagnostics (zero-trade triage)
For any run that emits zero trades, return this evidence before proposing changes:
1. **Data Loading**: Gold data access, symbol universe, date range, data quality
2. **SIP Screening** (if applicable): universe filtering, thresholds, symbol counts
3. **Feature Engineering**: feature pack application, missing values, hash validation
4. **Signal Generation**: policy rule evaluation, thresholds, near-miss symbols with specific values
5. **Risk & Sizing**: position sizing limits, risk caps, minimum notional, R-multiple constraints
6. **Order Generation**: order validity, size rounding, stop loss placement
7. **Fill Simulation**: market hours, liquidity constraints, execution rejects
8. **Time Alignment**: UTC timestamps, session boundaries, trading hours

**Required evidence format**: file:function, actual values vs thresholds, specific failure reasons, 5 concrete examples with exact data points.

---

## 6) Tests & Make targets
Required targets (create on approval if missing):
```
make smoke        # 1-day run proving health with real Gold data
make test         # pytest suite (unit + integration + reproducibility)
make lint         # ruff (formatting + linting)
make typecheck    # mypy/pyright
```

**Testing Requirements:**
- **Unit Tests**: ≥80% coverage, pure function testing, deterministic behavior
- **Integration Tests**: Component interaction, hash validation, end-to-end flows
- **Reproducibility Tests**: Hash consistency across runs, seed control
- **Smoke Tests**: Real Gold data, must emit trades or provide justified no-trade analysis
- **CI/CD**: Automated testing pipeline with performance budgets

**Smoke Test Requirements:**
- Use real Gold data from `/home/jacobw/gcs-mount`
- Emit `inputs_checksum.json` with hash validation
- Provide detailed logs for each pipeline stage
- Include trade analysis or zero-trade diagnostic narrative
- Complete within performance budget (≤60s smoke run)

---

## 7) Output schema (strict JSON)
```json
{
  "PLAN": [{"step":1,"goal":"map gates for 2025-02-14","tools":["context7.search"],"commands":["..."],"expected_proof":["eligibility counts","first failing gate"]}],
  "COMMANDS": ["make smoke", "pytest -q tests/strategies/<slug>/test_smoke_day.py::test_0214"],
  "CHANGES": {"files_touched":["configs/strategies/<slug>.yaml"],"api_breaks":false,"diff_summary":["+ confirm_hold_bars=2"]},
  "PROOF": {"tests_passed":true,"metrics":{"trades":">=1"},"log_snippets":["eligibility=pass ...","order=submitted ..."],"artifacts":["run/sim_reports/2025-02-14_<slug>.json"]},
  "RISKS": ["Param interacts with risk caps"],
  "NEXT": ["2-week walk-forward","ATR window sweep"],
  "ROLLBACK": "git restore -SW configs/strategies/<slug>.yaml"
}
```

---

## 8) Performance & safety limits
- **Runtime per step**: ≤120s total, ≤60s for smoke tests
- **File read per step**: ≤2000 lines unless scanning large documentation
- **Artifact safety**: Never modify `run/` artifacts, only read for analysis
- **Data access**: Read-only from `/home/jacobw/gcs-mount`, no modifications
- **Security**: No secrets in logs/code, use env vars for local credentials
- **Synthetic data**: Only in `tests/fixtures/`, never for performance reporting

## 9) Git policy
- **Branch naming**: `feat/<slug>-<ticket>` or `fix/<slug>-<ticket>`
- **Commit scope**: Code, configuration, tests, documentation only
- **Prohibited commits**: Never commit data files, `run/` outputs, or secrets
- **Documentation**: Update relevant docs for all API/interface changes
- **Validation**: Ensure CI passes before merge, including hash validation tests

## 10) Schema and reproducibility requirements

### Data Schema Compliance
- **Core Schemas**: Use `qx_core.schemas` (Bar, Signal, Order, Trade, etc.)
- **Validation**: Call `validate_*_dataframe()` functions at all IO boundaries
- **Timestamps**: UTC nanoseconds, deterministic sorting by `[symbol, ts]`
- **Hashing**: Use `qx_core.hashers` for all reproducibility validation

### Experiment Fairness
For A/B comparisons, ensure identical hashes across variants:
```json
{
  "identical_components": [
    "bars_norm_hash",    // Same input data
    "features_hash",     // Same feature engineering
    "sip_hash",         // Same universe screening
    "seed"              // Same random seed
  ],
  "varying_components": [
    "config_hash"       // Only policy/risk parameters differ
  ]
}
```

### Configuration Structure
- **Base Config**: Strategy definition in `experiments/*/strategy.yaml`
- **Overlay Configs**: Variant parameters in `experiments/*/overlays/`
- **Deep Merge**: qx-cli merges configs with overlay precedence
- **Validation**: Schema validation before experiment execution

## 11) Documentation standards
- **Type Hints**: Required for all public APIs with input/output contracts
- **Docstrings**: Comprehensive examples, parameter descriptions, error conditions
- **Examples**: Working code samples in documentation
- **Changelog**: Track all breaking changes with migration guidance
- **Architecture Decisions**: Document major design decisions in ADR format