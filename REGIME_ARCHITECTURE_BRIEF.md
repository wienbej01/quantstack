# Regime Detection Architecture Brief

## Overview

The Regime Detection system provides a modular intraday market regime classification gate that filters trading signals based on market conditions. It integrates seamlessly with the existing qx-* framework without breaking backward compatibility.

## Architecture Components

### 1. RegimeSignal Schema Extension
**Location**: `qx-core/src/qx_core/schemas.py`

New schema addition to existing Signal enum:
```python
class RegimeType(str, Enum):
    BULL = "BULL"      # Normal upward trending conditions
    BEAR = "BEAR"      # Normal downward trending conditions
    SIDEWAYS = "SIDEWAYS"  # Range-bound markets
    STRESS = "STRESS"  # High volatility/crisis conditions
    OFF = "OFF"        # Regime detection disabled

class RegimeSignal(BaseModel):
    """Regime classification signal."""
    ts: int = Field(..., description="UTC nanosecond timestamp")
    regime: RegimeType = Field(..., description="Current market regime")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence")
    features: dict[str, float] = Field(default_factory=dict, description="Underlying feature values")
    persistence_count: int = Field(default=0, description="Consecutive bars in current regime")
    model_version: str = Field("rules_v1", description="Detector version")
```

### 2. Regime Feature Pipeline
**Location**: `qx-features/src/qx_features/regime/features.py`

Streaming-friendly regime indicators:
- **MoD-normalized volatility**: Intraday volatility normalized by month-of-day patterns
- **Variance ratio**: Short/long period variance for trend detection
- **ADX proxy**: Trend strength indicator using price ranges
- **Band position**: Price position relative to rolling bands
- **Stress metrics**: Volatility spikes and volume surge detection

### 3. Rule-Based Detector
**Location**: `qx-core/src/qx_core/regime/detector.py`

Configurable thresholds with hysteresis:
```python
class RegimeDetectorRules:
    def evaluate(self, features_df: pd.DataFrame, ts: int) -> RegimeSignal
    def apply_persistence_guard(self, regime: RegimeType, count: int) -> RegimeType
    def apply_cooldown_logic(self, previous_regime: RegimeType, current: RegimeType) -> RegimeType
```

### 4. Strategy Gating Integration
**Location**: `qx-backtest/src/qx_backtest/engine.py`

Extension of existing strategy activation hooks:
- Regime signals evaluated before strategy `on_bar()` calls
- Configurable strategy mapping per regime type
- Stress regime enforces immediate risk-off behavior

### 5. Configuration Schema Extension
**Location**: Extend existing experiment YAML schema

New optional `regime` block:
```yaml
regime:
  enabled: true/false
  strategy_map:
    BULL: ["vwap_momentum", "vwap_revert"]
    BEAR: ["vwap_revert"]
    SIDEWAYS: ["vwap_revert"]
    STRESS: []  # No strategies in stress
  model: "rules"  # Future: "hsmm"
  persistence_bars: 3
  cooldown_minutes: 15
  features:
    volatility_window: 30
    trend_window: 60
    stress_threshold: 2.0
```

## Data Flow Integration

### Existing Data Flow (Unchanged)
```
Gold bars → SIP screen → Feature enrichment → Policy signals → Risk sizing → Backtest
```

### Enhanced Data Flow with Regime Gate
```
Gold bars → SIP screen → Feature enrichment → Regime detection → Policy gating → Risk sizing → Backtest
```

### Event Bus Integration
Regime signals publish on existing event bus using current `Signal` schema with new `src="regime"` tag.

## Backward Compatibility

- **Default behavior**: When `regime.enabled=false` (or omitted), system behaves exactly as before
- **No schema breaking**: Existing configurations continue to work unchanged
- **Optional dependency**: Strategies can ignore regime signals and operate as before
- **Graceful degradation**: If regime detection fails, strategies continue with last known regime

## Performance Constraints

- **Streaming computation**: All features use rolling windows suitable for real-time processing
- **Memory efficiency**: Feature windows limited to 60-90 minutes maximum
- **Latency budget**: Regime evaluation completes within 1ms per bar on SP500 universe
- **Forward-look prevention**: All features use only contemporaneous or historical data

## Risk & Compliance Controls

- **Audit trail**: Every regime change logged with timestamp, features, and confidence
- **Stress override**: Immediate switch to STRESS regime triggers risk-off and compliance alerts
- **Determinism**: Regime signals are deterministic given identical input data
- **Validation**: Unit tests enforce no forward-look using incremental feed simulation

## Monitoring & Observability

- **Regime duration tracking**: Track time spent in each regime type
- **Flip frequency**: Monitor excessive regime switching (sign of instability)
- **Feature drift alerts**: Automatic detection when feature distributions shift
- **Performance impact**: Measure strategy P&L differences with/without regime gating

## Integration Points

### qx-core Extensions
- New `RegimeType` enum and `RegimeSignal` schema
- Optional regime detector registration in dependency injection
- Validation functions for regime signals

### qx-features Extensions
- New `regime` feature namespace
- Streaming-friendly feature computations
- Integration with existing feature registry

### qx-backtest Extensions
- Strategy gating logic in engine loop
- Regime-aware portfolio risk controls
- Enhanced reporting with regime analysis

### qx-cli Extensions
- New `qx regime backtest <config>` command
- Sample configurations under `experiments/regime/`
- Regime-specific reporting and analysis

## Future Enhancements

### Phase 5: HSMM Integration
- Gaussian Hidden Semi-Markov Model behind feature flag
- State probability smoothing with duration priors
- Seamless swap maintaining identical `RegimeSignal` interface

### Advanced Features
- Multi-timeframe regime consensus
- Sector-specific regime detection
- Regime forecasting with confidence intervals

## Implementation Checklist

- [ ] Schema extensions (RegimeType, RegimeSignal)
- [ ] Feature pipeline implementation
- [ ] Rule-based detector with configurable thresholds
- [ ] Engine integration with strategy gating
- [ ] CLI commands and sample configs
- [ ] Comprehensive test suite (unit + integration)
- [ ] Documentation and developer guide
- [ ] Performance benchmarking
- [ ] Monitoring and alerting setup