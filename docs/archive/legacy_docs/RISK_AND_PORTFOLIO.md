# RISK & PORTFOLIO

## Risk
- Policy-level pre‑checks (e.g., stop placement) and post‑checks (limits).
- `risk_rejects.parquet`: `ts, symbol, side, reason_code, limit_name, value, threshold, context_json`.

## Portfolio
- Allocation and clipping recorded to `allocation_log.parquet`: `ts, symbol, requested_qty, sized_qty, clip_reason, cap_remaining, rank`.
