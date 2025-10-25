# HMM SIP Universe Selector

**A high-performance, deterministic universe selector for QuantStack that integrates Hidden Markov Model Stock-in-Play signals with minute-level probability gating.**

## Overview

The HMM SIP (Hidden Markov Model - Stocks In Play) Universe Selector provides intelligent universe selection by combining:

1. **External premarket Top-K signals** from HMM models
2. **Gold-only fallback** using premarket gap and volume analysis
3. **Optional minute-level p̂ gating** for intraday eligibility refinement

## Key Features

- **Deterministic hashing**: Produces stable `sip_hash` for A/B testing fairness
- **High performance**: < 1s execution for 1000+ symbols (requirement: < 30s)
- **Robust caching**: LRU caches for external files (1hr TTL) and p̂ data (30min TTL)
- **Graceful fallback**: Works with or without external HMM signals
- **Configurable thresholds**: Top-K selection, score floors, p̂ gating

## Configuration

### Basic Configuration

```yaml
sip:
  selector:
    type: hmm_sip
    params:
      top_k: 40                    # Maximum symbols in universe
      score_floor: 0.0            # Minimum score threshold
      enable_gold_fallback: true  # Use Gold data when external files missing
      p_hat_threshold: null       # Optional: minute-level probability threshold
      min_minutes_in_state: 0     # Optional: minimum minutes above threshold
```

### Advanced Configuration with Minute-level Gating

```yaml
sip:
  selector:
    type: hmm_sip
    params:
      top_k: 40
      score_floor: 0.5            # Filter out low-score symbols
      enable_gold_fallback: true
      p_hat_threshold: 0.7       # Only symbols with p_hat >= 0.7
      min_minutes_in_state: 5    # Must stay above threshold for 5+ minutes
```

## External File Structure

### Premarket Top-K Files
```
~/hybrid-local/signals/sip/universe/pre/
├── 2024-01-03_pre.parquet    # Daily premarket Top-K
├── 2024-01-04_pre.parquet
└── ...
```

**Schema:**
```python
{
    "sym": "AAPL",      # Symbol (string)
    "score": 0.85,      # HMM score (float)
    "rank": 1          # Optional rank (int)
}
```

### Minute-level p̂ Files (Optional)
```
~/hybrid-local/signals/sip/1m/
├── AAPL/
│   └── 2024/
│       ├── 2024-01.parquet
│       └── 2024-02.parquet
├── GOOGL/
│   └── 2024/
│       └── 2024-01.parquet
└── ...
```

**Schema:**
```python
{
    "ts": 1704303000000000000,  # UTC nanosecond timestamp (int64)
    "p_hat": 0.82               # Probability (float)
}
```

## Gold Fallback Algorithm

When external HMM files are unavailable, the selector computes a Gold-only premarket shortlist:

1. **Premarket window**: 04:00-09:29 ET
2. **Gap calculation**: `(open - prev_close) / prev_close`
3. **Volume metric**: Premarket dollar volume
4. **Scoring**: `0.6 * z(pre_rvol) + 0.4 * z(|gap_pct|)`
5. **Ranking**: Sort by score desc, symbol asc (deterministic ties)

## Performance Characteristics

| Operation | 1000 symbols | Description |
|-----------|--------------|-------------|
| External file load | ~0.2s | With LRU caching |
| Gold fallback | ~0.7s | Vectorized calculations |
| Minute-level gating | ~0.3s | With p̂ file caching |
| Total selector runtime | < 1s | Well under 30s requirement |

## Output Format

The selector returns `Dict[int_ts_ns, Set[str]]` mapping each RTH timestamp to eligible symbols:

```python
{
    1704303000000000000: {"AAPL", "GOOGL"},  # 9:30 AM ET
    1704303060000000000: {"AAPL", "GOOGL"},  # 9:31 AM ET
    1704303120000000000: {"AAPL"},           # 9:32 AM ET (filtered by p̂)
    ...
}
```

## Integration with QuantStack

### A/B Testing

Create overlay configurations to compare legacy vs HMM SIP:

**Legacy SIP (`sip_legacy.yaml`):**
```yaml
sip:
  selector:
    type: legacy
```

**HMM SIP (`sip_hmmsip_top40.yaml`):**
```yaml
sip:
  selector:
    type: hmm_sip
    params:
      top_k: 40
      p_hat_threshold: 0.6
```

### Run Commands

```bash
# One-day A/B test
python -m qx_cli exp entry-ab \
  --cfg experiments/vwap_revert/strategy.yaml \
  --variants experiments/vwap_revert/overlays/sip_legacy.yaml,experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml \
  --name vwap_hmmsip_ab_2024_01_03

# Two-week pilot
python -m qx_cli exp entry-ab \
  --cfg experiments/vwap_revert/strategy.yaml \
  --variants experiments/vwap_revert/overlays/sip_legacy.yaml,experiments/vwap_revert/overlays/sip_hmmsip_top40.yaml \
  --name vwap_hmmsip_ab_2w

# Compare results
python -m qx_cli exp compare --exp experiments/vwap_hmmsip_ab_2024_01_03
```

## Determinism Guarantees

- **Stable hashing**: Same inputs → same `sip_hash`
- **Timezone safety**: UTC timestamps preserved, ET used only for slicing
- **Tie resolution**: Secondary sort by symbol name (ascending)
- **Reproducible**: Fixed seeds and deterministic algorithms

## Troubleshooting

### No Trades Generated
1. Check `risk_rejects.parquet` before blaming selector
2. Verify `sip_hash` appears in `inputs_checksum.json`
3. Confirm external files exist in expected locations
4. Check timezone alignment (UTC vs ET)

### Performance Issues
1. Verify cache hit/miss logs
2. Check for excessive symbol count (> 10,000)
3. Monitor I/O bottlenecks on external file reads

### Missing p̂ Gating
1. Confirm `p_hat_threshold` is set (not null)
2. Verify p̂ file structure matches expected schema
3. Check timestamp alignment between bars and p̂ data

## License and Support

This module is part of the QuantStack trading system. See project-level documentation for licensing and support information.