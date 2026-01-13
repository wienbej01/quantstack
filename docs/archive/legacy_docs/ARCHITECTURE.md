# ARCHITECTURE

## High-level
- **Data layer:** read‑only lake access; in‑run normalization to UTC nanosecond timestamps for hashing only.
- **Features:** pure transforms with strict naming (`f__{pack}__{signal}`), no side effects.
- **Backtest:** emits a standard set of parquet+json artifacts per run.
- **Experiments:** orchestrates A/B, grids, sweeps, and comparisons with fairness checksums.
- **Reporting:** reads artifacts, never the lake, to produce tables and plots.
- **Finalization:** single VM‑only step to normalize parquet and validate Gold on real partitions.

## Modules
- `qx-core`: schemas, IO guards, checksum utilities, calendars.
- `qx-cli`: Typer/Rich CLI surface (`qx exp ...`) and experiment runners.
- `qx-features`: curated, reusable feature packs and thin adapters.
- `qx-backtest`: order → fill → position → PnL pipeline with risk hooks.
- `qx-report`: comparative reports, bootstrap CIs, statistical tests.

## Data flow (new strategies)
Gold bars → optional SIP screen → feature enrichment → model policy → risk & sizing → backtest → portfolio allocation → run artifacts → reports/compare.
