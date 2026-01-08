# qx-screener

Universe selection and screening for QuantStack.

## Overview

qx-screener provides deterministic universe selection using the shared **daily SIP universe** JSON artifacts for quantitative trading strategies.

## Features

- **Daily SIP Universe** - Shared JSON artifacts across all systems
- **News Attention Scoring** - `volume × |returns|` for catalyst detection  
- **Multi-factor Algorithm** - `news_attention×0.5 + volume×0.3 + volatility×0.2`
- **Configurable Filters** - Score floor and optional top_k cap
- **Parallel Processing** - ThreadPoolExecutor with configurable workers
- **Integration** with qx-features for feature engineering

## SIP Universe Generation

### Command Line Usage
```bash
# Single date (shared daily_sip JSON)
python -m qx_screener.hmm_sip --mode polygon --date 2025-12-22

# Using configuration
python scripts/generate_sip_from_feature_store.py --date 2025-12-22
```

### Python API
```python
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector

# Configure shared daily_sip mode
config = HMMSIPConfig(
    mode="polygon",
    top_k=40,
    score_floor=0.01,
    price_min=5.0,
    price_max=50.0,
    volume_min=100000
)

selector = HMMSIPUniverseSelector(config)
universe_map = selector.select(bars_utc, {"target_date": "2025-12-22"})
```

### Storage Location
```
SIP_DAILY_ROOT/date=YYYY-MM-DD/
├── date=2025-12-22/
│   └── sip_universe.json
```

## Installation

```bash
pip install qx-screener
```

## Legacy Compatibility

The system maintains backward compatibility with legacy modes:
- `mode="legacy"` - Original HMM SIP (deprecated)
- `mode="daily"` - Daily HMM SIP (deprecated)  
- `mode="polygon"` - **Recommended** shared daily_sip JSON method

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
