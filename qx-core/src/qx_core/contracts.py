from dataclasses import dataclass
from typing import Literal, Protocol

Side = Literal["BUY","SELL"]

@dataclass(frozen=True)
class Bar:
    ts: int; symbol: str
    open: float; high: float; low: float; close: float
    volume: int
    vwap: float | None = None
    trades: int | None = None
    spread: float | None = None
    turnover: float | None = None
    session: str | None = None
    provider: str | None = None

@dataclass
class Order:
    symbol: str; side: Side; qty: int
    type: str = "MKT"
    entry: float | None = None; stop: float | None = None; take_profit: float | None = None
    tif: str = "DAY"; link_id: str | None = None; tag: str | None = None

class DataClient(Protocol):
    def get_bars(self, symbols: list[str], start: str, end: str, timeframe: str="1m",
                 cols: list[str]|None=None, session: str|None=None): ...

class FeaturePipeline(Protocol):
    name: str
    def fit(self, df, **ctx) -> "FeaturePipeline": ...
    def transform(self, df, **ctx): ...

class UniverseSelector(Protocol):
    name: str
    def select(self, pre_df, ref: dict, **params): ...

class Policy(Protocol):
    def warmup(self, ctx): ...
    def on_bar(self, ctx, row) -> list[Order] | None: ...

class RiskManager(Protocol):
    def pre_check(self, account, portfolio, order) -> bool: ...
    def size(self, account, stop_dist: float, price: float, max_risk_frac: float) -> int: ...
    def apply(self, signals_df, df_feat, account, portfolio, params): ...

class BacktestEngine(Protocol):
    def run(self, bars, orders, cfg: dict) -> dict: ...

class Broker(Protocol):
    def preview(self, order: Order): ...
    def submit(self, order: Order): ...
    def cancel(self, order_id: str): ...
    def positions(self): ...
    def account(self): ...