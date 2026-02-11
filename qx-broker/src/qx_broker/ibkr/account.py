"""Account and PnL helpers."""

from __future__ import annotations

from ib_insync import PnL, PnLSingle
from qx_broker.ibkr.connection import IBKRSession


class IBKRAccount:
    def __init__(self, session: IBKRSession) -> None:
        self.session = session
        self._pnl_subscriptions: dict[str, PnL] = {}
        self._pnl_single_subscriptions: dict[str, PnLSingle] = {}

    def positions(self):
        return self.session.call(self.session.ib.positions, timeout=30)

    def account_summary(self):
        if hasattr(self.session.ib, "accountSummaryAsync"):
            return self.session.call_async(
                self.session.ib.accountSummaryAsync, timeout=30
            )
        return self.session.call(self.session.ib.accountSummary, timeout=30)

    def portfolio(self):
        return self.session.call(self.session.ib.portfolio, timeout=30)

    def trades(self):
        return self.session.call(self.session.ib.trades, timeout=10)

    def subscribe_pnl(self, account: str, model_code: str = "") -> PnL:
        pnl = self.session.call(self.session.ib.reqPnL, account, model_code, timeout=10)
        self._pnl_subscriptions[account] = pnl
        return pnl

    def cancel_pnl(self, account: str, model_code: str = "") -> None:
        self.session.call(self.session.ib.cancelPnL, account, model_code, timeout=5)
        self._pnl_subscriptions.pop(account, None)

    def subscribe_pnl_single(
        self, account: str, model_code: str, con_id: int
    ) -> PnLSingle:
        pnl = self.session.call(
            self.session.ib.reqPnLSingle, account, model_code, con_id, timeout=10
        )
        key = f"{account}:{con_id}"
        self._pnl_single_subscriptions[key] = pnl
        return pnl

    def cancel_pnl_single(self, account: str, model_code: str, con_id: int) -> None:
        self.session.call(
            self.session.ib.cancelPnLSingle, account, model_code, con_id, timeout=5
        )
        key = f"{account}:{con_id}"
        self._pnl_single_subscriptions.pop(key, None)
