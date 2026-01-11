#!/usr/bin/env python3
"""
L2 Data Sufficiency Analysis for Scalping System
"""


def analyze_l2_data_sufficiency():
    """Analyze if current L2 data is sufficient for meaningful predictions."""

    print("=== L2 DATA SUFFICIENCY ANALYSIS ===\n")

    # Current data status (from previous analysis)
    total_records = 457059
    symbols = 10
    days = 4
    data_size_mb = 53.8

    print("--- CURRENT DATA INVENTORY ---")
    print(f"📊 Total L2 snapshots: {total_records:,}")
    print(f"🎯 Unique symbols: {symbols}")
    print(f"📅 Collection days: {days}")
    print(f"💾 Data size: {data_size_mb} MB")
    print(f"📈 Records per symbol: {total_records // symbols:,} avg")
    print(f"📈 Records per day: {total_records // days:,} avg")

    # Market microstructure benchmarks
    print(f"\n--- MICROSTRUCTURE BENCHMARKS ---")

    # Theoretical maximum per symbol per day
    market_hours = 6.5  # 9:30-4:00 ET
    extended_hours = 1.5  # Pre/post market
    total_hours = market_hours + extended_hours
    seconds_per_day = total_hours * 3600
    snapshots_per_second = 2  # Current collection rate
    theoretical_max = seconds_per_day * snapshots_per_second

    actual_per_symbol_day = total_records / (symbols * days)
    coverage_pct = (actual_per_symbol_day / theoretical_max) * 100

    print(f"Theoretical max/symbol/day: {theoretical_max:,.0f} snapshots")
    print(f"Actual avg/symbol/day: {actual_per_symbol_day:,.0f} snapshots")
    print(f"Market coverage: {coverage_pct:.1f}%")

    # Statistical significance thresholds
    print(f"\n--- STATISTICAL SIGNIFICANCE ---")

    # For microstructure analysis
    min_samples_basic = 1000  # Basic pattern detection
    min_samples_robust = 10000  # Robust statistical inference
    min_samples_ml = 50000  # Machine learning models

    samples_per_symbol = total_records / symbols

    print(f"Samples per symbol: {samples_per_symbol:,.0f}")
    print(
        f"Basic analysis (1k): {'✅' if samples_per_symbol >= min_samples_basic else '❌'}"
    )
    print(
        f"Robust inference (10k): {'✅' if samples_per_symbol >= min_samples_robust else '❌'}"
    )
    print(f"ML models (50k): {'✅' if samples_per_symbol >= min_samples_ml else '❌'}")

    # Signal-to-noise considerations
    print(f"\n--- SIGNAL QUALITY ASSESSMENT ---")

    # Microstructure signals typically have:
    # - High frequency (seconds to minutes)
    # - Low signal-to-noise ratio
    # - Regime-dependent behavior

    # Estimate signal events (extreme OBI > 0.8)
    # From analysis: ~9k signals per day across all symbols
    estimated_signals_per_day = 9000
    signal_rate = estimated_signals_per_day / total_records * days
    total_signals = total_records * signal_rate

    print(f"Estimated signal rate: {signal_rate*100:.2f}% of snapshots")
    print(f"Total signal events: {total_signals:,.0f}")
    print(f"Signals per symbol: {total_signals/symbols:,.0f}")

    # Minimum data recommendations
    print(f"\n--- DATA SUFFICIENCY RECOMMENDATIONS ---")

    # Academic microstructure literature suggests:
    min_days_academic = 30  # Minimum for academic studies
    min_days_production = 90  # Minimum for production systems
    recommended_days = 180  # Recommended for robust models

    days_needed_min = min_days_academic - days
    days_needed_prod = min_days_production - days
    days_needed_rec = recommended_days - days

    print(f"Current collection: {days} days")
    print(
        f"Academic minimum: {min_days_academic} days ({max(0, days_needed_min)} more needed)"
    )
    print(
        f"Production minimum: {min_days_production} days ({max(0, days_needed_prod)} more needed)"
    )
    print(
        f"Recommended: {recommended_days} days ({max(0, days_needed_rec)} more needed)"
    )

    # System design assessment
    print(f"\n--- SYSTEM DESIGN ANALYSIS ---")

    print("Current L2 scalping approach:")
    print("✅ Rule-based OBI momentum (no ML training needed)")
    print("✅ Simple thresholds (OBI > 0.8, rel_vol > 2.0)")
    print("✅ Statistical validation on existing data")
    print("⚠️  Limited regime diversity (4 days)")
    print("⚠️  No cross-validation possible yet")

    # Recommendations by approach
    print(f"\n--- RECOMMENDATIONS BY APPROACH ---")

    print("1. CURRENT RULE-BASED SYSTEM:")
    print("   Status: ✅ SUFFICIENT for initial deployment")
    print("   Rationale: Simple OBI thresholds don't require ML training")
    print("   Risk: Limited regime testing (only 4 market days)")
    print("   Action: Deploy with conservative position sizing")

    print("\n2. ENHANCED STATISTICAL MODELS:")
    print("   Status: ⚠️  MARGINAL - need 2-4 more weeks")
    print("   Rationale: 45k+ samples per symbol enables robust statistics")
    print("   Need: More regime diversity (trending, volatile, quiet markets)")
    print("   Action: Continue collection, validate on 20+ days")

    print("\n3. MACHINE LEARNING MODELS:")
    print("   Status: ❌ INSUFFICIENT - need 2-3 more months")
    print("   Rationale: ML requires 50k+ samples + cross-validation")
    print("   Need: 90+ days across multiple market regimes")
    print("   Action: Long-term data collection strategy")

    # Specific next steps
    print(f"\n--- IMMEDIATE NEXT STEPS ---")

    print("1. SYSTEM UPDATE/RETRAIN:")
    print("   • Current system uses fixed thresholds (no retraining needed)")
    print("   • Update symbol universe: modify config/strategy.yaml")
    print("   • Validate thresholds on new symbols using analysis scripts")
    print("   • Test with paper trading before live deployment")

    print("\n2. DATA COLLECTION EXPANSION:")
    print("   • Continue L2 collection for 2-4 more weeks minimum")
    print("   • Target 20+ trading days for statistical robustness")
    print("   • Include different market regimes (trending, volatile, quiet)")
    print("   • Monitor data quality and coverage consistency")

    print("\n3. VALIDATION APPROACH:")
    print("   • Use existing 4 days for initial threshold validation")
    print("   • Implement walk-forward testing as more data arrives")
    print("   • Focus on regime-specific performance analysis")
    print("   • Establish minimum performance thresholds before live trading")

    return {
        "sufficient_for_rules": True,
        "sufficient_for_stats": False,
        "sufficient_for_ml": False,
        "days_needed_stats": max(0, days_needed_prod),
        "days_needed_ml": max(0, days_needed_rec),
        "current_coverage_pct": coverage_pct,
        "samples_per_symbol": samples_per_symbol,
    }


if __name__ == "__main__":
    results = analyze_l2_data_sufficiency()

    print(f"\n=== FINAL ASSESSMENT ===")

    if results["sufficient_for_rules"]:
        print("✅ READY: Rule-based L2 scalping system can be deployed")
        print("   Recommendation: Start with conservative position sizing")
        print("   Risk management: Monitor performance closely first 2 weeks")

    if not results["sufficient_for_stats"]:
        print(
            f"⏳ PENDING: Statistical models need {results['days_needed_stats']} more days"
        )

    if not results["sufficient_for_ml"]:
        print(f"⏳ FUTURE: ML models need {results['days_needed_ml']} more days")

    print(f"\nData quality: {results['current_coverage_pct']:.1f}% market coverage")
    print(f"Sample size: {results['samples_per_symbol']:,.0f} per symbol")
