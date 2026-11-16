"""Tick Data Quality and Integrity Validator."""

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional
import polars as pl


@dataclass
class ValidationReport:
    """Summary of data quality findings for a tick dataset."""
    total_ticks: int = 0
    negative_or_zero_spread_count: int = 0
    out_of_order_timestamp_count: int = 0
    duplicate_count: int = 0
    extreme_spike_count: int = 0
    min_spread: float = 0.0
    max_spread: float = 0.0
    avg_spread: float = 0.0
    min_bid: float = 0.0
    max_bid: float = 0.0
    is_valid: bool = True
    issues: list[str] = field(default_factory=list)

    def print_summary(self):
        """Print formatted report to stdout."""
        print("=" * 50)
        print("TICK DATA INTEGRITY REPORT")
        print("=" * 50)
        print(f"Total Ticks                : {self.total_ticks:,}")
        print(f"Valid Dataset Status       : {'PASS' if self.is_valid else 'FAIL'}")
        print(f"Negative/Zero Spreads      : {self.negative_or_zero_spread_count:,}")
        print(f"Out-of-order Timestamps    : {self.out_of_order_timestamp_count:,}")
        print(f"Duplicate Ticks            : {self.duplicate_count:,}")
        print(f"Extreme Price Spikes       : {self.extreme_spike_count:,}")
        print(f"Spread Range (Min / Max)   : ${self.min_spread:.3f} / ${self.max_spread:.3f}")
        print(f"Average Spread             : ${self.avg_spread:.3f}")
        print(f"Bid Range (Min / Max)      : ${self.min_bid:.2f} / ${self.max_bid:.2f}")
        if self.issues:
            print("\nIdentified Issues:")
            for issue in self.issues:
                print(f" - {issue}")
        print("=" * 50)


class TickDataValidator:
    """Validates real tick datasets before consumption by the backtesting engine."""

    def __init__(self, max_allowed_spread: float = 5.0, spike_threshold_usd: float = 15.0):
        self.max_allowed_spread = max_allowed_spread
        self.spike_threshold_usd = spike_threshold_usd

    def validate(self, df: pl.DataFrame) -> ValidationReport:
        """Run full battery of integrity checks on a Polars DataFrame of ticks."""
        report = ValidationReport()
        report.total_ticks = len(df)

        if df.is_empty():
            report.is_valid = False
            report.issues.append("Dataset is empty.")
            return report

        # 1. Spread Check (Ask > Bid)
        invalid_spread = df.filter(pl.col("ask") <= pl.col("bid"))
        report.negative_or_zero_spread_count = len(invalid_spread)
        if report.negative_or_zero_spread_count > 0:
            report.issues.append(f"Found {report.negative_or_zero_spread_count} ticks with Ask <= Bid.")

        # Compute spread stats
        spread_stats = df.select([
            pl.col("spread").min().alias("min_spread"),
            pl.col("spread").max().alias("max_spread"),
            pl.col("spread").mean().alias("avg_spread"),
            pl.col("bid").min().alias("min_bid"),
            pl.col("bid").max().alias("max_bid"),
        ]).to_dicts()[0]

        report.min_spread = float(spread_stats["min_spread"] or 0.0)
        report.max_spread = float(spread_stats["max_spread"] or 0.0)
        report.avg_spread = float(spread_stats["avg_spread"] or 0.0)
        report.min_bid = float(spread_stats["min_bid"] or 0.0)
        report.max_bid = float(spread_stats["max_bid"] or 0.0)

        # 2. Chronological Order Check
        time_diffs = df.select(
            (pl.col("timestamp") - pl.col("timestamp").shift(1)).dt.total_nanoseconds().alias("diff_ns")
        ).drop_nulls()
        out_of_order = time_diffs.filter(pl.col("diff_ns") < 0)
        report.out_of_order_timestamp_count = len(out_of_order)
        if report.out_of_order_timestamp_count > 0:
            report.issues.append(f"Found {report.out_of_order_timestamp_count} out-of-order timestamps.")

        # 3. Exact Duplicates Check
        exact_dupes = len(df) - len(df.unique(subset=["timestamp", "bid", "ask"]))
        report.duplicate_count = exact_dupes

        # 4. Price Spike / Flash Anomaly Check
        price_jumps = df.select([
            (pl.col("bid") - pl.col("bid").shift(1)).abs().alias("jump_1"),
            (pl.col("bid") - pl.col("bid").shift(2)).abs().alias("jump_2"),
        ]).drop_nulls()
        
        # An extreme spike that quickly reverts back
        spikes = price_jumps.filter(
            (pl.col("jump_1") > self.spike_threshold_usd) & (pl.col("jump_2") < 2.0)
        )
        report.extreme_spike_count = len(spikes)
        if report.extreme_spike_count > 0:
            report.issues.append(f"Found {report.extreme_spike_count} isolated price spikes > ${self.spike_threshold_usd}.")

        # Dataset validity determination
        if report.negative_or_zero_spread_count > 0 or report.out_of_order_timestamp_count > 0:
            report.is_valid = False

        return report
