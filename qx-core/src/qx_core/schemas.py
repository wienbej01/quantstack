"""Pydantic schemas for critical data structures."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class RegimeType(str, Enum):
    """Market regime classification types."""

    BULL = "BULL"  # Normal upward trending conditions
    BEAR = "BEAR"  # Normal downward trending conditions
    SIDEWAYS = "SIDEWAYS"  # Range-bound markets
    STRESS = "STRESS"  # High volatility/crisis conditions
    OFF = "OFF"  # Regime detection disabled


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MKT = "MKT"
    LMT = "LMT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


class ExperimentType(str, Enum):
    ENTRY_AB = "entry-ab"
    RISK_GRID = "risk-grid"
    COST_SWEEP = "cost-sweep"
    WORKFLOW = "wf"
    REGIME_SLICE = "regime-slice"
    PORTFOLIO = "portfolio"


class Bar(BaseModel):
    """Canonical bar data structure."""

    ts: int = Field(..., description="UTC nanosecond timestamp")
    symbol: str = Field(..., description="Symbol identifier")
    open: float = Field(..., ge=0, description="Open price")
    high: float = Field(..., ge=0, description="High price")
    low: float = Field(..., ge=0, description="Low price")
    close: float = Field(..., ge=0, description="Close price")
    volume: int = Field(..., ge=0, description="Volume")
    vwap: float | None = Field(None, ge=0, description="Volume-weighted average price")
    trades: int | None = Field(None, ge=0, description="Number of trades")
    spread: float | None = Field(None, ge=0, description="Bid-ask spread")
    turnover: float | None = Field(None, ge=0, description="Turnover")
    session: str | None = Field(None, description="Session identifier")
    provider: str | None = Field(None, description="Data provider")

    @field_validator("high", "low", "close", "open")
    @classmethod
    def validate_ohlc(cls, v, info):
        # Skip validation for initial fields
        if not hasattr(info, "data") or not info.data:
            return v

        if "low" in info.data and v < info.data["low"]:
            raise ValueError(f"Price {v} is below low {info.data['low']}")
        if "high" in info.data and v > info.data["high"]:
            raise ValueError(f"Price {v} is above high {info.data['high']}")
        return v

    @field_validator("ts")
    @classmethod
    def validate_timestamp(cls, v):
        if v <= 0:
            raise ValueError("Timestamp must be positive")
        return v


class Signal(BaseModel):
    """Trading signal data structure."""

    ts: int = Field(..., description="UTC nanosecond timestamp")
    symbol: str = Field(..., description="Symbol identifier")
    side: Side = Field(..., description="Buy/sell direction")
    strength: float = Field(..., description="Signal strength")
    entry_hint: float | None = Field(None, description="Suggested entry price")
    stop_hint: float | None = Field(None, description="Suggested stop price")
    tag: str | None = Field(None, description="Signal tag/identifier")
    src: str = Field(..., description="Signal source")

    @field_validator("strength")
    @classmethod
    def validate_strength(cls, v):
        if not (-1 <= v <= 1):
            raise ValueError("Signal strength must be between -1 and 1")
        return v


class RegimeSignal(BaseModel):
    """Regime classification signal for strategy gating."""

    ts: int = Field(..., description="UTC nanosecond timestamp")
    symbol: str | None = Field(None, description="Symbol associated with this regime signal")
    regime: RegimeType = Field(..., description="Current market regime")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence")
    features: dict[str, Any] = Field(default_factory=dict, description="Underlying feature values")
    persistence_count: int = Field(default=0, description="Consecutive bars in current regime")
    model_version: str = Field("rules_v1", description="Detector version")
    src: str = Field("regime", description="Signal source identifier")
    segment: str | None = Field(None, description="Intraday session segment label (e.g., AM/PM)")
    session_date: str | None = Field(
        None, description="Trading date in America/New_York (YYYY-MM-DD)"
    )


class Order(BaseModel):
    """Order data structure."""

    ts: int = Field(..., description="UTC nanosecond timestamp")
    symbol: str = Field(..., description="Symbol identifier")
    side: Side = Field(..., description="Buy/sell direction")
    qty: int = Field(..., gt=0, description="Order quantity")
    type: OrderType = Field(OrderType.MKT, description="Order type")
    entry: float | None = Field(None, gt=0, description="Limit price")
    stop: float | None = Field(None, gt=0, description="Stop price")
    take_profit: float | None = Field(None, gt=0, description="Take profit price")
    tif: TimeInForce = Field(TimeInForce.DAY, description="Time in force")
    link_id: str | None = Field(None, description="Link to other orders")
    tag: str | None = Field(None, description="Order tag")

    @field_validator("entry", "stop", "take_profit")
    @classmethod
    def validate_prices(cls, v):
        if v is not None and v <= 0:
            raise ValueError("Prices must be positive")
        return v


class Trade(BaseModel):
    """Completed trade data structure."""

    entry_ts: int = Field(..., description="Entry UTC nanosecond timestamp")
    exit_ts: int = Field(..., description="Exit UTC nanosecond timestamp")
    symbol: str = Field(..., description="Symbol identifier")
    side: Side = Field(..., description="Buy/sell direction")
    qty: int = Field(..., gt=0, description="Trade quantity")
    entry_px: float = Field(..., gt=0, description="Entry price")
    exit_px: float = Field(..., gt=0, description="Exit price")
    fees: float = Field(0.0, ge=0, description="Trading fees")
    slippage_est: float = Field(0.0, description="Estimated slippage")
    stop_dist_ps: float | None = Field(None, ge=0, description="Stop distance as percentage")
    pnl: float = Field(..., description="Profit/loss")
    r_multiple: float | None = Field(None, description="R-multiple")
    mfe: float | None = Field(None, description="Maximum favorable excursion")
    mae: float | None = Field(None, description="Maximum adverse excursion")
    duration_s: int = Field(..., ge=0, description="Duration in seconds")
    policy_tag: str | None = Field(None, description="Policy identifier")
    risk_tag: str | None = Field(None, description="Risk rule identifier")

    @field_validator("exit_ts")
    @classmethod
    def validate_exit_after_entry(cls, v, values):
        if "entry_ts" in values and v <= values["entry_ts"]:
            raise ValueError("Exit timestamp must be after entry timestamp")
        return v


class RiskReject(BaseModel):
    """Risk rejection data structure."""

    reason_code: str = Field(..., description="Reason for rejection")
    limit_name: str = Field(..., description="Risk limit name")
    value: float = Field(..., description="Actual value")
    threshold: float = Field(..., description="Limit threshold")
    ts: int | None = Field(None, description="UTC nanosecond timestamp")
    symbol: str | None = Field(None, description="Symbol identifier")


class AllocationLog(BaseModel):
    """Portfolio allocation log entry."""

    ts: int = Field(..., description="UTC nanosecond timestamp")
    symbol: str = Field(..., description="Symbol identifier")
    allocation: float = Field(..., description="Allocation amount/percentage")
    reason: str = Field(..., description="Allocation reason")


class InputsChecksum(BaseModel):
    """Inputs checksum for experiment fairness."""

    bars_norm_hash: str = Field(..., description="Normalized bars hash")
    features_hash: str = Field(..., description="Features hash")
    sip_hash: str | None = Field(None, description="SIP selection hash")
    config_hash: str = Field(..., description="Configuration hash")
    seed: int = Field(..., description="Random seed")

    @field_validator("bars_norm_hash", "features_hash", "sip_hash", "config_hash")
    @classmethod
    def validate_hash(cls, v):
        if v is not None and len(v) < 8:
            raise ValueError("Hash appears too short")
        return v


class Metrics(BaseModel):
    """Performance metrics."""

    trades: int = Field(..., ge=0, description="Number of trades")
    avg_R: float = Field(..., description="Average R-multiple")
    ES_95: float = Field(..., description="Expected shortfall at 95%")
    pvalue_u: float = Field(..., description="P-value (upper tail)")
    sharpe_CI_low: float = Field(..., description="Sharpe ratio CI lower bound")
    sharpe_CI_high: float = Field(..., description="Sharpe ratio CI upper bound")
    capacity_break_even_bps: float = Field(..., description="Capacity break-even in basis points")
    total_pnl: float | None = Field(None, description="Total P&L")
    win_rate: float | None = Field(None, ge=0, le=1, description="Win rate")
    max_drawdown: float | None = Field(None, le=0, description="Maximum drawdown")


class ExperimentManifest(BaseModel):
    """Experiment manifest metadata."""

    exp_id: str = Field(..., description="Experiment identifier")
    type: ExperimentType = Field(..., description="Experiment type")
    base_config: str | None = Field(None, description="Base configuration path")
    variants: list[str] = Field(default_factory=list, description="Variant configurations")
    grid: str | None = Field(None, description="Grid configuration")
    plan: str | None = Field(None, description="Plan configuration")
    regimes: str | None = Field(None, description="Regime configuration")
    regime_config: str | None = Field(None, description="Regime configuration path")
    run_ids: list[str] = Field(..., description="Run identifiers")
    seed: int = Field(..., description="Random seed")
    created_at: datetime | None = Field(None, description="Creation timestamp")
    description: str | None = Field(None, description="Experiment description")


class CompareReport(BaseModel):
    """A/B comparison report."""

    experiment: str = Field(..., description="Experiment identifier")
    variants: int = Field(..., gt=0, description="Number of variants")
    results: list[dict[str, Any]] = Field(..., description="Results per variant")
    leaderboard: list[dict[str, Any]] = Field(..., description="Ranked results")
    created_at: datetime | None = Field(None, description="Report creation timestamp")
    fairness_check: dict[str, bool] | None = Field(None, description="Fairness validation results")


# Legacy JSON schema functions for backward compatibility
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
            "provider": {"type": "string"},
        },
        "required": ["ts", "symbol", "open", "high", "low", "close", "volume"],
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
            "src": {"type": "string"},
        },
        "required": ["ts", "symbol", "side", "strength", "src"],
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
            "link_id": {"type": "string"},
        },
        "required": ["ts", "symbol", "side", "qty"],
    }


def experiment_manifest_schema() -> dict:
    """Schema for experiment manifest."""
    return {
        "type": "object",
        "required": ["exp_id", "type", "run_ids", "seed"],
        "properties": {
            "exp_id": {"type": "string"},
            "type": {
                "type": "string",
                "enum": [
                    "entry-ab",
                    "risk-grid",
                    "cost-sweep",
                    "wf",
                    "regime-slice",
                    "portfolio",
                ],
            },
            "base_config": {"type": "string"},
            "variants": {"type": "array", "items": {"type": "string"}},
            "grid": {"type": "string"},
            "plan": {"type": "string"},
            "regimes": {"type": "string"},
            "regime_config": {"type": "string"},
            "run_ids": {"type": "array", "items": {"type": "string"}},
            "seed": {"type": "integer"},
        },
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
            "seed": {"type": "integer"},
        },
    }


def trades_schema() -> dict:
    """Schema for trades DataFrame."""
    return {
        "type": "object",
        "required": [
            "entry_ts",
            "exit_ts",
            "symbol",
            "side",
            "qty",
            "entry_px",
            "exit_px",
            "pnl",
        ],
        "properties": {
            "entry_ts": {
                "type": "string",
                "format": "date-time",
                "x-tz": "UTC",
                "x-unit": "ns",
            },
            "exit_ts": {
                "type": "string",
                "format": "date-time",
                "x-tz": "UTC",
                "x-unit": "ns",
            },
            "symbol": {"type": "string"},
            "side": {"type": "string", "enum": ["BUY", "SELL"]},
            "qty": {"type": "integer"},
            "entry_px": {"type": "number"},
            "exit_px": {"type": "number"},
            "fees": {"type": "number"},
            "slippage_est": {"type": "number"},
            "stop_dist_ps": {"type": "number"},
            "pnl": {"type": "number"},
            "r_multiple": {"type": "number"},
            "mfe": {"type": "number"},
            "mae": {"type": "number"},
            "duration_s": {"type": "integer"},
            "policy_tag": {"type": "string"},
            "risk_tag": {"type": "string"},
        },
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
            "threshold": {"type": "number"},
        },
    }


def allocation_log_schema() -> dict:
    """Schema for allocation log DataFrame."""
    return {
        "type": "object",
        "properties": {
            "ts": {"type": "string", "format": "date-time"},
            "symbol": {"type": "string"},
            "allocation": {"type": "number"},
            "reason": {"type": "string"},
        },
    }


def metrics_schema() -> dict:
    """Schema for metrics JSON."""
    return {
        "type": "object",
        "required": [
            "trades",
            "avg_R",
            "ES_95",
            "pvalue_u",
            "sharpe_CI_low",
            "sharpe_CI_high",
            "capacity_break_even_bps",
        ],
        "properties": {
            "trades": {"type": "integer"},
            "avg_R": {"type": "number"},
            "ES_95": {"type": "number"},
            "pvalue_u": {"type": "number"},
            "sharpe_CI_low": {"type": "number"},
            "sharpe_CI_high": {"type": "number"},
            "capacity_break_even_bps": {"type": "number"},
        },
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
            "leaderboard": {"type": "array", "items": {"type": "object"}},
        },
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
