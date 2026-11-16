"""Parquet Storage and Partitioning Manager for Tick Data."""

from datetime import datetime
from pathlib import Path
from typing import Optional, Union
import polars as pl

from src.config import PathConfig
from src.ingestion.schema import TICK_COLUMNS, TICK_SCHEMA


class TickStorageManager:
    """Manages writing and reading partitioned tick data in Apache Parquet format."""

    def __init__(self, base_dir: Optional[Path] = None):
        paths = PathConfig()
        self.parquet_dir = base_dir or paths.parquet_data_dir
        self.parquet_dir.mkdir(parents=True, exist_ok=True)

    def save_ticks(self, df: pl.DataFrame, symbol: str = "XAUUSD") -> list[Path]:
        """Save a Polars DataFrame of ticks partitioned by year and month.
        
        Args:
            df: DataFrame adhering to TICK_SCHEMA.
            symbol: Financial instrument symbol (e.g. XAUUSD).
            
        Returns:
            List of Path objects for all written parquet files.
        """
        if df.is_empty():
            return []

        # Ensure correct types and canonical columns
        df = self._normalize_dataframe(df)

        # Extract year and month for partitioning
        df = df.with_columns([
            pl.col("timestamp").dt.year().alias("year"),
            pl.col("timestamp").dt.month().alias("month"),
        ])

        saved_files = []
        # Group by partition keys and save
        partitions = df.partition_by(["year", "month"], as_dict=True)
        for (year, month), part_df in partitions.items():
            partition_dir = self.parquet_dir / symbol.lower() / f"year={year}" / f"month={month:02d}"
            partition_dir.mkdir(parents=True, exist_ok=True)
            file_path = partition_dir / "ticks.parquet"

            # Drop temporary partition columns before saving
            clean_part = part_df.drop(["year", "month"])

            # If file already exists, merge, deduplicate and sort
            if file_path.exists():
                existing_df = pl.read_parquet(file_path)
                clean_part = pl.concat([existing_df, clean_part])
                clean_part = clean_part.unique(subset=["timestamp", "bid", "ask"]).sort("timestamp")
            else:
                clean_part = clean_part.unique(subset=["timestamp", "bid", "ask"]).sort("timestamp")

            clean_part.write_parquet(
                file_path,
                compression="zstd",
                compression_level=3,
                statistics=True,
            )
            saved_files.append(file_path)

        return saved_files

    def scan_ticks(
        self,
        symbol: str = "XAUUSD",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        columns: Optional[list[str]] = None,
    ) -> pl.LazyFrame:
        """Return a LazyFrame scanning the partitioned tick files with predicate pushdown.
        
        Args:
            symbol: Ticker symbol.
            start: Optional UTC datetime lower bound.
            end: Optional UTC datetime upper bound.
            columns: Optional subset of columns to load.
            
        Returns:
            pl.LazyFrame ready for querying or collecting.
        """
        symbol_dir = self.parquet_dir / symbol.lower()
        if not symbol_dir.exists():
            # Return empty lazy frame matching schema
            empty_df = pl.DataFrame(schema=TICK_SCHEMA)
            return empty_df.lazy()

        pattern = str(symbol_dir / "**" / "*.parquet")
        lazy_df = pl.scan_parquet(pattern)

        if columns:
            lazy_df = lazy_df.select(columns)

        if start is not None:
            lazy_df = lazy_df.filter(pl.col("timestamp") >= start)
        if end is not None:
            lazy_df = lazy_df.filter(pl.col("timestamp") <= end)

        return lazy_df.sort("timestamp")

    def load_ticks(
        self,
        symbol: str = "XAUUSD",
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        columns: Optional[list[str]] = None,
    ) -> pl.DataFrame:
        """Load filtered ticks into memory as a sorted Polars DataFrame."""
        return self.scan_ticks(symbol, start, end, columns).collect()

    def _normalize_dataframe(self, df: pl.DataFrame) -> pl.DataFrame:
        """Ensure standard schema, column types, and spread column."""
        # Calculate spread if missing
        if "spread" not in df.columns:
            df = df.with_columns((pl.col("ask") - pl.col("bid")).round(4).alias("spread"))

        # Select and cast to standard schema
        casts = {col: TICK_SCHEMA[col] for col in TICK_COLUMNS if col in df.columns}
        return df.select(TICK_COLUMNS).cast(casts)
