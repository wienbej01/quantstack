# Regime Detector Sprint Plan (2025-10-19)

## Overview
- Objective: deliver a modular intraday regime detection gate that classifies trading sessions using 1m OHLCV (with optional ETF/polygon.io context) and exposes on/off signals to downstream entry, exit, and risk managers without breaking existing schemas or hooks.
- Constraints: no forward-looking features; decisions made from data available up to evaluation time; support 2–5 trades/day with day-level regime lock and optional midday override; maintain compatibility with current `qx-core` state/event bus and config schemas.
- Key deliverables: feature pipeline, rule-based detector, integration with `qx-backtest` and `qx-cli`, validation artefacts, optional HSMM upgrade roadmap.

## Phase 0 – Discovery & Architecture Alignment (1 sprint)
- Tasks:
  - Audit `qx-core` state dispatch, `qx-backtest` strategy activation hooks, and config schemas under `experiments/` to confirm insertion points for a regime gate toggle (`regime.enabled`, `regime.strategy_map`).
  - Validate data plumbing for 1m OHLCV and optional SPY/sector inputs; document latency expectations and ensure no forward-look.
  - Review governance requirements (logging, auditability) and draft acceptance tests.
- Deliverables: architecture brief appended to `SYSTEM_TECH_DOC.md`, schema change request (if any), finalized interface contract (`RegimeSignal`, gating enum).
- Framework changes required: add optional `regime` block to experiment YAML schema; no upstream API changes otherwise.

## Phase 1 – Feature Pipeline Infrastructure (1–2 sprints)
- Tasks:
  - Implement `qx_features/regime/features.py` with MoD-normalized volatility, variance ratio, ADX proxy, band-position, stress metrics; ensure streaming-friendly windowing.
  - Add unit tests under `tests/test_regime_features.py` to confirm no forward-look, correct seasonality normalization, and resilience to missing bars.
  - Wire feature pipeline into existing data loaders via lightweight factory registered in `qx-core`.
- Deliverables: feature module, tests, documentation in `docs/features/market_regime_detection.md` (cross-referenced).
- Framework changes required: extend feature registry to accept `regime` namespace; ensure no breaking change.

## Phase 2 – Rule-Based Detector Implementation (1 sprint)
- Tasks:
  - Create `qx_core/regime/detector.py` exposing `RegimeDetectorRules` with configurable thresholds, hysteresis counters, and stress overrides.
  - Implement persistence guard (e.g., 3 consecutive 5m bars) and cooldown logic for `STRESS` regime without forward-looking leakage.
  - Provide serialization from config → detector via existing dependency injection container.
- Deliverables: detector module, configuration schema updates, unit tests (`tests/test_regime_detector_rules.py`).
- Framework changes required: add detector registration hook to strategy bootstrap; ensure gating signals publish on existing event bus.

## Phase 3 – Integration & Configurable Gating (1–2 sprints)
- Tasks:
  - Extend `qx-backtest` strategy orchestrator to consume `RegimeSignal` and enable/disable strategy families based on config mapping (`regime.strategy_map`).
  - Add CLI command `qx-cli regime backtest <config>` and sample YAML under `experiments/regime/`.
  - Update risk manager to respect `STRESS` override (e.g., enforce risk-off budgets) while remaining backward compatible when gate disabled.
  - Document toggle instructions in `docs/features/market_regime_detection.md` and `DEVELOPER_GUIDE.md`.
- Deliverables: integrated gating flow, sample configs, CLI entry point, updated documentation.
- Framework changes required: minor extension of strategy dispatch config; no change when `regime.enabled=false`.

## Phase 4 – Validation, Backtesting, and Deployment Readiness (1 sprint)
- Tasks:
  - Develop regression notebooks/scripts to compare strategy PnL, hit-rate, turnover with/without gating using historical 1m data; ensure full trading-day regime lock with optional midday pivot.
  - Add pytest integration covering gating behavior in `tests/test_regime_integration.py`, including stress overrides and config toggling.
  - Define monitoring metrics (state duration, flip count, drawdown impact) and add to reporting pipeline.
- Deliverables: validation report, test coverage, deployment checklist, monitoring plan.
- Framework changes required: add metric hooks if not already present; otherwise reuse existing telemetry bus.

## Phase 5 – Advanced Modeling Upgrade (Optional, 1–2 sprints after Phase 4)
- Tasks:
  - Prototype Gaussian HSMM on existing features; ensure state probability smoothing and duration priors align with day/midday cadence.
  - Integrate HSMM behind feature flag (`regime.model: hsmm`), defaulting to rules; maintain identical `RegimeSignal` interface.
  - Benchmark turnover, fill costs, and alpha retention versus rules baseline; document migration guidelines.
- Deliverables: optional HSMM module, evaluation summary, rollout plan.
- Framework changes required: none beyond Phase 3 interfaces; HSMM swaps implementation behind existing hook.

## Risk Controls & Compliance Checklist
- Verify all features use only contemporaneous or past data; unit tests enforce no forward-look by simulating incremental feed.
- Ensure stress overrides trigger immediate risk-off and log audit trail entries for compliance review.
- Confirm strategy gating defaults to “off” (baseline behavior) when config omitted to avoid unexpected production changes.
- Conduct peer review of schema updates and configs to maintain deterministic YAML ordering and governance standards.
