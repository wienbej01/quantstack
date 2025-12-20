# Paper Trading Guide

Operational standards for paper trading infrastructure with a focus on
stability, deterministic behavior, and safe IBKR integration.

## Core Standards

### System Identity
- Use unique IBKR client IDs per service (no shared client IDs).
- Tag sessions and logs with a stable system name + client ID.

### Deterministic Scheduling
- Use explicit trading windows and timezone-aware scheduling.
- Use stable, repeatable symbol rotation (no Python hash randomness).
- Skip weekends and configured market holidays.

### L2 Collection Safety
- Match contract exchange to subscribed depth feeds.
- Enforce NYSE-only contracts for L2, with `exchange: NYSE` and
  `allowed_primary_exchanges: [NYSE]`.
- When `smart_depth` is false, `nyse_only` must be true to prevent
  unsupported symbols and IBKR gateway instability.
- Disable symbols after hard depth errors to avoid repeated request loops.
- Keep a hard cap on concurrent L2 subscriptions (`max_symbols`).

### Storage Integrity
- Partition writes by `date` + `symbol` to avoid cross-symbol mixing.
- Flush in bounded batches; handle write errors without crashing the process.

### Error Handling
- Fail fast on connection errors and log actionable messages.
- Do not allow unhandled exceptions in the main collection loop.
- Persist IBKR errors in the journal with symbol context.

## L2 Configuration Standards

Minimal safe baseline for mixed-universe collection:

```yaml
symbols:
  mode: "external"
  exchange: "SMART"
  max_symbols: 6
collection:
  smart_depth: true
  snapshot_interval_ms: 1000
  poll_interval_sec: 0.1
```

NYSE OpenBook-only safe baseline:

```yaml
symbols:
  mode: "static"
  exchange: "NYSE"
  allowed_primary_exchanges: ["NYSE"]
  max_symbols: 6
collection:
  smart_depth: false
  snapshot_interval_ms: 1000
  poll_interval_sec: 0.1
```

## IBKR Gateway Protection

- Avoid repeated unsupported depth requests. If error codes repeat for a symbol,
  disable the symbol for the remainder of the session.
- Keep symbol lists aligned with the data subscription (NYSE OpenBook vs SMART).
- Use a single L2 collector process per client ID.

## Observability

Required logs and journals:
- `l2_collector.log`: collection loop, errors, and session lifecycle.
- `data/l2*/journal.db`: session stats, error events, and daily rollups.

Runbook checks:
- `tail -f l2_collector.log`
- `sqlite3 data/l2*/journal.db 'select * from errors order by timestamp desc limit 20;'`

## Release Discipline

Before deploying L2 changes:
- Run local unit tests that do not require market connectivity.
- Validate configuration changes against real subscription constraints.
- Record the exact command line used in the change log.
