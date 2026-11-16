"""MT5 terminal connection bridge for the web dashboard (ticket T-01).

Owns the MetaTrader5 Python API session lifecycle for the FastAPI server so the
browser can connect/disconnect the terminal with one click, without a CLI.
MetaTrader5 is imported lazily: the web app must boot even when the package or
the terminal is unavailable, showing a clean "disconnected" state instead.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.config import PathConfig

logger = logging.getLogger(__name__)


class MT5Bridge:
    """Thread-safe wrapper around the MetaTrader5 session."""

    def __init__(
        self, symbol: str = "XAUUSD", terminal_path: Optional[str] = None
    ) -> None:
        paths = PathConfig()
        # Prefer the terminal this project already locked for research (src/config.py).
        self.terminal_path = terminal_path or paths.mt5_terminal_path
        self.requested_symbol = symbol
        self.symbol: Optional[str] = None
        self.last_error: Optional[str] = None
        self._connected = False
        self._lock = threading.Lock()

    # ---------------------------------------------------------------- internals

    @staticmethod
    def _mt5():
        import MetaTrader5 as mt5  # lazy: keeps the web server importable offline

        return mt5

    def _init_args(self) -> dict[str, Any]:
        if self.terminal_path and Path(self.terminal_path).exists():
            return {"path": self.terminal_path}
        return {}

    def _resolve_symbol(self, mt5) -> Optional[str]:
        """Find the broker's exact gold symbol name (XAUUSD, XAUUSDm, GOLD, ...)."""
        if mt5.symbol_info(self.requested_symbol) is not None:
            mt5.symbol_select(self.requested_symbol, True)
            return self.requested_symbol

        names = [s.name for s in (mt5.symbols_get() or [])]
        candidates = [
            name
            for name in names
            if self.requested_symbol.upper() in name.upper() or "XAU" in name.upper()
        ]
        for preferred in (
            f"{self.requested_symbol}m",
            f"{self.requested_symbol}.a",
            "GOLD",
            "GOLDm",
        ):
            if preferred in candidates:
                mt5.symbol_select(preferred, True)
                return preferred
        if candidates:
            mt5.symbol_select(candidates[0], True)
            return candidates[0]
        return None

    # ------------------------------------------------------------------- public

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_rates(
        self, timeframe_name: str, count: int = 200
    ) -> Optional[list[dict[str, Any]]]:
        """Latest `count` bars for a timeframe, oldest first. None when unavailable."""
        with self._lock:
            if not self._connected or self.symbol is None:
                return None
            try:
                mt5 = self._mt5()
                timeframe = getattr(mt5, f"TIMEFRAME_{timeframe_name.upper()}", None)
                if timeframe is None:
                    self.last_error = f"Timeframe tidak dikenal: {timeframe_name}"
                    logger.error(self.last_error)
                    return None
                rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
                if rates is None or len(rates) == 0:
                    return None
                return [
                    {
                        "time": int(rate["time"]),
                        "open": float(rate["open"]),
                        "high": float(rate["high"]),
                        "low": float(rate["low"]),
                        "close": float(rate["close"]),
                        "volume": float(rate["tick_volume"]),
                    }
                    for rate in rates
                ]
            except Exception as exc:
                self.last_error = f"copy_rates_from_pos gagal: {exc}"
                logger.exception(self.last_error)
                return None

    def get_tick(self) -> Optional[dict[str, Any]]:
        """Latest bid/ask snapshot, or None when disconnected."""
        with self._lock:
            if not self._connected or self.symbol is None:
                return None
            try:
                tick = self._mt5().symbol_info_tick(self.symbol)
                if tick is None:
                    return None
                return {
                    "symbol": self.symbol,
                    "bid": float(tick.bid),
                    "ask": float(tick.ask),
                    "time": int(tick.time),
                    "time_msc": int(tick.time_msc),
                }
            except Exception as exc:
                self.last_error = f"symbol_info_tick gagal: {exc}"
                logger.exception(self.last_error)
                return None

    def initialize(self) -> bool:
        """Attach to the running MT5 terminal. Returns False (never raises) on failure."""
        with self._lock:
            if self._connected:
                return True
            try:
                mt5 = self._mt5()
            except Exception as exc:  # package missing / broken install
                self.last_error = f"Paket MetaTrader5 tidak tersedia: {exc}"
                logger.error(self.last_error)
                return False

            try:
                if not mt5.initialize(**self._init_args()):
                    self.last_error = f"initialize() gagal: {mt5.last_error()}"
                    logger.error(self.last_error)
                    return False

                self.symbol = self._resolve_symbol(mt5)
                if self.symbol is None:
                    self.last_error = f"Simbol {self.requested_symbol} tidak ditemukan di Market Watch terminal."
                    logger.error(self.last_error)
                    mt5.shutdown()
                    return False
            except Exception as exc:
                self.last_error = f"Koneksi MT5 error: {exc}"
                logger.exception(self.last_error)
                return False

            self._connected = True
            self.last_error = None
            logger.info(
                "MT5 connected: symbol=%s path=%s", self.symbol, self.terminal_path
            )
            return True

    def shutdown(self) -> None:
        """Detach from MT5 cleanly. Safe to call when already disconnected."""
        with self._lock:
            if not self._connected:
                self.symbol = None
                return
            try:
                self._mt5().shutdown()
            except Exception as exc:
                self.last_error = f"shutdown() error: {exc}"
                logger.warning(self.last_error)
            finally:
                self._connected = False
                self.symbol = None

    def get_status(self) -> dict[str, Any]:
        """Snapshot for the dashboard header. Always returns the same dict shape."""
        with self._lock:
            status: dict[str, Any] = {
                "connected": False,
                "terminal_running": False,
                "account": None,
                "symbol": None,
                "spread": None,
                "latency_ms": None,
                "last_error": self.last_error,
                "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            if not self._connected:
                return status

            try:
                mt5 = self._mt5()
            except Exception as exc:
                self.last_error = f"Paket MetaTrader5 tidak tersedia: {exc}"
                status["last_error"] = self.last_error
                return status

            try:
                # Full snapshot duration: local IPC round-trip to the terminal process.
                started = time.perf_counter()
                tick = mt5.symbol_info_tick(self.symbol)
                terminal = mt5.terminal_info()
                if tick is None or terminal is None:
                    self._connected = False
                    self.last_error = f"Terminal tidak merespons: {mt5.last_error()}"
                    status["last_error"] = self.last_error
                    logger.warning(self.last_error)
                    return status

                info = mt5.symbol_info(self.symbol)
                account = mt5.account_info()
                latency_ms = (time.perf_counter() - started) * 1000.0

                bid = float(tick.bid)
                ask = float(tick.ask)
                points = float(info.spread) if info is not None else None
                status.update(
                    {
                        "connected": True,
                        "terminal_running": True,
                        "symbol": self.symbol,
                        "spread": {
                            "points": points,
                            "price": round(ask - bid, 4),
                            "bid": round(bid, 2),
                            "ask": round(ask, 2),
                        },
                        "latency_ms": round(latency_ms, 1),
                        "last_error": None,
                    }
                )
                if account is not None:
                    status["account"] = {
                        "login": int(account.login),
                        "balance": float(account.balance),
                        "equity": float(account.equity),
                        "server": str(account.server),
                        "currency": str(account.currency),
                        "leverage": int(account.leverage),
                    }
                return status
            except Exception as exc:
                self.last_error = f"Status MT5 error: {exc}"
                status["last_error"] = self.last_error
                logger.exception(self.last_error)
                return status
