"""Super-fast MT5 CSV Tick Exporter parser using Polars streaming."""

from pathlib import Path
from typing import Optional, Union
import polars as pl

from src.ingestion.schema import TICK_COLUMNS, TICK_SCHEMA
from src.ingestion.storage import TickStorageManager


class MT5CSVImporter:
    """Parses MT5 History Center tick export CSVs and saves to partitioned Parquet."""

    def __init__(self, storage_manager: Optional[TickStorageManager] = None):
        self.storage = storage_manager or TickStorageManager()

    def import_csv(
        self,
        file_path: Union[str, Path],
        symbol: str = "XAUUSD",
        save_to_parquet: bool = True,
    ) -> pl.DataFrame:
        """Parse an MT5 tick CSV file into a normalized Polars DataFrame.
        
        Args:
            file_path: Path to MT5 CSV export file.
            symbol: Ticker symbol (default XAUUSD).
            save_to_parquet: If True, automatically persists to partitioned Parquet.
            
        Returns:
            Normalized Polars DataFrame matching TICK_SCHEMA.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        # Detect separator (inspect first few lines)
        separator = self._detect_separator(path)

        # Read sample to inspect columns
        sample_df = pl.read_csv(path, separator=separator, n_rows=10, infer_schema_length=10)
        col_names = [c.strip("<>").lower() for c in sample_df.columns]

        # Scenario A: Separate <DATE> and <TIME> columns
        if "date" in col_names and "time" in col_names:
            df = self._parse_separate_datetime(path, separator)
        # Scenario B: Combined datetime column
        elif any("time" in c or "date" in c for c in col_names):
            df = self._parse_combined_datetime(path, separator)
        else:
            # Headerless MT5 export: assume col 0 is date, 1 is time, 2 is bid, 3 is ask, etc.
            df = self._parse_headerless(path, separator)

        # Compute spread and enforce schema
        df = self._normalize(df)

        if save_to_parquet:
            self.storage.save_ticks(df, symbol=symbol)

        return df

    def _detect_separator(self, path: Path) -> str:
        """Inspect first line of file to determine delimiter."""
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            first_line = f.readline()
            if "\t" in first_line:
                return "\t"
            elif ";" in first_line:
                return ";"
            return ","

    def _parse_separate_datetime(self, path: Path, sep: str) -> pl.DataFrame:
        """Parse CSV with separate Date and Time columns."""
        df = pl.read_csv(
            path,
            separator=sep,
            has_header=True,
            infer_schema_length=1000,
        )
        # Rename lower-cased stripped headers
        df = df.rename({col: col.strip("<> ").lower() for col in df.columns})

        # Combine date + time
        df = df.with_columns(
            pl.concat_str([pl.col("date").cast(pl.String), pl.lit(" "), pl.col("time").cast(pl.String)]).alias("dt_str")
        )

        # Parse datetime (format: YYYY.MM.DD HH:MM:SS.fff or YYYY-MM-DD...)
        df = df.with_columns(
            pl.col("dt_str")
            .str.replace_all("/", ".")
            .str.to_datetime(format="%Y.%m.%d %H:%M:%S%.f", time_zone="UTC")
            .alias("timestamp")
        )

        return df

    def _parse_combined_datetime(self, path: Path, sep: str) -> pl.DataFrame:
        """Parse CSV with a single combined datetime column."""
        df = pl.read_csv(path, separator=sep, has_header=True, infer_schema_length=1000)
        df = df.rename({col: col.strip("<> ").lower() for col in df.columns})

        # Identify timestamp column name
        dt_col = [c for c in df.columns if "time" in c or "date" in c][0]

        df = df.with_columns(
            pl.col(dt_col)
            .cast(pl.String)
            .str.replace_all("/", ".")
            .str.to_datetime(format="%Y.%m.%d %H:%M:%S%.f", time_zone="UTC")
            .alias("timestamp")
        )
        return df

    def _parse_headerless(self, path: Path, sep: str) -> pl.DataFrame:
        """Parse CSV without headers assuming standard MT5 column positions."""
        df = pl.read_csv(
            path,
            separator=sep,
            has_header=False,
            infer_schema_length=1000,
        )
        col0 = df.columns[0]
        col1 = df.columns[1]
        col2 = df.columns[2]
        col3 = df.columns[3]
        col4 = df.columns[4] if len(df.columns) > 4 else None
        col5 = df.columns[5] if len(df.columns) > 5 else None

        df = df.with_columns(
            pl.concat_str([pl.col(col0).cast(pl.String), pl.lit(" "), pl.col(col1).cast(pl.String)]).alias("dt_str")
        )
        df = df.with_columns(
            pl.col("dt_str")
            .str.replace_all("/", ".")
            .str.to_datetime(format="%Y.%m.%d %H:%M:%S%.f", time_zone="UTC")
            .alias("timestamp"),
            pl.col(col2).cast(pl.Float64).alias("bid"),
            pl.col(col3).cast(pl.Float64).alias("ask"),
            pl.col(col4).cast(pl.Float64).alias("volume") if col4 else pl.lit(1.0).alias("volume"),
            pl.col(col5).cast(pl.UInt32).alias("flags") if col5 else pl.lit(0).cast(pl.UInt32).alias("flags"),
        )
        return df

    def _normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        """Standardize column names, calculate spread, and ensure TICK_SCHEMA."""
        # Find bid and ask columns
        bid_col = [c for c in df.columns if "bid" in c][0]
        ask_col = [c for c in df.columns if "ask" in c][0]
        vol_col = [c for c in df.columns if "vol" in c]
        flags_col = [c for c in df.columns if "flag" in c]

        exprs = [
            pl.col("timestamp"),
            pl.col(bid_col).cast(pl.Float64).alias("bid"),
            pl.col(ask_col).cast(pl.Float64).alias("ask"),
        ]

        if vol_col:
            exprs.append(pl.col(vol_col[0]).cast(pl.Float64).alias("volume"))
        else:
            exprs.append(pl.lit(1.0).alias("volume"))

        if flags_col:
            exprs.append(pl.col(flags_col[0]).cast(pl.UInt32).alias("flags"))
        else:
            exprs.append(pl.lit(0).cast(pl.UInt32).alias("flags"))

        res = df.select(exprs)
        # Compute spread
        res = res.with_columns((pl.col("ask") - pl.col("bid")).round(4).alias("spread"))
        return res.select(TICK_COLUMNS).cast(TICK_SCHEMA).sort("timestamp")
