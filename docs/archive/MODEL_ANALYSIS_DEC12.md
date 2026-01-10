# Model Setup Analysis & Enhancement Recommendations
## December 12, 2025

## Executive Summary

The current ML trading system has weak predictive power (AUC ~0.59) due to:
1. Poor feature quality (max correlation 0.06)
2. Single model architecture without tuning
3. Suboptimal label definition (5-bar exit too short)
4. No multi-timeframe or market context features

This report provides a comprehensive analysis and actionable recommendations.

---

## Current System Analysis

### 1. Feature Set (35 features)

| Category | Count | Features | Assessment |
|----------|-------|----------|------------|
| Returns/Momentum | 6 | ret_1m, returns, returns_5, returns_10 | OK |
| Volume/VPA | 4 | volume_ratio, pressure_ratio | Weak correlations |
| Volatility/ATR | 5 | volatility_5, atr_pct, range_pct | OK |
| ICT | 8 | order_block, displacement, bos, killzone | **NOT PREDICTIVE** |
| Time | 3 | is_morning, time_since_open | OK |
| Candle | 5 | body_pct, wick_pct, is_bullish | Weak |
| Other | 4 | close, vwap_session, atr | **RAW PRICES** |

**Critical Issues:**
- Maximum feature correlation with labels: **0.06** (extremely weak)
- ICT features show near-zero predictive power
- Raw price features still present (close, vwap_session, atr)
- No multi-timeframe features
- No market context features

### 2. Model Architecture

**Current:** Single LightGBM classifier

**Hyperparameters:**
```python
params = {
    "num_leaves": 31,        # Default, may be too simple
    "learning_rate": 0.05,   # Reasonable
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "min_data_in_leaf": 20,
    "lambda_l1": 0.1,
    "lambda_l2": 0.1,
    "num_boost_round": 300,
    "early_stopping": 30
}
```

**Issues:**
- No hyperparameter tuning
- No ensemble approach
- No feature selection
- Single model for complex market dynamics

### 3. Label Definition

**Current:**
- Threshold: 1.5x ATR
- Exit: 5 bars (5 minutes)
- Label rate: ~10% for both LONG and SHORT

**Issues:**
- 5-bar exit too short for meaningful moves
- No stop-loss/take-profit in label definition
- Binary classification loses magnitude information

### 4. Roll-Forward Method

**Current:**
- Training: 6 months
- Validation: 1 month
- OOS: 1 month
- Time stratification: Morning vs Afternoon

**Issues:**
- 6-month training may include stale patterns
- No regime detection
- No adaptive training window
- No purging/embargo for time series

### 5. Model Performance

| Metric | Value | Assessment |
|--------|-------|------------|
| Morning AUC Long | 0.592 | Weak |
| Morning AUC Short | 0.603 | Weak |
| Afternoon AUC Long | 0.423 | Worse than random |
| Afternoon AUC Short | 0.457 | Worse than random |
| AUC Trend | 0.599 → 0.585 | Slight degradation |

---

## Enhancement Recommendations

### Priority 1: Feature Engineering Overhaul (Highest Impact)

#### 1.1 Multi-Timeframe Features (Critical)
```python
# 5-minute aggregates
returns_5m = close.resample('5T').last().pct_change()
volatility_5m = returns_1m.rolling(5).std()
volume_ratio_5m = volume_5m / volume_5m.rolling(20).mean()

# 15-minute aggregates
returns_15m = close.resample('15T').last().pct_change()
trend_15m = (close_15m > close_15m.shift(1)).astype(int)

# Cross-timeframe divergence
momentum_divergence = returns_1m.sign() != returns_5m.sign()
```

#### 1.2 Session Context Features (High)
```python
# Gap analysis
gap_pct = (session_open - prev_session_close) / prev_session_close
gap_fill_pct = (session_high - session_open) / (session_open - prev_session_close)

# Range analysis
session_range_pct = (session_high - session_low) / session_open
distance_to_high = (session_high - close) / close
distance_to_low = (close - session_low) / close
```

#### 1.3 Improved ICT Features (High)
```python
# Multi-bar FVG (not single bar)
fvg_bullish = (low.shift(-1) > high.shift(1))  # Gap between bars
fvg_size = (low.shift(-1) - high.shift(1)) / close
fvg_unfilled = fvg_bullish & (close < low.shift(-1))

# Order block with volume confirmation
ob_bullish = (is_bearish.shift(1)) & (displacement_up) & (volume > volume_ma * 1.5)

# Liquidity sweep with rejection
sweep_high = (high > high_5.shift(1)) & (close < high_5.shift(1)) & (lower_wick > body)
```

#### 1.4 Enhanced VPA Features (Medium)
```python
# Cumulative volume delta
cum_delta = (up_volume - down_volume).cumsum()
delta_divergence = (cum_delta.diff() > 0) != (close.diff() > 0)

# Volume profile approximation
volume_at_price = volume.groupby(price_bucket).sum()
poc_distance = (close - poc) / close
```

#### 1.5 Features to Remove
- `close` (raw price)
- `vwap_session` (raw price)
- `atr` (raw price, keep `atr_pct`)

### Priority 2: Model Architecture

#### 2.1 Recommended: XGBoost + Optuna Tuning

```python
import xgboost as xgb
import optuna

def objective(trial):
    params = {
        'max_depth': trial.suggest_int('max_depth', 3, 10),
        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1),
        'n_estimators': trial.suggest_int('n_estimators', 100, 500),
        'min_child_weight': trial.suggest_int('min_child_weight', 1, 10),
        'subsample': trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample_bytree', 0.6, 1.0),
        'reg_alpha': trial.suggest_float('reg_alpha', 0, 1.0),
        'reg_lambda': trial.suggest_float('reg_lambda', 0, 1.0),
    }
    
    model = xgb.XGBClassifier(**params)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], early_stopping_rounds=30)
    return roc_auc_score(y_val, model.predict_proba(X_val)[:, 1])

study = optuna.create_study(direction='maximize')
study.optimize(objective, n_trials=100)
```

#### 2.2 Alternative: Ensemble Approach

```python
from sklearn.ensemble import VotingClassifier

ensemble = VotingClassifier(
    estimators=[
        ('xgb', XGBClassifier(**xgb_params)),
        ('lgb', LGBMClassifier(**lgb_params)),
        ('rf', RandomForestClassifier(**rf_params))
    ],
    voting='soft'
)
```

#### 2.3 Feature Selection with SHAP

```python
import shap

explainer = shap.TreeExplainer(model)
shap_values = explainer.shap_values(X_val)
importance = np.abs(shap_values).mean(axis=0)

# Keep top 20 features
top_features = feature_cols[np.argsort(importance)[-20:]]
```

### Priority 3: Label Definition

#### 3.1 Longer Exit Horizon
```python
# Test multiple horizons
for bars in [10, 15, 30, 60]:
    forward_return = close.shift(-bars) / close - 1
    label = (forward_return > threshold).astype(int)
```

#### 3.2 Regression Model
```python
# Predict return directly
model = XGBRegressor()
model.fit(X_train, y_train_return)

# Convert to trading signal
predictions = model.predict(X_test)
signals = np.where(predictions > threshold, 1, np.where(predictions < -threshold, -1, 0))
```

#### 3.3 Multi-Class Labels
```python
def create_multiclass_label(forward_return, atr_pct):
    if forward_return > 2 * atr_pct:
        return 2  # Strong Long
    elif forward_return > atr_pct:
        return 1  # Weak Long
    elif forward_return < -2 * atr_pct:
        return -2  # Strong Short
    elif forward_return < -atr_pct:
        return -1  # Weak Short
    else:
        return 0  # Neutral
```

### Priority 4: Roll-Forward Method

#### 4.1 Shorter Training Window
```python
TRAIN_MONTHS = 3  # Instead of 6
VAL_MONTHS = 1
OOS_MONTHS = 1
```

#### 4.2 Purging and Embargo
```python
def create_purged_splits(df, train_end, val_end, purge_bars=5):
    train = df[df.index < train_end - purge_bars]
    val = df[(df.index > train_end + purge_bars) & (df.index < val_end - purge_bars)]
    test = df[df.index > val_end + purge_bars]
    return train, val, test
```

#### 4.3 Regime Detection
```python
def detect_regime(df, lookback=20):
    volatility = df['returns'].rolling(lookback).std()
    vol_percentile = volatility.rank(pct=True)
    
    regime = np.where(vol_percentile > 0.7, 'high_vol',
                     np.where(vol_percentile < 0.3, 'low_vol', 'normal'))
    return regime
```

---

## Implementation Plan

### Phase 1: Feature Engineering (Week 1)
1. Add multi-timeframe features (5m, 15m aggregates)
2. Add session-level features (gap fill %, range expansion)
3. Improve ICT features (multi-bar patterns)
4. Remove raw price features
5. **Target: 50-60 high-quality features**

**Expected Impact:** AUC 0.59 → 0.65+

### Phase 2: Model Upgrade (Week 2)
1. Switch to XGBoost
2. Add Optuna hyperparameter tuning
3. Implement SHAP-based feature selection
4. Test ensemble approach

**Expected Impact:** AUC 0.65 → 0.70+

### Phase 3: Label Optimization (Week 3)
1. Test longer exit horizons (15-30 bars)
2. Implement regression model
3. Add stop-loss/take-profit in label definition

**Expected Impact:** Better alignment with actual trading

### Phase 4: Advanced Techniques (Week 4)
1. Add regime detection
2. Implement purging/embargo
3. Test LSTM for sequence patterns
4. Add market context features

**Expected Impact:** More robust across market conditions

---

## Expected Outcomes

### Current Performance
- AUC: 0.59
- Win Rate: 46.9%
- Total PnL: -$1,538

### Target Performance (After All Phases)
- AUC: 0.70+
- Win Rate: 55%+
- Positive expectancy
- Sharpe Ratio > 1.0

### Key Success Metrics
| Metric | Minimum | Target |
|--------|---------|--------|
| AUC | 0.65 | 0.70+ |
| Win Rate | 52% | 55%+ |
| Sharpe Ratio | 0.5 | 1.0+ |
| Max Drawdown | 25% | 15% |

---

## Recommended Model: XGBoost with Optuna

Based on research and the specific characteristics of this problem:

1. **XGBoost** often outperforms LightGBM on smaller datasets
2. **Optuna** provides efficient Bayesian hyperparameter optimization
3. **SHAP** enables interpretable feature selection
4. **Ensemble** approach provides robustness

The combination of better features + tuned XGBoost + proper validation should significantly improve predictive power.

---

*Analysis Date: December 12, 2025*
*Status: Ready for Implementation*
