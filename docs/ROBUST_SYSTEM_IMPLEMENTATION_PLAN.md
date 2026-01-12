# ROBUST PATTERN DISCOVERY SYSTEM - IMPLEMENTATION PLAN

**Goal:** Build a system that produces 1-3 AAA-grade strategies monthly with high OOS success rate

**Target Metrics:**
- OOS Win Rate: >60% of deployed strategies profitable
- Capital Preservation: Max 2% drawdown per strategy
- Recalibration: Monthly with 3-period validation

---

## PHASE 1: CORE FILTERING (Week 1)

### 1.1 Overfitting Detector
**File:** `sip_pattern_discovery/src/overfitting_filter.py`

```python
def is_overfit(pattern: dict) -> tuple[bool, str]:
    """Reject patterns with extreme metrics"""
    if pattern['win_rate'] > 0.65:
        return True, "Win rate too high (>65%)"
    if pattern['sharpe'] > 3.0:
        return True, "Sharpe too high (>3.0)"
    if pattern['expectancy'] > 0.10:
        return True, "Expectancy too high (>0.10%)"
    if pattern['n_samples'] < 10000:
        return True, "Insufficient samples (<10k)"
    return False, "PASS"
```

### 1.2 Regime Filter
**File:** `sip_pattern_discovery/src/regime_filter.py`

```python
def get_current_regime(spy_data: pd.DataFrame) -> str:
    """Detect current SPY regime"""
    # bull/bear: SPY vs SMA50
    # high/low vol: VIX or realized vol
    return regime  # e.g., "bull_high_vol"

def matches_regime(pattern: dict, current_regime: str) -> bool:
    """Only allow patterns from matching regime"""
    return pattern['regime'] == current_regime
```

### 1.3 Event-Only Filter
**File:** `sip_pattern_discovery/src/pattern_filter.py`

```python
def is_event_based(rule: str) -> bool:
    """Require time-constrained conditions"""
    event_keywords = ['is_first_hour', 'is_power_hour', 'at_session_low', 'at_session_high']
    return any(kw in rule for kw in event_keywords)
```

**Deliverable:** Scanner rejects 80%+ of patterns, only surfaces AAA candidates

---

## PHASE 2: TEMPORAL VALIDATION (Week 2)

### 2.1 3-Period Split
**File:** `sip_pattern_discovery/src/temporal_split.py`

```python
def split_data(df: pd.DataFrame, scan_months: int = 7, val_months: int = 2):
    """Split into scan/validation/oos periods"""
    # Scan: months 1-7
    # Validation: months 8-9
    # OOS: month 10
    return scan_df, val_df, oos_df
```

### 2.2 Validation Gate
**File:** `sip_pattern_discovery/src/validation_gate.py`

```python
def passes_validation(scan_metrics: dict, val_metrics: dict) -> bool:
    """Check degradation limits"""
    wr_drop = abs(scan_metrics['win_rate'] - val_metrics['win_rate'])
    if wr_drop > 0.10:  # >10% absolute drop
        return False
    
    exp_drop = 1 - (val_metrics['expectancy'] / scan_metrics['expectancy'])
    if exp_drop > 0.50:  # >50% relative drop
        return False
    
    if val_metrics['n_trades'] < 20:  # Insufficient validation trades
        return False
    
    return True
```

**Deliverable:** Only patterns that pass validation gate proceed to OOS

---

## PHASE 3: AAA SCORING (Week 3)

### 3.1 Composite Score
**File:** `sip_pattern_discovery/src/aaa_scorer.py`

```python
def calculate_aaa_score(pattern: dict, current_regime: str) -> float:
    """Composite score favoring moderate metrics"""
    
    # T-stat component (25-40 optimal)
    t_score = min(pattern['t_stat'] / 40.0, 1.0)
    
    # Win rate penalty for extremes (54% optimal)
    wr_penalty = 1 - abs(pattern['win_rate'] - 0.54) / 0.54
    
    # Sharpe cap at 2.0
    sharpe_score = min(pattern['sharpe'] / 2.0, 1.0)
    
    # Regime match bonus
    regime_bonus = 1.5 if pattern['regime'] == current_regime else 0.5
    
    # Sample size bonus
    sample_score = min(pattern['n_samples'] / 50000, 1.0)
    
    return t_score * wr_penalty * sharpe_score * regime_bonus * sample_score
```

**Deliverable:** Patterns ranked by AAA score, not raw t-stat

---

## PHASE 4: LLM ENHANCEMENT (Week 3)

### 4.1 Updated LLM Prompt
**File:** `sip_pattern_discovery/src/llm_analysis.py`

Add to prompt:
```
CRITICAL OVERFITTING CHECKS:
1. Flag any pattern with win_rate > 65% as "HIGH OVERFIT RISK"
2. Flag any pattern with sharpe > 3.0 as "EXTREME METRICS - SUSPECT"
3. Flag any pattern with n_samples < 10,000 as "INSUFFICIENT DATA"
4. Verify regime matches current market (check SPY regime)
5. Require clear causal mechanism, reject statistical artifacts

DEGRADATION RISK SCORE:
Risk = (win_rate - 0.50) * 2 + (sharpe - 1.5) * 0.5 + (expectancy - 0.03) * 10
If Risk > 1.0: REJECT pattern

Only approve patterns with:
- Moderate metrics (not extreme)
- Clear economic rationale
- Regime alignment
- Event-based conditions
```

**Deliverable:** LLM rejects 60%+ of patterns with quantitative reasoning

---

## PHASE 5: MONTHLY PIPELINE (Week 4)

### 5.1 Automated Monthly Workflow
**File:** `sip_pattern_discovery/run_monthly_discovery.py`

```python
def monthly_discovery_pipeline():
    """Full pipeline with 3-period validation"""
    
    # 1. Detect current regime
    current_regime = get_current_regime(spy_data)
    
    # 2. Split data (7 months scan, 2 months validation)
    scan_df, val_df = split_data(full_data)
    
    # 3. Run discovery on scan period
    patterns = discover_patterns(scan_df)
    
    # 4. Apply filters
    patterns = [p for p in patterns if is_event_based(p['rule'])]
    patterns = [p for p in patterns if not is_overfit(p)[0]]
    patterns = [p for p in patterns if matches_regime(p, current_regime)]
    
    # 5. Validate on holdout period
    validated = []
    for p in patterns:
        val_metrics = backtest_pattern(p, val_df)
        if passes_validation(p, val_metrics):
            validated.append(p)
    
    # 6. Rank by AAA score
    validated.sort(key=lambda p: calculate_aaa_score(p, current_regime), reverse=True)
    
    # 7. LLM analysis on top 10
    top_patterns = validated[:10]
    llm_approved = llm_filter(top_patterns, current_regime)
    
    # 8. Deploy top 1-3 for OOS
    return llm_approved[:3]
```

### 5.2 Staleness Monitor
**File:** `pattern_backtest/src/staleness_monitor.py`

```python
def check_staleness(strategy: dict, live_metrics: dict) -> bool:
    """Detect if pattern has decayed"""
    
    # Win rate drift
    if abs(live_metrics['win_rate'] - strategy['win_rate']) > 0.05:
        return True  # Stale
    
    # Trade frequency anomaly
    expected_trades = strategy['expected_trades_per_day']
    if live_metrics['trades_per_day'] < 0.5 * expected_trades:
        return True  # Stale
    
    # Consecutive losses
    if live_metrics['consecutive_losses'] > 5:
        return True  # Stale
    
    return False  # Still fresh
```

**Deliverable:** Automated monthly discovery + staleness detection

---

## PHASE 6: PRODUCTION INTEGRATION (Week 5)

### 6.1 Monthly Schedule
```
Day 1-3:   Run discovery pipeline (scan + validation)
Day 4-5:   LLM analysis + risk review
Day 6-7:   Deploy top 1-3 strategies for OOS
Day 8-30:  Monitor live performance + staleness
Day 31:    Recalibrate (new scan period)
```

### 6.2 Configuration
**File:** `sip_pattern_discovery/config/aaa_config.yaml`

```yaml
aaa_criteria:
  t_stat_range: [25, 40]
  win_rate_range: [0.50, 0.58]
  sharpe_range: [1.0, 2.5]
  expectancy_range: [0.02, 0.06]
  min_samples: 20000
  require_event_based: true
  require_regime_match: true

temporal_periods:
  scan_months: 7
  validation_months: 2
  oos_months: 1
  recalibration_frequency: "monthly"

validation_gates:
  max_win_rate_drop: 0.10
  max_expectancy_drop_pct: 0.50
  min_validation_trades: 20

deployment:
  max_strategies: 3
  position_size_per_strategy: 100
  max_positions_per_strategy: 5
```

**Deliverable:** Production-ready monthly discovery system

---

## SUCCESS METRICS

### System-Level KPIs
- **OOS Success Rate:** >60% of deployed strategies profitable
- **Average Strategy Lifespan:** 2-4 months before recalibration
- **Monthly Strategy Count:** 1-3 AAA strategies
- **Capital Preservation:** <2% max drawdown per strategy

### Quality Gates
- **Scan → Validation Pass Rate:** 10-20% (strict filtering)
- **Validation → OOS Pass Rate:** 60-80% (robust patterns)
- **LLM Approval Rate:** 30-50% of validated patterns

---

## ROLLOUT TIMELINE

| Week | Phase | Deliverable |
|------|-------|-------------|
| 1 | Core Filtering | Overfitting + Regime + Event filters |
| 2 | Temporal Validation | 3-period split + validation gate |
| 3 | AAA Scoring + LLM | Composite score + enhanced LLM |
| 4 | Monthly Pipeline | Automated discovery workflow |
| 5 | Production | Live deployment + monitoring |

**Go-Live:** Week 6 with first monthly discovery run

---

## NEXT STEPS

1. Review and approve plan
2. Create feature branches for each phase
3. Implement Phase 1 (Core Filtering) first
4. Test on historical data (2024) before production
5. Deploy with paper trading for 1 month validation
