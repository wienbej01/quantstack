"""JSON Schemas for critical tables."""

import jsonschema

def bars_schema() -> dict:
    """Schema for bars DataFrame."""
    return {
        "type": "object",
        "properties": {
            "ts": {"type": "integer"},
            "symbol": {"type": "string"},
            "open": {"type": "number"},
            "high": {"type": "number"},
            "low": {"type": "number"},
            "close": {"type": "number"},
            "volume": {"type": "integer"},
            "vwap": {"type": "number"},
            "trades": {"type": "integer"},
            "spread": {"type": "number"},
            "turnover": {"type": "number"},
            "session": {"type": "string"},
            "provider": {"type": "string"}
        },
        "required": ["ts", "symbol", "open", "high", "low", "close", "volume"]
    }

def signals_schema() -> dict:
    """Schema for signals DataFrame."""
    return {
        "type": "object",
        "properties": {
            "ts": {"type": "integer"},
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "strength": {"type": "number"},
            "entry_hint": {"type": "number"},
            "stop_hint": {"type": "number"},
            "tag": {"type": "string"},
            "src": {"type": "string"}
        },
        "required": ["ts", "symbol", "side", "strength", "src"]
    }

def orders_schema() -> dict:
    """Schema for orders DataFrame."""
    return {
        "type": "object",
        "properties": {
            "ts": {"type": "integer"},
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "qty": {"type": "integer"},
            "type": {"type": "string"},
            "entry": {"type": "number"},
            "stop": {"type": "number"},
            "take_profit": {"type": "number"},
            "tif": {"type": "string"},
            "link_id": {"type": "string"}
        },
        "required": ["ts", "symbol", "side", "qty"]
    }
def experiment_manifest_schema() -> dict:
    """Schema for experiment manifest."""
    return {
        "type": "object",
        "required": ["exp_id", "type", "run_ids", "seed"],
        "properties": {
            "exp_id": {"type": "string"},
            "type": {"type": "string", "enum": ["entry-ab", "risk-grid", "cost-sweep", "wf", "regime-slice", "portfolio"]},
            "base_config": {"type": "string"},
            "variants": {"type": "array", "items": {"type": "string"}},
            "grid": {"type": "string"},
            "plan": {"type": "string"},
            "regimes": {"type": "string"},
            "run_ids": {"type": "array", "items": {"type": "string"}},
            "seed": {"type": "integer"}
        }
    }

def inputs_checksum_schema() -> dict:
    """Schema for inputs checksum."""
    return {
        "type": "object",
        "required": ["bars_norm_hash", "features_hash", "config_hash", "seed"],
        "properties": {
            "bars_norm_hash": {"type": "string"},
            "features_hash": {"type": "string"},
            "sip_hash": {"type": "string"},
            "config_hash": {"type": "string"},
            "seed": {"type": "integer"}
        }
    }

def trades_schema() -> dict:
    """Schema for trades DataFrame."""
    return {
        "type": "object",
        "required": ["entry_ts", "exit_ts", "symbol", "side", "qty", "entry_px", "exit_px", "pnl"],
        "properties": {
            "entry_ts": {"type": "string", "format": "date-time", "x-tz": "UTC", "x-unit": "ns"},
            "exit_ts": {"type": "string", "format": "date-time", "x-tz": "UTC", "x-unit": "ns"},
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "qty": {"type": "integer"},
            "entry_px": {"type": "number"},
            "exit_px": {"type": "number"},
            "fees": {"type": "number"},
            "slippage_est": {"type": "number"},
            "pnl": {"type": "number"},
            "r_multiple": {"type": "number"},
            "mfe": {"type": "number"},
            "mae": {"type": "number"},
            "duration_s": {"type": "integer"},
            "policy_tag": {"type": "string"},
            "risk_tag": {"type": "string"}
        }
    }

def risk_rejects_schema() -> dict:
    """Schema for risk rejects DataFrame."""
    return {
        "type": "object",
        "required": ["reason_code", "limit_name", "value", "threshold"],
        "properties": {
            "reason_code": {"type": "string"},
            "limit_name": {"type": "string"},
            "value": {"type": "number"},
            "threshold": {"type": "number"}
        }
    }

def allocation_log_schema() -> dict:
    """Schema for allocation log DataFrame."""
    return {
        "type": "object",
        "properties": {
            "ts": {"type": "string", "format": "date-time"},
            "symbol": {"type": "string"},
            "allocation": {"type": "number"},
            "reason": {"type": "string"}
        }
    }

def metrics_schema() -> dict:
    """Schema for metrics JSON."""
    return {
        "type": "object",
        "required": ["trades", "avg_R", "ES_95", "pvalue_u", "sharpe_CI_low", "sharpe_CI_high", "capacity_break_even_bps"],
        "properties": {
            "trades": {"type": "integer"},
            "avg_R": {"type": "number"},
            "ES_95": {"type": "number"},
            "pvalue_u": {"type": "number"},
            "sharpe_CI_low": {"type": "number"},
            "sharpe_CI_high": {"type": "number"},
            "capacity_break_even_bps": {"type": "number"}
        }
    }

def compare_report_schema() -> dict:
    """Schema for compare report JSON."""
    return {
        "type": "object",
        "required": ["experiment", "variants", "results", "leaderboard"],
        "properties": {
            "experiment": {"type": "string"},
            "variants": {"type": "integer"},
            "results": {"type": "array", "items": {"type": "object"}},
            "leaderboard": {"type": "array", "items": {"type": "object"}}
        }
    }


# Validation functions

def validate_experiment_manifest(data: dict) -> None:
    """Validate experiment manifest against schema."""
    jsonschema.validate(data, experiment_manifest_schema())


def validate_inputs_checksum(data: dict) -> None:
    """Validate inputs checksum against schema."""
    jsonschema.validate(data, inputs_checksum_schema())


def validate_trades(data: dict) -> None:
    """Validate trades data against schema."""
    jsonschema.validate(data, trades_schema())


def validate_risk_rejects(data: dict) -> None:
    """Validate risk rejects data against schema."""
    jsonschema.validate(data, risk_rejects_schema())


def validate_allocation_log(data: dict) -> None:
    """Validate allocation log data against schema."""
    jsonschema.validate(data, allocation_log_schema())


def validate_metrics(data: dict) -> None:
    """Validate metrics against schema."""
    jsonschema.validate(data, metrics_schema())


def validate_compare_report(data: dict) -> None:
    """Validate compare report against schema."""
    jsonschema.validate(data, compare_report_schema())