# Daily HMM_SIP Universe Selection

## Overview

Daily HMM_SIP is a universe selection feature that uses Hidden Markov Model scoring to select tradable symbols on a daily basis. This feature can be enabled for any trading strategy through simple configuration changes.

## Key Features

- **Daily Universe Selection**: Selects top-k symbols each day based on HMM scores
- **Dynamic Universe Size**: Uses score thresholds rather than fixed symbol counts
- **Framework Agnostic**: Works with any trading strategy (VWAP, ML, custom policies)
- **Configuration Driven**: Simple enable/disable via SIP configuration
- **Position Protection**: Existing positions continue until natural exit when symbols drop from universe

## Configuration

### Basic Setup

```yaml
sip:
  method: "hmm"
  config:
    mode: "daily"
    score_floor: 0.01      # Minimum HMM score threshold
    top_k: 40             # Maximum symbols per day
    rebalance_frequency: "daily"
    broadcast_time: "09:30:00"
```

### Parameters

- `mode`: "daily" to enable daily selection, "legacy" for original behavior
- `score_floor`: Minimum HMM score (0.0-1.0). Only symbols above this score are eligible
- `top_k`: Maximum number of symbols to select per day
- `rebalance_frequency`: Currently only "daily" supported
- `broadcast_time`: Time when daily universe is applied (default market open)

## Usage Examples

### VWAP Strategy with Daily HMM_SIP

```yaml
# experiments/vwap_daily_hmm/strategy.yaml
policy: "vwap_revert"
sip:
  method: "hmm"
  config:
    mode: "daily"
    score_floor: 0.02
    top_k: 20
```

### Command Line Usage

```bash
# Run entry-ab experiment with daily HMM_SIP
qx-cli exp entry-ab experiments/vwap_daily_hmm/strategy.yaml

# Compare daily vs legacy HMM_SIP
qx-cli exp compare \
  experiments/vwap_legacy_hmm/ \
  experiments/vwap_daily_hmm/
```

## Implementation Details

### Architecture

The feature is implemented as an enhancement to the existing HMM_SIP module:

1. **DailyHMMSIPSelector**: Handles daily universe computation
2. **Enhanced HMMSIPUniverseSelector**: Routes between legacy and daily modes
3. **Backtest Engine Integration**: Filters bars based on daily universe
4. **Experiment Framework Support**: Works with A/B testing and other experiments

### Data Flow

```
Daily Market Open → HMM_SIP Scoring → Universe Selection → Strategy Execution
      ↓                    ↓                   ↓                ↓
  09:30 AM ET        Top-K Symbols      Filter Bars     Generate Signals
```

### Performance Considerations

- **Hybrid Caching**: Daily universes computed once per day and cached
- **Memory Efficient**: Only stores current and previous day's universes
- **Fast Lookup**: O(1) symbol eligibility checks during strategy execution

## Best Practices

1. **Score Floor Tuning**: Start with `score_floor: 0.01` and adjust based on backtest results
2. **Top-K Selection**: Balance diversification (higher k) vs concentration (lower k)
3. **Validation**: Always compare with legacy HMM_SIP using the compare command
4. **Monitoring**: Track daily universe sizes and score distributions

## Troubleshooting

### Zero Trades Issue

If the strategy produces zero trades with daily HMM_SIP:

1. Check if `score_floor` is too high for current market conditions
2. Verify sufficient date range and symbol coverage
3. Use the compare command to verify against legacy HMM_SIP

### Performance Issues

For slow backtests:

1. Reduce `top_k` to limit daily universe size
2. Ensure HMM premarket files are available and accessible
3. Check memory usage with large symbol universes

## Advanced Configuration

### Custom Rebalance Times

```yaml
sip:
  method: "hmm"
  config:
    mode: "daily"
    broadcast_time: "10:00:00"  # Custom universe application time
```

### Conservative Selection

```yaml
sip:
  method: "hmm"
  config:
    mode: "daily"
    score_floor: 0.05  # Higher threshold for quality
    top_k: 10          # Smaller, focused universe
```

## Integration with Experiment Framework

The daily HMM_SIP feature integrates seamlessly with the qx-cli experiment framework:

### Entry/Exit A/B Testing

```python
from qx_cli.exp.entry_ab import run_entry_ab_experiment

config = {
    'base_config': {
        'sip': {
            'method': 'hmm',
            'config': {
                'mode': 'daily',
                'score_floor': 0.01,
                'top_k': 20
            }
        }
    },
    'variants': [
        {'name': 'conservative', 'policy_params': {'entry_threshold': 0.02}},
        {'name': 'aggressive', 'policy_params': {'entry_threshold': 0.01}}
    ]
}

results = run_entry_ab_experiment(config)
```

## Monitoring and Analysis

### Daily Universe Metrics

When running experiments, the daily HMM_SIP provides detailed metrics:

```
[HMM SIP] Using daily mode with top_k=20, score_floor=0.01
[HMM SIP] Daily universe map: 390 timestamps, sip_hash: a1b2c3d4...
```

### Performance Comparison

Use the compare command to analyze performance differences:

```bash
qx-cli exp compare experiments/legacy_hmm/ experiments/daily_hmm/
```

## Migration from Legacy HMM_SIP

### Simple Migration

To migrate from legacy to daily HMM_SIP, simply add the `mode` parameter:

```yaml
# Before (legacy)
sip:
  method: "hmm"
  config:
    score_floor: 0.01
    top_k: 40

# After (daily)
sip:
  method: "hmm"
  config:
    mode: "daily"      # Add this line
    score_floor: 0.01
    top_k: 40
```

### Validation Steps

1. Run a small date range test with daily mode
2. Compare results with legacy baseline
3. Adjust parameters if needed
4. Run full validation

## Technical Specifications

### Memory Usage

- Daily universes stored as `{date: set[symbols]}`
- Memory usage scales with `O(days * top_k)`
- Automatic cleanup of old universes

### Computational Complexity

- Universe selection: `O(symbols * log symbols)` per day
- Symbol eligibility lookup: `O(1)` per bar
- Overall backtest impact: <5% for typical configurations

### File Dependencies

- Requires access to HMM premarket score files
- Gold fallback option for missing external data
- Compatible with existing data infrastructure