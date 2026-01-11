# Pattern Scanner & Backtest Development Plan

## CRITICAL ISSUE: Overtrading (26,611 trades/month)

**Root Cause**: Scanner criteria too loose, generating 1,200 trades/day vs target 10/day
**Solution**: Ultra-strict criteria + false positive analysis + anti-overtrading LLM

## Phase 1: Scanner Fixes (COMPLETED)

### 1.1 Fix Technical Issues ✅
- **Fixed**: `NameError: name 'pd' is not defined` in discover.py line 207
- **Fixed**: Import organization and type annotations
- **Status**: Scanner runs without errors

### 1.2 Ultra-Strict Criteria ✅
- **Min Lift**: 10.0x (was 3.0x) - only exceptional moves
- **Min Support**: 0.002 (0.2%) - rare patterns only (~10 trades/day)
- **Max P-value**: 0.000001 - extremely significant
- **Max Patterns**: 2 per direction (was 10) - ultra selective
- **File**: `sip_pattern_discovery/run_long_short_discovery.py`

### 1.3 Anti-Overtrading LLM Prompts ✅
- **System Prompt**: Reject 90% of patterns, target 10 positions/day max
- **User Prompt**: Mandatory false positive analysis during discovery period
- **Criteria**: Must analyze overtrading risk, regime robustness, economic rationale
- **File**: `sip_pattern_discovery/src/llm_analysis.py`

## Phase 2: Execute & Validate (NEXT)

### 2.1 Run Updated Scanner
```bash
cd /home/jacobw/quantstack/sip_pattern_discovery
.venv/bin/python3 run_long_short_discovery.py
```

**Expected Output:**
- 2 LONG patterns max (10x+ lift, 0.2% support)
- 2 SHORT patterns max (10x+ lift, 0.2% support)
- LLM analysis with false positive assessment
- Go/No-go decisions for each pattern

### 2.2 Validate Pattern Quality
**Check Criteria:**
- All patterns have lift ≥ 10.0x
- All patterns have support ≤ 0.2%
- LLM provides false positive analysis
- LLM estimates daily trade frequency
- Clear economic rationale for each pattern

**Files to Review:**
- `output_high_quality/patterns_up_180m.csv`
- `output_high_quality/patterns_down_180m.csv`
- `output_high_quality/llm_analysis_180m.md`

## Phase 3: Backtest Integration

### 3.1 Replace Manual Patterns
**Current**: 3 manual patterns (high ATR, momentum, volume + power hour)
**New**: Use discovered patterns from Phase 2

**Steps:**
1. Parse discovered patterns from CSV
2. Generate pattern evaluators
3. Update `pattern_backtest/src/manual_patterns.py`
4. Test pattern evaluation logic

### 3.2 Run Clean Backtest
```bash
cd /home/jacobw/quantstack/pattern_backtest
.venv/bin/python3 test_clean_180m.py
```

**Target Metrics:**
- Total trades: <3,000 (vs 26,611)
- Daily trades: ~10 (vs 1,200)
- Avg P&L: >$0.10 (vs $0.01)
- Win rate: >45%

### 3.3 Validate Trade Count
**Calculation**: Support rate × bars per day × trading days
- Support 0.2% × 390 bars/day × 22 days = ~17 trades/month
- Target: <100 trades/month across all patterns

## Phase 4: Quality Assurance

### 4.1 False Positive Analysis
**Manual Review**:
- Check pattern triggers during June-July 2024
- Estimate false positive rate
- Validate LLM analysis accuracy
- Confirm economic rationale

### 4.2 Regime Testing
**Stress Test Patterns**:
- Bull market periods
- Bear market periods  
- High volatility periods
- Different sector rotations
- Earnings seasons

### 4.3 Implementation Reality Check
**Execution Considerations**:
- Slippage impact on 10x lift
- Commission costs
- Market impact
- Timing precision requirements

## Phase 5: Deployment Preparation

### 5.1 Pattern Integration
**Update Live System**:
- Replace current patterns with discovered patterns
- Update pattern evaluation logic
- Test pattern triggering
- Validate position sizing

### 5.2 Monitoring Setup
**Track Key Metrics**:
- Daily trade count
- Pattern hit rate
- False positive rate
- P&L per pattern
- Overtrading alerts

## Critical Success Criteria

### Scanner Quality Gates
1. **Pattern Count**: ≤4 total patterns (2 long + 2 short)
2. **Lift Threshold**: All patterns ≥10x lift
3. **Support Threshold**: All patterns ≤0.2% support
4. **LLM Analysis**: False positive assessment for each pattern
5. **Economic Rationale**: Clear microstructure explanation

### Backtest Quality Gates
1. **Trade Count**: <3,000 trades/year (vs 26,611/month)
2. **Daily Frequency**: ~10 trades/day (vs 1,200/day)
3. **P&L Quality**: Avg P&L >$0.10 (vs $0.01)
4. **Pattern Attribution**: Each trade tagged with pattern ID
5. **Overnight Logic**: Proper 180-bar exits

### Deployment Quality Gates
1. **No Overtrading**: <100 trades/month across all patterns
2. **High Conviction**: Only exceptional 10x+ moves
3. **Regime Robust**: Works across different market conditions
4. **Executable**: Realistic slippage/commission assumptions
5. **Monitored**: Real-time overtrading detection

## File Locations

### Scanner Files
- `sip_pattern_discovery/run_long_short_discovery.py` - Ultra-strict discovery
- `sip_pattern_discovery/discover.py` - Main discovery engine
- `sip_pattern_discovery/src/llm_analysis.py` - Anti-overtrading prompts
- `sip_pattern_discovery/output_high_quality/` - Results directory

### Backtest Files
- `pattern_backtest/test_clean_180m.py` - Clean backtest implementation
- `pattern_backtest/src/manual_patterns.py` - Pattern definitions (to update)
- `pattern_backtest/src/manual_pattern_policy.py` - qx-backtest integration
- `pattern_backtest/output/` - Backtest results

### Configuration
- Min lift: 10.0x
- Min support: 0.002 (0.2%)
- Max p-value: 0.000001
- Max patterns: 2 per direction
- Target: 10 trades/day max

## Risk Mitigation

### Overtrading Prevention
- Ultra-strict statistical thresholds
- LLM rejection mandate (90% rejection rate)
- Daily trade count monitoring
- Support rate limits (0.2% max)

### Overfitting Prevention
- False positive analysis during discovery period
- Regime robustness testing
- Economic rationale requirement
- Out-of-sample validation (August 2024)

### Implementation Risk
- Realistic slippage assumptions
- Commission impact analysis
- Market impact considerations
- Timing precision requirements

## Next Actions (Post Token Refresh)

1. **Execute Phase 2.1**: Run updated scanner with ultra-strict criteria
2. **Validate Phase 2.2**: Check pattern quality and LLM analysis
3. **Implement Phase 3**: Replace manual patterns and run backtest
4. **Verify Trade Count**: Ensure <3,000 trades/year target met
5. **Deploy Phase 5**: If quality gates passed, update live system
