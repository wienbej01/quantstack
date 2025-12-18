# Trading System Separation Guide

## Overview
This guide shows how to clearly distinguish between multiple trading systems using the same IBKR connection.

## 🔧 Implementation Methods

### 1. Client ID Separation (Recommended)
Each system uses a unique client ID (1-32):

```python
# System 1: Quantstack
quantstack_manager = TaggedIBKRManager(
    system_name="QUANTSTACK",
    client_id=999
)

# System 2: Your other system  
system2_manager = TaggedIBKRManager(
    system_name="SYSTEM2", 
    client_id=998
)
```

### 2. Order Reference Tagging
Every order gets a unique reference tag:

```python
# Quantstack order
order.orderRef = "QUANTSTACK_999_ML_REGIME_AAPL"

# System 2 order  
order.orderRef = "SYSTEM2_998_CUSTOM_STRAT_MSFT"
```

### 3. Strategy-Level Tagging
Tag orders by specific strategy:

```python
# Place tagged order
manager.place_tagged_order(
    symbol="AAPL",
    action="BUY", 
    quantity=100,
    strategy_tag="ML_REGIME"  # Strategy identifier
)
```

## 📊 Monitoring & Analysis

### Real-time Monitoring
```bash
# Monitor both systems
python monitor_systems.py
```

### Filter by System
```python
# Get only Quantstack trades
quantstack_trades = [
    trade for trade in all_trades 
    if trade.order.orderRef.startswith("QUANTSTACK_999")
]

# Get only System2 trades  
system2_trades = [
    trade for trade in all_trades
    if trade.order.orderRef.startswith("SYSTEM2_998") 
]
```

### TWS Activity Monitor
In TWS, you can filter by:
- **Client ID**: Filter executions by client ID
- **Order Reference**: Search by order ref pattern
- **Account**: If using sub-accounts

## 🏷️ Tagging Conventions

### Order Reference Format
```
{SYSTEM_NAME}_{CLIENT_ID}_{STRATEGY}_{SYMBOL}
```

Examples:
- `QUANTSTACK_999_ML_REGIME_AAPL`
- `QUANTSTACK_999_L2_MOMENTUM_MSFT` 
- `SYSTEM2_998_CUSTOM_STRAT1_GOOGL`

### Strategy Tags
- **ML_REGIME**: Regime-aware ML strategy
- **L2_MOMENTUM**: L2 data momentum strategy  
- **VWAP_REVERSION**: VWAP reversion strategy
- **CUSTOM_STRAT1**: Your custom strategy 1
- **CUSTOM_STRAT2**: Your custom strategy 2

## 🔍 Identification in Logs

### IBKR Execution Logs
```
INFO:ib_insync.wrapper:execDetails Execution(
    orderId=195, 
    clientId=999,  # <- System identifier
    orderRef='QUANTSTACK_999_ML_REGIME_AAPL'  # <- Full tag
)
```

### System Logs
```
INFO:[QUANTSTACK] Order placed: BUY 100 AAPL (ref: QUANTSTACK_999_ML_REGIME_AAPL)
INFO:[SYSTEM2] Order placed: SELL 200 MSFT (ref: SYSTEM2_998_CUSTOM_STRAT1_MSFT)
```

## ⚙️ Configuration

### Current Quantstack Setup
- **System Name**: QUANTSTACK
- **Client ID**: 999
- **Strategies**: ML_REGIME, L2_MOMENTUM, VWAP_REVERSION

### Recommended System2 Setup  
- **System Name**: SYSTEM2
- **Client ID**: 998  
- **Strategies**: CUSTOM_STRAT1, CUSTOM_STRAT2

## 🚀 Quick Start

1. **Update your second system** to use client ID 998:
   ```python
   ib.connect('127.0.0.1', 7497, clientId=998)
   ```

2. **Add order reference tagging**:
   ```python
   order.orderRef = f"SYSTEM2_998_{strategy_name}_{symbol}"
   ```

3. **Monitor both systems**:
   ```bash
   python monitor_systems.py
   ```

## 📈 Benefits

- **Clear Attribution**: Know which system placed each order
- **Performance Tracking**: Separate P&L by system
- **Risk Management**: Monitor exposure per system  
- **Debugging**: Isolate issues to specific systems
- **Compliance**: Audit trail for each system

## 🔧 Troubleshooting

### Client ID Conflicts
- Ensure each system uses unique client ID (1-32)
- Check TWS API settings for max client connections

### Order Reference Issues  
- Keep references under 100 characters
- Use alphanumeric + underscore only
- Avoid special characters

### Connection Problems
- Only one connection per client ID allowed
- Restart TWS if client IDs conflict
- Check firewall settings for multiple connections
