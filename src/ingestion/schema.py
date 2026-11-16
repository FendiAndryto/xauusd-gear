"""Schema definitions and type constants for XAUUSD Tick Data."""

import polars as pl

# Standard Schema for normalized tick data in Polars & Parquet
TICK_SCHEMA = {
    "timestamp": pl.Datetime("ns", "UTC"),
    "bid": pl.Float64,
    "ask": pl.Float64,
    "spread": pl.Float64,
    "volume": pl.Float64,
    "flags": pl.UInt32,
}

# Column list in canonical order
TICK_COLUMNS = ["timestamp", "bid", "ask", "spread", "volume", "flags"]
