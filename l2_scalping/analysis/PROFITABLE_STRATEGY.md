# L2 Scalping Profitable Strategy

**Updated**: 2025-12-20  
**Status**: ✅ Live on paper trading with hard gates

## Final Strategy: OBI > 0.8 + rel_vol > 2.0 + RSI > 50 + Hard Gates

### Entry Criteria
```yaml
strategy:
  entry:
    obi_threshold: 0.8        # Order Book Imbalance > 0.8 or < -0.8
    min_rel_volume: 2.0       # Relative volume > 2x average
    rsi_min: 50               # RSI(14) > 50 (bullish context)
  
  hard_gates:                 # Additional filters (CRITICAL)
    block_vol_expansion: true # Block during volatility spikes
    block_bb_squeeze: true    # Block during consolidation
  
  position:
    size_pct: 0.40            # 40% of account ($4,000 on $10k)
    hold_time_seconds: 300    # 5-minute hold
```

### Backtest Results (Dec 17-19, 2025)

| Configuration | Trades | Win Rate | Avg P&L | Total P&L | Monthly Est. |
|---------------|--------|----------|---------|-----------|--------------|
| Winning Strategy (baseline) | 154 | 58.4% | $1.31 | $201.40 | $2,115 |
| **+ Hard Gates** | **85** | **84.7%** | **$4.72** | **$401.60** | **$4,217** |

### Hard Gates Impact

| Gate | Effect | Improvement |
|------|--------|-------------|
| `block_vol_expansion` | Filters volatility spikes | Removes noisy signals |
| `block_bb_squeeze` | Filters consolidation | Waits for breakouts |
| **Combined** | -45% trades, +99% profit | Win rate 58% → 85% |

### Why Hard Gates Work

1. **Volatility Expansion** (-1.54 bps without filter)
   - High volatility = noisy L2 signals
   - Order book imbalance less predictive

2. **Bollinger Squeeze** (-0.88 bps without filter)
   - Consolidation = no directional edge
   - Wait for breakout before trading

### Soft Gates (DISABLED)

Tiered sizing based on RSI>70, displacement, counter-momentum was tested but showed -$19 impact. Disabled until more data available.

### Projections ($10k Account)

| Period | P&L | ROI |
|--------|-----|-----|
| Daily (avg) | $200.80 | 2.0% |
| Monthly (21 days) | $4,216.78 | 42.2% |
| Annual (252 days) | $50,601 | **506%** |

⚠️ **Caution**: Based on 2 trading days. More data needed.

### Live System Status

```bash
# Service running with hard gates
systemctl status l2-scalping.service

# Logs
journalctl -u l2-scalping.service -f
```

### Implementation Files

- `src/signals/context_filter.py` - Hard gate logic
- `src/main.py` - Integration with trading loop
- `config/strategy.yaml` - Gate configuration
