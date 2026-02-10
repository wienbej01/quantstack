# Agent: Quant Researcher (L2 Impact Study)

Define a falsifiable experiment and robustness checks.

## Inputs
- `handoffs/ticket.yaml`

## Output
- Create/overwrite: `handoffs/experiment_spec.md`
- You MAY update `handoffs/ticket.yaml` only by filling in "definitions" details (do not change goal/scope).

## Requirements
- Define at least TWO alternative event definitions for "unusual deep liquidity".
- Specify time alignment rules between L2 timestamps and OHLCV minutes.
- Include:
  - placebo test (shuffled event times within day/session)
  - lead/lag pre-trend check (e.g., -300s to 0)
  - time-of-day normalization (at least bucketed)
  - regime stratification suggestion (e.g., high vs low vol)
- Specify estimation:
  - pooled effect and per-symbol effect
  - confidence intervals (bootstrap ok)
- Keep it implementable in Python with pandas/polars.
