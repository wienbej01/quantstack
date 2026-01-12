"""LLM analysis integration for pattern interpretation."""

import os
from pathlib import Path

import pandas as pd


def format_patterns_for_llm(
    patterns_df: pd.DataFrame, target_name: str, top_n: int = 20
) -> str:
    """Format discovered patterns for LLM analysis with AAA overfitting checks."""
    top_patterns = patterns_df.head(top_n)

    # Handle both n_trades and n_samples column names
    samples_col = "n_samples" if "n_samples" in patterns_df.columns else "n_trades"

    output = f"# Discovered Patterns for Target: {target_name}\n\n"
    output += f"Total patterns found: {len(patterns_df)}\n"
    output += f"Showing top {len(top_patterns)} patterns\n\n"
    
    # Add AAA criteria reminder
    output += "## CRITICAL OVERFITTING CHECKS\n"
    output += "You MUST flag patterns with:\n"
    output += "- Win rate > 65% as **HIGH OVERFIT RISK**\n"
    output += "- Sharpe > 3.0 as **EXTREME METRICS - SUSPECT**\n"
    output += "- Expectancy > 0.10% as **UNREALISTIC EDGE**\n"
    output += "- Samples < 10,000 as **INSUFFICIENT DATA**\n\n"
    output += "## DEGRADATION RISK SCORE\n"
    output += "Calculate: Risk = (win_rate - 0.50) * 2 + (sharpe - 1.5) * 0.5 + (expectancy - 0.03) * 10\n"
    output += "If Risk > 1.0: **REJECT** pattern as likely overfit\n\n"
    output += "## APPROVAL CRITERIA\n"
    output += "Only approve patterns with:\n"
    output += "- Moderate metrics (not extreme)\n"
    output += "- Clear economic rationale with causal mechanism\n"
    output += "- Regime alignment with current market\n"
    output += "- Event-based conditions (time-constrained)\n\n"
    output += "---\n\n"

    for idx, row in top_patterns.iterrows():
        # Calculate overfit risk
        wr_risk = max(0, row['win_rate'] - 0.50) * 2
        sharpe_risk = max(0, row['sharpe'] - 1.5) * 0.5
        exp_risk = max(0, row['expectancy'] - 0.03) * 10
        overfit_risk = wr_risk + sharpe_risk + exp_risk
        
        output += f"## Pattern {idx + 1}\n"
        output += f"**Rule:** {row['rule']}\n"
        output += f"**Direction:** {row.get('direction', 'N/A')}\n"
        output += f"**Regime:** {row.get('regime', 'N/A')}\n"
        output += f"**T-Statistic:** {row['t_stat']:.2f} (p={row['p_value']:.2e})\n"
        output += f"**Expectancy:** {row['expectancy']:.4f}% per trade\n"
        output += f"**Win Rate:** {row['win_rate']:.1%}\n"
        output += f"**Profit Factor:** {row['profit_factor']:.2f}\n"
        output += f"**Sharpe Ratio:** {row['sharpe']:.2f}\n"
        output += f"**Avg Win:** {row['avg_win']:.4f}% | **Avg Loss:** {row['avg_loss']:.4f}%\n"
        output += f"**Samples:** {int(row[samples_col]):,} bar observations\n"
        output += f"**OVERFIT RISK SCORE:** {overfit_risk:.2f} {'⚠️ REJECT' if overfit_risk > 1.0 else '✅ ACCEPTABLE'}\n\n"

    return output


def format_consolidated_patterns(patterns_df: pd.DataFrame, top_n: int = 30) -> str:
    """Format all patterns consolidated by economic theme for LLM analysis."""
    # Handle both n_trades and n_samples column names
    samples_col = "n_samples" if "n_samples" in patterns_df.columns else "n_trades"

    # Sort by t_stat and take top N
    top_patterns = patterns_df.nlargest(top_n, "t_stat")

    # Group patterns by key features
    themes = {
        "power_hour": [],
        "first_hour": [],
        "spy_momentum": [],
        "price_vs_vwap": [],
        "atr_volatility": [],
        "momentum_returns": [],
        "other": [],
    }

    for _, row in top_patterns.iterrows():
        rule = row["rule"].lower()
        if "power_hour" in rule:
            themes["power_hour"].append(row)
        elif "first_hour" in rule:
            themes["first_hour"].append(row)
        elif "spy_" in rule and "power_hour" not in rule and "first_hour" not in rule:
            themes["spy_momentum"].append(row)
        elif "vwap" in rule or "avwap" in rule:
            themes["price_vs_vwap"].append(row)
        elif "atr" in rule:
            themes["atr_volatility"].append(row)
        elif "ret_" in rule:
            themes["momentum_returns"].append(row)
        else:
            themes["other"].append(row)

    output = "# Consolidated Pattern Analysis\n\n"
    output += f"Total patterns: {len(top_patterns)} (top by t-stat)\n"
    output += f"Horizons: 30m, 60m, 90m, 180m\n"
    output += f"Directions: LONG, SHORT\n\n"

    theme_names = {
        "power_hour": "Power Hour Patterns (3-4 PM)",
        "first_hour": "First Hour Patterns (9:30-10:30 AM)",
        "spy_momentum": "SPY Momentum Context",
        "price_vs_vwap": "Price vs VWAP Patterns",
        "atr_volatility": "Volatility (ATR) Patterns",
        "momentum_returns": "Momentum/Return Patterns",
        "other": "Other Patterns",
    }

    for theme_key, theme_label in theme_names.items():
        patterns = themes[theme_key]
        if not patterns:
            continue

        output += f"## {theme_label}\n\n"
        output += f"*{len(patterns)} patterns in this category*\n\n"

        for row in patterns:
            horizon = row["horizon"].replace("fwd_ret_", "").replace("m", "")
            output += f"### {row['direction']} {horizon}m: {row['rule']}\n"
            output += f"- T-stat: {row['t_stat']:.1f} | Expectancy: {row['expectancy']:.3f}%\n"
            output += f"- Win Rate: {row['win_rate']:.1%} | Profit Factor: {row['profit_factor']:.2f} | Sharpe: {row['sharpe']:.2f}\n"
            output += f"- Samples: {int(row[samples_col]):,} observations\n\n"

    return output


def generate_consolidated_prompt(patterns_text: str) -> str:
    """Generate LLM prompt for consolidated pattern analysis."""
    prompt = f"""You are a senior quantitative researcher analyzing trading patterns discovered from 1-minute SIP-filtered stock data.

The patterns are grouped by ECONOMIC THEME to help identify which market microstructure effects are most tradeable.

{patterns_text}

CRITICAL: All patterns use POSITIVE conditions (event == True, high momentum bins). No "NOT X" patterns.

ANALYSIS FRAMEWORK:

1. **ECONOMIC RATIONALE (MOST IMPORTANT)**:
   - WHY would this pattern exist?
   - What market microstructure creates this edge?
   - Is it exploiting:
     * Cross-asset momentum (stock vs SPY)?
     * Volume-price divergence (weak/strong volume)?
     * Session range dynamics (breakouts, extremes)?
     * Time-of-day effects (first hour, power hour)?
   - Reject patterns without clear economic explanation

2. **CROSS-HORIZON ANALYSIS**:
   - For each theme, which horizon (30m, 60m, 90m, 180m) shows strongest edge?
   - Does the pattern strengthen or decay with longer horizons?
   - Is there an optimal holding period?

3. **LONG vs SHORT ASYMMETRY**:
   - Are SHORT patterns stronger than LONG? Why?
   - Does this reflect market microstructure (e.g., end-of-day selling)?
   - Which direction is more tradeable?

4. **EXECUTION REALITY**:
   - After 0.5-1 bps slippage/commissions, still profitable?
   - Expectancy ≥ 0.02% after costs?
   - Profit factor > 1.3?
   - Sharpe > 1.0?

5. **PORTFOLIO CONSTRUCTION**:
   - Which 3-5 patterns would you combine for a diversified strategy?
   - Are patterns correlated or independent?
   - What's the expected combined Sharpe?

APPROVAL CRITERIA (ALL must apply):
- Clear economic rationale (WHY does this work?)
- Expectancy ≥ 0.02% after costs
- Profit factor > 1.3
- Sharpe > 1.0
- Actionable entry signal (not "NOT X")

REJECTION CRITERIA (ANY applies):
- No economic rationale
- Expectancy < 0.02%
- Profit factor < 1.3
- Sharpe < 1.0
- Pattern is "NOT X" (negative condition)

DELIVERABLES:
1. Rank themes by economic rationale strength (not just t-stat)
2. Identify the single best pattern per theme with clear WHY
3. Recommend a 3-5 pattern portfolio with economic diversity
4. Flag any patterns that lack economic rationale despite high t-stat
"""
    return prompt


def call_llm_api(prompt: str, system_prompt: str | None = None) -> str:
    """Call LLM API for pattern analysis."""
    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY")

    if not api_key:
        return "# LLM Analysis Skipped\n\nNo API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY."

    if system_prompt is None:
        system_prompt = """You are a senior quantitative researcher analyzing trading patterns.
Focus on economic rationale, regime robustness, and practical tradability.

APPROVAL CRITERIA:
- T-stat ≥ 3.0, Expectancy ≥ 0.02%, Profit factor > 1.3, Clear economic rationale

REJECTION CRITERIA:
- Expectancy < 0.01%, Profit factor < 1.2, No economic rationale, Regime-dependent"""

    # Try Anthropic first
    if "ANTHROPIC_API_KEY" in os.environ:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
            message = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            )
            return message.content[0].text
        except Exception as e:
            return f"# LLM Analysis Failed\n\nError: {e}"

    # Try OpenAI
    if "OPENAI_API_KEY" in os.environ:
        try:
            import openai

            client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
            response = client.chat.completions.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4096,
            )
            return response.choices[0].message.content or "Empty response"
        except Exception as e:
            return f"# LLM Analysis Failed\n\nError: {e}"

    return "# LLM Analysis Skipped\n\nNo compatible API key found."


def analyze_patterns_with_llm(
    patterns_df: pd.DataFrame,
    target_name: str,
    horizon: int,
    output_path: Path,
    top_n: int = 20,
) -> str:
    """Analyze patterns using LLM and save report (per-horizon analysis)."""
    print(f"Formatting top {top_n} patterns for LLM analysis...")
    patterns_text = format_patterns_for_llm(patterns_df, target_name, top_n)

    prompt = f"""Analyze these {horizon}-minute forward return patterns:

{patterns_text}

For each pattern, provide GO/NO-GO with reasoning based on:
- Statistical significance (t-stat ≥ 3.0)
- Economic rationale
- Expectancy after costs (≥ 0.02%)
- Profit factor (> 1.3)
"""

    print("Calling LLM API...")
    analysis = call_llm_api(prompt)

    # Save report
    report = f"# Pattern Analysis Report\n\n"
    report += f"**Target:** {target_name}\n"
    report += f"**Horizon:** {horizon} minutes\n"
    report += f"**Patterns analyzed:** {min(top_n, len(patterns_df))}\n\n"
    report += "---\n\n"
    report += patterns_text
    report += "\n---\n\n"
    report += "# LLM Analysis\n\n"
    report += analysis

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)

    print(f"Report saved to {output_path}")
    return analysis


def analyze_consolidated_patterns(
    patterns_df: pd.DataFrame,
    output_path: Path,
    top_n: int = 30,
) -> str:
    """Analyze all patterns consolidated by theme using LLM."""
    print(f"Formatting top {top_n} patterns consolidated by theme...")
    patterns_text = format_consolidated_patterns(patterns_df, top_n)

    print("Generating consolidated LLM prompt...")
    prompt = generate_consolidated_prompt(patterns_text)

    print("Calling LLM API for consolidated analysis...")
    analysis = call_llm_api(prompt)

    # Save report
    report = "# Consolidated Pattern Analysis Report\n\n"
    report += f"**Patterns analyzed:** {min(top_n, len(patterns_df))}\n"
    report += f"**Horizons:** 30m, 60m, 90m, 180m\n"
    report += f"**Directions:** LONG, SHORT\n\n"
    report += "---\n\n"
    report += patterns_text
    report += "\n---\n\n"
    report += "# LLM Analysis\n\n"
    report += analysis

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(report)

    print(f"Consolidated report saved to {output_path}")
    return analysis
