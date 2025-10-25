# Schema Change Request: Regime Detection Gate

## Request Information
- **Date**: 2025-10-19
- **Requester**: Regime Detection Sprint Plan
- **Target Components**: qx-core schemas, experiment configuration schema
- **Breaking Change**: NO - Fully backward compatible

## Summary

Add optional regime detection capabilities to the existing trading system without breaking backward compatibility. The regime gate will filter strategy signals based on market conditions while maintaining all existing functionality when disabled.

## Schema Changes

### 1. qx-core/schemas.py - Add RegimeType Enum

**Change**: Add new enum before existing `Side` enum

```python
class RegimeType(str, Enum):
    """Market regime classification types."""
    BULL = "BULL"          # Normal upward trending conditions
    BEAR = "BEAR"          # Normal downward trending conditions
    SIDEWAYS = "SIDEWAYS"   # Range-bound markets
    STRESS = "STRESS"      # High volatility/crisis conditions
    OFF = "OFF"            # Regime detection disabled
```

**Impact**: None (pure addition)

### 2. qx-core/schemas.py - Add RegimeSignal Pydantic Model

**Change**: Add new model after existing `Signal` model

```python
class RegimeSignal(BaseModel):
    """Regime classification signal for strategy gating."""
    ts: int = Field(..., description="UTC nanosecond timestamp")
    regime: RegimeType = Field(..., description="Current market regime")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence")
    features: dict[str, float] = Field(default_factory=dict, description="Underlying feature values")
    persistence_count: int = Field(default=0, description="Consecutive bars in current regime")
    model_version: str = Field("rules_v1", description="Detector version")
    src: str = Field("regime", description="Signal source identifier")
```

**Impact**: None (pure addition)

### 3. Experiment Schema - Add Optional Regime Block

**Change**: Extend existing experiment YAML schema to include optional `regime` block

```yaml
# New optional top-level section (defaults to disabled if omitted)
regime:
  enabled: false                    # Default: disabled for backward compatibility
  strategy_map:                    # Optional: mapping of regimes to allowed strategies
    BULL: ["vwap_momentum", "vwap_revert"]
    BEAR: ["vwap_revert"]
    SIDEWAYS: ["vwap_revert"]
    STRESS: []                     # No strategies allowed in stress regime
  model: "rules"                   # Detector model: "rules" or future "hsmm"
  persistence_bars: 3              # Minimum consecutive bars for regime change
  cooldown_minutes: 15             # Cooldown period after regime changes
  features:                        # Optional feature configuration
    volatility_window: 30
    trend_window: 60
    stress_threshold: 2.0
    vwap_window: 30
    atr_window: 14
```

**Impact**: None (pure addition, defaults to existing behavior)

### 4. ExperimentManifest Schema Update

**Change**: Add optional `regime_config` field to existing `ExperimentManifest`

```python
class ExperimentManifest(BaseModel):
    # ... existing fields ...
    regime_config: str | None = Field(None, description="Regime configuration path")
```

**Impact**: None (optional field addition)

## JSON Schema Updates

### 5. experiment_manifest_schema() Function Update

**Change**: Add optional `regime_config` property

```python
def experiment_manifest_schema() -> dict:
    return {
        "type": "object",
        "required": ["exp_id", "type", "run_ids", "seed"],
        "properties": {
            # ... existing properties ...
            "regime_config": {"type": "string"},
        }
    }
```

**Impact**: None (optional property addition)

## Backward Compatibility Analysis

### ✅ Fully Backward Compatible

1. **Existing Configurations**: All existing experiment YAML files continue to work unchanged
   - `regime.enabled` defaults to `false` when omitted
   - Strategy behavior identical when regime detection disabled

2. **Code Integration**: Existing policy classes require zero changes
   - Policies can optionally check regime signals but not required
   - Engine continues normal operation when regime disabled

3. **API Stability**: No breaking changes to existing interfaces
   - All existing function signatures unchanged
   - New regime functionality is purely additive

4. **Data Artifacts**: Existing backtest results remain valid
   - No changes to existing result schemas
   - Historical analysis unaffected

## Migration Path

### Phase 0: Schema Foundation (Current Request)
- [ ] Add RegimeType enum and RegimeSignal model to qx-core/schemas.py
- [ ] Update ExperimentManifest with optional regime_config field
- [ ] Update JSON schema functions
- [ ] Validate no existing tests break

### Phase 1-2: Feature Implementation (Future)
- [ ] Implement regime features in qx-features/regime/
- [ ] Implement rule-based detector in qx-core/regime/
- [ ] No additional schema changes required

### Phase 3: Integration (Future)
- [ ] Engine integration with regime gating
- [ ] CLI support for regime configurations
- [ ] No additional schema changes required

## Risk Assessment

### LOW RISK Changes
- Pure additions to existing schemas
- Optional fields with sensible defaults
- No modification of existing structures

### Mitigations
- Comprehensive test coverage for new schema validation
- Backward compatibility test suite
- Documentation of default behavior

## Testing Strategy

### Schema Validation Tests
```python
def test_regime_signal_validation():
    """Test RegimeSignal schema validation."""
    # Valid signal should pass
    # Invalid confidence should fail
    # Missing required fields should fail

def test_backward_compatibility():
    """Test existing configs still work."""
    # Load existing experiment configs
    # Validate no regime field required
    # Ensure default behavior unchanged
```

### Integration Tests
```python
def test_regime_disabled_default():
    """Test system behaves identically when regime disabled."""
    # Run backtest with existing config
    # Verify results match baseline exactly
```

## Implementation Notes

### Dependencies
- No new external dependencies required
- Uses existing pydantic validation framework
- Compatible with existing JSON schema validation

### Performance Impact
- Zero performance impact when regime disabled
- Minimal overhead when enabled (rolling window calculations)
- Memory usage scales with feature window sizes (configurable)

### Security Considerations
- Regime signals logged for audit trail
- No additional security risks introduced
- Maintains existing data validation standards

## Approval Checklist

- [ ] Schema changes reviewed by architecture team
- [ ] Backward compatibility tests passing
- [ ] Documentation updated
- [ ] Migration plan approved
- [ ] Rollback procedure documented

## Rollback Plan

If issues arise, rollback involves:
1. Remove regime-specific code additions
2. Keep RegimeType enum for future use (harmless)
3. All existing functionality restored immediately
4. Zero impact on production systems