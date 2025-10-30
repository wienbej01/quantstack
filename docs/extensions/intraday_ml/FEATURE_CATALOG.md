# Intraday ML Feature Catalog

Human-readable definitions, formulas, and parameters for all features in the intraday ML feature pack.

## Overview

The feature pack contains ≤150 leakage-proof features organized into 8 families. All features respect strict time discipline and only use data ≤ ts_cut.

## Feature Families

### 1. Returns & Trend (`returns_trend`)

Captures price momentum and trend direction over multiple time horizons.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__ret__simple_N` | Simple N-minute return | `(close_t / close_{t-N}) - 1` | 1, 5, 10, 20, 30 | close |
| `f__ret__log_N` | Log N-minute return | `log(close_t / close_{t-N})` | 1, 5, 10, 20, 30 | close |

**Notes:**
- Simple returns provide linear momentum signals
- Log returns provide better statistical properties for larger windows
- Forward filling handles missing values at window boundaries

### 2. Volatility & Ranges (`volatility_ranges`)

Measures price volatility and range characteristics across timeframes.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__vol__atr_N` | Average True Range | `max(high-low, abs(high-prev_close), abs(low-prev_close))` | 5, 14, 30 | high, low, close |
| `f__vol__rolling_std_N` | Rolling volatility | `std(returns) * sqrt(390)` | 5, 10, 20, 30 | close |
| `f__range__ratio_X` | Range ratio | `(high-low) / (avg_range_{20} * X)` | - | high, low |

**Notes:**
- ATR uses True Range for more robust volatility measurement
- Rolling volatility is annualized (390 trading minutes per day)
- Range ratios identify unusual price expansion/compression

### 3. Volume & Flow (`volume_flow`)

Analyzes volume patterns and volume-weighted price metrics.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__vol__sum_N` | Volume aggregation | `sum(volume_{t-N+1:t})` | 5, 10, 20 | volume |
| `f__vwap__value_N` | Volume-weighted average price | `sum(price*volume) / sum(volume)` | 5, 10, 20, 30 | close, volume |
| `f__vol__rel_N` | Relative volume | `current_volume / avg_volume_same_time` | 10, 20, 30 | volume, ts |

**Notes:**
- Relative volume compares to historical average for same time of day
- VWAP provides institutional-level price reference
- Volume aggregations identify accumulation/distribution patterns

### 4. VWAP Distance & Z-Scores (`vwap_distance`)

Measures distance from volume-weighted benchmarks and statistical significance.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__vwap__dist_N` | VWAP distance | `(close - vwap_N) / close` | 5, 10, 20, 30 | close, volume |
| `f__vwap__z_N_M` | VWAP z-score | `(return_to_vwap - mean) / std` | N×M combinations | close, volume |

**Notes:**
- VWAP distance identifies overbought/oversold conditions relative to volume
- Z-scores normalize distance by historical volatility
- Multiple windows provide short and medium-term perspectives

### 5. Time Seasonality (`time_seasonality`)

Captures intraday and weekly patterns through cyclical encoding.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__time__hour_sin/cos` | Hour of day (cyclical) | `sin/cos(2π * hour / 24)` | - | ts |
| `f__time__minute_sin/cos` | Minute of hour (cyclical) | `sin/cos(2π * minute / 60)` | - | ts |
| `f__time__dow_sin/cos` | Day of week (cyclical) | `sin/cos(2π * dow / 7)` | - | ts |

**Notes:**
- Cyclical encoding preserves temporal continuity
- Hour features capture intraday session patterns
- Day of week captures weekly seasonality effects

### 6. Cross-Section (`cross_section`)

Ranks securities relative to peers at each timestamp.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__cross__ret_percentile_N` | Cross-sectional return rank | `rank(pct_change_N) / count` | 5, 20 | close |

**Notes:**
- Percentile ranks identify relative strength vs universe
- Helps models understand which securities are outperforming/underperforming
- Requires multiple symbols at same timestamp for meaningful ranking

### 7. Price Momentum (`price_momentum`)

Technical indicators for trend strength and momentum.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__mom__roc_N` | Rate of change | `pct_change_N * 100` | 1, 5, 10, 20 | close |
| `f__mom__rsi_N` | Relative Strength Index | `100 - (100 / (1 + RS))` | 14, 30 | close |
| `f__ma__ratio_N` | Price to MA ratio | `close / moving_avg_N` | 5, 10, 20, 30 | close |

**Notes:**
- ROC measures momentum in percentage terms
- RSI identifies overbought (>70) and oversold (<30) conditions
- MA ratios show position relative to historical averages

### 8. Microstructure (`microstructure`)

Captures market microstructure effects and short-term imbalances.

| Feature | Description | Formula | Window | Dependencies |
|---------|-------------|---------|--------|--------------|
| `f__micro__spread_N` | Effective spread | `(high - low) / close` | 1, 5, 10 | high, low, close |
| `f__micro__imbalance_N` | Volume imbalance | `sum(price_change * volume)` | 1, 5, 10 | close, volume |
| `f__vwap__5m` | 5-minute VWAP | Standard VWAP calculation | 5 | close, volume |

**Notes:**
- Spread measures market impact and liquidity
- Imbalance identifies buying/selling pressure using volume-weighted price changes
- 5-minute VWAP provides very short-term institutional price level

## Feature Naming Convention

Features follow a structured naming convention:

```
f__{family}__{metric}[_{window}[_{secondary_window}]]
```

Examples:
- `f__ret__simple_5` - 5-minute simple return
- `f__vol__atr_14` - 14-minute ATR
- `f__vwap__z_10_30` - 10-minute VWAP with 30-minute z-score window

## Null Handling Policies

- **forward_fill**: Fill missing values with last valid observation
- **zero_fill**: Fill missing values with zero (for time features)
- **drop**: Drop rows with missing values (rare, only for critical features)

## Time Discipline Compliance

All features are designed to be leakage-proof:
- Only use data available at or before `ts_cut`
- Rolling windows use past data only (no future information)
- Cross-sectional features use current timestamp data only
- Time features use deterministic calendar information

## Configuration Parameters

Feature families can be enabled/disabled and configured via `features.yaml`:

- **Windows**: Lookback periods for rolling calculations
- **Enables**: Turn families on/off based on strategy needs
- **Encoding**: Choose between cyclical and one-hot encoding
- **Quality controls**: Null ratio limits and correlation thresholds

## Performance Considerations

- Total feature count capped at 150 to prevent overfitting
- Warmup period determined by maximum window across all features
- Features designed for efficient vectorized computation
- Memory-conscious implementation for large datasets

## Integration with ML Pipeline

Features integrate seamlessly with:
- Dataset manifest generation (features_hash)
- Label computation (aligned timestamps)
- Model training (consistent feature schema)
- Inference (real-time feature computation)