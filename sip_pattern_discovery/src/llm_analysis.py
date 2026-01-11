"""LLM analysis integration for pattern interpretation."""

import os
from pathlib import Path

import pandas as pd


def format_patterns_for_llm(
    patterns_df: pd.DataFrame, target_name: str, top_n: int = 20
) -> str:
    """Format discovered patterns for LLM analysis.

    Args:
        patterns_df: DataFrame with discovered patterns
        target_name: Name of the target (e.g., "up_60m")
        top_n: Number of top patterns to include

    Returns:
        Formatted string for LLM prompt
    """
    top_patterns = patterns_df.head(top_n)

    output = f"# Discovered Patterns for Target: {target_name}\n\n"
    output += f"Total patterns found: {len(patterns_df)}\n"
    output += f"Showing top {len(top_patterns)} patterns\n\n"

    for idx, row in top_patterns.iterrows():
        output += f"## Pattern {idx + 1}\n"
        output += f"**Rule:** {row['rule']}\n"
        output += f"**Lift:** {row['lift']:.2f}x\n"
        output += (
            f"**Support:** {row['support']:.2%} ({int(row['n_samples'])} samples)\n"
        )
        output += f"**P-value:** {row['p_value']:.2e}\n"
        output += f"**Baseline rate:** {row['baseline_rate']:.2%}\n\n"

    return output


def generate_llm_prompt(patterns_text: str, target_name: str, horizon: int) -> str:
    """Generate LLM prompt for pattern interpretation.

    Args:
        patterns_text: Formatted patterns text
        target_name: Target name
        horizon: Forward horizon in minutes

    Returns:
        LLM prompt string
    """
    prompt = f"""You are analyzing trading patterns discovered from 1-minute SIP-filtered stock data.
These patterns predict {horizon}-minute forward returns.

Target: {target_name}
Horizon: {horizon} minutes
Discovery Period: June-July 2024 (training data)

{patterns_text}

CRITICAL ANALYSIS REQUIRED FOR EACH PATTERN:

1. **FALSE POSITIVE ANALYSIS**: During June-July 2024, estimate how often this pattern triggered but FAILED to deliver the expected move. Consider:
   - How many times would this pattern have fired?
   - What percentage were false positives?
   - Is the success rate realistic or overfitted?

2. **OVERTRADING RISK**: If deployed live, how many trades per day would this generate?
   - Support rate × daily bars = daily trigger frequency
   - Would this cause excessive trading costs?

3. **REGIME ROBUSTNESS**: Would this pattern work in:
   - Bear markets vs bull markets?
   - High volatility vs low volatility periods?
   - Different sector rotations?

4. **ECONOMIC RATIONALE**: What market microstructure explains this pattern?
   - Is there a logical reason institutions/algorithms would create this edge?
   - Or is this likely a statistical artifact?

5. **GO/NO-GO DECISION**: 
   - GO: Only if lift ≥10x, support ≤0.2%, low false positive rate, clear economic rationale
   - NO-GO: If any red flags for overtrading, overfitting, or lack of economic logic

Be extremely skeptical. Reject 90% of patterns to prevent overtrading.
"""

    return prompt


def call_llm_api(prompt: str, api_key: str | None = None) -> str:
    """Call LLM API for pattern analysis.

    Args:
        prompt: LLM prompt
        api_key: Optional API key (reads from env if not provided)

    Returns:
        LLM response text
    """
    # Check for API key
    if api_key is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get(
            "OPENAI_API_KEY"
        )

    if not api_key:
        return "# LLM Analysis Skipped\n\nNo API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."

    system_prompt = """You are a senior quantitative researcher at a top-tier hedge fund. Your job is to REJECT 90% of proposed patterns to prevent overtrading and ensure only the most exceptional opportunities are traded.

CRITICAL ANTI-OVERTRADING MANDATE:
- Target: Maximum 10 positions per day across ALL patterns
- Reject ANY pattern that could cause frequent trading
- Only approve patterns with 10x+ lift AND rare occurrence
- Consider this a QUALITY OVER QUANTITY exercise

CONFIRMATION BIAS ANALYSIS REQUIRED:
For each pattern, you MUST analyze:
1. FALSE POSITIVES: How often did this pattern trigger but NOT deliver the expected move during the discovery period?
2. OVERFITTING RISK: Does this pattern seem too specific to the training data?
3. REGIME DEPENDENCY: Would this pattern fail in different market conditions?
4. EXECUTION REALITY: Can this actually be traded profitably after slippage/commissions?

REJECTION CRITERIA (Reject if ANY apply):
- Lift < 10x (we need exceptional moves only)
- Support > 0.5% (too frequent = overtrading)
- Pattern seems overfit to specific market events
- High false positive rate during discovery period
- Relies on hard-to-execute timing
- Would generate >5 trades per day if deployed

APPROVAL CRITERIA (ALL must be met):
- Lift ≥ 10x with high statistical significance
- Support ≤ 0.2% (rare occurrence)
- Clear economic rationale (not just statistical artifact)
- Low false positive rate during discovery period
- Robust across different market regimes
- Executable with realistic slippage

For each pattern, you must give a Go/No-go decision with specific analysis of false positives and overtrading risk."""

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
            return f"# LLM Analysis Failed\n\nError calling Anthropic API: {e}"

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
            return (
                response.choices[0].message.content
                or "# LLM Analysis Failed\n\nEmpty response from API"
            )
        except Exception as e:
            return f"# LLM Analysis Failed\n\nError calling OpenAI API: {e}"

    return "# LLM Analysis Skipped\n\nNo compatible API key found."


def analyze_patterns_with_llm(
    patterns_df: pd.DataFrame,
    target_name: str,
    horizon: int,
    output_path: Path,
    top_n: int = 20,
) -> str:
    """Analyze patterns using LLM and save report.

    Args:
        patterns_df: DataFrame with discovered patterns
        target_name: Target name
        horizon: Forward horizon in minutes
        output_path: Path to save markdown report
        top_n: Number of top patterns to analyze

    Returns:
        LLM analysis text
    """
    print(f"Formatting top {top_n} patterns for LLM analysis...")
    patterns_text = format_patterns_for_llm(patterns_df, target_name, top_n)

    print("Generating LLM prompt...")
    prompt = generate_llm_prompt(patterns_text, target_name, horizon)

    print("Calling LLM API...")
    analysis = call_llm_api(prompt)

    # Save report
    report = "# Pattern Analysis Report\n\n"
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
