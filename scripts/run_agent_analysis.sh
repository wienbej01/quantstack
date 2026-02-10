#!/bin/bash
# Orchestration script to run specialized agents for comprehensive analysis

OUTPUT_DIR="/home/jacobw/quantstack/reports/agent_analysis_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "🚀 Starting comprehensive analysis with specialized agents..."
echo "📁 Output directory: $OUTPUT_DIR"
echo ""

# Task 1: Systemd duplication and bloat
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Task 1: Analyzing systemd services for duplication and bloat"
echo "Agent: code-bloat-auditor"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Audit /etc/systemd/system for trading services (l2-scalping, l2-vwap-reversion, l2-collector, l2-health-monitor, l2-watchdog). Check for duplicate configurations, unused parameters, and unnecessary complexity. Provide specific recommendations." | \
  kiro-cli chat --agent code-bloat-auditor > "$OUTPUT_DIR/1_systemd_bloat_analysis.txt" 2>&1 &
PID1=$!

# Task 2: Documentation alignment
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Task 2: Checking code-documentation alignment"
echo "Agent: documentation-consolidator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Check ~/quantstack/docs for alignment with current implementation. Find outdated docs, duplicate content, and missing documentation for l2_scalping, l2_vwap_reversion, and qx-* packages." | \
  kiro-cli chat --agent documentation-consolidator > "$OUTPUT_DIR/2_documentation_alignment.txt" 2>&1 &
PID2=$!

# Task 3: Temporal compliance
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Task 3: Validating temporal compliance"
echo "Agent: market-reality-validator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Review ~/quantstack/l2_scalping/src/strategy and ~/quantstack/l2_vwap_reversion/src/strategy for temporal violations. Check signal generation, feature engineering for look-ahead bias. Verify no future data leakage." | \
  kiro-cli chat --agent market-reality-validator > "$OUTPUT_DIR/3_temporal_compliance.txt" 2>&1 &
PID3=$!

echo ""
echo "⏳ Running agents in parallel..."
echo "   PID $PID1: code-bloat-auditor"
echo "   PID $PID2: documentation-consolidator"
echo "   PID $PID3: market-reality-validator"
echo ""

# Wait for all agents to complete
wait $PID1
echo "✅ Task 1 complete: systemd bloat analysis"

wait $PID2
echo "✅ Task 2 complete: documentation alignment"

wait $PID3
echo "✅ Task 3 complete: temporal compliance"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ All agent analyses complete!"
echo "📁 Results saved to: $OUTPUT_DIR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "View results:"
echo "  cat $OUTPUT_DIR/1_systemd_bloat_analysis.txt"
echo "  cat $OUTPUT_DIR/2_documentation_alignment.txt"
echo "  cat $OUTPUT_DIR/3_temporal_compliance.txt"
