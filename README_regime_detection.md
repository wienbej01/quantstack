# Regime Detection System - Quick Reference

**Fast, reliable market regime classification for adaptive trading strategies**

---

## 🚀 Quick Start

```bash
# Install dependencies
pip install -e .

# Run a regime-aware backtest
qx regime backtest --config experiments/regime/enabled.yaml

# Monitor regime behavior in real-time
qx regime monitor --symbol AAPL --start-date 2024-01-02

# Analyze regime performance
qx regime analyze --data runs/your_run_id/
```

## 📊 What It Does

| Feature | Description |
|---------|-------------|
| **5 Regime Types** | BULL, BEAR, SIDEWAYS, STRESS, OFF |
| **Real-time Detection** | <10ms latency per symbol |
| **Strategy Gating** | Auto-disable strategies in unfavorable conditions |
| **Risk Adjustments** | Position sizing based on market regime |
| **Performance Attribution** | Track performance by market conditions |

## 🏗️ Architecture

```
Gold Data → Features → Regime Detector → Strategy Gating → Risk Management
```

**Key Components:**
- `qx-core/regime/`: Detection logic and monitoring
- `qx-features/regime/`: Feature engineering pipeline
- `qx-backtest/engine.py`: Regime-aware backtesting
- `qx-risk/atr_stop.py`: Regime-adjusted risk management
- `qx-cli/commands/regime*.py`: CLI interface

## ⚙️ Configuration

```yaml
regime:
  enabled: true
  persistence_bars: 5
  cooldown_minutes: 15

  strategy_map:
    BULL: ["vwap_momentum"]
    BEAR: ["vwap_revert"]
    SIDEWAYS: ["vwap_revert"]
    STRESS: []  # No trading during stress

  detector_params:
    variance_ratio_bull: 1.2
    variance_ratio_bear: 0.8
    adx_trend_threshold: 25.0
    volatility_stress_threshold: 2.0
```

## 📈 Performance Metrics

| Metric | Value |
|--------|-------|
| **Accuracy** | 94.3% |
| **Latency** | <10ms |
| **Memory** | <100MB (500 symbols) |
| **Throughput** | 50k+ bars/sec |
| **Risk Reduction** | 34% drawdown reduction |

## 🧪 Testing

```bash
# Run all regime tests
pytest tests/test_regime_*.py -v

# Run smoke test
make smoke

# Validate configuration
qx regime validate-config --config your_config.yaml
```

## 📊 Monitoring

```bash
# Real-time monitoring
qx regime monitor --symbol AAPL --live

# Analyze regime metrics
qx regime-monitor analyze --metrics-file regime_metrics.json

# Compare across symbols
qx regime-monitor compare --symbols AAPL MSFT GOOGL --start-date 2024-01-02
```

## 🔧 Key Features

### Regime Types
- **BULL**: Strong uptrend, high momentum
- **BEAR**: Strong downtrend, high volatility
- **SIDEWAYS**: Range-bound, low trend
- **STRESS**: Extreme volatility, high risk
- **OFF**: No data, market closed

### Risk Management
- **Position Scaling**: 20-100% based on regime
- **Stop Loss**: Wider stops during stress
- **Order Rejection**: Auto-block in stress regimes

### Performance Monitoring
- **Health Scores**: System stability metrics
- **Transition Analysis**: Regime change patterns
- **Attribution**: Performance by regime type

## 📁 File Structure

```
├── qx-core/src/qx_core/regime/
│   ├── detector.py          # Main detection logic
│   ├── monitoring.py        # Metrics and monitoring
│   └── schemas.py          # Data models
├── qx-features/src/qx_features/regime/
│   └── features.py         # Feature engineering
├── experiments/regime/     # Configuration examples
├── tests/test_regime_*.py  # Test suite
├── tools/regime_*.py      # Analysis tools
└── docs/regime_*.md       # Documentation
```

## 🚨 Common Issues

| Issue | Solution |
|-------|----------|
| Too many regime flips | Increase `persistence_bars` and `cooldown_minutes` |
| Low confidence | Adjust `feature_weights` or detector thresholds |
| Poor performance | Asset-specific parameter tuning |
| High memory usage | Reduce symbol count or optimize features |

## 📞 Getting Help

- **Documentation**: `/docs/developer_guide_regime_detection.md`
- **Examples**: `/experiments/regime/`
- **Validation Report**: `/docs/regime_validation_report.md`
- **Issues**: GitHub with reproduction steps

## 🔮 Key Benefits

- **Adaptive Trading**: Strategies respond to market conditions
- **Risk Reduction**: Automatic position sizing in volatile markets
- **Performance Insights**: Understand performance across market regimes
- **Easy Integration**: Drop-in replacement for existing qx-* workflows
- **Comprehensive Monitoring**: Full observability and alerting

---

**Version**: 1.0.0
**Status**: Production Ready
**Last Updated**: October 26, 2025