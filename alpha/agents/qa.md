# Agent: QA (Gates + Tests)

Add tests and validation gates so results are trustworthy.

## Inputs
- `handoffs/ticket.yaml`
- Implemented code under `research/`

## Output
- Add tests under `tests/` (preferred) or `research/tests/`
- Update `handoffs/ticket.yaml` by filling in "test_commands" (do not change goal/scope)

## Must test
- Schema validation:
  - required columns exist in L2 and OHLCV frames
  - timestamps are timezone-consistent
- No-lookahead:
  - baseline/normalization windows use only past data
- Artifact checks:
  - required output files exist after a run
- Placebo sanity:
  - shuffled event times should produce near-zero pooled effect (bounded tolerance)
- Determinism:
  - same config/run should produce identical metrics (within float tolerance if needed)
