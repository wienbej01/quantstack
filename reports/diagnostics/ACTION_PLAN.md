# Immediate Action Plan

## Summary
✅ **Models are strong** (Stage 1: 0.88 AUC, Stage 2: 0.93 AUC)  
⚠️ **Backtest has bugs** (negative Sharpe with positive PnL)  
🎯 **Optimal thresholds identified:** 0.75/0.70 for 3-5 trades/day

---

## Priority 1: Fix & Re-run (Today)

### A. Check Sweep Grid Configuration
```bash
cat configs/extensions/intraday_ml/policy_sweep_grid.yaml
```

**Expected issue:** Grid tests 0.15-0.45 thresholds (too low)  
**Fix:** Update to test 0.65-0.80 range

### B. Investigate Sharpe Calculation
```bash
# Find where Sharpe is calculated
grep -r "sharpe_ratio" extensions/intraday_ml/experiments/
```

**Likely bug:** Sign error or wrong volatility denominator  
**Symptom:** Negative Sharpe with positive PnL

### C. Re-run Sweep with Correct Range
```yaml
# configs/extensions/intraday_ml/policy_sweep_grid_v2.yaml
bigmove_policy.probability_threshold: [0.65, 0.70, 0.75, 0.80]
prob_threshold_long: [0.60, 0.65, 0.70, 0.75]
score_margin: [0.0, 0.01, 0.02]
max_open_positions_global: [2, 3, 5]
```

---

## Priority 2: Implement Ranking (Tomorrow)

### Current Problem
- System generates 6.8 signals/day at 0.75/0.70
- Need to pick best 3-5, not just first 3-5

### Solution: Expected Value Ranking
```python
# Add to BigMovePolicy
def rank_signals(self, signals_df):
    """Rank signals by expected value."""
    signals_df['edge'] = (signals_df['prob_bigmove_long'] - 0.5) * 2
    signals_df['volatility'] = signals_df['f__vol__atr_6'] / signals_df['close']
    signals_df['expected_value'] = signals_df['edge'] / signals_df['volatility']
    
    # Penalize if symbol already traded today
    signals_df['score'] = signals_df['expected_value'] * (
        0.5 if symbol_traded_today else 1.0
    )
    
    return signals_df.nlargest(5, 'score')
```

---

## Priority 3: Add Cost Model (Tomorrow)

### Current State
- No commission modeled
- No slippage modeled
- PnL unrealistic for small account

### Add to Backtest
```python
# Per-trade costs
COMMISSION_PER_SIDE = 1.00  # $1 per trade
SLIPPAGE_BPS = 4.0  # 4 basis points

# Adjust fill prices
fill_price_buy = market_price * (1 + SLIPPAGE_BPS / 10000)
fill_price_sell = market_price * (1 - SLIPPAGE_BPS / 10000)

# Deduct commissions
pnl_net = pnl_gross - (COMMISSION_PER_SIDE * 2)
```

---

## Priority 4: Validation Tests (Day 3)

### A. Walk-Forward Test
- Retrain monthly on expanding window
- Test on next month
- Measure performance decay

### B. Stress Tests
```python
# Test scenarios
scenarios = [
    "high_vol_regime",  # VIX > 25
    "low_vol_regime",   # VIX < 15
    "trending_market",  # SPY up 5 days
    "choppy_market",    # SPY range-bound
]
```

### C. Symbol Concentration
```python
# Check if overtrading same symbols
symbol_counts = trades.groupby('symbol').size()
top_5_pct = symbol_counts.nlargest(5).sum() / symbol_counts.sum()

if top_5_pct > 0.40:
    print("⚠️ Too concentrated in top 5 symbols")
```

---

## Quick Wins (Can Do Now)

### 1. Create Enhanced Config
```bash
cp configs/extensions/intraday_ml/policy_config_bigmove.json \
   configs/extensions/intraday_ml/policy_config_bigmove_selective.json
```

Edit thresholds:
```json
{
  "bigmove_policy": {
    "probability_threshold": 0.75,
    "prob_threshold_long": 0.70,
    "prob_threshold_short": 0.70,
    "max_trades_per_day": 5
  }
}
```

### 2. Document Current State
```bash
# Save all diagnostic outputs
tar -czf reports/diagnostics_2025-12-04.tar.gz reports/diagnostics/
```

### 3. Check Rejection Reasons
```python
# Why are signals being rejected?
import pandas as pd
df = pd.read_csv('artefacts/extensions/intraday_ml/policy_sweeps/bigmove_frontier.csv')
print(df['rejection_counts'].iloc[0])
```

---

## Success Criteria (After Fixes)

### Minimum Viable
- [ ] Sharpe > 1.0 (after costs)
- [ ] Win Rate > 45%
- [ ] 3-5 trades/day average
- [ ] Max Drawdown < 15%

### Target Performance
- [ ] Sharpe > 1.5
- [ ] Win Rate > 50%
- [ ] Profit Factor > 1.8
- [ ] Avg R-multiple > 1.5

### Red Flags
- [ ] Sharpe < 0.8 → Major revision needed
- [ ] Win Rate < 40% → Directional model failing
- [ ] Trades < 2/day → Thresholds too tight
- [ ] Trades > 10/day → Thresholds too loose

---

## Timeline

**Today (Dec 4):**
- [x] Complete diagnostics
- [ ] Fix Sharpe calculation
- [ ] Update sweep grid
- [ ] Re-run sweep

**Tomorrow (Dec 5):**
- [ ] Implement ranking mechanism
- [ ] Add cost model
- [ ] Test with 0.75/0.70 thresholds

**Day 3 (Dec 6):**
- [ ] Walk-forward validation
- [ ] Stress tests
- [ ] Final decision: Paper trade or iterate?

---

## Files to Review

1. `extensions/intraday_ml/experiments/policy_sweep.py` - Sharpe calculation
2. `configs/extensions/intraday_ml/policy_sweep_grid.yaml` - Threshold ranges
3. `extensions/intraday_ml/policy/bigmove_policy_adapter.py` - Add ranking
4. `qx-backtest/` - Add commission/slippage

---

**Bottom Line:** Models are good. Fix backtest bugs, re-run with correct thresholds, add ranking. Should be ready for paper trading by end of week.
