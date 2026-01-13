# SCHEMAS

## Overview

This document defines the canonical data schemas used throughout the QuantStack system. All schemas are designed for deterministic processing and reproducible results.

## Core Data Contracts

### Bars (canonical Gold data)
```json
{
  "type": "object",
  "required": ["ts", "symbol", "open", "high", "low", "close", "volume"],
  "properties": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "UTC timestamp in nanoseconds since epoch"
    },
    "symbol": {
      "type": "string",
      "description": "Trading symbol identifier"
    },
    "open": {
      "type": "number",
      "description": "Opening price"
    },
    "high": {
      "type": "number",
      "description": "Highest price during the period"
    },
    "low": {
      "type": "number",
      "description": "Lowest price during the period"
    },
    "close": {
      "type": "number",
      "description": "Closing price"
    },
    "volume": {
      "type": "integer",
      "description": "Trading volume"
    },
    "trades": {
      "type": "integer",
      "description": "Number of trades (optional)"
    },
    "vwap": {
      "type": "number",
      "description": "Volume-weighted average price (optional)"
    },
    "session": {
      "type": "string",
      "description": "Trading session identifier (optional)"
    },
    "date_et": {
      "type": "string",
      "description": "Eastern Time date string (optional)"
    }
  },
  "required": ["ts", "symbol", "open", "high", "low", "close", "volume"]
}
```

**Key Characteristics:**
- **Deterministic Sorting**: Data must be sorted by `[symbol, ts]` before processing
- **UTC Timestamps**: All timestamps in UTC nanoseconds for consistency
- **Stable Types**: Numeric values use float64, integers use int64
- **Optional Fields**: Some columns like VWAP may be added by feature engineering

### Trades (per-run artifact)
```json
{
  "type": "object",
  "required": [
    "entry_ts", "exit_ts", "symbol", "side", "qty",
    "entry_px", "exit_px", "pnl", "fees", "slippage_est"
  ],
  "properties": {
    "entry_ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "Entry timestamp (UTC ns)"
    },
    "exit_ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "Exit timestamp (UTC ns)"
    },
    "symbol": {
      "type": "string",
      "description": "Trading symbol"
    },
    "side": {
      "type": "string",
      "enum": ["BUY", "SELL"],
      "description": "Trade direction"
    },
    "qty": {
      "type": "integer",
      "description": "Quantity traded"
    },
    "entry_px": {
      "type": "number",
      "description": "Entry price"
    },
    "exit_px": {
      "type": "number",
      "description": "Exit price"
    },
    "pnl": {
      "type": "number",
      "description": "Profit/loss in currency units"
    },
    "r_multiple": {
      "type": "number",
      "description": "Return multiple relative to risk"
    },
    "fees": {
      "type": "number",
      "description": "Trading fees incurred"
    },
    "slippage_est": {
      "type": "number",
      "description": "Estimated slippage cost"
    },
    "mfe": {
      "type": "number",
      "description": "Maximum favorable excursion"
    },
    "mae": {
      "type": "number",
      "description": "Maximum adverse excursion"
    },
    "duration_minutes": {
      "type": "integer",
      "description": "Trade duration in minutes"
    },
    "policy_tag": {
      "type": "string",
      "description": "Policy that generated the trade"
    },
    "risk_tag": {
      "type": "string",
      "description": "Risk management method used"
    },
    "rvol_at_entry": {
      "type": "number",
      "description": "Relative volume at trade entry (optional)"
    }
  }
}
```

### Signals (per-run artifact)
```json
{
  "type": "object",
  "required": ["ts", "symbol", "signal"],
  "properties": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "Signal timestamp (UTC ns)"
    },
    "symbol": {
      "type": "string",
      "description": "Trading symbol"
    },
    "signal": {
      "type": "integer",
      "enum": [0, 1],
      "description": "Signal value (0=flat, 1=long)"
    },
    "strength": {
      "type": "number",
      "description": "Signal strength score"
    },
    "vwap": {
      "type": "number",
      "description": "VWAP at signal time"
    },
    "rvol": {
      "type": "number",
      "description": "Relative volume at signal time"
    },
    "decision_trace": {
      "type": "object",
      "description": "JSON trace of decision logic (for debugging)"
    }
  }
}
```

### Orders (per-run artifact)
```json
{
  "type": "object",
  "required": ["ts", "symbol", "side", "qty", "type"],
  "properties": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "Order timestamp (UTC ns)"
    },
    "symbol": {
      "type": "string",
      "description": "Trading symbol"
    },
    "side": {
      "type": "string",
      "enum": ["BUY", "SELL"],
      "description": "Order direction"
    },
    "qty": {
      "type": "integer",
      "description": "Order quantity"
    },
    "type": {
      "type": "string",
      "enum": ["MKT", "LMT", "STP", "IOC"],
      "description": "Order type"
    },
    "tif": {
      "type": "string",
      "enum": ["DAY", "GTC", "IOC"],
      "description": "Time in force"
    },
    "price": {
      "type": "number",
      "description": "Limit price (for limit orders)"
    },
    "tags": {
      "type": "object",
      "description": "Additional order metadata"
    }
  }
}
```

### Fills (per-run artifact)
```json
{
  "type": "object",
  "required": ["ts", "symbol", "side", "qty", "fill_px", "fill_qty"],
  "properties": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "Fill timestamp (UTC ns)"
    },
    "symbol": {
      "type": "string",
      "description": "Trading symbol"
    },
    "side": {
      "type": "string",
      "enum": ["BUY", "SELL"],
      "description": "Fill direction"
    },
    "qty": {
      "type": "integer",
      "description": "Order quantity"
    },
    "fill_px": {
      "type": "number",
      "description": "Fill price"
    },
    "fill_qty": {
      "type": "integer",
      "description": "Filled quantity"
    },
    "commission": {
      "type": "number",
      "description": "Commission cost"
    },
    "fees": {
      "type": "number",
      "description": "Additional fees"
    }
  }
}
```

### Positions (per-run artifact)
```json
{
  "type": "object",
  "required": ["ts", "symbol", "qty", "avg_cost", "market_value", "unrealized_pnl"],
  "properties": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "Position timestamp (UTC ns)"
    },
    "symbol": {
      "type": "string",
      "description": "Trading symbol"
    },
    "qty": {
      "type": "integer",
      "description": "Position quantity (positive for long, negative for short)"
    },
    "avg_cost": {
      "type": "number",
      "description": "Average cost basis"
    },
    "market_value": {
      "type": "number",
      "description": "Current market value"
    },
    "unrealized_pnl": {
      "type": "number",
      "description": "Unrealized profit/loss"
    },
    "realized_pnl": {
      "type": "number",
      "description": "Realized profit/loss"
    }
  }
}
```

### Equity (per-run artifact)
```json
{
  "type": "object",
  "required": ["ts", "equity", "cash", "positions_value"],
  "properties": {
    "ts": {
      "type": "string",
      "format": "date-time",
      "x-tz": "UTC",
      "x-unit": "ns",
      "description": "Equity timestamp (UTC ns)"
    },
    "equity": {
      "type": "number",
      "description": "Total portfolio equity"
    },
    "cash": {
      "type": "number",
      "description": "Available cash"
    },
    "positions_value": {
      "type": "number",
      "description": "Value of open positions"
    },
    "max_drawdown": {
      "type": "number",
      "description": "Current maximum drawdown"
    }
  }
}
```

## Configuration Schemas

### Experiment Manifest
```json
{
  "type": "object",
  "required": [
    "exp_id", "type", "created_at", "data_slice",
    "feature_packs", "policy_params", "run_ids"
  ],
  "properties": {
    "exp_id": {
      "type": "string",
      "description": "Unique experiment identifier"
    },
    "name": {
      "type": "string",
      "description": "Human-readable experiment name"
    },
    "type": {
      "type": "string",
      "enum": ["entry_ab", "cost_sweep", "risk_grid", "portfolio"],
      "description": "Experiment type"
    },
    "created_at": {
      "type": "string",
      "format": "date-time",
      "description": "Experiment creation timestamp"
    },
    "data_slice": {
      "type": "object",
      "required": ["gold_root", "family", "symbols", "dates"],
      "properties": {
        "gold_root": {
          "type": "string",
          "description": "Path to Gold data source"
        },
        "family": {
          "type": "string",
          "description": "Data family (e.g., 'bars_1m')"
        },
        "symbols": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Trading symbols"
        },
        "dates": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Trading dates"
        }
      }
    },
    "feature_packs": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "params"]
      },
      "description": "Feature pack configurations"
    },
    "policy_params": {
      "type": "object",
      "description": "Policy parameters"
    },
    "risk_params": {
      "type": "object",
      "description": "Risk management parameters"
    },
    "seed": {
      "type": "integer",
      "description": "Random seed for reproducibility"
    },
    "run_ids": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Generated run identifiers"
    }
  }
}
```

### Inputs Checksum (Reproducibility)
```json
{
  "type": "object",
  "required": [
    "bars_norm_hash", "features_hash", "sip_hash",
    "config_hash", "seed"
  ],
  "properties": {
    "bars_norm_hash": {
      "type": "string",
      "description": "Hash of normalized input bars data",
      "pattern": "^[a-f0-9]{16}$"
    },
    "features_hash": {
      "type": "string",
      "description": "Hash of computed features",
      "pattern": "^[a-f0-9]{16}$"
    },
    "sip_hash": {
      "type": "string",
      "description": "Hash of SIP screening results",
      "pattern": "^[a-f0-9]{16}$"
    },
    "config_hash": {
      "type": "string",
      "description": "Hash of experiment configuration",
      "pattern": "^[a-f0-9]{16}$"
    },
    "seed": {
      "type": "integer",
      "description": "Random seed used for reproducibility"
    },
    "model_hash": {
      "type": "string",
      "description": "Hash of trained model (for ML experiments)",
      "pattern": "^[a-f0-9]{16}$"
    }
  }
}
```

## Metrics Schema

### Run Metrics (per-run)
```json
{
  "type": "object",
  "properties": {
    "trades": {
      "type": "integer",
      "description": "Total number of trades"
    },
    "avg_R": {
      "type": "number",
      "description": "Average R-multiple across all trades"
    },
    "sharpe_CI_high": {
      "type": "number",
      "description": "Sharpe ratio confidence interval upper bound"
    },
    "win_rate": {
      "type": "number",
      "description": "Win rate as percentage (0-1)"
    },
    "total_pnl": {
      "type": "number",
      "description": "Total profit/loss"
    },
    "max_drawdown": {
      "type": "number",
      "description": "Maximum drawdown percentage"
    },
    "total_return": {
      "type": "number",
      "description": "Total return percentage"
    },
    "avg_trade_pnl": {
      "type": "number",
      "description": "Average profit/loss per trade"
    },
    "ES_95": {
      "type": "number",
      "description": "Expected shortfall at 95% confidence"
    },
    "pvalue_u": {
      "type": "number",
      "description": "p-value (upper bound)"
    },
    "sharpe_CI_low": {
      "type": "number",
      "description": "Sharpe ratio confidence interval lower bound"
    },
    "policy": {
      "type": "string",
      "description": "Policy name"
    },
    "risk_config": {
      "type": "object",
      "description": "Risk management configuration"
    }
  }
}
```

## VPA Schema Extensions

### VPA Pattern Flags
```json
{
  "p__vpa__volume_spike": {
    "type": "integer",
    "enum": [0, 1],
    "description": "Volume spike pattern flag"
  },
  "p__vpa__price_breakout": {
    "type": "integer",
    "enum": [0, 1],
    "description": "Price breakout pattern flag"
  },
  "p__vpa__volume_divergence": {
    "type": "integer",
    "enum": [0, 1],
    "description": "Volume-price divergence pattern flag"
  },
  "p__vpa__absorption": {
    "type": "integer",
    "enum": [0, 1],
    "description": "Volume absorption pattern flag"
  },
  "p__vpa__climax": {
    "type": "integer",
    "enum": [0, 1],
    "description": "Volume climax pattern flag"
  }
}
```

### VPA Confidence Scores
```json
{
  "conf__vpa__volume_spike": {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": "Volume spike confidence score"
  },
  "conf__vpa__price_breakout": {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": "Price breakout confidence score"
  },
  "conf__vpa__volume_divergence": {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": "Volume divergence confidence score"
  },
  "conf__vpa__absorption": {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": "Absorption confidence score"
  },
  "conf__vpa__climax": {
    "type": "number",
    "minimum": 0,
    "maximum": 1,
    "description": "Climax confidence score"
  }
}
```

## Data Quality and Validation

### Required Columns
All DataFrames must contain the required columns for their type. Missing required columns will cause validation errors.

### Data Types
- **Timestamps**: UTC nanoseconds (int64)
- **Prices**: Float64 for precision
- **Integers**: Int64 for consistency
- **Strings**: Object for flexibility

### Sorting Requirements
All data must be sorted by `[symbol, ts]` (ascending) to ensure deterministic processing.

### Hashing
Hash values are computed using stable sorting and type normalization to ensure reproducible results across runs.

## Artifact Storage

### File Format
- **Data Files**: Parquet format for efficiency
- **Metadata**: JSON format for readability
- **Compression**: Default Parquet compression

### Directory Structure
```
runs/<run_id>/
├── signals.parquet
├── orders.parquet
├── fills.parquet
├── positions.parquet
├── equity.parquet
├── trades.parquet
├── risk_rejects.parquet
├── allocation_log.parquet
└── metrics.json

experiments/<exp_id>/
├── manifest.json
├── inputs_checksum.json
├── compare.json
└── compare.md
```

## Reproducibility Guarantees

### Deterministic Behavior
1. **Fixed Seeds**: Random seeds must be specified and documented
2. **Stable Sorting**: Data sorting is enforced before processing
3. **Hash Validation**: Input hashes must match for fair comparisons
4. **Type Consistency**: Data types are normalized for hashing

### Fair Comparison Requirements
For A/B experiments, the following must be identical across variants:
- `bars_norm_hash`: Input data hash
- `features_hash`: Feature computation hash
- `sip_hash`: SIP screening hash
- `seed`: Random seed
- `config_hash`: Only the policy parameters may differ

### Validation Rules
- All hashes must be 16-character hexadecimal strings
- Seeds must be integers
- Timestamps must be in UTC nanoseconds
- Required columns must be present and non-null
- Data must be properly sorted before processing