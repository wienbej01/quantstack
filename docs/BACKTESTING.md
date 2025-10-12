# BACKTESTING ENGINE

## Responsibilities
- Consume signals → generate orders → simulate fills → update positions → compute PnL.
- Emit standardized parquet and json artifacts (see Experiments doc).

## Requirements
- Deterministic with a given config and seed.
- No data lake writes; read Gold only (or sample) for smoke/integration tests.
