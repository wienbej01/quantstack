# Sprint: Multi-Regime Debrief and Fixes  
**Target window:** 2025-10-20 → 2025-10-31  
**Goal:** Ship reliable morning/afternoon regime detection with functioning regime-aligned strategies and validated feature packs.

---

## 1. Scope & Success Criteria
- Regime detector supports two intra-day segments (AM/PM) with correct persistence/cooldown behaviour.
- Enhanced feature pack (AVWAP, volume profile, ICT, OFI/VPA, stress) produces deterministic, unit-tested outputs and honours configuration parameters.
- Regime-aligned policies trade as specced, using the new segment-aware regimes and corrected risk/feature logic.
- Regression suite covers AM/PM regime transitions, feature computations, and representative policy signals.
- Documentation updated (governance doc, README_regime_detection) to reflect redesigned flow.

---

## 2. Workstream Breakdown

### WS1 — Feature Pack Corrections
1. **Anchor & session math**
   - Fix `compute_session_anchors` to preserve int64 nanosecond timestamps (drop extra ×1e9 scaling).
   - Rework session grouping to reset at each symbol/date boundary; enforce `f__warmup_ok` alignment.
2. **ICT/order-flow metrics**
   - Normalise FVG proximity checks in dollar terms (ATR × price tick).
   - Introduce parameter plumb-through so `FeatureRegistry` passes overrides into `compute_all_regime_enhanced_features`.
3. **Unit tests**
   - Update existing tests to build timestamps via `datetime64[ns]`.
   - Add cases for non-default profile window, sweep thresholds, OFI span.

### WS2 — Two-Segment Regime Detector
1. **Session segmentation**
   - Define `SessionSegment` enum (`AM`/`PM`) and helper that maps timestamps using ET clock.
   - Replace `_daily_regime_cache` with segment-aware cache & persistence dictionaries.
2. **Enhanced feature usage**
   - Integrate AVWAP bias, value acceptance, and OFI thresholds into `_detect_trend_regime`.
   - Surface segment label in `RegimeSignal` metadata for logging/analytics.
3. **Tests**
   - Extend `tests/test_regime_detector.py` with AM→PM pivot scenario (only one allowed switch).
   - Update integration tests to assert segment-specific stats instead of minute-level distribution.

### WS3 — Engine & Policy Wiring
1. **Engine annotations**
   - When `_update_regime_if_needed` runs, stamp `f__regime__current` and `f__regime__segment` onto each bar before strategy execution.
   - Ensure SIP-universe filtering still occurs before policies run.
2. **Policy fixes**
   - Adjust FVG/ATR comparisons to use absolute price deltas.
   - Align pullback thresholds with ATR in price terms; verify `f__ict__in_discount/premium` gating.
   - Ensure telemetry uses existing feature keys; avoid missing-key lookups.
3. **Smoke tests**
   - Add targeted policy tests with synthetic bars for momentum, pullback, and rotation setups (AM/PM gating).

### WS4 — Documentation & Tooling
1. Update `20251020_regime_aligned_strategies.md` and `README_regime_detection.md` with new segment model.
2. Provide dashboard note for AM/PM regime telemetry (if applicable).
3. Refresh experiment configs referencing `regime_enhanced` packs to include new parameter paths.

---

## 3. Validation Matrix
| Area | Tests / Commands |
| --- | --- |
| Features | `pytest tests/test_regime_enhanced_features.py` |
| Detector | `pytest tests/test_regime_detector.py -k "segment"` |
| Policies | `pytest tests/test_regime_integration.py tests/test_regime_integration_extended.py` |
| Full regression | `make test -k regime` (focus run) |
| Backtests | `python examples/daily_hmm_sip_example.py` with AM/PM logging |

---

## 4. Timeline & Owners
- **Days 1-3:** WS1 fixes & tests (Features team).
- **Days 3-6:** WS2 implementation & unit tests (Core regime team).
- **Days 5-8:** WS3 engine/policy wiring + smoke tests (Backtest/policy team).
- **Days 8-10:** WS4 docs & final regression (Shared).
- Daily sync to review blockers; merge via feature branches with reviewer from another workstream.

---

## 5. Risk & Mitigation
- **Risk:** Segment cache logic reintroduces thrash.  
  **Mitigation:** Add configurable persistence/cooldown per segment; monitor AM/PM transitions in tests.
- **Risk:** Feature recalculations slow dataset builds.  
  **Mitigation:** Benchmark feature pack timings; parallelise by symbol if needed.
- **Risk:** Policies over-fit to synthetic tests.  
  **Mitigation:** Replay historical day to confirm expected trades before sign-off.

---

## 6. Exit Checklist
- [ ] All WS tasks merged with reviewer sign-off.
- [ ] CI green on focused regime job + full `make test`.
- [ ] Updated docs + sprint retro note filed.
- [ ] Telemetry captures AM/PM regime labels in latest backtest run.

