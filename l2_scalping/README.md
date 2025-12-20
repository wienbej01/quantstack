# L2 Scalping System

A high-frequency scalping system based on Level-2 order book imbalance signals.

## Quick Start

```bash
# 1. Run tests
./run.sh test

# 2. Validate system (requires IBKR connection)
./run.sh validate

# 3. Start paper trading
./run.sh run
```

## System Overview

- **Strategy**: OBI momentum scalping with 5-15 second holds
- **Target**: 15-20 bps per trade
- **Symbols**: PFE (primary), HAL, LUV
- **Risk**: 10 bps stop loss, 100 bps daily limit

## Configuration

### Before Paper Trading

1. **Disable mock data** in `config/strategy.yaml`:
   ```yaml
   mock_data:
     enabled: false  # MUST be false for live trading
   ```

2. **Ensure IBKR paper trading** in `config/ibkr.yaml`:
   ```yaml
   ibkr:
     port: 7497  # Paper trading port
   ```

3. **Start TWS/Gateway** on port 7497 with paper trading account

### Key Configuration Files

- `config/strategy.yaml` - Signal thresholds and symbol settings
- `config/risk.yaml` - Risk limits and position sizing
- `config/ibkr.yaml` - IBKR connection settings

## Architecture

```
src/
├── signals/          # L2 signal generation
│   └── l2_signals.py
├── execution/        # IBKR order management  
│   └── order_manager.py
├── risk/            # Risk management
│   └── risk_manager.py
├── data/            # Market data feed
│   └── l2_feed.py
└── main.py          # Main trading loop
```

## Key Features

### Signal Generation
- **OBI Momentum**: Primary entry signal (threshold ±0.3)
- **Hidden Liquidity**: Institutional flow detection
- **Execution Windows**: Optimal timing for fills
- **Thin Book Warning**: Slippage protection

### Risk Management
- **Per-trade limits**: 10 bps max loss, 1% position size
- **Daily limits**: 100 bps max loss, 100 trades max
- **Circuit breaker**: Auto-stop on consecutive losses
- **Position sizing**: Dynamic based on signal strength

### Execution
- **IOC orders**: Immediate-or-cancel for quick fills
- **IBKR integration**: Paper trading via TWS/Gateway
- **Fill tracking**: Real-time P&L monitoring
- **Auto-exit**: Time and P&L based exits

## Monitoring

System logs to `logs/scalping_system.log` with:
- Signal generation and validation
- Order placement and fills
- Risk metrics and warnings
- System health checks

## Testing

Run comprehensive tests before live trading:

```bash
./run.sh test
```

Tests cover:
- Signal generation accuracy
- Risk limit enforcement
- Circuit breaker functionality
- Mock data feed operation
- End-to-end integration

## Safety Features

1. **Mock data detection**: System warns if mock data enabled
2. **Connection monitoring**: Auto-reconnect on IBKR disconnect
3. **Error handling**: Graceful degradation on errors
4. **Emergency stop**: Manual and automatic shutdown
5. **Position limits**: Hard caps on exposure

## Performance Expectations

Based on analysis of 135k L2 snapshots:

| Metric | Expected Value |
|--------|----------------|
| Win Rate | 20-30% |
| Avg Win | +15-20 bps |
| Avg Loss | -10 bps |
| Signals/Day | ~50-100 |
| Sharpe Ratio | 1.5-2.0 |

## Troubleshooting

### Common Issues

1. **IBKR Connection Failed**
   - Ensure TWS/Gateway running on port 7497
   - Check paper trading account is active
   - Verify client ID not in use

2. **No Signals Generated**
   - Check symbol configuration
   - Verify L2 data subscription
   - Review signal thresholds

3. **Orders Not Filling**
   - Check spread conditions
   - Verify account permissions
   - Review order types (IOC vs LMT)

### Log Analysis

Key log patterns:
- `Signal rejected`: Check validation rules
- `Risk check failed`: Review position limits
- `CIRCUIT BREAKER`: Check consecutive losses
- `Connection lost`: IBKR connectivity issue

## Development

### Adding New Signals

1. Extend `L2SignalGenerator` in `src/signals/l2_signals.py`
2. Add configuration parameters to `config/strategy.yaml`
3. Update tests in `tests/test_system.py`

### Modifying Risk Rules

1. Update `RiskManager` in `src/risk/risk_manager.py`
2. Adjust limits in `config/risk.yaml`
3. Test with `./run.sh test`

## Deployment Checklist

Before going live:

- [ ] All tests pass (`./run.sh test`)
- [ ] IBKR connection validated (`./run.sh validate`)
- [ ] Mock data disabled (`mock_data.enabled: false`)
- [ ] Paper trading port configured (`port: 7497`)
- [ ] Risk limits appropriate for account size
- [ ] Monitoring and alerting configured
- [ ] Emergency procedures documented

## Support

For issues or questions:
1. Check logs in `logs/scalping_system.log`
2. Run diagnostic tests with `./run.sh validate`
3. Review configuration files for errors
4. Consult L2 analysis documentation in `../docs/`
