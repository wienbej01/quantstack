# Intraday ML System Technical Documentation

## Executive Summary
The Intraday ML System is a high-frequency algorithmic trading platform designed to capture "Big Moves" (significant directional price excursions) in US equities. It leverages a two-stage Gradient Boosting Machine (LightGBM) pipeline to predict volatility breakouts and directionality. The system operates on 10-minute bars, utilizing a universe of "Stocks In Play" (SIP) to maximize signal-to-noise ratio.

## 1. Universe Selection: "Stocks In Play" (SIP)
The system does not trade the entire market. It filters for high-activity tickers likely to exhibit expanded volatility.

### 1.1 The SIP Filter
*   **Primary Criteria:**
    *   **Stocks In Play (SIP):** A pre-computed membership set based on high relative volume, overnight gaps, and news catalysts (HMM-based regime detection).
    *   **Static Universe:** A subset of ~100 liquid US equities (e.g., BAC, CCL, PLTR, UAL) defined in `universe_intraday_sip_5_50.yaml`.
*   **Hard Constraints:**
    *   Price Range: $5.00 - $50.00 (Focus on accessible volatility).
    *   Min Avg Daily Volume: $10M (Liquidity check).
    *   Max Universe Size: 600 symbols.

## 2. Data Pipeline & Feature Engineering
The system uses a **leakage-free sliding window** architecture to generate features.

### 2.1 Data Granularity
*   **Input:** 1-minute OHLCV bars from Gold Layer.
*   **Processing:** Resampled to **10-minute** bars for stability.
*   **Time Discipline:** Features for timestamp $T$ use only data from $t \le T$. Labels for timestamp $T$ use only data from $t > T$.

### 2.2 Feature Families (150+ Features)
The `IntradayMLFeaturePack` generates features across 7 core families:
1.  **Returns & Trend:** Simple and Log returns over [1, 2, 3, 6, 12] windows (10m to 2h).
2.  **Volatility (ATR):** Absolute and normalized Average True Range (Windows: 3, 6).
3.  **Volume Flow:** VWAP, Volume Sums, and Relative Volume (RVOL) normalized by time-of-day.
4.  **VWAP Distance:** Z-scores of price relative to 5m, 10m, 20m, 30m VWAPs.
5.  **Price Momentum:** RSI, Rate of Change (ROC), and Moving Average ratios.
6.  **Microstructure:** Effective spread proxies and volume imbalance estimators.
7.  **Time Seasonality:** Cyclical encoding (Sin/Cos) of Hour, Minute, and Day-of-Week.

*Configuration:* `configs/extensions/intraday_ml/features_10m.yaml`

## 3. Target Definition: The "Big Move"
The system aims to predict anomalous price excursions, defined dynamically relative to the asset's volatility.

### 3.1 Dynamic Threshold Logic
A "Big Move" occurs if the maximum forward return within the horizon exceeds a dynamic volatility barrier.

$$ \text{Threshold}_t = \max(\text{ATR}_t \times \text{Multiplier}, \text{Floor}) $$ 

*   **Horizon:** 60 minutes (6 bars).
*   **ATR Input:** `f__vol__atr_6` (absolute dollar volatility).
*   **Multiplier:** 1.10x ATR.
*   **Floor:** 0.75% absolute price change (Safety minimum).
*   **Labeling:**
    *   `y_bigmove` (Binary): 1 if $|Return_{fwd}| > Threshold$, else 0.
    *   `y_bigmove_direction` (Ternary): +1 (Long), -1 (Short), 0 (None).

*Correction Note:* Previous configurations incorrectly treated dollar-ATR as percentage-ATR. This was corrected to ensure realistic signal generation.

## 4. Machine Learning Architecture
The system employs a **Two-Stage Pipeline** to decouple volatility prediction from directional prediction.

### Stage 1: Volatility Classifier (Will it move?)
*   **Objective:** Predict `P(y_bigmove == 1)`.
*   **Algorithm:** LightGBM Classifier (Binary).
*   **Key Params:**
    *   `learning_rate`: 0.045
    *   `n_estimators`: 640
    *   `num_leaves`: 64
    *   `class_weight`: Balanced (to handle rarity of big moves).
*   **Input:** Full feature set.

### Stage 2: Directional Classifier (Which way?)
*   **Objective:** Predict `P(Long)` vs `P(Short)` *conditional* on a big move.
*   **Algorithm:** LightGBM Classifier (Binary/Multiclass).
*   **Training Data:** Trained *only* on samples where `y_bigmove == 1` (The "Big Move" subset).
*   **Input:** Full feature set + Stage 1 probability score.

## 5. Trading Policy & Execution
The `BigMovePolicy` converts model probabilities into executable orders with strict risk management.

### 5.1 Signal Generation
A trade is generated if:
1.  **Stage 1 Score** (`prob_bigmove`) > Threshold (e.g., 0.60).
2.  **Stage 2 Score** (`prob_long` or `prob_short`) > Directional Threshold (e.g., 0.60).
3.  **Time of Day:** Signal occurs within allowed windows (e.g., 09:40 - 15:50).

### 5.2 Time-of-Day (TOD) Profiles
Thresholds adapt dynamically based on market session:
*   **OPEN (09:40-10:10):** High thresholds (Prob > 0.70) to filter auction noise.
*   **MID (10:10-14:30):** Moderate thresholds (Prob > 0.65).
*   **LATE (14:30-15:50):** Loose thresholds (Prob > 0.62) to capture close moves.

### 5.3 Risk Management
*   **Position Sizing:** 1 share per trade (Fixed for Pilot/Testing).
*   **Stop Loss:** Dynamic ATR-based.
    *   Stop Price = Entry $\pm$ (1.0 $\times$ ATR).
    *   Hard Stop Cap: Max 4.5% loss.
*   **Take Profit:** 2.0 $\times$ ATR (Risk:Reward = 1:2).
*   **Timeouts:**
    *   **Early Cut:** Exit if trade is < 0.5R profit after 20 mins.
    *   **Dead Trade:** Exit if PnL is flat (< 0.2R) after 30 mins.
    *   **Max Hold:** 60 minutes hard cap.

## 6. Validation & Backtesting
*   **OOS Scoring:** Models are scored on Out-of-Sample data (Phase A) to simulate live performance.
*   **Policy Sweep:** A grid search runs across probability thresholds (0.5 - 0.7) and risk settings to generate an efficient frontier of viable strategies.
*   **Fairness:** The system enforces "1 trade per symbol per day" and "Max 5 trades per day" to prevent overfitting to a single active ticker.
