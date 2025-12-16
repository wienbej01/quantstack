# FINALIZATION PHASE (VM‑Only)

> Single, deferred step after the infrastructure is solid and explicitly approved.

## Tasks
1. Full Bronze parquet scan; enumerate schema variants and tz state.
2. Generate `silver_norm_plan.json` (rename/cast/tz).
3. Execute Silver normalization (with backup and optional dry‑run).
4. Validate Gold on real partitions; write `gold_validation_report.md`.
5. Materialize `bronze_scan.json`, `bronze_issues.md` to the audit bucket.
6. Freeze a data snapshot tag and record hashes.

## Acceptance
- `timegpt_v2` and `intraday_stack` smoke tests pass post‑migration.
- Experiment checksums’ normalized view equals new Silver.
- Gold validator passes across target partitions.
