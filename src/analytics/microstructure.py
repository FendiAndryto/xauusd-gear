"""Market Microstructure, Spread Distribution, and Liquidity Profiler for XAUUSD."""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import polars as pl
from rich.console import Console
from rich.table import Table

from src.config import PathConfig


@dataclass
class MicrostructureProfile:
    """Hourly microstructure metrics."""
    hour_utc: int
    hour_wib: int
    total_ticks: int
    ticks_per_sec: float
    mean_spread: float
    median_spread: float
    p95_spread: float
    max_spread: float
    trading_regime: str  # "PRIME_SCALPING", "MODERATE", "AVOID_ROLLOVER"


class MicrostructureProfiler:
    """Analyzes real tick data to discover optimal scalping windows and spread regimes."""

    def __init__(self, output_dir: Optional[Path] = None):
        paths = PathConfig()
        self.output_dir = output_dir or paths.reports_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.console = Console()

    def profile(self, df: pl.DataFrame) -> list[MicrostructureProfile]:
        """Aggregate tick metrics grouped by hour of the day."""
        if df.is_empty():
            raise ValueError("Input DataFrame is empty.")

        # Extract UTC hour and calculate WIB hour (UTC+7)
        # Note: 3600 seconds per hour; assuming active market weekdays (~22 trading days per month)
        df_hour = df.with_columns([
            pl.col("timestamp").dt.hour().alias("hour_utc"),
            ((pl.col("timestamp").dt.hour() + 7) % 24).alias("hour_wib"),
        ])

        # Group by hour_utc and calculate statistics
        stats = (
            df_hour.group_by(["hour_utc", "hour_wib"])
            .agg([
                pl.len().alias("tick_count"),
                pl.col("spread").mean().round(3).alias("mean_spread"),
                pl.col("spread").median().round(3).alias("median_spread"),
                pl.col("spread").quantile(0.95).round(3).alias("p95_spread"),
                pl.col("spread").max().round(3).alias("max_spread"),
            ])
            .sort("hour_utc")
        )

        # Estimate average trading days in dataset to calculate average ticks/sec per hour
        total_days = max(1, (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400.0)
        # Assuming ~5/7 of days are trading days
        trading_days = max(1.0, total_days * (5.0 / 7.0))

        profiles = []
        for row in stats.iter_rows(named=True):
            h_utc = row["hour_utc"]
            h_wib = row["hour_wib"]
            count = row["tick_count"]
            mean_sp = float(row["mean_spread"])
            med_sp = float(row["median_spread"])
            p95_sp = float(row["p95_spread"])
            max_sp = float(row["max_spread"])

            # Ticks per second across active trading hours
            ticks_sec = round(count / (trading_days * 3600.0), 1)

            # Classify regime
            if p95_sp > 0.35 or h_utc in [21, 22]:
                regime = "AVOID_ROLLOVER"
            elif p95_sp <= 0.25 and ticks_sec >= 15.0:
                regime = "PRIME_SCALPING"
            else:
                regime = "MODERATE"

            profiles.append(MicrostructureProfile(
                hour_utc=h_utc,
                hour_wib=h_wib,
                total_ticks=count,
                ticks_per_sec=ticks_sec,
                mean_spread=mean_sp,
                median_spread=med_sp,
                p95_spread=p95_sp,
                max_spread=max_sp,
                trading_regime=regime,
            ))

        return profiles

    def print_profile_table(self, profiles: list[MicrostructureProfile]):
        """Render Rich table with color-coded microstructure regimes."""
        table = Table(
            title="XAUUSD Market Microstructure & Spread Profile (Broker Real Ticks)",
            header_style="bold cyan",
            border_style="bright_blue",
        )
        table.add_column("Hour UTC", justify="center", style="dim")
        table.add_column("Hour WIB", justify="center", style="bold yellow")
        table.add_column("Ticks/Sec", justify="right")
        table.add_column("Median Spread", justify="right")
        table.add_column("95th % Spread", justify="right")
        table.add_column("Max Spread", justify="right")
        table.add_column("Trading Regime", justify="center", style="bold")

        for p in profiles:
            if p.trading_regime == "PRIME_SCALPING":
                regime_style = "[bold green]PRIME SCALPING[/bold green]"
                sp_style = "green"
            elif p.trading_regime == "AVOID_ROLLOVER":
                regime_style = "[bold red]AVOID / ROLLOVER[/bold red]"
                sp_style = "red"
            else:
                regime_style = "[yellow]MODERATE[/yellow]"
                sp_style = "white"

            table.add_row(
                f"{p.hour_utc:02d}:00",
                f"{p.hour_wib:02d}:00",
                f"{p.ticks_per_sec:.1f}",
                f"[{sp_style}]${p.median_spread:.3f}[/{sp_style}]",
                f"[{sp_style}]${p.p95_spread:.3f}[/{sp_style}]",
                f"${p.max_spread:.3f}",
                regime_style,
            )

        self.console.print(table)

    def export_csv(self, profiles: list[MicrostructureProfile], filename: str = "microstructure_analysis.csv") -> Path:
        """Export profile metrics to CSV."""
        records = [{
            "hour_utc": p.hour_utc,
            "hour_wib": p.hour_wib,
            "total_ticks": p.total_ticks,
            "ticks_per_sec": p.ticks_per_sec,
            "mean_spread": p.mean_spread,
            "median_spread": p.median_spread,
            "p95_spread": p.p95_spread,
            "max_spread": p.max_spread,
            "trading_regime": p.trading_regime,
        } for p in profiles]

        df = pl.DataFrame(records)
        out_path = self.output_dir / filename
        df.write_csv(out_path)
        return out_path
