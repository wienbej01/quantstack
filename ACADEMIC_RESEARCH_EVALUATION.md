# Academic Research Evaluation: ML Features for Intraday Trading
## December 14, 2025

---

## 1. KEY ACADEMIC FINDINGS

### A. Intraday Market Predictability (ResearchGate, 2020)

**Key Paper**: "Intraday market predictability: A machine learning approach"

**Findings**:
- Out-of-sample R² of **0.24%** from 2001-2016 (very small but significant)
- **Best models**: Lasso, Elastic Net, Random Forest
- **Best predictors**: Cross-section of lagged constituent returns (not just market returns)
- Predictability is **inverse-U shaped** throughout the day (lowest at open/close)
- Predictability **increases** during high volatility and illiquidity periods
- After transaction costs, Sharpe ratios of **0.4-0.9** achievable

**Critical Insight**: 
> "Price trend variables fail to improve model predictability" - momentum/trend features alone don't work

### B. Order Flow Imbalance (Multiple Papers)

**Key Paper**: "Deep Order Flow Imbalance: Extracting Alpha at Multiple Horizons"

**Findings**:
- Order flow imbalance (OFI) has **statistically significant correlation** to price movement
- Multi-level OFI (across price levels) outperforms single-level
- LSTM networks achieve high forecasting accuracy on order book data
- "Information-rich" stocks can be predicted more accurately

**Critical Insight**:
> Order book data (bid/ask imbalance, depth) is more predictive than price-based features

### C. Alternative Data & Sentiment

**Key Findings**:
- Sentiment-enhanced models improved accuracy by **21.6%** for high-discourse stocks
- News sentiment + market data hybrid models outperform price-only models
- Real-time social media sentiment (Twitter, Reddit) adds predictive value
- NLP transformers are reshaping news-based prediction

---

## 2. COMPARISON: ACADEMIC BEST PRACTICES vs OUR SYSTEM

### Feature Categories

| Category | Academic Best Practice | Our System | Gap |
|----------|----------------------|------------|-----|
| **Order Flow** | Multi-level OFI, bid-ask imbalance | ❌ Not included | CRITICAL |
| **Cross-sectional** | Lagged returns of constituents | ❌ Single stock only | HIGH |
| **Sentiment** | News NLP, social media | ❌ Not included | HIGH |
| **Microstructure** | Spread, depth, trade size | ❌ Not included | HIGH |
| **Technical** | RSI, MACD, Bollinger | ✅ Included | OK |
| **Multi-timeframe** | Multiple horizons | ✅ Included | OK |
| **Time-of-day** | Session indicators | ✅ Included | OK |
| **Volatility** | ATR, realized vol | ✅ Included | OK |
| **Volume** | Volume ratios | ✅ Included | OK |

### Model Comparison

| Model | Academic Performance | Our Performance | Gap |
|-------|---------------------|-----------------|-----|
| Lasso/Elastic Net | R² 0.24%, Sharpe 0.4-0.9 | AUC 0.50 | LARGE |
| Random Forest | Competitive with Lasso | AUC 0.52 | LARGE |
| Neural Networks | Best on volatile stocks | AUC 0.53 | MODERATE |
| LSTM | Best for order book | Not tested | N/A |

---

## 3. CRITICAL GAPS IN OUR FEATURE SET

### Gap 1: NO ORDER FLOW DATA (CRITICAL)
Academic research consistently shows order flow imbalance is the **strongest predictor** for intraday returns.

**Missing Features**:
- Bid-ask imbalance at multiple levels
- Order flow direction
- Trade size distribution
- Queue position
- Depth imbalance

**Impact**: Without order flow, we're missing the most predictive signal

### Gap 2: NO CROSS-SECTIONAL FEATURES (HIGH)
The academic paper found that **lagged returns of S&P 500 constituents** predict market returns better than autoregressive models.

**Missing Features**:
- Sector momentum
- Market-wide momentum
- Cross-asset correlations
- Relative strength vs peers

**Impact**: Single-stock features miss market-wide information flow

### Gap 3: NO SENTIMENT/NEWS DATA (HIGH)
Sentiment-enhanced models show **21.6% improvement** for high-discourse stocks.

**Missing Features**:
- News sentiment scores
- Social media sentiment
- Earnings surprise
- Analyst revisions
- Event flags (FDA, earnings, etc.)

**Impact**: Missing fundamental catalysts that drive "stocks in play"

### Gap 4: NO MICROSTRUCTURE FEATURES (MODERATE)
Market microstructure features capture trading dynamics.

**Missing Features**:
- Effective spread
- Realized spread
- Price impact
- Kyle's lambda
- Trade arrival rate

---

## 4. EVALUATION OF OUR CURRENT FEATURES

### Features That SHOULD Work (per academic research)

| Feature | Academic Support | Our Result | Assessment |
|---------|-----------------|------------|------------|
| ret_20bar | Momentum documented | +0.028 corr | ✅ Weak but correct sign |
| vol_10bar | Volatility predicts | +0.018 corr | ✅ Weak but correct |
| bb_width | Volatility regime | +0.016 corr | ✅ Weak but correct |
| macd_hist | Momentum | -0.016 corr | ⚠️ Wrong sign? |
| stoch | Mean reversion | -0.015 corr | ⚠️ Weak |
| rsi_14 | Overbought/oversold | +0.006 corr | ❌ Too weak |

### Features That Are MISSING (per academic research)

| Feature | Academic Support | Priority |
|---------|-----------------|----------|
| Order flow imbalance | Strongest predictor | CRITICAL |
| Cross-sectional momentum | Significant R² | HIGH |
| News sentiment | 21.6% improvement | HIGH |
| Bid-ask spread | Liquidity proxy | MODERATE |
| Trade size imbalance | Informed trading | MODERATE |

---

## 5. WHY OUR SYSTEM UNDERPERFORMS

### Root Cause Analysis

1. **Missing the strongest predictors**
   - Order flow imbalance not available
   - Cross-sectional features not computed
   - No sentiment data

2. **Feature correlations too weak**
   - Best feature: 0.028 correlation
   - Academic benchmark: 0.24% R² ≈ 0.05 correlation
   - We're 2x weaker than academic baseline

3. **Wrong feature focus**
   - Heavy on technical indicators (RSI, MACD)
   - Academic research: "price trend variables fail to improve predictability"
   - Should focus on: order flow, cross-sectional, microstructure

4. **Single-stock approach**
   - We predict each stock independently
   - Academic: cross-sectional constituent returns predict market
   - Missing information spillover effects

---

## 6. RECOMMENDATIONS

### Immediate Actions (Data Available)

1. **Add cross-sectional features**
   - Sector momentum (avg return of sector peers)
   - Market momentum (SPY return)
   - Relative strength vs sector

2. **Improve time-of-day modeling**
   - Academic: predictability is inverse-U shaped
   - Focus on midday (10:30 AM - 2:30 PM)
   - Avoid open/close

3. **Add volatility regime features**
   - Academic: predictability increases in high volatility
   - Condition models on VIX level
   - Separate models for different regimes

### Medium-term Actions (Requires New Data)

4. **Add order flow data**
   - Source: Level 2 quotes, TAQ data
   - Compute: bid-ask imbalance, OFI
   - This is the **highest priority** improvement

5. **Add sentiment data**
   - Source: News APIs, Twitter, Reddit
   - Compute: NLP sentiment scores
   - Focus on "stocks in play" with high news volume

### Long-term Actions

6. **Implement LSTM for order book**
   - Academic: LSTM achieves high accuracy on LOB data
   - Requires tick-level data

7. **Cross-sectional model**
   - Predict market using constituent returns
   - Then trade individual stocks based on market prediction

---

## 7. REALISTIC EXPECTATIONS

### Academic Benchmarks

| Metric | Academic Result | Our Current | Achievable Target |
|--------|----------------|-------------|-------------------|
| R² | 0.24% | ~0% | 0.1-0.2% |
| Sharpe (pre-cost) | 2.0-3.0 | ~0 | 0.5-1.0 |
| Sharpe (post-cost) | 0.4-0.9 | ~0 | 0.2-0.5 |
| Win Rate | 52-55% | 50% | 52-54% |

### Key Insight from Academic Research

> "Predictability decreased post-decimalization" - markets have become more efficient
> "After transaction costs, Sharpe ratios of 0.4-0.9" - edge is small but real
> "Predictability increases during high volatility and illiquidity" - focus on these periods

---

## 8. CONCLUSION

### Our System's Fundamental Problem

We are using **price-based technical features** when academic research shows:
1. Order flow imbalance is the strongest predictor
2. Cross-sectional features outperform single-stock features
3. Price trend variables "fail to improve predictability"

### Path Forward

1. **Short-term**: Add cross-sectional and regime features (no new data needed)
2. **Medium-term**: Acquire order flow and sentiment data
3. **Long-term**: Implement LSTM on order book data

### Expected Improvement

With proper features (order flow, cross-sectional, sentiment):
- R² could improve from ~0% to 0.1-0.2%
- Sharpe could improve from ~0 to 0.3-0.5 after costs
- Win rate could improve from 50% to 52-54%

**This is still a small edge, but potentially tradeable.**

---

*Report based on academic research from ResearchGate, SSRN, MDPI, and arXiv*
*Content was rephrased for compliance with licensing restrictions*

References:
[1] Intraday market predictability: A machine learning approach - ResearchGate
[2] Deep order flow imbalance: Extracting alpha at multiple horizons - SSRN
[3] Multi-Level Order-Flow Imbalance in a Limit Order Book - arXiv
[4] Using LLMs to Predict Stock Price: Hybrid Model - NHSJS
