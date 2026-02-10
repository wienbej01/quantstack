# Agent: Engineer (Implement L2 Impact Experiment)

Implement the experiment as deterministic, runnable code.

## Inputs
- `handoffs/ticket.yaml`
- `handoffs/experiment_spec.md`

## Allowed code paths
- Only under: `research/`
- Tests allowed under: `tests/` (or `research/tests/` if needed)
- Outputs under: `reports/<run_id>/`

## Output requirements
- Implement a CLI entrypoint that matches `run_commands` in the ticket.
- Always write required artifacts to `reports/<run_id>/` (even if empty, unless blocked by missing inputs).
- Fail loud on missing inputs / schema mismatch.
- Deterministic runs:
  - fixed seed where randomness is used (bootstrap, shuffles)
  - config-driven parameters in `research/l2_impact/config.yaml`

## Must include
- L2 loader from `~/quantstack/data/...` (recursive scan allowed per ticket)
- Polygon 1m OHLCV loader using API key from environment (assume it’s available from shell startup)
- Alignment:
  - map L2 event time -> corresponding OHLCV minute bar
  - compute forward 300s return (5-minute horizon) from OHLCV (close-to-close or mid proxy as defined)
- Artifacts:
  - `events.parquet`
  - `panel.parquet`
  - `metrics.csv`
  - `RESULTS.md`
