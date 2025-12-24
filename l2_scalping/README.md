# L2 Scalping System

A high-frequency scalping system based on Level-2 order book imbalance signals using the shared **daily SIP universe**.

## Quick Start

```bash
# 1. Generate SIP universe (shared daily_sip JSON)
python /home/jacobw/intraday_stack/scripts/generate_daily_sip_universe.py --date 2025-12-22

# 2. Run tests
./run.sh test

# 3. Validate system (requires IBKR connection)
./run.sh validate

# 4. Start paper trading (manual)
./run.sh run

# 5. Install as system service (automatic)
./run.sh install
sudo systemctl start l2-scalping
```

## System Overview

- **Strategy**: OBI momentum scalping with 5-30 second holds
- **Target**: 0.5-1.1 bps gross at 10-30s in the latest sample  
- **Universe**: Daily SIP universe ranked by score
- **Selection**: Top 3 symbols from daily SIP ranking
- **Risk**: 10 bps stop loss, 100 bps daily limit
- **Schedule**: Automatic start/stop with market hours

## SIP Universe Integration

### Daily SIP Generation
```bash
# Inspect SIP universe for L2 scalping
python src/data/sip_integration.py --date 2025-12-22
```

### SIP Configuration
- **Algorithm**: `news_attention×0.5 + volume×0.3 + volatility×0.2`
- **Parameters**: score_floor configurable in generator
- **Output**: All passing symbols ranked → Top 3 selected for scalping
- **Storage**: `SIP_DAILY_ROOT/date=YYYY-MM-DD/sip_universe.json`

## System Requirements Met ✅

### 1. Separate IBKR Client IDs
- **L2 Scalping Orders**: Client ID 10
- **L2 Scalping Data**: Client ID 11
- **L2 Collector**: Client ID 521 (existing)
- **Intraday Stack**: Client ID 1-3 (existing)

### 2. Automatic Timer-Based Operation
- **Market Hours Detection**: Automatic start/stop with NYSE hours
- **Schedule Configuration**: 5-minute buffers before/after market
- **Systemd Service**: `l2-scalping.service` for production deployment
- **Auto-restart**: Handles disconnections and errors

### 3. SIP Integration
- **Shared Data Source**: Reads from `/home/jacobw/intraday_stack/data/daily_sip/` (override with `SIP_DAILY_ROOT`)
- **Same Universe**: Uses identical SIP files as l2-collector
- **Top 3 Selection**: Automatically selects top 3 symbols from daily HMM ranking
- **Fallback**: Uses PFE, HAL, LUV if SIP data unavailable

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
├── reporting/       # Trade journal & reports
│   ├── trade_journal.py
│   └── performance_reporter.py
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

### Trade Journal & Reports

**Trade Journal**: All trades recorded to `data/trades_YYYYMMDD.jsonl`
- Entry/exit prices and times
- Signal type and strength  
- P&L and commission
- Hold duration

**Daily Reports**: Generated automatically at session end
- Text report: `logs/daily_report_YYYY-MM-DD.txt`
- JSON summary: `logs/daily_summary_YYYY-MM-DD.json`

**Key Metrics**:
- Win rate and profit factor
- Average win/loss amounts
- Hold time statistics
- Execution quality

**View Reports**:
```bash
# View today's report
cat logs/daily_report_$(date +%Y-%m-%d).txt

# View trade journal
cat data/trades_$(date +%Y%m%d).jsonl | jq

# Monitor live performance
tail -f logs/scalping_system.log
```

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

Based on analysis of 272,808 L2 records (Dec 19 & Dec 23, 2025):

| Metric | Expected Value |
|--------|----------------|
| Mean Return (10-30s) | 0.4-0.7 bps (gross) |
| Win Rate (30s extreme OBI) | ~41-42% |
| Win Rate (5m strict filter) | ~56% (182 trades, Dec 23) |
| Signals/Day (30s extreme OBI) | ~9k (sample) |
| Cost Note | Break-even size ~ $17.5k for 30s at $2 commission |
| Long Holds (net positive) | 600-900s for OBI>0.8 + rel_vol>2 + RSI>50 |

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
