udit scope, criteria, and status codes

We’re grading every component the same way we grade sushi on day three:

A. Fully operational: exists, imports cleanly, required functions present, tests pass, produces expected artifacts on smoke run.

B. Partially operational: core functions exist and run, but tests missing, incomplete outputs, or feature gaps.

C. Simple methods only: file/module exists with real code but minimal logic; not production-useful.

D. Placeholder/stub: exists but mostly pass, TODO, NotImplementedError, or “dummy” values.

E. Missing: not found on disk.

Audit dimensions per component:

Presence (files, modules, configs)

Contracts (function/class signatures that must exist)

Static red flags (stubs, TODOs, dummy_*, unreferenced params)

Runtime checks (imports, CLI help, unit tests, smoke E2E)

Artifacts (files created with correct schemas)

Determinism/fairness (inputs_checksum equality on re-run)

Outputs:

audit_report.md human report

audit_matrix.json machine-readable component statuses + reasons

artifacts_inventory.json list of files produced with row counts and schema deltas

findings.log raw logs
