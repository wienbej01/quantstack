
# LLM‑Accessible Optimization & Trading Repository — Wireframe + Plan (v0)

You’re about to run a lot of experiments and forget most of them. This repository exists so Future‑You doesn’t have to speed‑read parquet folders at 2 a.m.

---

## 1) Wireframe (what the user sees)

### A. Chat + SQL Pane (LLM Assistant)
```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Q&A Chat                                                                     │
│  • User: “Best VPA combos OOS in Q2? Did SIP help?”                          │
│  • Assistant: table + short readout + links to runs                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ SQL Preview (read-only, auto‑generated from templates)                       │
│  SELECT feature_name, median_oos_sharpe, runs_count ...                      │
│  -- Requires scope='oos', min_trades >= 50                                   │
├──────────────────────────────────────────────────────────────────────────────┤
│ Provenance Panel                                                              │
│  • exp_id/run_id list, inputs_checksum.json diffs                             │
│  • Click to open artifact tree (signals/trades/metrics)                       │
└──────────────────────────────────────────────────────────────────────────────┘
Left drawer: Filters (phase, symbol, date range, strategy_id).  
Right drawer: Schema (views only) + Metrics Dictionary + Query Templates (read‑only).

Hotkeys: `v` VPA leaderboard, `s` SIP A/B, `g` Generalization, `p` Production daily.
```

### B. “Experiments” Dashboard
- Filters: phase, strategy_id, policy_tag, symbol, date window
- Cards: runs with trades, avg_R, ES@95, Sharpe, fees, slippage, seed
- Click a card → **Run Detail** with artifact links, parameter diff to baseline

### C. “A/B Contrasts”
- Table of pairs with deltas (trades, avg_R, ES@95) and significance flags
- Pair inspector: show fairness key, overlays that changed, first differing signals

### D. “VPA Leaderboard”
- Aggregation of OOS metrics by `p__vpa__*` flags and combos
- Stability bands (IQR), run counts, click into supporting runs

### E. “Production”
- Daily PnL net/gross, realized slippage vs model, exposure, rejects
- Links back to the research artifact tuple (features_hash, model_hash, config_hash)

---

## 2) System Objectives (don’t move the goalposts later)
- **Reproducible comparisons** across strategies, features, policies, costs, SIP settings
- **Cross‑referenced** lineage: inputs, data slice, code ref, model, config
- **Searchable** across numbers and notes
- **Read‑only** from research UI; no accidental lake mutations

Non‑goals right now: real‑time live trading UI, multi‑tenant auth, or yearning dashboards.

---

## 3) Storage & Layout

```
strategy_repo/
  catalog/                         # Columnar facts (Parquet/Delta), append-only
    fact_run.parquet
    fact_metrics.parquet
    fact_trade_summary.parquet
    fact_ab_pair.parquet
    fact_feature_presence.parquet
    fact_intervention.parquet
    fact_production_daily.parquet
    dim_*.parquet
  warehouse.db                     # DuckDB for interactive queries + views + FTS mirror
  ingestors/
    ingest_runs.py                 # parse experiments/<exp_id> and runs/<run_id>
    rebuild_indexes.py             # rebuild views, FTS, statistics
  views/
    mv_runs_wide.sql
    mv_vpa_leaderboard.sql
    mv_sip_effects.sql
    mv_repro_checks.sql
  queries/
    vpa_leaderboard.sql
    sip_impact_ab.sql
    generalization_gap.sql
    top_configs_for_symbol.sql
    change_between_runs.sql
  dashboards/
    streamlit_app.py               # optional thin UI
    snapshots/                     # exported HTML/MD
  docs/
    METRICS_DICTIONARY.yaml
    SCHEMA.md
    RUNBOOK.md
```

Backtest artifacts stay where they belong (`experiments/` and `runs/`). Repository ingests summaries + keys, never raw lake data.

---

## 4) Data Model (star-ish; facts + dims)

### Dimensions
- **dim_strategy**(strategy_id, description, owner, created_at)
- **dim_policy**(policy_tag, params_json, version)
- **dim_risk**(risk_tag, params_json, version)
- **dim_cost**(cost_tag, bps, per_share, slippage_ticks, tick_size)
- **dim_featureset**(features_hash, packs, params_json)
- **dim_dataset**(dataset_hash, source, date_range, symbols, label_def)
- **dim_model**(model_hash, type, features_used, threshold, training_metrics_json, dataset_hash)
- **dim_universe**(sip_hash, sip_params_json)
- **dim_code**(code_ref, py_version, dep_fingerprints)
- **dim_experiment**(exp_id, name, hypothesis, notes, registered_at)

### Facts (append-only)
- **fact_run**(run_id PK, exp_id FK, strategy_id FK, policy_tag FK, risk_tag FK, cost_tag FK, features_hash FK, dataset_hash FK, model_hash FK, sip_hash FK, bars_norm_hash, config_hash, code_ref FK, phase, start_ts, end_ts, symbols, window, seed)
- **fact_metrics**(run_id, scope ENUM[overall, oos, valid, train, regime:*], metric, value)
- **fact_trade_summary**(run_id, trades, win_rate, avg_R, ES_95, sharpe, mean_pnl, fees_total, slippage_total, turnover, holding_time_med)
- **fact_feature_presence**(run_id, feature_name, enabled BOOL, params_json)
- **fact_intervention**(run_id, key, value_before, value_after, diff_class)
- **fact_ab_pair**(pair_id, exp_id, run_id_A, run_id_B, fairness_key, delta_json, significant_bool)
- **fact_production_daily**(strategy_id, trade_date, symbols, gross_pnl, net_pnl, fees, slippage, exposure, orders_cnt, rejects_cnt)

Big raw tables (trades, signals) remain in Parquet; queried via DuckDB when needed.

**Fairness key** = hash tuple of (`bars_norm_hash`,`features_hash`,`sip_hash`,`config_hash`,`seed`) shared by variants.

---

## 5) Ingestion (automated, idempotent)

**ingestors/ingest_runs.py**
1. Discover new `experiments/<exp_id>` and `runs/<run_id>`
2. Validate artifact schemas (fail loud)
3. Extract hashes from `inputs_checksum.json`, params from `manifest.json`
4. Summarize `trades.parquet` → `fact_trade_summary` (keep raw trades external)
5. Compute **interventions** vs baseline under same fairness key
6. Pair up A/B runs → `fact_ab_pair` with deltas (trades, avg_R, ES_95, fees_total)
7. Upsert dims, append facts
8. Rebuild views/indexes

**ingestors/rebuild_indexes.py**
- Create/refresh `mv_*` views
- Update FTS mirror of experiment notes
- Analyze statistics for DuckDB

---

## 6) Access Surfaces (for LLMs and Humans)

### A. MCP Server (preferred for chat)
Tools:
- `warehouse.get_schema()` → whitelisted tables/views and columns
- `warehouse.get_metrics_dictionary()` → canonical metric definitions
- `warehouse.sql(query, params)` → **read‑only** SQL; param binding only
- `warehouse.search_notes(text, k)` → returns notes with metadata and exp/run IDs
- `warehouse.sample_runs(filter_json, limit)` → returns run summaries with links
- `warehouse.open_artifacts(run_id)` → returns artifact paths (read‑only)

### B. HTTP Microservice (optional automation)
`GET /schema`, `GET /metrics`, `POST /sql`, `POST /search-notes`, `GET /runs?filter=...`

### C. CLI
`qx log ingest`, `qx log rebuild-index`, `qx log query --file queries/vpa_leaderboard.sql`

**Guardrails:** read‑only DB connection, query time/row budgets, view whitelist, provenance returned with every result.

---

## 7) Metrics Dictionary (skeleton)

```yaml
avg_R_oos:
  sql: >
    -- view-based, safe join to trades
    SELECT run_id, AVG(r_multiple) AS avg_R
    FROM trades_view WHERE scope='oos'
    GROUP BY run_id
  min_trades: 30
  notes: Mean or median R over OOS trades only.

sip_effect_delta:
  description: Matched-pair delta for SIP on vs off under identical fairness key.
  source_view: mv_sip_effects
  primary_metric: avg_R
  significance: wilcoxon_signed_rank

gen_gap:
  formula: sharpe_oos - sharpe_valid
  min_trades: 50
  behavior: lower is better (closer to 0)
```

LLM must build queries using these primitives, not vibes.

---

## 8) Query Templates (the ones we’ll actually support)

- **VPA leaderboard**: by `feature_name`, scope='oos', min trades filter → rank on median Sharpe, show IQR, run counts
- **SIP impact A/B**: fetch matched pairs, compute deltas in trades/avg_R/ES_95, significance flag
- **Generalization gap**: valid vs OOS metrics per policy/featureset
- **Top configs for symbol/date**: rank by avg_R with cost/slippage columns
- **Change between runs**: diff params and report metric deltas
- **Capacity curve**: from cost sweeps, elasticity of net PnL to bps

Each template includes: required filters, safe joins, suppression rules for small N, and required provenance list.

---

## 9) Governance, QA, and Anti‑nonsense
- Study registry: `dim_experiment.hypothesis` and target metric must exist **before** runs
- Phase separation in filters: don’t mix `optimize` with `production`
- Repro checks: `mv_repro_checks` flags drift between identical fairness keys
- CI: question→SQL→expected tests; schema‑drift tests auto‑updated from METRICS_DICTIONARY

---

## 10) Security
- Read‑only mount of `warehouse.db` in the chat process
- Views only; raw tables can be hidden if you’re paranoid
- Parameterized SQL only; string concatenation blocked
- Rate limits, row/time caps with explicit override flags

---

## 11) Rollout Plan (sane increments)

**Sprint W1** — Warehouse skeleton  
- Create dims/facts (Parquet) + DuckDB views, write SCHEMA.md  
- Acceptance: `mv_runs_wide` returns rows from a tiny backfill

**Sprint W2** — Ingestor v1  
- Parse experiments/runs, compute interventions and A/B pairs  
- Acceptance: 10 historical runs ingested, 5 A/B pairs generated

**Sprint W3** — Views & Indexes  
- Build `mv_vpa_leaderboard`, `mv_sip_effects`, `mv_repro_checks`  
- Acceptance: saved queries return results under 1s on the sample

**Sprint W4** — MCP + Templates + Metrics Dict  
- Expose tools, add 6 query templates, wire metrics dictionary  
- Acceptance: scripted Q&A returns SQL + provenance for each

**Sprint W5** — Dashboards (optional)  
- Streamlit read‑only app with four pages above  
- Acceptance: filters work, links open artifacts

**Sprint W6** — Production ETL (optional)  
- Populate `fact_production_daily` from live logs  
- Acceptance: prod page shows daily net, slippage vs model

---

## 12) What Success Looks Like
- Ask: “Did SIP help VWAP on mega‑caps this quarter?” → numbers + significance + run links.
- Ask: “Which VPA patterns lifted OOS hit rate above 55% with ≥ 100 trades?” → ranked list + stability bands + supporting experiments.
- Re-run last quarter’s leaderboard and get the **same** answer, because hashes and views make it deterministic.
