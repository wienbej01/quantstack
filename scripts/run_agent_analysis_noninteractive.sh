#!/bin/bash
# Non-interactive orchestration script for comprehensive analysis

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
cat << 'EOF' | kiro-cli chat --agent code-bloat-auditor > "$OUTPUT_DIR/1_systemd_bloat_analysis.txt" 2>&1 &
Audit /etc/systemd/system for trading services: l2-scalping.service, l2-vwap-reversion.service, l2-collector.service, l2-health-monitor.service, l2-watchdog.service. 

Check for:
1. Duplicate configurations across services
2. Unused parameters
3. Unnecessary complexity
4. Opportunities for consolidation

Provide specific recommendations with file locations and line numbers.
EOF
PID1=$!

# Task 2: Documentation alignment  
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Task 2: Checking code-documentation alignment"
echo "Agent: documentation-consolidator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'EOF' | kiro-cli chat --agent documentation-consolidator > "$OUTPUT_DIR/2_documentation_alignment.txt" 2>&1 &
Check ~/quantstack/docs for alignment with current implementation.

Find:
1. Outdated docs that contradict current code
2. Duplicate content across multiple docs
3. Missing documentation for: l2_scalping, l2_vwap_reversion, qx-* packages
4. Inconsistent terminology

Check these directories exist and have docs:
- ~/quantstack/l2_scalping/
- ~/quantstack/l2_vwap_reversion/
- ~/quantstack/qx-*/

Provide specific file paths and recommendations.
EOF
PID2=$!

# Task 3: Temporal compliance
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Task 3: Validating temporal compliance"
echo "Agent: market-reality-validator"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
cat << 'EOF' | kiro-cli chat --agent market-reality-validator > "$OUTPUT_DIR/3_temporal_compliance.txt" 2>&1 &
Review trading systems for temporal violations and look-ahead bias.

Check these locations:
- ~/quantstack/l2_scalping/src/
- ~/quantstack/l2_vwap_reversion/src/

Focus on:
1. Signal generation - uses only historical data?
2. Feature engineering - no future data leakage?
3. Order execution - realistic delays modeled?
4. Backtests - proper train/test splits?

Find any files with signal, strategy, features, or backtest in the name.
Report violations with file:line and severity (CRITICAL/HIGH/MEDIUM/LOW).
EOF
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
echo ""
echo "Generate summary report:"
echo "  cat $OUTPUT_DIR/*.txt > $OUTPUT_DIR/FULL_REPORT.txt"
