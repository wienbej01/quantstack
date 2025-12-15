# Live Trading with L2 Data

## Overview

This implementation integrates your existing IBKR L2 data collection system with quantstack's regime-aware ML strategy for live trading.

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Polygon API   │    │   IBKR Gateway   │    │  Quantstack ML  │
│  (SIP Universe) │────│   (L2 Data)      │────│   (Trading)     │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

**Data Flow:**
1. **Polygon**: Daily HMM SIP universe selection (40 symbols)
2. **IBKR L2**: Deep data collection on top 3 symbols
3. **ML Model**: Regime-aware predictions with L2 features

## Setup

### 1. Install Dependencies
```bash
make install-live
```

### 2. Configure IBKR
- Ensure TWS/Gateway running on port 7497 (paper trading)
- Subscribe to market data (see L2_DATA_ACCESS_SUMMARY.md)
- Test connection: `make test-l2`

### 3. Set Environment
```bash
export POLYGON_API_KEY="your_key_here"
```

## Usage

### Test L2 Integration
```bash
make test-l2
```

### Run Live Trading
```bash
make live-trade
```

## Configuration

Edit `experiments/live_regime_aware/config.yaml`:

```yaml
data:
  l2:
    max_symbols: 3        # L2 collection limit
    rotate_seconds: 300   # Symbol rotation
    levels: 10           # Order book depth
    
sip:
  config:
    top_k: 40           # Full universe size
```

## L2 Data Collection Strategy

**Recommended Approach**: 3 symbols with 5-minute rotation

**Benefits:**
- Respects IBKR data limits
- Maximizes L2 feature quality
- Covers diverse market conditions
- Builds training dataset over time

**Collection Schedule:**
- **09:30-10:30**: Market open volatility
- **11:30-12:30**: Midday consolidation  
- **15:00-16:00**: Power hour momentum

## Integration Points

### 1. SIP Selection
- Uses existing HMM logic for universe
- Selects top 3 for L2 focus
- Daily rotation based on performance

### 2. L2 Features
- Order book imbalance (1, 3, 5, 10 levels)
- Microprice deviation
- Depth-weighted pressure
- Time-series deltas (5s, 30s)

### 3. ML Integration
- Blends L2 features with existing 11 cross-sectional features
- Regime-aware model selection
- Real-time prediction pipeline

## Monitoring

**Live Logs:**
```bash
tail -f logs/live_trading.log
```

**L2 Data Quality:**
- Check `./data/live_l2/` for collected data
- Monitor depth rate (target: >85%)
- Validate feature completeness

## Next Steps

1. **Phase 1**: Test with paper trading
2. **Phase 2**: Validate L2 feature quality
3. **Phase 3**: Retrain models with L2 data
4. **Phase 4**: Deploy to live account

## Troubleshooting

**Connection Issues:**
- Verify TWS/Gateway running
- Check port 7497 availability
- Ensure market data subscriptions

**Data Quality:**
- Monitor `has_depth` rate
- Check symbol rotation logs
- Validate feature calculations
