"""IBKR error classification utilities."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IBKRError:
    code: int
    message: str
    context: str | None = None

    def __str__(self) -> str:
        suffix = f" ({self.context})" if self.context else ""
        return f"IBKR error {self.code}: {self.message}{suffix}"


CONNECTION_ERROR_CODES = {1100, 1101, 1102}
CLIENT_ID_IN_USE = {326}
SECURITY_DEFINITION_ERRORS = {200, 162}
ORDER_REJECTED_CODES = {201, 202, 203}


def is_connection_error(code: int) -> bool:
    return code in CONNECTION_ERROR_CODES


def is_client_id_in_use(code: int) -> bool:
    return code in CLIENT_ID_IN_USE


def is_security_definition_error(code: int) -> bool:
    return code in SECURITY_DEFINITION_ERRORS


def is_order_rejected(code: int) -> bool:
    return code in ORDER_REJECTED_CODES
