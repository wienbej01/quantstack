# L2 Scalping System Design

**Version**: 1.0  
**Created**: 2025-12-20  
**Based on**: L2_SCALPING_SYSTEM_FOUNDATION.md analysis

## System Architecture

```
l2_scalping/
├── src/
│   ├── signals/          # L2 signal generation
│   ├── execution/        # Order management
│   ├── risk/            # Risk management
│   ├── data/            # Data handling
│   └── main.py          # Main trading loop
├── config/
│   ├── symbols.yaml     # Symbol configuration
│   ├── strategy.yaml    # Strategy parameters
│   └── risk.yaml        # Risk parameters
├── tests/               # Unit tests
├── docs/               # Documentation
├── data/               # Local data cache
└── logs/               # System logs
```

## Core Components

### 1. Signal Engine (`src/signals/`)
- `l2_signals.py` - OBI momentum, hidden liquidity detection
- `regime_detector.py` - Market regime classification
- `signal_aggregator.py` - Combine signals into trading decisions

### 2. Execution Engine (`src/execution/`)
- `order_manager.py` - IBKR order placement and management
- `position_tracker.py` - Track positions and P&L
- `execution_optimizer.py` - Timing and sizing optimization

### 3. Risk Management (`src/risk/`)
- `risk_manager.py` - Per-trade and daily risk limits
- `position_sizer.py` - Dynamic position sizing
- `circuit_breaker.py` - Emergency stop mechanisms

### 4. Data Pipeline (`src/data/`)
- `l2_feed.py` - Real-time L2 data processing
- `feature_engine.py` - Real-time feature computation
- `data_validator.py` - Data quality checks

## Implementation Plan

### Phase 1: Core Infrastructure (Day 1-2)
1. Signal generation from L2 features
2. Mock execution engine for testing
3. Basic risk management
4. Configuration system

### Phase 2: IBKR Integration (Day 3-4)
1. Real-time L2 data feed
2. Order placement via IBKR API
3. Position tracking
4. Paper trading validation

### Phase 3: Production Ready (Day 5-7)
1. Performance optimization
2. Monitoring and alerting
3. Error handling and recovery
4. Documentation and testing

## Key Design Principles

1. **Modular**: Each component can be tested independently
2. **Configurable**: All parameters externalized to YAML files
3. **Observable**: Comprehensive logging and metrics
4. **Resilient**: Graceful error handling and recovery
5. **Fast**: Sub-50ms signal-to-order latency target

## Risk Controls

1. **Per-trade stop loss**: 10 bps maximum
2. **Daily loss limit**: 100 bps circuit breaker
3. **Position limits**: 1% of account per trade
4. **Thin book detection**: Automatic size reduction
5. **Connection monitoring**: Auto-flatten on disconnect

## Configuration Management

All strategy parameters will be externalized:
- Signal thresholds per symbol
- Risk limits and position sizing
- Execution preferences
- Logging and monitoring settings

## Testing Strategy

1. **Unit tests**: Each component tested in isolation
2. **Integration tests**: End-to-end signal-to-order flow
3. **Backtesting**: Historical L2 data validation
4. **Paper trading**: Live market validation before production
