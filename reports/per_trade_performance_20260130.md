# Per-Trade Performance - January 30, 2026
## Intraday Paper Trading (Corrected with Actual Fill Prices)

---

## Trade #1: HL Long @ 10:38:52 ET
```
Signal Entry:    $24.135
Actual Entry:    $24.420  (slippage: +$0.285, +1.18%)
Actual Exit:     $24.430  (TARGET)
Quantity:        100 shares
Gross P&L:       +$1.00
Net P&L:         +$1.00  ✅ WIN
Hold Time:       ~10 seconds
```
**Analysis:** Target hit quickly despite poor entry slippage. Only trade with correct fill recording in database.

---

## Trade #2: SLV Long @ 10:38:54 ET
```
Signal Entry:    $89.56
Actual Entry:    $90.46   (slippage: +$0.90, +1.00%)
Actual Exit:     $90.48   (TARGET)
Quantity:        100 shares
Gross P&L:       +$2.00
Net P&L:         +$2.00  ✅ WIN
Hold Time:       ~34 seconds
```
**Analysis:** Large entry slippage but still hit target. Database incorrectly shows EMERGENCY_EOD closure.

---

## Trade #3: HL Long @ 10:39:55 ET
```
Signal Entry:    $24.135
Actual Entry:    $24.410  (slippage: +$0.275, +1.14%)
Actual Exit:     $24.430  (TARGET)
Quantity:        100 shares
Gross P&L:       +$2.00
Net P&L:         +$2.00  ✅ WIN
Hold Time:       ~6 seconds
```
**Analysis:** Second HL entry, similar slippage pattern. Quick target hit. Database shows EMERGENCY_EOD (incorrect).

---

## Trade #4: SLV Long @ 10:40:56 ET
```
Signal Entry:    $89.56
Actual Entry:    $90.80   (slippage: +$1.24, +1.38%)
Actual Exit:     $90.78   (TARGET)
Quantity:        100 shares
Gross P&L:       -$2.00
Net P&L:         -$2.00  ❌ LOSS
Hold Time:       ~0 seconds (immediate reversal)
```
**Analysis:** Worst slippage of the day. Entry so poor that immediate target hit resulted in loss. Database shows +$122 profit (phantom gain from using signal price).

---

## Trade #5: VZ Short @ 10:40:58 ET
```
Signal Entry:    $42.73
Actual Entry:    $43.25   (slippage: -$0.52, +1.22% worse for short)
Actual Exit:     $43.28   (STOP)
Quantity:        100 shares
Gross P&L:       -$3.00
Net P&L:         -$3.00  ❌ LOSS
Hold Time:       ~1 second
```
**Analysis:** Poor short entry (filled above signal), stop hit immediately. Database shows EMERGENCY_EOD (incorrect).

---

## Summary Statistics

### P&L Breakdown
| Metric | Value |
|--------|-------|
| Total Trades | 5 |
| Winning Trades | 3 (60%) |
| Losing Trades | 2 (40%) |
| **Total P&L** | **$0.00** |
| Avg Win | +$1.67 |
| Avg Loss | -$2.50 |
| Largest Win | +$2.00 |
| Largest Loss | -$3.00 |
| Win Rate | 60% |

### Exit Analysis
| Exit Type | Count | % |
|-----------|-------|---|
| TARGET | 4 | 80% |
| STOP | 1 | 20% |
| EMERGENCY_EOD | 0 | 0% |

### Slippage Analysis
| Trade | Symbol | Direction | Slippage | % |
|-------|--------|-----------|----------|---|
| 1 | HL | Long | +$0.285 | +1.18% |
| 2 | SLV | Long | +$0.900 | +1.00% |
| 3 | HL | Long | +$0.275 | +1.14% |
| 4 | SLV | Long | +$1.240 | +1.38% |
| 5 | VZ | Short | -$0.520 | +1.22% |
| **Avg** | | | **$0.644** | **+1.18%** |

---

## Key Insights

### 1. Strategy Performance
- **4 out of 5 targets hit** (80% target rate)
- **Only 1 stop hit** (20% stop rate)
- Strategy logic working as intended

### 2. Execution Quality
- **Average slippage: +$0.644 per trade** (1.18%)
- **All entries worse than signal** (100% negative slippage)
- **Worst case: SLV +$1.24** (1.38%) - turned win into loss
- Market orders in paper trading getting poor fills

### 3. Net Result
- **Breakeven day: $0.00 P&L**
- Slippage ate all potential profits
- Without slippage: Would be +$3.22 profit

### 4. Data Quality Issues
- **80% of fills not recorded** (4/5 orders)
- **Database shows +$122** (phantom profit from bad data)
- **3 trades show EMERGENCY_EOD** (actually hit targets)
- Fill communication bug now fixed

### 5. Hold Times
- **Extremely short holds** (0-34 seconds)
- Targets very close to entry (tight profit targets)
- Slippage represents 50-100% of target distance

---

## Recommendations

### Immediate
1. ✅ Fix fill recording (implemented)
2. Monitor slippage on next trading day
3. Consider limit orders instead of market orders

### Strategy Adjustments
1. **Widen targets** - Current targets too tight for market order slippage
2. **Add slippage buffer** - Account for 1-1.5% entry slippage in signal logic
3. **Review entry timing** - Entries happening at unfavorable prices

### Execution Improvements
1. Use limit orders at signal price + small buffer
2. Add fill price validation (reject if slippage > threshold)
3. Monitor paper trading fill quality vs live

---

## Comparison: Database vs Actual

| Metric | Database (Wrong) | Actual (Corrected) |
|--------|------------------|-------------------|
| Net P&L | +$122.00 | $0.00 |
| Win Rate | 11.1% | 60% |
| Targets Hit | 0 | 4 |
| Stops Hit | 0 | 1 |
| Emergency EOD | 8 | 0 |
| Avg Slippage | $0.00 | +$0.644 |

The database showed a profitable day due to recording signal prices instead of actual fills. The reality is a breakeven day with good strategy performance but poor execution quality.
