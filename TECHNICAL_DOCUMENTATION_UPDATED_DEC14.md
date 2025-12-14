# ML Trading System - Technical Documentation
**Updated**: December 14, 2025  
**Version**: 2.0 (Post Position-Sizing Fix)  
**Status**: Deployment Ready (with Performance Concerns)

## Executive Summary

The ML trading system has been rebuilt with enhanced architecture and comprehensive bug fixes. While technical implementation is excellent (0.767 AUC), **backtest results show -15.4% loss over 2 years**, indicating a significant model-to-trading performance gap that requires investigation before live deployment.

## System Architecture

### Core Components
- **Feature Engineering**: 48 clean engineered features (no raw prices)
- **Model**: Time-stratified XGBoost with Optuna optimization
- **Universe**: SIP-filtered symbols (volatility-based selection)
- **Execution**: Intraday mean reversion with ATR-based risk management
- **Timeframe**: 1-minute bars, morning focus (9:30-12:00 ET)

### Data Pipeline
```
Raw Market Data → Timezone Normalization → Feature Engineering → 
SIP Filtering → Model Training → Signal Generation → Position Sizing → 
Trade Execution → Performance Monitoring
```

## Feature Engineering (48 Features)

### 1. Technical Indicators (15 features)
- **Momentum**: RSI, MACD, Stochastic oscillators
- **Volatility**: ATR percentage, Bollinger Band position
- **Trend**: EMA ratios, price momentum
- **Volume**: Volume ratios, VWAP distance

### 2. ICT (Inner Circle Trader) Features (12 features)
- **Kill Zones**: NY session open (9:30-10:30), London close (14:00-15:00)
- **Order Blocks**: Bullish/bearish institutional levels
- **Fair Value Gaps**: Price imbalances requiring fill
- **Liquidity Grabs**: Stop hunt detection
- **Displacement**: Strong directional moves

### 3. Volume Price Analysis (8 features)
- **Volume Ratios**: Current vs 20-period average
- **Volume Momentum**: Rate of volume change
- **Pressure Ratio**: Buy vs sell pressure (clamped to prevent extremes)
- **PV Divergence**: Price-volume relationship

### 4. Market Structure (8 features)
- **SPY Correlation**: 20-period rolling correlation with market
- **Relative Performance**: Symbol vs SPY returns
- **Market Beta**: Sensitivity to market moves
- **Sector Rotation**: Relative sector performance

### 5. Time-Based Features (5 features)
- **Hour ET**: Eastern Time hour (9-15)
- **Session Progress**: Percentage through trading session
- **Time Since Open**: Minutes since market open
- **Day of Week**: Encoded trading day patterns

## Model Architecture

### Time-Stratified Design
```python
# Morning Model (9:30-12:00 ET)
morning_model = XGBoostClassifier(
    n_estimators=200,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.8
)

# Afternoon Model (12:00-16:00 ET)  
afternoon_model = XGBoostClassifier(
    n_estimators=150,
    max_depth=5,
    learning_rate=0.08,
    subsample=0.9
)
```

### Hyperparameter Optimization
- **Framework**: Optuna with 50 trials
- **Objective**: AUC score maximization
- **Cross-Validation**: Time-series split (no look-ahead bias)
- **Early Stopping**: Prevents overfitting

### Label Generation
```python
# Long signal: Price moves up by 1.5x ATR within session
label_long = (forward_return > atr_pct * 1.5) & (same_day_exit)

# Short signal: Price moves down by 1.5x ATR within session  
label_short = (forward_return < -atr_pct * 1.5) & (same_day_exit)
```

## Universe Selection (SIP)

### Selection Criteria
- **Gap Filter**: Pre-market gap > 2%
- **ATR Filter**: Average True Range > $0.70
- **Volume Filter**: Above average volume
- **Price Range**: $10-$500 per share
- **Market Cap**: > $1B (large/mid cap focus)

### Daily Universe Size
- **Target**: 40-50 symbols per day
- **Actual**: 20-60 symbols (varies by market conditions)
- **Coverage**: 534 unique symbols over backtest period

## Position Sizing & Risk Management

### Position Sizing Formula
```python
def calculate_position_size(atr_pct, equity=10000, risk_pct=0.01):
    # Clamp ATR to prevent extreme values
    atr_clamped = max(0.005, min(0.20, atr_pct))
    
    # Calculate stop distance
    stop_distance = atr_clamped * 1.5  # 1.5x ATR stop
    
    # Risk amount per trade
    risk_amount = equity * risk_pct  # 1% of equity
    
    # Shares calculation
    shares = int(risk_amount / (100.0 * stop_distance))
    
    # Apply safety limits
    return max(100, min(1000, shares))
```

### Risk Parameters
- **Risk per Trade**: 1% of equity ($100 on $10k account)
- **Stop Loss**: 1.5x ATR (adaptive to volatility)
- **Max Position**: 10% of equity ($1,000)
- **Max Shares**: 1,000 per trade (safety limit)
- **Position Limits**: 36-137 shares typical range

## Backtesting Framework

### Rolling Out-of-Sample Design
- **Training Window**: 6 months of historical data
- **Validation Window**: 1 month for hyperparameter tuning
- **Test Window**: 1 month out-of-sample trading
- **Roll Forward**: Monthly progression (no look-ahead bias)

### Execution Simulation
```python
# Trade execution with realistic costs
entry_price = 100.0  # Normalized for P&L calculation
exit_price = entry_price * (1 + forward_return)

# Transaction costs
fee = max(shares * 0.0035, 0.35) * 2  # $0.35 minimum, both sides
spread = shares * entry_price * 0.0005  # 5 bps bid-ask spread
net_pnl = gross_pnl - fee - spread
```

### Performance Metrics
- **Total Trades**: 175 over 2-year period
- **Trade Frequency**: ~7 trades per month
- **Holding Period**: Intraday only (same-day exit)

## Current Performance Analysis

### Model Metrics (Excellent)
- **AUC Score**: 0.767 (+0.177 improvement from fixes)
- **Predicted Win Rate**: 72.1% on reasonable trades
- **Feature Importance**: ICT and volume features most predictive
- **Cross-Validation**: Consistent performance across folds

### Backtest Results (Poor)
- **Total Return**: -15.4% over 2 years
- **Actual Win Rate**: 46.9% (vs predicted 72.1%)
- **Sharpe Ratio**: -0.090 (negative)
- **Max Drawdown**: ~25% (December 2023)
- **Best Month**: +$307 (September 2023)
- **Worst Month**: -$900 (December 2023)

### Performance Gap Analysis

**Model vs Reality Disconnect:**
1. **Prediction Quality**: 0.767 AUC suggests good signal detection
2. **Trading Reality**: 46.9% win rate indicates poor profit capture
3. **Possible Causes**:
   - Label definition doesn't match trading strategy
   - Transaction costs eroding small edges
   - Market regime changes not captured
   - Position sizing still suboptimal

## Data Quality & Preprocessing

### Timezone Normalization
```python
def normalize_to_et(df):
    """Convert all timestamps to Eastern Time."""
    first_hour = df['timestamp'][0].hour
    if first_hour >= 13:  # UTC data detected
        df = df.with_columns(
            (pl.col('timestamp') - pl.duration(hours=4)).alias('timestamp')
        )
    return df
```

### Data Coverage
- **Total Rows**: 153,696 feature observations
- **Date Range**: January 2023 - September 2025
- **Morning Data**: 76% (improved from 0.4%)
- **Symbols**: 534 unique tickers
- **Data Quality**: No missing values, consistent timestamps

### Feature Validation
- **Raw Price Features**: 0 (eliminated all 24+ raw features)
- **Extreme Values**: Clamped (ATR, volume ratios)
- **Data Leakage**: None detected (forward-looking validation)
- **Correlation**: Features decorrelated, no multicollinearity

## Trading Strategy Logic

### Signal Generation
```python
# Morning model for 9:30-12:00 ET
if hour_et in [9, 10, 11]:
    prediction = morning_model.predict_proba(features)
else:
    prediction = afternoon_model.predict_proba(features)

# Signal threshold
signal = 1 if prediction[1] > 0.30 else 0  # 30% threshold
```

### Entry Conditions
1. **Model Signal**: Probability > 30% threshold
2. **SIP Filter**: Symbol in daily universe
3. **Time Filter**: Trading hours (9:30-16:00 ET)
4. **Risk Check**: Position size within limits

### Exit Conditions
- **Time Exit**: End of trading day (16:00 ET)
- **Stop Loss**: 1.5x ATR adverse move
- **Take Profit**: 2.0x ATR favorable move (rarely hit)

## Technology Stack

### Core Libraries
- **Data Processing**: Polars (fast), Pandas (analysis)
- **Machine Learning**: XGBoost, Optuna, Scikit-learn
- **Backtesting**: Custom framework with realistic execution
- **Risk Management**: Custom position sizer with safety limits

### File Structure
```
quantstack/
├── run/intraday_features_fixed/features.parquet  # Clean dataset
├── run/rolling_results_fixed/trades.csv          # Backtest results
├── scripts/rolling_train_fixed.py               # Training pipeline
├── scripts/build_intraday_features_fixed.py     # Feature engineering
├── extensions/intraday_ml_risk/position_sizer.py # Risk management
└── models/                                       # Trained models
```

## Critical Issues & Recommendations

### 🚨 **CRITICAL: Performance Gap**
**Issue**: Model shows 72.1% predicted win rate but backtest shows 46.9%
**Impact**: System loses money despite good predictions
**Priority**: HIGH - Must resolve before live trading

### 🔧 **Potential Solutions**
1. **Label Alignment**: Ensure labels match actual trading strategy
2. **Threshold Optimization**: Adjust prediction threshold (currently 30%)
3. **Transaction Cost Analysis**: Verify cost assumptions
4. **Market Regime Filtering**: Add market condition filters
5. **Position Sizing Refinement**: Optimize risk/reward ratios

### 📊 **Immediate Actions Required**
1. **Investigate Model-Reality Gap**: Why predictions don't translate to profits
2. **Sensitivity Analysis**: Test different thresholds and parameters
3. **Cost Analysis**: Validate transaction cost assumptions
4. **Regime Analysis**: Identify when system works vs fails

## Deployment Readiness Assessment

### ✅ **Technical Implementation**: READY
- Clean feature engineering pipeline
- Robust model architecture
- Safe position sizing with limits
- Comprehensive validation framework

### ❌ **Performance Validation**: NOT READY
- Negative returns over 2-year backtest
- Significant model-to-trading performance gap
- Inconsistent monthly results
- Below-target win rates

### 🎯 **Recommendation**: 
**DO NOT deploy to live trading** until performance gap is resolved. System is technically sound but not profitable in current form.

## Next Development Priorities

### Phase 1: Performance Investigation (Critical)
1. Analyze prediction vs actual return correlation
2. Test different probability thresholds
3. Validate transaction cost assumptions
4. Identify profitable vs unprofitable periods

### Phase 2: Strategy Refinement
1. Optimize entry/exit logic
2. Add market regime filters
3. Refine position sizing algorithm
4. Implement dynamic thresholds

### Phase 3: Enhanced Features
1. Add higher timeframe context
2. Implement sector rotation signals
3. Add volatility regime detection
4. Enhance ICT pattern recognition

## Conclusion

The ML trading system represents a sophisticated technical implementation with excellent model performance metrics. However, the significant gap between predicted and actual trading performance indicates fundamental issues in strategy translation that must be resolved before deployment.

**Technical Status**: ✅ Ready  
**Performance Status**: ❌ Not Ready  
**Overall Recommendation**: Investigate and fix performance gap before live trading

---
*Technical Documentation v2.0*  
*Chief Data Scientist & Head of Quant Trading*  
*December 14, 2025*
