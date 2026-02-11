"""Contract utilities and caching."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

from ib_insync import Contract, ContractDetails, Stock
from qx_broker.ibkr.connection import IBKRSession


@dataclass(frozen=True)
class ContractKey:
    symbol: str
    exchange: str
    currency: str
    primary_exchange: str | None


class ContractCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._contracts: dict[ContractKey, Contract] = {}
        self._details: dict[int, ContractDetails] = {}

    def get_contract(self, key: ContractKey) -> Contract | None:
        with self._lock:
            return self._contracts.get(key)

    def set_contract(self, key: ContractKey, contract: Contract) -> None:
        with self._lock:
            self._contracts[key] = contract

    def get_details(self, con_id: int) -> ContractDetails | None:
        with self._lock:
            return self._details.get(con_id)

    def set_details(self, con_id: int, details: ContractDetails) -> None:
        with self._lock:
            self._details[con_id] = details


class ContractFactory:
    def __init__(
        self, session: IBKRSession, cache: ContractCache | None = None
    ) -> None:
        self.session = session
        self.cache = cache or ContractCache()

    def stock(
        self,
        symbol: str,
        exchange: str = "SMART",
        currency: str = "USD",
        primary_exchange: str | None = None,
    ) -> Contract:
        key = ContractKey(
            symbol=symbol,
            exchange=exchange,
            currency=currency,
            primary_exchange=primary_exchange,
        )
        cached = self.cache.get_contract(key)
        if cached:
            return cached
        contract = Stock(symbol, exchange, currency)
        if primary_exchange:
            contract.primaryExchange = primary_exchange
        self.cache.set_contract(key, contract)
        return contract

    def qualify(self, contract: Contract) -> Contract:
        if hasattr(self.session.ib, "qualifyContractsAsync"):
            qualified = self.session.call_async(
                self.session.ib.qualifyContractsAsync, contract, timeout=10
            )
        else:
            qualified = self.session.call(
                self.session.ib.qualifyContracts, contract, timeout=10
            )
        if not qualified:
            raise ValueError(f"No contract qualified for {contract}")
        return qualified[0]

    def get_details(self, contract: Contract) -> ContractDetails:
        if hasattr(self.session.ib, "reqContractDetailsAsync"):
            details_list = self.session.call_async(
                self.session.ib.reqContractDetailsAsync, contract, timeout=10
            )
        else:
            details_list = self.session.call(
                self.session.ib.reqContractDetails, contract, timeout=10
            )
        if not details_list:
            raise ValueError(f"No contract details for {contract}")
        details = details_list[0]
        if details.contract and details.contract.conId:
            self.cache.set_details(details.contract.conId, details)
        return details

    def min_tick(self, contract: Contract) -> float:
        con_id = getattr(contract, "conId", 0) or 0
        if con_id:
            cached = self.cache.get_details(con_id)
            if cached and cached.minTick:
                return float(cached.minTick)
        details = self.get_details(contract)
        return float(details.minTick or 0.0)

    def get_cached_details(self, con_id: int) -> ContractDetails | None:
        return self.cache.get_details(con_id)
