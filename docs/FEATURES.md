# FEATURES

## Contract
- Input: DataFrame with at least `ts` (UTC, ns) and `symbol`.
- Output: DataFrame with new feature columns; no mutation beyond documented outputs.
- Naming: `f__{pack}__{signal}` (e.g., `f__ta__rsi_14`).
- Purity: no file or network side effects; deterministic for a given input slice.

## Scanner (refactor)
- Allowlist: only your strategy repos’ `src/**`, `lib/**`, `features/**`.
- Denylist: `**/.venv/**`, `**/site-packages/**`, `**/build/**`, `**/dist/**`, `**/.git/**`, `**/tests/**`.
- AST heuristics to identify DataFrame-consuming functions producing new columns.

## Outputs
- `features_catalog_v2.json|md`
- `feature_adapters_todo.md` (thin wrappers to conform to the contract)
