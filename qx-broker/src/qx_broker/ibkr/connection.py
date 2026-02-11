"""Connection and event loop management for ib_insync."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import Future
from typing import Callable, TypeVar

from ib_insync import IB
from qx_broker.ibkr.config import IBKRSessionConfig
from qx_broker.ibkr.errors import IBKRError, is_client_id_in_use, is_connection_error

logger = logging.getLogger(__name__)

T = TypeVar("T")


class _IBKREventLoop:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ib: IB | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=10):
            raise RuntimeError("IBKR event loop did not start")

    def stop(self) -> None:
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ib = IB()
        self._ready.set()
        loop.run_forever()
        loop.close()

    @property
    def ib(self) -> IB:
        if not self._ib:
            raise RuntimeError("IB instance not initialized")
        return self._ib

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if not self._loop:
            raise RuntimeError("Event loop not initialized")
        return self._loop

    def run_coroutine(self, coro: asyncio.Future, timeout: float | None = None) -> T:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout)

    def call(
        self, func: Callable[..., T], *args, timeout: float | None = None, **kwargs
    ) -> T:
        async def _call() -> T:
            return func(*args, **kwargs)

        return self.run_coroutine(_call(), timeout=timeout)

    def call_soon(self, func: Callable[..., None], *args, **kwargs) -> Future:
        fut: Future = Future()

        def _wrapper() -> None:
            try:
                func(*args, **kwargs)
                fut.set_result(True)
            except Exception as exc:
                fut.set_exception(exc)

        self.loop.call_soon_threadsafe(_wrapper)
        return fut


class IBKRSession:
    def __init__(self, config: IBKRSessionConfig) -> None:
        self.config = config
        self.config.validate()
        self._loop = _IBKREventLoop()
        self._connected = False
        self._last_error: IBKRError | None = None
        self._active_client_id: int | None = None

    def start(self) -> None:
        self._loop.start()
        self._configure_ib()

    def connect(self) -> bool:
        self.start()
        if self.is_connected():
            return True

        connection = self.config.connection
        client_id = connection.client_id

        for attempt in range(connection.reconnect_attempts + 1):
            try:
                logger.info("IBKR connect attempt %s with clientId %s", attempt + 1, client_id)
                if self._connect_with_client_id(client_id):
                    self._connected = True
                    return True
            except Exception as exc:
                logger.warning("IBKR connect attempt %s failed: %s", attempt + 1, exc)

            if connection.allow_client_id_fallback:
                client_id += 1
                max_id = connection.client_id + connection.client_id_fallbacks
                if client_id > max_id:
                    logger.warning("Exhausted client_id range %s-%s, giving up", connection.client_id, max_id)
                    break

            backoff = min(connection.reconnect_backoff_sec * (2 ** attempt), 60)
            logger.info("Reconnect backoff: %.1fs", backoff)
            time.sleep(backoff)

        return False

    def disconnect(self) -> None:
        if not self._loop or not self._loop.ib:
            return
        try:
            self._loop.call(self._loop.ib.disconnect, timeout=5)
        except Exception as exc:
            logger.warning("IBKR disconnect error: %s", exc)
        self._connected = False
        self._loop.stop()

    def is_connected(self) -> bool:
        if not self._loop:
            return False
        try:
            _ = self._loop.ib
        except RuntimeError:
            return False
        try:
            return self._loop.call(self._loop.ib.isConnected, timeout=5)
        except Exception:
            return False

    def check_connection(self) -> bool:
        if not self.is_connected():
            return False
        try:
            _ = self._loop.call(self._loop.ib.reqCurrentTime, timeout=10)
            return True
        except Exception as exc:
            logger.warning("IBKR current time check failed: %s", exc)
            return False

    def call(
        self, func: Callable[..., T], *args, timeout: float | None = None, **kwargs
    ) -> T:
        return self._loop.call(func, *args, timeout=timeout, **kwargs)

    def call_async(
        self,
        func: Callable[..., asyncio.Future],
        *args,
        timeout: float | None = None,
        **kwargs,
    ):
        return self._loop.run_coroutine(func(*args, **kwargs), timeout=timeout)

    def call_soon(self, func: Callable[..., None], *args, **kwargs) -> Future:
        return self._loop.call_soon(func, *args, **kwargs)

    @property
    def ib(self) -> IB:
        return self._loop.ib

    @property
    def last_error(self) -> IBKRError | None:
        return self._last_error

    @property
    def active_client_id(self) -> int:
        return self._active_client_id or self.config.connection.client_id

    def _configure_ib(self) -> None:
        ib = self._loop.ib
        connection = self.config.connection
        ib.RequestTimeout = connection.request_timeout
        ib.RaiseRequestErrors = connection.raise_request_errors
        if connection.timezone_tws:
            ib.TimezoneTWS = connection.timezone_tws
        ib.errorEvent += self._on_error
        ib.disconnectedEvent += self._on_disconnect

    def _connect_with_client_id(self, client_id: int) -> bool:
        connection = self.config.connection
        try:
            coro = self._loop.ib.connectAsync(
                host=connection.host,
                port=connection.port,
                clientId=client_id,
                timeout=connection.connect_timeout,
                readonly=connection.readonly,
                raiseSyncErrors=True,
            )
        except TypeError:
            logger.info(
                "ib_insync connectAsync missing raiseSyncErrors; retrying without it"
            )
            coro = self._loop.ib.connectAsync(
                host=connection.host,
                port=connection.port,
                clientId=client_id,
                timeout=connection.connect_timeout,
                readonly=connection.readonly,
            )
        self._loop.run_coroutine(coro, timeout=connection.connect_timeout + 2)
        connected = self._loop.call(self._loop.ib.isConnected, timeout=5)
        if not connected:
            raise RuntimeError("IBKR connection failed")
        self._active_client_id = client_id
        return True

    def _on_error(
        self, req_id: int, error_code: int, error_string: str, contract
    ) -> None:
        error = IBKRError(code=error_code, message=error_string, context=str(req_id))
        self._last_error = error
        if is_client_id_in_use(error_code):
            logger.warning("Client ID in use: %s", error)
        elif is_connection_error(error_code):
            logger.error("Connection error: %s", error)
        else:
            logger.info("IBKR message: %s", error)

    def _on_disconnect(self) -> None:
        self._connected = False
        logger.warning("IBKR disconnected")
