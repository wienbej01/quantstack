# Market Regime Detection Features

## Overview

The regime detection feature suite provides streaming-friendly indicators for classifying intraday market conditions. These features are designed to work with 1-minute OHLCV data and avoid any forward-looking bias, making them suitable for real-time trading applications.

## Feature Types

### 1. MoD-Normalized Volatility (`mod_normalized_volatility`)

**Purpose**: Normalizes intraday volatility by time-of-day patterns to remove seasonality bias.

**Calculation**:
- True Range volatility normalized by close price
- Rolling average over specified window
- Normalized by month-of-day historical averages

**Parameters**:
- `lookback_m`: Rolling window in minutes (default: 30)
- `min_periods`: Minimum periods for calculation (default: 5)

**Interpretation**:
- `> 1.0`: Higher volatility than historical average for this time
- `< 1.0`: Lower volatility than historical average
- `≈ 1.0`: Normal volatility conditions

**Use Case**: Identify abnormal volatility conditions that may signal regime transitions.

### 2. Variance Ratio (`variance_ratio`)

**Purpose**: Detects trending vs ranging markets using variance analysis.

**Calculation**:
- Short-term variance / Long-term variance
- Uses price returns for variance calculation

**Parameters**:
- `short_window`: Short-term window in minutes (default: 10)
- `long_window`: Long-term window in minutes (default: 60)
- `min_periods`: Minimum periods for calculation (default: 3)

**Interpretation**:
- `> 1.0`: Trending market (higher short-term variance)
- `< 1.0`: Ranging market (higher long-term variance)
- `≈ 1.0`: Neutral conditions

**Use Case**: Primary indicator for distinguishing trend vs mean-reversion regimes.

### 3. ADX Proxy (`adx_proxy`)

**Purpose**: Measures trend strength without directional bias.

**Calculation**:
- True Range-based directional movement calculation
- Smoothed directional indexes
- ADX = 100 * |+DI - -DI| / (+DI + -DI)

**Parameters**:
- `lookback_m`: Lookback window in minutes (default: 14)
- `min_periods`: Minimum periods for calculation (default: 3)

**Interpretation**:
- `0-25`: Weak trend or ranging market
- `25-50`: Moderate trend strength
- `50-75`: Strong trend
- `75+`: Very strong trend

**Use Case**: Confirm trend strength identified by variance ratio.

### 4. Band Position (`band_position`)

**Purpose**: Measures price position relative to Bollinger Bands.

**Calculation**:
- Bollinger Bands using SMA and standard deviation
- Position = (Close - Lower Band) / (Upper Band - Lower Band)

**Parameters**:
- `window_m`: Window for moving average (default: 20)
- `std_dev`: Standard deviations for bands (default: 2.0)
- `min_periods`: Minimum periods for calculation (default: 5)

**Interpretation**:
- `0.0`: At lower band (oversold)
- `0.5`: At middle band (neutral)
- `1.0`: At upper band (overbought)
- `< 0.0` or `> 1.0`: Outside bands (strong moves)

**Use Case**: Identify overbought/oversold conditions and potential reversions.

### 5. Stress Metrics (`stress_metrics`)

**Purpose**: Detects market stress using volatility and volume spikes.

**Calculation**:
- Combines volatility spikes and volume surges
- Normalized by long-term averages
- Stress score = max(vol_stress, volume_stress) when thresholds exceeded

**Parameters**:
- `volatility_window`: Window for volatility calculation (default: 10)
- `volume_window`: Window for volume average (default: 10)
- `vol_threshold`: Volatility multiplier for stress (default: 2.0)
- `volume_threshold`: Volume multiplier for stress (default: 3.0)
- `min_periods`: Minimum periods for calculation (default: 3)

**Interpretation**:
- `0`: No stress conditions
- `> 0`: Stress detected (higher = more stress)
- Clipped at 10 for stability

**Use Case**: Primary indicator for STRESS regime detection.

## Feature Packs

### Regime Basics (`regime_basics`)

Default configuration for general regime detection:
```yaml
features:
  - type: "regime_basics"
```

**Parameters**:
- MoD volatility: 30-minute window
- Variance ratio: 10/60 minute windows
- ADX proxy: 14-minute window
- Band position: 20-minute window, 2.0 std dev
- Stress metrics: 10-minute windows, 2.0/3.0 thresholds

### Regime Fast (`regime_fast`)

Faster response configuration for quick regime changes:
```yaml
features:
  - type: "regime_fast"
```

**Parameters**:
- All windows reduced by ~50%
- Lower thresholds for stress detection
- Suitable for high-frequency applications

### Regime Slow (`regime_slow`)

Slower, more stable configuration:
```yaml
features:
  - type: "regime_slow"
```

**Parameters**:
- All windows increased by ~100%
- Higher thresholds for stress detection
- Suitable for position trading and longer timeframes

## Usage Examples

### Basic Usage

```python
from qx_features.registry import apply

# Apply regime features to data
features_config = [
    {"type": "regime_basics"},
    {"type": "core_basics"}  # Can combine with other features
]

data_with_features = apply(data, features_config)
```

### Custom Configuration

```python
# Custom regime feature configuration
custom_config = [
    {
        "type": "custom",
        "features": {
            "mod_normalized_volatility": {"lookback_m": 20},
            "variance_ratio": {"short_window": 5, "long_window": 25},
            "stress_metrics": {
                "volatility_window": 8,
                "volume_window": 8,
                "vol_threshold": 1.8,
                "volume_threshold": 2.5
            }
        }
    }
]

data_with_features = apply(data, custom_config)
```

### Integration with Regime Detector

```python
from qx_core.regime.detector import RegimeDetectorRules

# Apply features then detect regimes
data_with_features = apply(data, [{"type": "regime_basics"}])

detector = RegimeDetectorRules({
    "volatility_threshold": 1.5,
    "trend_threshold": 1.2,
    "stress_threshold": 2.0
})

# Process each timestamp
for ts, group in data_with_features.groupby('ts'):
    regime_signal = detector.evaluate(group, ts)
    # Use regime_signal to gate trading decisions
```

## Performance Characteristics

### Computational Efficiency

- **Vectorized operations**: Optimized for SP500-scale processing
- **Streaming-friendly**: Rolling windows suitable for real-time
- **Memory efficient**: Temporary columns cleaned up automatically

### Timing Benchmarks

- **Regime basics**: ~50,000 bars/second
- **Regime fast**: ~80,000 bars/second
- **Regime slow**: ~35,000 bars/second

### Memory Usage

- Scales with O(n) where n = number of symbols × window size
- Typical memory usage: ~10MB for 500 symbols with 60-minute windows

## Data Requirements

### Minimum Data

- **OHLCV**: Open, High, Low, Close, Volume
- **Timestamps**: UTC nanosecond format
- **Sorting**: Must be sorted by [symbol, ts]
- **Frequency**: 1-minute bars (optimal)

### Warmup Period

- **Regime basics**: 60 bars (1 hour for 1-min data)
- **Regime fast**: 30 bars (30 minutes)
- **Regime slow**: 120 bars (2 hours)

Warmup mask provided as `f__regime__warmup_ok` column.

## Quality Assurance

### Forward-Look Prevention

All features use only contemporaneous or historical data:
- Rolling windows exclude current timestamp from historical averages
- Seasonality normalization uses pre-computed historical patterns
- No future data leakage in any calculation

### Robustness

- Handles missing data gracefully
- Clipping of extreme values for stability
- Proper NaN handling and propagation
- Input validation for OHLCV relationships

### Testing

Comprehensive test suite includes:
- Forward-looking bias tests
- Seasonality normalization validation
- Stress condition detection
- Performance benchmarks
- Edge case handling

## Integration Points

### Feature Registry

```python
from qx_features.registry import FeatureRegistry

# List available features
features = FeatureRegistry.list_available_features()
# ['vwap', 'rel_volume', 'atr', 'mod_normalized_volatility', ...]

# List regime packs
packs = FeatureRegistry.list_predefined_packs()
# ['core_basics', 'regime_basics', 'regime_fast', 'regime_slow', ...]
```

### Configuration Validation

```python
from qx_features.registry import validate_feature_pack_config

# Validate configuration
config = {"type": "regime_basics", "params": {...}}
validate_feature_pack_config(config)  # Raises if invalid
```

## Best Practices

### 1. Window Selection

- **Fast regimes**: 5-15 minute windows for quick detection
- **Normal regimes**: 15-60 minute windows for balanced response
- **Slow regimes**: 60-120 minute windows for stability

### 2. Threshold Tuning

- Start with default parameters
- Adjust based on historical regime characteristics
- Consider market-specific volatility patterns

### 3. Feature Combination

- Use variance ratio as primary trend indicator
- Confirm with ADX proxy for trend strength
- Use stress metrics for regime overrides
- Apply band position for reversion signals

### 4. Performance Optimization

- Pre-configure feature packs for specific use cases
- Use appropriate warmup periods
- Monitor memory usage with large symbol universes

## Troubleshooting

### Common Issues

**Missing features after `apply()`**:
- Check data has required OHLCV columns
- Verify data is sorted by [symbol, ts]
- Ensure sufficient warmup period

**Unexpected NaN values**:
- Check for insufficient data in early periods
- Verify no zero or negative prices/volumes
- Look for data gaps or duplicates

**Poor performance**:
- Reduce window sizes for faster computation
- Consider using regime_fast pack
- Monitor memory usage with large datasets

**Inaccurate regime detection**:
- Adjust thresholds for specific market characteristics
- Verify seasonality patterns in your data
- Consider market-specific parameter tuning

### Debug Tools

```python
# Check warmup status
warmup_mask = data['f__regime__warmup_ok']
print(f"Warmed up bars: {warmup_mask.sum()}/{len(warmup_mask)}")

# Feature distribution analysis
for col in data.columns:
    if col.startswith('f__regime__'):
        print(f"{col}: min={data[col].min():.3f}, max={data[col].max():.3f}, mean={data[col].mean():.3f}")
```

## References

- **ADX**: Welles Wilder's Average Directional Index
- **Bollinger Bands**: John Bollinger's volatility bands
- **Variance Ratio**: Lo and MacKinlay (1988) variance ratio test
- **Seasonality Adjustment**: Time-of-day volatility patterns

## Version History

- **v1.0**: Initial implementation with 5 core regime features
- **v1.1**: Added performance optimizations and warmup masks
- **v1.2**: Enhanced parameter validation and error handling