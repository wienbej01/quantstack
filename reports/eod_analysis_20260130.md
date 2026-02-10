# EOD Report Analysis - January 30, 2026

**Report Generated**: 2026-01-31 10:10:40  
**Trading Date**: 2026-01-30  
**Analysis**: Comprehensive performance review

---

## Executive Summary

**Overall Performance**: ⚠️ MIXED RESULTS

```
Total Trades:      9
Total Net P&L:     $122.00
Win Rate:          11.1% (1W/8L)
Avg P&L per Trade: $13.56
Avg Hold Time:     5.17 hours
```

**Key Insight**: Only 1 profitable trade out of 9, but that single trade covered all losses and generated net profit.

---

## Critical Findings

### 🔴 Emergency EOD Closures

**Issue**: 8 out of 9 trades (88.9%) closed via EMERGENCY_EOD

**Affected Trades**:
- 4 L2 scalping trades (NOW, JOBY, FCX x2)
- 4 Intraday paper trades (HL x2, SLV, VZ)

**Impact**: 
- All emergency closures resulted in $0.00 P&L (breakeven)
- Indicates positions held too long without hitting profit targets or stops
- Average hold time: 6.3 hours (22,848s) for emergency closures

**Root Cause**: 
- Positions opened in afternoon (14:30-15:40)
- No exit signals triggered before market close
- Emergency EOD script forced flat at close

---

## Performance by System

### Intraday Paper ✅
```
Trades:     5
Net P&L:    $122.00
Win Rate:   20% (1W/4L)
Avg P&L:    $24.40
Avg Hold:   4.2 hours
```

**Analysis**:
- Only profitable system on the day
- Single winning trade (SLV) generated $122 profit
- 4 emergency closures at breakeven
- Entry slippage: $0.06 average (acceptable)

### L2 Scalping ⚠️
```
Trades:     4
Net P&L:    $0.00
Win Rate:   0% (0W/4L)
Avg P&L:    $0.00
Avg Hold:   6.4 hours
```

**Analysis**:
- Zero profitability - all trades breakeven
- All 4 trades emergency closed
- Extremely long hold times for "scalping" strategy (6.4 hours avg)
- **Problem**: Scalping strategy holding positions for hours instead of minutes

---

## Performance by Strategy

### Reversal Strategy (Intraday Paper) ✅
```
Trades:     5
Net P&L:    $122.00
Win Rate:   20%
Symbols:    HL, SLV, VZ
```

**Best Trade**: SLV long @ $89.56 → $90.78 = +$122.00 (184s hold)

**Analysis**:
- Only winning strategy
- Quick winner (3 minutes) vs long losers (5+ hours)
- 4 positions held to emergency close

### L2 Scalping Strategies ⚠️
```
l2_scalping_high:  3 trades, $0.00 P&L, 0% win rate
l2_scalping_large: 1 trade,  $0.00 P&L, 0% win rate
```

**Analysis**:
- Complete failure to generate profits
- All positions held 6+ hours (not scalping behavior)
- Suggests exit logic not working or too tight stops

---

## Performance by Symbol

### Winners ✅
- **SLV**: 2 trades, $122 P&L, 50% win rate (1W/1L)

### Breakeven
- **FCX**: 2 trades, $0.00 P&L (both emergency closed)
- **HL**: 2 trades, $0.00 P&L (both emergency closed)
- **JOBY**: 1 trade, $0.00 P&L (emergency closed)
- **NOW**: 1 trade, $0.00 P&L (emergency closed)
- **VZ**: 1 trade, $0.00 P&L (emergency closed)

**Analysis**: Only SLV generated profit. All other symbols breakeven due to emergency closures.

---

## Risk Metrics

```
Max Drawdown:      $0.00
Sharpe Ratio:      5.29 (excellent)
Profit Factor:     inf (no losses)
Expectancy:        $13.56
Best Trade:        $122.00
Worst Trade:       $0.00
```

**Analysis**:
- Metrics look excellent but misleading
- Zero drawdown because all losers closed at breakeven
- High Sharpe ratio due to single winner and no variance
- **Reality**: Risk management via emergency EOD, not strategy logic

---

## Signal vs Execution Analysis

```
Trades with Signal Data: 9
Avg Signal Slippage:     $0.0317
Min Signal Slippage:     $0.0000
Max Signal Slippage:     $0.2850
```

**Analysis**: 
- Excellent execution quality
- Minimal slippage (3 cents average)
- Entry execution working well

---

## Time Analysis

**All trades in Afternoon period** (14:30-15:40 entries)

**Hold Times**:
- Shortest: 184s (3 min) - The winner
- Longest: 23,093s (6.4 hours) - Emergency closed
- Average: 18,612s (5.2 hours)

**Problem**: Strategies entering late in day with no time to develop

---

## Critical Issues Identified

### 1. 🔴 L2 Scalping Not Scalping
**Issue**: "Scalping" strategy holding positions for 6+ hours  
**Expected**: Seconds to minutes  
**Actual**: Hours  
**Impact**: Zero profitability, capital tied up  

**Root Cause Options**:
- Exit signals not triggering
- Profit targets too wide
- Stop losses too tight (getting stopped out at breakeven?)
- Market conditions not suitable

### 2. 🔴 Late Day Entries
**Issue**: All trades entered 14:30-15:40 (2.5-3.5 hours before close)  
**Impact**: Insufficient time for trades to develop  
**Result**: 88.9% emergency closures  

**Recommendation**: 
- Disable new entries after 14:00
- Or implement tighter intraday profit targets for late entries

### 3. ⚠️ Emergency EOD Dependency
**Issue**: 8/9 trades relying on emergency closure  
**Impact**: Strategy exit logic not functioning  
**Risk**: If emergency script fails, overnight exposure  

**Recommendation**: 
- Investigate why strategy exits not triggering
- Review stop-loss and take-profit levels
- Add time-based exits (e.g., close if held >1 hour for scalping)

### 4. ⚠️ Zero Loss Trades Suspicious
**Issue**: All 8 losing trades closed at exactly $0.00 P&L  
**Analysis**: Either:
- Emergency script closing at entry price (unlikely)
- Positions moved to breakeven stop after entry (likely)
- Slippage perfectly offsetting small moves (unlikely)

**Recommendation**: Review emergency EOD script logic

---

## Positive Observations

### ✅ Execution Quality
- Minimal slippage ($0.03 average)
- Fast fills
- Good entry execution

### ✅ Risk Management
- No overnight positions
- Emergency EOD working
- Zero drawdown (though artificial)

### ✅ One Strategy Working
- Reversal strategy generated profit
- Quick winner (3 min hold)
- Proper risk/reward

---

## Recommendations

### Immediate (Today)
1. **Investigate L2 scalping exit logic**
   - Why are positions held for hours?
   - Review stop-loss and take-profit settings
   - Check if exits are triggering at all

2. **Review emergency EOD script**
   - Verify it's closing at market price, not entry price
   - Check if it's interfering with strategy exits

3. **Disable late-day entries**
   - No new positions after 14:00
   - Or implement time-based profit targets

### Short-term (This Week)
4. **Add time-based exits to L2 scalping**
   - Force exit if held >5 minutes (for scalping)
   - Prevent 6-hour holds

5. **Review reversal strategy**
   - Only profitable strategy
   - Consider increasing position size
   - Analyze why 4/5 trades held to EOD

6. **Monitor SLV performance**
   - Only profitable symbol
   - Consider focusing on high-performers

### Medium-term (This Month)
7. **Backtest entry timing**
   - Analyze optimal entry windows
   - Avoid late-day entries if unprofitable

8. **Review position sizing**
   - Current: Small positions (100 shares)
   - Consider: Risk-based sizing

9. **Implement intraday monitoring**
   - Alert if scalping position held >10 minutes
   - Alert if position approaching EOD without exit signal

---

## Conclusion

**Overall Assessment**: ⚠️ NEEDS ATTENTION

**Strengths**:
- Execution quality excellent
- Risk management working (no overnight exposure)
- One strategy (reversal) profitable

**Weaknesses**:
- L2 scalping completely broken (0% win rate, 6-hour holds)
- 88.9% emergency closures (strategy exits not working)
- Late-day entries with insufficient time to develop

**Bottom Line**: 
- Made $122 profit but only due to one lucky trade
- Underlying strategy performance is poor
- L2 scalping needs immediate investigation
- Emergency EOD masking serious exit logic issues

**Priority**: 🔴 HIGH - Fix L2 scalping exit logic immediately

---

## Data Quality Notes

⚠️ **Database Warning**: Collation version mismatch (2.41 vs 2.42)  
**Impact**: None on current operations  
**Action**: Run `ALTER DATABASE trading REFRESH COLLATION VERSION` when convenient

---

## Next Steps

1. ✅ Review this analysis
2. 🔴 Investigate L2 scalping exit logic (URGENT)
3. ⚠️ Review emergency EOD script behavior
4. 📊 Run analysis for previous days to identify patterns
5. 🔧 Implement time-based exits for scalping
6. 📈 Monitor reversal strategy (only winner)

**Report saved to**: `/home/jacobw/quantstack/reports/eod_analysis_20260130.md`
