#!/usr/bin/env python3
"""
Comprehensive Strategy Analysis Framework

Evaluates multiple trading strategies on news-driven "stocks in play":
1. Mean Reversion
2. Momentum/Continuation  
3. Breakout
4. Gap Fade
5. Support/Resistance

With proper position sizing (1% risk) and realistic costs.
"""

import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Try imports
try:
    import lightgbm as lgb

    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import precision_score, recall_score, roc_auc_score

    HAS_SKLEARN = True
except ImportError:
    HAS_SKLEARN = False


class PositionSizer:
    """Correct 1% risk position sizing."""

    def __init__(self, risk_pct=0.01, max_position_pct=0.25):
        self.risk_pct = risk_pct
        self.max_position_pct = max_position_pct

    def calculate_shares(self, equity, entry_price, stop_distance):
        """
        shares = (equity * risk_pct) / stop_distance
        """
        if stop_distance <= 0 or entry_price <= 0:
            return 0

        dollar_risk = equity * self.risk_pct
        shares = int(dollar_risk / stop_distance)

        # Cap at max position size
        max_shares = int((equity * self.max_position_pct) / entry_price)
        return max(1, min(shares, max_shares, 5000))


class StrategyLabeler:
    """Generate labels for different strategy types."""

    @staticmethod
    def mean_reversion_label(df, threshold_pct=0.02, hold_bars=6):
        """
        Mean reversion: Price reverts toward VWAP/mean.
        Label=1 if price moves back toward entry by threshold within hold_bars.
        """
        labels = []
        for i in range(len(df) - hold_bars):
            entry = df.iloc[i]["close"]
            vwap = df.iloc[i].get("vwap", entry)

            # Determine direction (fade the move)
            if entry > vwap * 1.01:  # Overbought - expect down
                target = entry * (1 - threshold_pct)
                future_lows = df.iloc[i + 1 : i + hold_bars + 1]["low"].min()
                labels.append(1 if future_lows <= target else 0)
            elif entry < vwap * 0.99:  # Oversold - expect up
                target = entry * (1 + threshold_pct)
                future_highs = df.iloc[i + 1 : i + hold_bars + 1]["high"].max()
                labels.append(1 if future_highs >= target else 0)
            else:
                labels.append(0)  # No setup

        return labels + [0] * hold_bars

    @staticmethod
    def momentum_label(df, threshold_pct=0.015, hold_bars=6):
        """
        Momentum: Price continues in direction of recent move.
        Label=1 if price continues by threshold within hold_bars.
        """
        labels = []
        for i in range(len(df) - hold_bars):
            if i < 3:
                labels.append(0)
                continue

            # Recent momentum
            recent_return = df.iloc[i]["close"] / df.iloc[i - 3]["close"] - 1
            entry = df.iloc[i]["close"]

            if recent_return > 0.005:  # Upward momentum
                target = entry * (1 + threshold_pct)
                future_highs = df.iloc[i + 1 : i + hold_bars + 1]["high"].max()
                labels.append(1 if future_highs >= target else 0)
            elif recent_return < -0.005:  # Downward momentum
                target = entry * (1 - threshold_pct)
                future_lows = df.iloc[i + 1 : i + hold_bars + 1]["low"].min()
                labels.append(1 if future_lows <= target else 0)
            else:
                labels.append(0)

        return labels + [0] * hold_bars

    @staticmethod
    def breakout_label(df, threshold_pct=0.02, hold_bars=10):
        """
        Breakout: Price breaks recent high/low and continues.
        """
        labels = []
        lookback = 20

        for i in range(len(df) - hold_bars):
            if i < lookback:
                labels.append(0)
                continue

            entry = df.iloc[i]["close"]
            recent_high = df.iloc[i - lookback : i]["high"].max()
            recent_low = df.iloc[i - lookback : i]["low"].min()

            if entry > recent_high:  # Breakout up
                target = entry * (1 + threshold_pct)
                future_highs = df.iloc[i + 1 : i + hold_bars + 1]["high"].max()
                labels.append(1 if future_highs >= target else 0)
            elif entry < recent_low:  # Breakout down
                target = entry * (1 - threshold_pct)
                future_lows = df.iloc[i + 1 : i + hold_bars + 1]["low"].min()
                labels.append(1 if future_lows <= target else 0)
            else:
                labels.append(0)

        return labels + [0] * hold_bars

    @staticmethod
    def gap_fade_label(df, min_gap_pct=0.02, hold_bars=12):
        """
        Gap fade: Fade opening gaps that are likely to fill.
        """
        labels = []

        for i in range(len(df) - hold_bars):
            row = df.iloc[i]

            # Check if this is near market open (first 30 min)
            if "hour_et" in row and row["hour_et"] >= 10:
                labels.append(0)
                continue

            # Check for gap
            if i > 0:
                prev_close = df.iloc[i - 1]["close"]
                gap_pct = (row["open"] - prev_close) / prev_close

                if abs(gap_pct) >= min_gap_pct:
                    entry = row["close"]
                    if gap_pct > 0:  # Gap up - fade down
                        target = entry * (1 - min_gap_pct * 0.5)
                        future_lows = df.iloc[i + 1 : i + hold_bars + 1]["low"].min()
                        labels.append(1 if future_lows <= target else 0)
                    else:  # Gap down - fade up
                        target = entry * (1 + min_gap_pct * 0.5)
                        future_highs = df.iloc[i + 1 : i + hold_bars + 1]["high"].max()
                        labels.append(1 if future_highs >= target else 0)
                else:
                    labels.append(0)
            else:
                labels.append(0)

        return labels + [0] * hold_bars


class FeatureEngineer:
    """Enhanced feature engineering for news-driven stocks."""

    @staticmethod
    def build_features(df):
        """Build comprehensive feature set."""
        features = pd.DataFrame(index=df.index)

        # Price action features
        features["return_1"] = df["close"].pct_change(1)
        features["return_3"] = df["close"].pct_change(3)
        features["return_5"] = df["close"].pct_change(5)
        features["return_10"] = df["close"].pct_change(10)

        # Volatility features
        features["volatility_5"] = df["close"].pct_change().rolling(5).std()
        features["volatility_10"] = df["close"].pct_change().rolling(10).std()
        features["volatility_20"] = df["close"].pct_change().rolling(20).std()

        # ATR-based features
        high_low = df["high"] - df["low"]
        features["atr_5"] = high_low.rolling(5).mean() / df["close"]
        features["atr_10"] = high_low.rolling(10).mean() / df["close"]

        # Volume features
        features["volume_ratio_5"] = df["volume"] / df["volume"].rolling(5).mean()
        features["volume_ratio_10"] = df["volume"] / df["volume"].rolling(10).mean()
        features["volume_ratio_20"] = df["volume"] / df["volume"].rolling(20).mean()

        # VWAP features (if available)
        if "vwap" in df.columns:
            features["vwap_distance"] = (df["close"] - df["vwap"]) / df["vwap"]
            features["vwap_cross"] = (df["close"] > df["vwap"]).astype(int)

        # Range features
        features["range_pct"] = (df["high"] - df["low"]) / df["close"]
        features["body_pct"] = abs(df["close"] - df["open"]) / df["close"]
        features["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df[
            "close"
        ]
        features["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df[
            "close"
        ]

        # Momentum indicators
        features["rsi_14"] = FeatureEngineer._rsi(df["close"], 14)
        features["rsi_7"] = FeatureEngineer._rsi(df["close"], 7)

        # Moving average features
        features["ma_5_dist"] = (df["close"] - df["close"].rolling(5).mean()) / df[
            "close"
        ]
        features["ma_10_dist"] = (df["close"] - df["close"].rolling(10).mean()) / df[
            "close"
        ]
        features["ma_20_dist"] = (df["close"] - df["close"].rolling(20).mean()) / df[
            "close"
        ]

        # Time features
        if "hour_et" in df.columns:
            features["hour"] = df["hour_et"]
            features["is_morning"] = (df["hour_et"] < 11).astype(int)
            features["is_power_hour"] = (df["hour_et"] >= 15).astype(int)

        # Trend features
        features["higher_high"] = (df["high"] > df["high"].shift(1)).astype(int)
        features["lower_low"] = (df["low"] < df["low"].shift(1)).astype(int)
        features["trend_strength"] = (
            features["higher_high"].rolling(5).sum()
            - features["lower_low"].rolling(5).sum()
        )

        # Gap features
        features["gap_pct"] = (df["open"] - df["close"].shift(1)) / df["close"].shift(1)

        return features.fillna(0)

    @staticmethod
    def _rsi(series, period):
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))


class StrategyBacktester:
    """Backtest strategies with proper position sizing."""

    def __init__(self, initial_equity=10000, risk_pct=0.01, cost_pct=0.001):
        self.initial_equity = initial_equity
        self.sizer = PositionSizer(risk_pct=risk_pct)
        self.cost_pct = cost_pct

    def backtest_strategy(self, df, predictions, strategy_name, hold_bars=6):
        """Run backtest for a strategy."""
        equity = self.initial_equity
        trades = []

        i = 0
        while i < len(df) - hold_bars:
            if predictions[i] != 1:
                i += 1
                continue

            # Entry
            entry_price = df.iloc[i]["close"]
            atr = (
                df.iloc[i].get("atr_10", 0.02) * entry_price
                if "atr_10" in df.columns
                else entry_price * 0.02
            )
            stop_distance = atr * 2  # 2 ATR stop

            shares = self.sizer.calculate_shares(equity, entry_price, stop_distance)
            if shares == 0:
                i += 1
                continue

            # Exit after hold_bars
            exit_price = df.iloc[i + hold_bars]["close"]

            # P&L calculation
            position_value = shares * entry_price
            gross_pnl = shares * (exit_price - entry_price)
            costs = position_value * self.cost_pct
            net_pnl = gross_pnl - costs

            equity += net_pnl

            trades.append(
                {
                    "entry_idx": i,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "shares": shares,
                    "gross_pnl": gross_pnl,
                    "net_pnl": net_pnl,
                    "equity": equity,
                    "return_pct": (exit_price / entry_price - 1) * 100,
                }
            )

            i += hold_bars  # Skip to after exit

        return pd.DataFrame(trades), equity


def load_and_prepare_data():
    """Load gold data and prepare for analysis."""

    # Try to load existing features
    features_path = Path("run/news_driven_features/features.parquet")
    if features_path.exists():
        print("📊 Loading news-driven features...")
        try:
            import polars as pl

            df = pl.read_parquet(features_path).to_pandas()
            print(f"   Loaded {len(df):,} rows")
            return df
        except Exception as e:
            print(f"   Error: {e}")

    # Try enhanced features
    features_path = Path("run/enhanced_features/features.parquet")
    if features_path.exists():
        print("📊 Loading enhanced features...")
        try:
            import polars as pl

            df = pl.read_parquet(features_path).to_pandas()
            print(f"   Loaded {len(df):,} rows")
            return df
        except Exception as e:
            print(f"   Error: {e}")

    # Load raw gold data
    gold_path = Path("data/gold")
    if gold_path.exists():
        print("📊 Loading raw gold data...")
        files = list(gold_path.glob("*.parquet"))[:10]  # Limit for speed
        dfs = []
        for f in files:
            try:
                import polars as pl

                dfs.append(pl.read_parquet(f).to_pandas())
            except:
                pass
        if dfs:
            df = pd.concat(dfs, ignore_index=True)
            print(f"   Loaded {len(df):,} rows from {len(files)} files")
            return df

    print("❌ No data found")
    return None


def analyze_strategy_edge(df, strategy_name, labels, features, feature_cols):
    """Analyze if a strategy has genuine edge."""

    print(f"\n{'='*60}")
    print(f"STRATEGY: {strategy_name.upper()}")
    print(f"{'='*60}")

    # Basic label statistics
    label_rate = np.mean(labels)
    print(f"Label rate (win conditions met): {label_rate:.1%}")

    if label_rate < 0.01 or label_rate > 0.99:
        print("⚠️ Extreme label imbalance - strategy may not be viable")
        return None

    # Split data
    n = len(labels)
    train_end = int(n * 0.6)
    val_end = int(n * 0.8)

    X_train = features.iloc[:train_end][feature_cols]
    y_train = labels[:train_end]
    X_val = features.iloc[train_end:val_end][feature_cols]
    y_val = labels[train_end:val_end]
    X_test = features.iloc[val_end:][feature_cols]
    y_test = labels[val_end:]

    results = {}

    # Test multiple models
    models = {}

    if HAS_SKLEARN:
        models["LogisticRegression"] = LogisticRegression(max_iter=500, random_state=42)
        models["RandomForest"] = RandomForestClassifier(
            n_estimators=100, max_depth=5, random_state=42
        )
        models["GradientBoosting"] = GradientBoostingClassifier(
            n_estimators=100, max_depth=3, random_state=42
        )

    if HAS_LGB:
        models["LightGBM"] = lgb.LGBMClassifier(
            n_estimators=100, max_depth=3, verbose=-1, random_state=42
        )

    print(f"\nModel Comparison (Test Set):")
    print(f"{'-'*60}")
    print(f"{'Model':<25} {'AUC':>8} {'Precision':>10} {'Recall':>8} {'Edge':>8}")
    print(f"{'-'*60}")

    for name, model in models.items():
        try:
            model.fit(X_train, y_train)

            # Predictions
            proba = model.predict_proba(X_test)[:, 1]
            preds = (proba > 0.5).astype(int)

            # Metrics
            auc = roc_auc_score(y_test, proba) if len(np.unique(y_test)) > 1 else 0.5
            precision = precision_score(y_test, preds, zero_division=0)
            recall = recall_score(y_test, preds, zero_division=0)

            # Edge calculation: precision above base rate
            base_rate = np.mean(y_test)
            edge = precision - base_rate

            print(
                f"{name:<25} {auc:>8.3f} {precision:>10.3f} {recall:>8.3f} {edge:>+8.1%}"
            )

            results[name] = {
                "auc": auc,
                "precision": precision,
                "recall": recall,
                "edge": edge,
                "model": model,
            }
        except Exception as e:
            print(f"{name:<25} Error: {e}")

    # Find best model
    if results:
        best_model = max(results.items(), key=lambda x: x[1]["edge"])
        print(f"\n✅ Best model: {best_model[0]} (Edge: {best_model[1]['edge']:+.1%})")

        if best_model[1]["edge"] > 0.05:
            print("   → Potential tradeable edge detected")
        elif best_model[1]["edge"] > 0:
            print("   → Marginal edge - may not survive costs")
        else:
            print("   → No edge detected")

        return results

    return None


def run_comprehensive_analysis():
    """Run full analysis across all strategies."""

    print("=" * 70)
    print("COMPREHENSIVE STRATEGY ANALYSIS")
    print("News-Driven Stocks in Play - Multi-Strategy Evaluation")
    print("=" * 70)
    print(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()

    # Load data
    df = load_and_prepare_data()
    if df is None:
        return

    # Ensure required columns
    required = ["close", "high", "low", "open", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        print(f"❌ Missing columns: {missing}")
        return

    # Limit to 3 months for pilot
    if "timestamp" in df.columns or "signal_timestamp" in df.columns:
        ts_col = "timestamp" if "timestamp" in df.columns else "signal_timestamp"
        df[ts_col] = pd.to_datetime(df[ts_col])
        df = df.sort_values(ts_col)

        # Last 3 months
        end_date = df[ts_col].max()
        start_date = end_date - timedelta(days=90)
        df = df[df[ts_col] >= start_date]
        print(f"📅 Analysis period: {start_date.date()} to {end_date.date()}")
        print(f"   Data points: {len(df):,}")

    # Build features
    print("\n🔧 Building features...")
    features = FeatureEngineer.build_features(df)
    feature_cols = [
        c for c in features.columns if features[c].dtype in ["float64", "int64"]
    ]
    print(f"   Features: {len(feature_cols)}")

    # Analyze each strategy
    strategies = {
        "Mean Reversion": StrategyLabeler.mean_reversion_label,
        "Momentum": StrategyLabeler.momentum_label,
        "Breakout": StrategyLabeler.breakout_label,
        "Gap Fade": StrategyLabeler.gap_fade_label,
    }

    all_results = {}

    for strategy_name, labeler in strategies.items():
        try:
            labels = labeler(df)
            if len(labels) != len(df):
                labels = (
                    labels[: len(df)]
                    if len(labels) > len(df)
                    else labels + [0] * (len(df) - len(labels))
                )

            results = analyze_strategy_edge(
                df, strategy_name, labels, features, feature_cols
            )
            if results:
                all_results[strategy_name] = results
        except Exception as e:
            print(f"\n❌ {strategy_name} failed: {e}")

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY: STRATEGY VIABILITY")
    print("=" * 70)

    viable_strategies = []

    for strategy, results in all_results.items():
        best = max(results.values(), key=lambda x: x["edge"])
        edge = best["edge"]
        auc = best["auc"]

        status = (
            "✅ VIABLE" if edge > 0.05 else "⚠️ MARGINAL" if edge > 0 else "❌ NO EDGE"
        )
        print(f"{strategy:<20} Edge: {edge:>+6.1%}  AUC: {auc:.3f}  {status}")

        if edge > 0.05:
            viable_strategies.append((strategy, edge, auc))

    print("\n" + "-" * 70)

    if viable_strategies:
        print(f"✅ {len(viable_strategies)} viable strategies found:")
        for s, e, a in sorted(viable_strategies, key=lambda x: -x[1]):
            print(f"   • {s}: {e:+.1%} edge, {a:.3f} AUC")
        print(
            "\nRecommendation: Focus on highest-edge strategies with proper risk management"
        )
    else:
        print("❌ No strategies with significant edge detected")
        print("\nRecommendations:")
        print(
            "   1. Review feature engineering - current features may not capture edge"
        )
        print(
            "   2. Consider alternative data sources (order flow, options, sentiment)"
        )
        print("   3. Reduce trading frequency - edge may exist on longer timeframes")
        print("   4. Implement stricter entry filters to improve precision")

    return all_results


if __name__ == "__main__":
    results = run_comprehensive_analysis()
