# Parameter Tuning Results - December 12, 2025

## Executive Summary

Tested **24 parameter combinations** on limited period (Jul-Sep 2025). **All configurations lost money**, indicating fundamental model issues rather than parameter problems.

## Test Configuration

- **Period**: July 1 - September 30, 2025 (3 months)
- **Data**: 74,786 rows
- **Parameters Tested**:
  - Thresholds: 0.30, 0.35, 0.40, 0.45
  - ATR Multipliers: 1.0, 1.2, 1.5
  - Hour Filters: Morning (9-11), All hours (9-15)

## Results Summary

| Metric | Best | Worst | Average |
|--------|------|-------|---------|
| **Win Rate** | 46.9% | 37.3% | 42.1% |
| **PnL** | -$2,108 | -$19,199 | -$7,234 |
| **Trades** | 49 | 329 | 125 |
| **Symbols** | 20 | 70 | 37 |

## Top 3 Configurations

| Rank | Threshold | ATR Mult | Win Rate | PnL | Trades |
|------|-----------|----------|----------|-----|--------|
| 1 | 0.45 | 1.5 | **46.9%** | -$2,108 | 49 |
| 2 | 0.30 | 1.2 | 45.6% | -$8,273 | 195 |
| 3 | 0.35 | 1.2 | 44.9% | -$6,342 | 138 |

## Key Findings

### ❌ **Critical Issues Identified**

1. **All Configurations Lose Money**
   - Best PnL: -$2,108 (still negative)
   - Worst PnL: -$19,199
   - No profitable configuration found

2. **Win Rates Below Breakeven**
   - Best: 46.9% (need >50% for profitability)
   - All configurations <47%
   - Systematic underperformance

3. **Hour Filtering Ineffective**
   - Morning vs all hours: identical results
   - No time-of-day edge detected
   - Suggests model issues, not timing

### 📊 **Parameter Sensitivity**

- **Lower thresholds** → More trades, worse performance
- **Higher ATR multipliers** → Fewer trades, better win rates
- **Hour filtering** → No impact on performance

## Root Cause Analysis

### The Problem is NOT Parameters
The fact that **all 24 configurations lose money** indicates:

1. **Model Quality Issues**
   - Features may not be predictive
   - Labels may be poorly defined
   - Training data may have issues

2. **Systematic Bias**
   - Models consistently wrong direction
   - Cost structure too high
   - Market regime mismatch

3. **Feature Engineering Problems**
   - ATR-normalized labels may be too strict
   - Relative features may have lost signal
   - Time features may not capture regime

## Recommended Next Steps

### 🔧 **Immediate Actions**

1. **Validate Model Quality**
   ```python
   # Check AUC scores - should be >0.6
   # Check feature importance
   # Validate label distribution
   ```

2. **Test Simpler Approach**
   - Use original fixed 1.5% labels
   - Test on known profitable period (Aug 2023)
   - Verify basic profitability

3. **Debug Feature Engineering**
   - Compare improved vs original features
   - Check if relative features lost signal
   - Validate ATR calculations

### 📈 **Medium Term**

4. **Model Diagnostics**
   - Feature importance analysis
   - Prediction distribution analysis
   - Cross-validation on known good periods

5. **Alternative Approaches**
   - Test LONG-only strategy
   - Try different label definitions
   - Consider ensemble methods

## Conclusion

**Parameter tuning revealed the real issue**: The improved system has fundamental model quality problems, not parameter problems.

**Next Priority**: Fix model quality before optimizing parameters.

**Action Plan**:
1. Validate model on known profitable period
2. Debug feature engineering changes
3. Compare improved vs original system on same data
4. Fix model quality issues
5. Then retry parameter optimization

---

**Status**: ⚠️ **Model Quality Issues Identified**
**Recommendation**: Fix fundamentals before parameter tuning
**Files**: `run/parameter_tuning_results.csv` (24 configurations tested)
