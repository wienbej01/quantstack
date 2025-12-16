# Intraday ML Extension

A comprehensive machine learning extension for intraday trading strategies, featuring robust data preparation, feature engineering, and model training pipelines.

## Overview

This extension implements a sliding window approach to intraday ML, solving the critical feature-label alignment issue that prevented model training in previous implementations. The system processes each timestamp independently, ensuring strict temporal discipline and eliminating lookahead bias.

## Architecture

### Core Components

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Gold Data     │───▶│  Sliding Window   │───▶│ Aligned Features │
│ (bars_1m data)  │    │  Data Prep       │    │    & Labels     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │                        │
                              ▼                        ▼
                        ┌─────────────────┐    ┌─────────────────┐
                        │  Feature Pack   │    │  Label Engine   │
                        │  (≤150 feats)    │    │  (ATR-threshold) │
                        └─────────────────┘    └─────────────────┘
                              │                        │
                              └──────────┬───────────────┘
                                         ▼
                                ┌─────────────────┐
                                │  Training Dataset │
                                │  (aligned DF)     │
                                └─────────────────┘
                                         │
                                         ▼
                                ┌─────────────────┐
                                │   LightGBM       │
                                │   Model Training │
                                └─────────────────┘
```

### Data Flow

1. **Data Loading**: Load continuous historical data with proper timestamp conversion
2. **Sliding Window**: Process each timestamp independently
3. **Feature Generation**: Compute features using only historical data (≤ timestamp)
4. **Label Computation**: Calculate labels using only future data (> timestamp)
5. **Alignment**: Combine into single DataFrame with perfect feature-label alignment
6. **Model Training**: Train LightGBM model with calibration

## Key Features

### ✅ **Temporal Discipline**
- **No Lookahead Bias**: Strict separation of historical vs future data
- **Sliding Window**: Each timestamp processed independently
- **Time Validation**: Built-in checks prevent temporal leakage

### ✅ **Feature Engineering**
- **150+ Features**: Organized by families (returns, volatility, volume, VWAP, time, etc.)
- **Leakage-Proof**: All features respect time discipline
- **Modular Design**: Enable/disable feature families via configuration

### ✅ **Label Generation**
- **ATR-Thresholded**: Prominent moves labeled using Average True Range
- **Tri-Class**: {-1, 0, +1} classification (down, neutral, up)
- **First-Hit Logic**: Multiple horizons with first threshold hit
- **Deprecation**: Old `create_labels` method marked with warnings

### ✅ **Model Training**
- **LightGBM**: Gradient boosting with calibration
- **Cross-Validation**: Time series aware CV with purging/embargo
- **Performance Metrics**: Accuracy, Brier score, calibration improvement

## Usage

### Basic Data Preparation

```python
from extensions.intraday_ml.data_prep import create_training_dataset

# Create aligned training dataset
training_data = create_training_dataset(
    symbols=['BAC', 'AAPL'],
    start_date='2023-01-01',
    end_date='2023-12-31',
    features_config=features_config,
    targets_config=targets_config
)

# Result: DataFrame with features + 'label' column
print(f"Shape: {training_data.shape}")
print(f"Features: {[col for col in training_data.columns if col.startswith('f__')]}")
print(f"Label distribution: {training_data['label'].value_counts()}")
```

### Model Training

```python
from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer

# Separate features and labels
feature_cols = [col for col in training_data.columns if col.startswith('f__')]
X = training_data[feature_cols]
y = training_data['label']

# Train model
trainer = LightGBMTrainer(model_config)
result = trainer.train_model(X, y, features_hash='hash1', targets_hash='hash2')

print(f"Training accuracy: {result.metrics['accuracy']}")
print(f"Brier score improvement: {result.metrics['brier_improvement']}")
```

## Configuration

### Features Configuration (`features.yaml`)

```yaml
families:
  returns_trend:
    enabled: true
    windows: [1, 5, 10, 20]
    include_log: false

  volatility_ranges:
    enabled: true
    atr_windows: [5, 14, 30]
    volatility_windows: [5, 10, 20, 30]

  volume_flow:
    enabled: true
    volume_windows: [5, 10, 20]
    vwap_windows: [5, 10, 20, 30]
    relative_volume_windows: [10, 20, 30]

max_total_features: 150
```

### Targets Configuration (`targets.yaml`)

```yaml
label_type: "triclass_atr_threshold"
horizons: [30, 60, 90]  # minutes
atr_multiplier: 0.038
atr_multiplier_long: 0.036
atr_multiplier_short: 0.040
atr_window: 14
volatility_scaling:
  enabled: true
  target_move_pct: 0.009
  price_quantile: 0.55
  atr_quantile: 0.75
  mix: 0.55
  multiplier_bounds: {min: 0.004, max: 0.08}
directional_balance:
  enabled: true
  target_ratio: 1.0
  tolerance: 0.2
  max_iterations: 8
  adjust_step: 0.1
  multiplier_bounds: {min: 0.004, max: 0.09}
first_hit_logic:
  enabled: true
  stop_at_hit: true
  min_bars_required: 1
require_min_atr: 0.01
```

## Pipeline Integration

The extension integrates seamlessly with the Phase A pipeline:

```bash
# Run complete pipeline
python run_phaseA_pipeline.py
```

**Pipeline Steps:**
1. ✅ Dataset manifest creation
2. ✅ **NEW**: Sliding window data preparation (features + labels)
3. ✅ LightGBM model training
4. ✅ Cross-validation
5. ✅ Decision policy configuration

## Performance Characteristics

### Data Processing
- **Speed**: ~1,000 timestamps/second (feature-lite config)
- **Memory**: Streaming approach, constant memory usage
- **Scalability**: Handles 100K+ timestamps efficiently
- **Progress**: Reports every 10,000 timestamps

### Model Performance
- **Accuracy**: 40-60% (typical for tri-class financial prediction)
- **Calibration**: Brier score improvement 5-15%
- **Probability balance**: Auto-balanced class weights keep long/short probabilities within ±0.05.
- **Feature Count**: 50-150 features (configurable)
- **Training Time**: 1-5 minutes for full year of data

## Testing

### Unit Tests
```bash
# Test individual components
python -m pytest tests/extensions/intraday_ml/test_compute_label_for_timestamp.py
python -m pytest tests/extensions/intraday_ml/test_create_training_dataset.py
```

### Integration Tests
```bash
# Test complete pipeline
python -m pytest tests/extensions/intraday_ml/test_m3_ml_model.py
```

### Smoke Tests
```bash
# Test with real data
python -m pytest tests/extensions/intraday_ml/test_m1_smoke.py
```

## Troubleshooting

### Common Issues

**Q: All labels are 0 (neutral)**
A: Review `volatility_scaling.target_move_pct` and `directional_balance` bounds; lowering the
target move or the long/short multipliers will relax thresholds.

**Q: Pipeline runs slowly**
A: Reduce feature families or date range. Progress tracking shows current status.

**Q: "Number of classes should be specified" error**
A: Real data needed - synthetic test data often has all neutral labels.

**Q: Timestamp errors**
A: Ensure data loading converts microseconds to datetime (handled automatically).

### Performance Optimization

1. **Reduce Features**: Disable unnecessary feature families
2. **Limit Date Range**: Start with 1-3 months for testing
3. **Monitor Progress**: Use built-in progress tracking
4. **Memory Management**: Streaming approach prevents memory issues

## Migration from Previous Version

### Old Approach (Deprecated)
```python
# ❌ Old separate approach - causes misalignment
features = feature_pack.compute_features(data, ts_cut)
labels = labeler.create_labels(data, ts_cut)  # Different time periods!
```

### New Approach (Recommended)
```python
# ✅ New aligned approach
training_data = create_training_dataset(
    symbols, start_date, end_date,
    features_config, targets_config
)
# Features and labels perfectly aligned!
```

## Architecture Decisions

### Sliding Window Rationale
The sliding window approach solves the fundamental alignment issue:
- **Old Problem**: Features and labels from different time periods
- **New Solution**: Each timestamp gets its own aligned feature-label pair
- **Benefit**: Enables proper model training with temporal consistency

### Feature Limitation
150 feature limit prevents overfitting and ensures computational efficiency:
- **Comprehensive Coverage**: All major intraday patterns included
- **Performance**: Fast training and inference
- **Maintainability**: Clear feature organization

### ATR-Based Labeling
ATR-thresholded labels adapt to market volatility:
- **Dynamic Thresholds**: Different for each symbol/time period
- **Prominent Moves**: Only significant price changes labeled
- **Market Reality**: Reflects actual trading opportunities

## Contributing

### Development Guidelines
1. **No Lookahead**: Always respect temporal boundaries
2. **Test Coverage**: Unit tests for all new functions
3. **Documentation**: Clear docstrings and examples
4. **Performance**: Monitor memory and speed impact
5. **Validation**: Test with real market data

### Code Review Checklist
- [ ] No core qx-* modules modified
- [ ] Temporal discipline enforced
- [ ] Tests passing (unit + integration)
- [ ] Documentation updated
- [ ] Performance acceptable
- [ ] No breaking changes

## License

This extension is part of the QuantStack project and follows the same licensing terms.

## Support

For questions or issues:
1. Check existing tests and documentation
2. Review configuration examples
3. Validate with smaller date ranges first
4. Monitor progress output for debugging

---

**Last Updated**: 2025-01-30
**Version**: Sprint 1 + Sprint 2 Implementation
**Status**: Production Ready
