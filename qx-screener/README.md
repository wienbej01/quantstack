# qx-screener

Universe selection and screening for QuantStack.

## Overview

qx-screener provides deterministic universe selection based on relative volume ranking with cross-sectional filtering for quantitative trading strategies.

## Features

- **SIP (Symbol Selection by Independent Popularity)** screener
- **Deterministic ranking** by relative volume
- **Configurable filters** for price, volume, and other criteria
- **Integration** with qx-features for feature engineering
- **Cross-sectional selection** with top-N capabilities

## Installation

```bash
pip install qx-screener
```

## Quick Start

```python
from qx_screener.sip import SipScreener, ScreenerConfig, create_sample_universe_data

# Create sample data
data = create_sample_universe_data()

# Configure screener
config = ScreenerConfig(
    top_n=10,
    min_relative_volume=1.0,
    min_price=10.0,
    max_price=1000.0
)

# Screen universe
screener = SipScreener(config)
result = screener.screen_universe(data)

print(f"Selected {len(result)} symbols:")
print(result[['symbol', 'close', 'relative_volume', 'rvol_rank']])
```

## Configuration

The `ScreenerConfig` class provides various filtering options:

- `top_n`: Number of symbols to select (default: 10)
- `min_relative_volume`: Minimum relative volume threshold (default: 1.0)
- `min_price`/`max_price`: Price range filters (default: 10.0-1000.0)
- `min_dollar_volume`: Minimum daily dollar volume (default: $1M)
- `volume_window`: Lookback window for relative volume (default: 30)
- `exclude_symbols`: Symbols to exclude from selection

## Integration with qx-features

```python
from qx_features.registry import apply

# Screen universe first
screener = SipScreener()
screened_data = screener.screen_universe(data)

# Filter data to selected symbols
selected_symbols = screened_data['symbol'].tolist()
filtered_data = data[data['symbol'].isin(selected_symbols)]

# Apply feature engineering
feature_packs = [{'type': 'core_basics', 'params': {'vwap_window_m': 10}}]
feature_data = apply(filtered_data, feature_packs)
```

## Deterministic Selection

The screener ensures deterministic selection through:

- Consistent sorting by relative volume (descending) then symbol (ascending)
- Stable ranking with ties resolved by symbol name
- Reproducible results across multiple runs

## Testing

Run tests with:

```bash
pytest tests/
```