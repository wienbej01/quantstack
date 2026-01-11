#!/usr/bin/env python3
"""
L2 Pattern Discovery Tool v2

Scans L2 data for patterns that precede positive OBI momentum (proxy for price moves).
Uses statistical analysis + LLM interpretation for holistic pattern discovery.

Note: Current L2 data has OBI features but not raw price data, so we use
cumulative OBI momentum as a proxy for directional moves.
"""

import glob
import json
import os
import warnings
from datetime import datetime
from itertools import combinations

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Load API key
import subprocess

result = subprocess.run(
    ["bash", "-c", "source ~/.bashrc && echo $OPENAI_API_KEY"],
    capture_output=True,
    text=True,
)
OPENAI_API_KEY = result.stdout.strip()

LOOK_FORWARD_SECONDS = 300  # 5 minutes
MIN_MOVE_THRESHOLD = 0.3  # OBI momentum threshold


def load_l2_data(limit_files=None):
    """Load all L2 feature data."""
    features_path = "/home/jacobw/quantstack/data/l2_maximum/features"
    parquet_files = sorted(glob.glob(f"{features_path}/date=*/symbol=*/*.parquet"))

    if limit_files:
        parquet_files = parquet_files[:limit_files]

    print(f"Loading {len(parquet_files)} files...")

    dfs = []
    for pf in parquet_files:
        try:
            df = pd.read_parquet(pf)
            symbol = pf.split("symbol=")[1].split("/")[0]
            date = pf.split("date=")[1].split("/")[0]
            df["symbol"] = symbol
            df["date"] = date
            dfs.append(df)
        except Exception as e:
            continue

    if not dfs:
        return pd.DataFrame()

    data = pd.concat(dfs, ignore_index=True)
    data = data.sort_values(["symbol", "date", "ts_epoch"]).reset_index(drop=True)

    print(f"Loaded {len(data):,} records across {data['symbol'].nunique()} symbols")
    return data


def compute_forward_momentum(data):
    """Compute 5-minute forward OBI momentum as proxy for price direction."""
    print("Computing forward momentum (OBI-based)...")

    data["fwd_momentum"] = np.nan
    data["fwd_pressure"] = np.nan

    for symbol in data["symbol"].unique():
        mask = data["symbol"] == symbol
        idx = data.loc[mask].index.tolist()
        symbol_data = data.loc[mask].copy().reset_index(drop=True)

        n = len(symbol_data)
        ts = symbol_data["ts_epoch"].values
        obi_1 = symbol_data["obi_1"].values
        pressure = symbol_data["pressure_k"].values

        fwd_momentum = np.full(n, np.nan)
        fwd_pressure = np.full(n, np.nan)

        for i in range(n - 10):
            target_time = ts[i] + LOOK_FORWARD_SECONDS

            # Find index at +5min
            future_mask = ts >= target_time
            if not future_mask.any():
                continue

            future_idx = np.argmax(future_mask)

            if future_idx > i + 5:  # Need some samples
                # Average OBI in forward window
                window_obi = obi_1[i + 1 : future_idx]
                window_pressure = pressure[i + 1 : future_idx]

                if len(window_obi) > 0:
                    # Cumulative OBI momentum (sum of positive OBI = buying pressure)
                    fwd_momentum[i] = np.mean(window_obi)
                    fwd_pressure[i] = np.mean(window_pressure)

        # Map back to original indices
        for local_i, global_i in enumerate(idx):
            data.loc[global_i, "fwd_momentum"] = fwd_momentum[local_i]
            data.loc[global_i, "fwd_pressure"] = fwd_pressure[local_i]

    valid = data["fwd_momentum"].notna()
    print(f"Computed momentum for {valid.sum():,} records")

    momentum = data["fwd_momentum"].dropna()
    print(
        f"Momentum distribution: mean={momentum.mean():.4f}, std={momentum.std():.4f}"
    )
    print(f"Momentum range: {momentum.min():.4f} to {momentum.max():.4f}")

    return data


def label_moves(data):
    """Label positive vs negative momentum."""
    threshold = MIN_MOVE_THRESHOLD

    data["move_label"] = "neutral"
    data.loc[data["fwd_momentum"] >= threshold, "move_label"] = "positive"
    data.loc[data["fwd_momentum"] <= -threshold, "move_label"] = "negative"

    counts = data["move_label"].value_counts()
    print(f"Move distribution: {dict(counts)}")

    # Also create pressure-based labels
    pressure_std = data["fwd_pressure"].std()
    data["pressure_label"] = "neutral"
    data.loc[data["fwd_pressure"] > pressure_std, "pressure_label"] = "buying"
    data.loc[data["fwd_pressure"] < -pressure_std, "pressure_label"] = "selling"

    return data


def extract_feature_patterns(data):
    """Extract statistical patterns from features."""
    print("\nExtracting feature patterns...")

    # Get numeric features with variance
    exclude_cols = [
        "ts_utc",
        "ts_epoch",
        "date_et",
        "symbol",
        "date",
        "exchange",
        "fwd_momentum",
        "fwd_pressure",
        "move_label",
        "pressure_label",
        "smart_depth",
        "has_depth",
    ]

    feature_cols = []
    for c in data.columns:
        if c not in exclude_cols and data[c].dtype in ["float64", "float32", "int64"]:
            if data[c].std() > 0:
                feature_cols.append(c)

    print(f"Analyzing {len(feature_cols)} features: {feature_cols}")

    patterns = {}

    # 1. Single feature patterns
    print("\n--- Single Feature Patterns ---")
    positive = data[data["move_label"] == "positive"]
    negative = data[data["move_label"] == "negative"]

    if len(positive) == 0 or len(negative) == 0:
        print("Warning: Not enough positive/negative samples")
        return {"single": {}, "combinations": [], "temporal": [], "regime": []}

    for feat in feature_cols:
        if data[feat].isna().all():
            continue

        pos_mean = positive[feat].mean()
        neg_mean = negative[feat].mean()
        all_std = data[feat].std()

        if all_std > 0:
            separation = abs(pos_mean - neg_mean) / all_std

            if separation > 0.05:  # Any meaningful separation
                patterns[feat] = {
                    "type": "single",
                    "pos_mean": float(pos_mean),
                    "neg_mean": float(neg_mean),
                    "separation": float(separation),
                    "direction": "higher" if pos_mean > neg_mean else "lower",
                }

    sorted_patterns = sorted(
        patterns.items(), key=lambda x: x[1]["separation"], reverse=True
    )

    print(f"Top single-feature patterns:")
    for feat, p in sorted_patterns[:10]:
        print(
            f"  {feat}: {p['direction']} before positive moves (sep={p['separation']:.3f})"
        )

    # 2. Feature combinations (cross-behavior)
    print("\n--- Cross-Feature Patterns ---")

    top_features = [f for f, _ in sorted_patterns[:6]]
    combo_patterns = []

    for f1, f2 in combinations(top_features, 2):
        # High f1 AND high f2 -> positive?
        f1_high = data[f1].quantile(0.7)
        f2_high = data[f2].quantile(0.7)
        f1_low = data[f1].quantile(0.3)
        f2_low = data[f2].quantile(0.3)

        # Test high-high combination
        combo_mask = (data[f1] > f1_high) & (data[f2] > f2_high)
        if combo_mask.sum() > 30:
            combo_pos_rate = (data.loc[combo_mask, "move_label"] == "positive").mean()
            baseline_pos_rate = (data["move_label"] == "positive").mean()

            if baseline_pos_rate > 0:
                lift = combo_pos_rate / baseline_pos_rate

                if lift > 1.1:
                    combo_patterns.append(
                        {
                            "features": [f1, f2],
                            "condition": f"high {f1} AND high {f2}",
                            "pos_rate": float(combo_pos_rate),
                            "baseline": float(baseline_pos_rate),
                            "lift": float(lift),
                            "samples": int(combo_mask.sum()),
                        }
                    )

        # Test divergence: high f1 AND low f2
        div_mask = (data[f1] > f1_high) & (data[f2] < f2_low)
        if div_mask.sum() > 30:
            div_pos_rate = (data.loc[div_mask, "move_label"] == "positive").mean()

            if baseline_pos_rate > 0:
                lift = div_pos_rate / baseline_pos_rate

                if lift > 1.1 or lift < 0.9:
                    combo_patterns.append(
                        {
                            "features": [f1, f2],
                            "condition": f"high {f1} AND low {f2}",
                            "pos_rate": float(div_pos_rate),
                            "baseline": float(baseline_pos_rate),
                            "lift": float(lift),
                            "samples": int(div_mask.sum()),
                        }
                    )

    combo_patterns.sort(key=lambda x: abs(x["lift"] - 1), reverse=True)

    print(f"Top cross-feature patterns:")
    for p in combo_patterns[:10]:
        print(
            f"  {p['condition']}: {p['pos_rate']*100:.1f}% positive (lift={p['lift']:.2f}, n={p['samples']})"
        )

    # 3. Regime patterns (depth/pressure regimes)
    print("\n--- Regime Patterns ---")

    regime_patterns = []

    # High depth regime
    depth_high = data["depth_bid_k"] > data["depth_bid_k"].quantile(0.7)
    if depth_high.sum() > 50:
        regime_pos = (data.loc[depth_high, "move_label"] == "positive").mean()
        baseline = (data["move_label"] == "positive").mean()
        if baseline > 0:
            regime_patterns.append(
                {
                    "regime": "high_depth",
                    "condition": "depth_bid_k > 70th percentile",
                    "pos_rate": float(regime_pos),
                    "lift": float(regime_pos / baseline),
                    "samples": int(depth_high.sum()),
                }
            )

    # Imbalanced book regime
    imb_high = data["depth_imb_k"].abs() > data["depth_imb_k"].abs().quantile(0.8)
    if imb_high.sum() > 50:
        regime_pos = (data.loc[imb_high, "move_label"] == "positive").mean()
        if baseline > 0:
            regime_patterns.append(
                {
                    "regime": "imbalanced_book",
                    "condition": "|depth_imb_k| > 80th percentile",
                    "pos_rate": float(regime_pos),
                    "lift": float(regime_pos / baseline),
                    "samples": int(imb_high.sum()),
                }
            )

    print(f"Regime patterns:")
    for p in regime_patterns:
        print(
            f"  {p['regime']}: {p['pos_rate']*100:.1f}% positive (lift={p['lift']:.2f})"
        )

    # 4. OBI momentum patterns
    print("\n--- OBI Momentum Patterns ---")

    temporal_patterns = []

    # OBI acceleration
    data["obi_accel"] = data.groupby("symbol")["obi_1"].transform(
        lambda x: x.diff().rolling(3, min_periods=1).mean()
    )

    accel_high = data["obi_accel"] > data["obi_accel"].quantile(0.8)
    if accel_high.sum() > 50:
        accel_pos = (data.loc[accel_high, "move_label"] == "positive").mean()
        if baseline > 0:
            temporal_patterns.append(
                {
                    "pattern": "obi_accelerating",
                    "condition": "OBI acceleration > 80th percentile",
                    "pos_rate": float(accel_pos),
                    "lift": float(accel_pos / baseline),
                    "samples": int(accel_high.sum()),
                }
            )

    # OBI reversal (was negative, now positive)
    data["obi_reversal"] = (data["d_obi_1_30s"] > 0.5) & (data["obi_1"].shift(1) < 0)
    if data["obi_reversal"].sum() > 30:
        rev_pos = (data.loc[data["obi_reversal"], "move_label"] == "positive").mean()
        if baseline > 0:
            temporal_patterns.append(
                {
                    "pattern": "obi_reversal_bullish",
                    "condition": "OBI flips from negative to positive",
                    "pos_rate": float(rev_pos),
                    "lift": float(rev_pos / baseline),
                    "samples": int(data["obi_reversal"].sum()),
                }
            )

    print(f"Temporal patterns:")
    for p in temporal_patterns:
        print(
            f"  {p['pattern']}: {p['pos_rate']*100:.1f}% positive (lift={p['lift']:.2f})"
        )

    return {
        "single": dict(sorted_patterns[:15]),
        "combinations": combo_patterns[:15],
        "temporal": temporal_patterns,
        "regime": regime_patterns,
    }


def generate_pattern_summary(patterns, data):
    """Generate human-readable pattern summary for LLM analysis."""

    baseline = (data["move_label"] == "positive").mean()

    summary = []
    summary.append("=== L2 PATTERN ANALYSIS SUMMARY ===\n")
    summary.append(
        f"Data: {len(data):,} L2 snapshots across {data['symbol'].nunique()} symbols"
    )
    summary.append(f"Look-forward: 5 minutes")
    summary.append(
        f"Target: OBI momentum >= {MIN_MOVE_THRESHOLD} (proxy for bullish price action)"
    )
    summary.append(f"Positive samples: {(data['move_label']=='positive').sum():,}")
    summary.append(f"Negative samples: {(data['move_label']=='negative').sum():,}")
    summary.append(f"Baseline positive rate: {baseline*100:.1f}%\n")

    summary.append("TOP SINGLE-FEATURE PREDICTORS:")
    for feat, p in list(patterns["single"].items())[:10]:
        summary.append(
            f"  - {feat}: {p['direction']} values precede positive moves (separation={p['separation']:.3f})"
        )
        summary.append(
            f"    pos_mean={p['pos_mean']:.4f}, neg_mean={p['neg_mean']:.4f}"
        )

    summary.append("\nTOP FEATURE COMBINATIONS:")
    for p in patterns["combinations"][:10]:
        summary.append(
            f"  - {p['condition']}: {p['pos_rate']*100:.1f}% positive rate (lift={p['lift']:.2f}x, n={p['samples']})"
        )

    summary.append("\nREGIME PATTERNS:")
    for p in patterns["regime"]:
        summary.append(
            f"  - {p['regime']}: {p['pos_rate']*100:.1f}% positive (lift={p['lift']:.2f}x)"
        )

    summary.append("\nTEMPORAL/MOMENTUM PATTERNS:")
    for p in patterns["temporal"]:
        summary.append(
            f"  - {p['pattern']}: {p['pos_rate']*100:.1f}% positive (lift={p['lift']:.2f}x)"
        )

    summary.append("\nFEATURE GLOSSARY:")
    summary.append(
        "  - obi_N: Order Book Imbalance at N levels (positive=more bids, range -1 to +1)"
    )
    summary.append("  - depth_bid/ask_k: Total depth in $thousands at bid/ask")
    summary.append("  - depth_imb_k: (bid_depth - ask_depth) / total_depth")
    summary.append("  - pressure_k: Net buying pressure in $thousands")
    summary.append("  - d_obi_1_Ns: Change in OBI over N seconds")

    return "\n".join(summary)


def llm_analyze_patterns(pattern_summary):
    """Use LLM to interpret patterns and suggest trading rules."""

    print("\n--- LLM Pattern Analysis ---")

    try:
        import openai

        client = openai.OpenAI(api_key=OPENAI_API_KEY)

        prompt = f"""You are an expert quantitative trader analyzing L2 order book patterns.

{pattern_summary}

Based on these patterns, provide:

1. INTERPRETATION: What market microstructure dynamics do these patterns reveal? Why might these features predict forward momentum?

2. TRADING RULES: Suggest 3-5 specific, actionable trading rules based on the strongest patterns. Format as:
   - Entry condition (specific thresholds based on the data)
   - Expected edge (based on lift values)
   - Position sizing suggestion
   - Exit criteria

3. CROSS-BEHAVIOR INSIGHTS: What combinations of features suggest institutional activity, momentum ignition, or mean reversion?

4. REGIME CONSIDERATIONS: How should these rules be adjusted for different market conditions (high/low depth, trending vs ranging)?

5. WARNINGS: Any patterns that might be spurious, overfit, or regime-dependent?

Be specific and quantitative. Reference the actual feature names and values from the analysis."""

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a quantitative trading expert specializing in market microstructure and L2 order book analysis. Provide specific, actionable insights.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2500,
            temperature=0.3,
        )

        return response.choices[0].message.content

    except Exception as e:
        print(f"LLM analysis failed: {e}")
        return None


def save_results(patterns, llm_analysis, summary, output_dir):
    """Save analysis results."""

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Save patterns as JSON
    patterns_file = f"{output_dir}/patterns_{timestamp}.json"
    with open(patterns_file, "w") as f:
        json.dump(patterns, f, indent=2, default=str)
    print(f"Saved patterns to {patterns_file}")

    # Save full report
    report_file = f"{output_dir}/pattern_report_{timestamp}.md"
    with open(report_file, "w") as f:
        f.write(f"# L2 Pattern Discovery Report - {timestamp}\n\n")
        f.write("## Statistical Analysis\n\n")
        f.write("```\n" + summary + "\n```\n\n")
        if llm_analysis:
            f.write("## LLM Interpretation\n\n")
            f.write(llm_analysis)
    print(f"Saved report to {report_file}")

    return report_file


def main():
    """Main analysis pipeline."""

    print("=" * 60)
    print("L2 PATTERN DISCOVERY TOOL v2")
    print(f"Look-forward period: {LOOK_FORWARD_SECONDS}s (5 minutes)")
    print(f"Target: OBI momentum >= {MIN_MOVE_THRESHOLD}")
    print("=" * 60)

    # Load data (use all files for comprehensive analysis)
    data = load_l2_data(limit_files=500)

    if len(data) == 0:
        print("No data loaded!")
        return

    # Compute forward momentum
    data = compute_forward_momentum(data)

    # Label moves
    data = label_moves(data)

    # Extract patterns
    patterns = extract_feature_patterns(data)

    # Generate summary
    summary = generate_pattern_summary(patterns, data)
    print("\n" + summary)

    # LLM analysis
    llm_analysis = llm_analyze_patterns(summary)

    if llm_analysis:
        print("\n" + "=" * 60)
        print("LLM INTERPRETATION")
        print("=" * 60)
        print(llm_analysis)

    # Save results
    output_dir = "/home/jacobw/quantstack/l2_scalping/analysis/output"
    save_results(patterns, llm_analysis, summary, output_dir)

    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    main()
