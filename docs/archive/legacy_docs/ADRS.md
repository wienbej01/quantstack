# ARCHITECTURAL DECISIONS

- **ADR‑007: No‑mutation QA (Deferred scans).** All lake‑wide scans and any restructuring are deferred to the Finalization Phase.
- **ADR‑008: Gold is additive‑only.** No resampling across sessions or timestamp shifts.
- **ADR‑009: Feature naming and contracts.** Columns must follow `f__{pack}__{signal}` and accept `ts` (UTC ns) and `symbol`.
