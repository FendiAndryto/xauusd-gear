"""Direct Tick Collector from MetaTrader 5 terminal via official Python API with auto-chunking."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union
import logging
import MetaTrader5 as mt5
import numpy as np
import polars as pl

from src.config import PathConfig
from src.ingestion.schema import TICK_COLUMNS, TICK_SCHEMA
from src.ingestion.storage import TickStorageManager

logger = logging.getLogger(__name__)


class MT5TickCollector:
    """Collects real tick data directly from an active MetaTrader 5 terminal."""

    def __init__(
        self,
        terminal_path: Optional[str] = None,
        storage_manager: Optional[TickStorageManager] = None,
    ):
        paths = PathConfig()
        self.terminal_path = terminal_path or paths.mt5_terminal_path
        self.storage = storage_manager or TickStorageManager()
        self._is_initialized = False

    def connect(self) -> bool:
        """Initialize connection to MT5 terminal."""
        if self._is_initialized:
            return True

        init_args = {}
        if self.terminal_path and Path(self.terminal_path).exists():
            init_args["path"] = self.terminal_path

        if not mt5.initialize(**init_args):
            err = mt5.last_error()
            logger.error(f"Failed to connect to MetaTrader 5: {err}")
            return False

        terminal_info = mt5.terminal_info()
        logger.info(f"Connected to MT5: {terminal_info.name} ({terminal_info.path})")
        self._is_initialized = True
        return True

    def disconnect(self):
        """Shutdown MT5 connection."""
        if self._is_initialized:
            mt5.shutdown()
            self._is_initialized = False

    def resolve_symbol(self, requested_symbol: str = "XAUUSD") -> str:
        """Find the broker's exact symbol name for gold (e.g. XAUUSD, XAUUSDm, GOLD)."""
        if not self._is_initialized:
            self.connect()

        # Check direct match
        info = mt5.symbol_info(requested_symbol)
        if info is not None:
            mt5.symbol_select(requested_symbol, True)
            return requested_symbol

        # Search candidates
        all_symbols = [s.name for s in mt5.symbols_get() or []]
        candidates = [s for s in all_symbols if requested_symbol.upper() in s.upper() or "XAU" in s.upper()]
        
        # Priority order
        for cand in [f"{requested_symbol}m", f"{requested_symbol}.a", "GOLD", "GOLDm"]:
            if cand in candidates:
                mt5.symbol_select(cand, True)
                return cand

        if candidates:
            mt5.symbol_select(candidates[0], True)
            return candidates[0]

        raise ValueError(f"Could not find any symbol matching '{requested_symbol}' in MT5.")

    def fetch_ticks(
        self,
        symbol: str = "XAUUSD",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        save_to_parquet: bool = True,
        chunk_days: int = 7,
        return_dataframe: bool = True,
    ) -> pl.DataFrame:
        """Fetch tick data chunk-by-chunk to prevent memory limits in MT5 API.
        
        Args:
            symbol: Ticker symbol (will be auto-resolved to broker naming).
            start: Start datetime in UTC.
            end: End datetime in UTC.
            save_to_parquet: Automatically save each chunk to partitioned Parquet files.
            chunk_days: Number of days per fetch chunk (default: 7 days).
            return_dataframe: Whether to keep and return the full combined DataFrame in memory.
                             Set to False when downloading massive multi-month datasets.
            
        Returns:
            Polars DataFrame with normalized ticks matching TICK_SCHEMA.
        """
        if not self._is_initialized:
            if not self.connect():
                raise ConnectionError("Could not connect to MetaTrader 5 terminal.")

        real_symbol = self.resolve_symbol(symbol)
        mt5.symbol_select(real_symbol, True)

        if end is None:
            end = datetime.now(timezone.utc)
        if start is None:
            # Default to 30 days prior to end
            start = end - timedelta(days=30)

        # Ensure start and end are UTC
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)

        logger.info(f"Fetching ticks for {real_symbol} from {start} to {end} in {chunk_days}-day chunks...")

        current_start = start
        all_dfs: list[pl.DataFrame] = []
        total_ticks_count = 0

        while current_start < end:
            current_end = min(current_start + timedelta(days=chunk_days), end)
            print(f"Fetching chunk {current_start.strftime('%Y-%m-%d')} -> {current_end.strftime('%Y-%m-%d')}...")

            raw_ticks = mt5.copy_ticks_range(real_symbol, current_start, current_end, mt5.COPY_TICKS_ALL)
            if raw_ticks is not None and len(raw_ticks) > 0:
                chunk_df = self._convert_raw_ticks_to_df(raw_ticks)
                total_ticks_count += len(chunk_df)
                print(f" -> Received {len(chunk_df):,} ticks (Total so far: {total_ticks_count:,})")

                if save_to_parquet:
                    # Save each chunk immediately to free memory
                    self.storage.save_ticks(chunk_df, symbol="xauusd")
                
                if return_dataframe:
                    all_dfs.append(chunk_df)
            else:
                print(f" -> 0 ticks in chunk {current_start.strftime('%Y-%m-%d')}.")

            current_start = current_end

        if return_dataframe and all_dfs:
            combined = pl.concat(all_dfs).unique(subset=["timestamp", "bid", "ask"]).sort("timestamp")
            return combined
        
        print(f"[Done] Total ticks ingested: {total_ticks_count:,}")
        return pl.DataFrame(schema=TICK_SCHEMA)

    def _convert_raw_ticks_to_df(self, raw_ticks: np.ndarray) -> pl.DataFrame:
        """Convert MT5 structured numpy tick array into standard Polars DataFrame."""
        vol_col = "volume_real" if "volume_real" in raw_ticks.dtype.names else "volume"
        df = pl.DataFrame({
            "time_msc": raw_ticks["time_msc"],
            "bid": raw_ticks["bid"],
            "ask": raw_ticks["ask"],
            "volume": raw_ticks[vol_col],
            "flags": raw_ticks["flags"],
        })

        # Convert epoch milliseconds to UTC Datetime nanoseconds
        df = df.with_columns(
            (pl.col("time_msc") * 1_000_000).cast(pl.Datetime("ns", "UTC")).alias("timestamp")
        )

        # Calculate spread
        df = df.with_columns((pl.col("ask") - pl.col("bid")).round(4).alias("spread"))

        return df.select(TICK_COLUMNS).cast(TICK_SCHEMA).sort("timestamp")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
