"""In-Sample Backtesting & Cost Sensitivity Analysis on Real MT5 Ticks (TICK-204)."""

from datetime import datetime
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl
from rich.console import Console
from rich.table import Table

from src.analytics.metrics import BacktestMetrics, MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.ingestion.storage import TickStorageManager
from src.simulator.engine import TickBacktestEngine
from src.strategies.flow_momentum_scalper import FlowMomentumScalper

console = Console()


def run_sensitivity_scenario(
    is_df: pl.DataFrame,
    scenario_name: str,
    latency_min: int,
    latency_max: int,
    slippage_std: float,
) -> BacktestMetrics:
    """Run a single backtest scenario with specific execution friction."""
    broker_cfg = BrokerConfig(
        symbol="XAUUSDm",
        contract_size=100.0,
        point_size=0.001,
        digits=3,
        commission_per_lot_round_turn=0.0,  # Exness Standard: costs embedded in $0.24 spread
    )
    exec_cfg = ExecutionConfig(
        latency_min_ms=latency_min,
        latency_max_ms=latency_max,
        base_slippage_mean_points=0.01,
        base_slippage_std_points=slippage_std,
    )
    config = BacktestConfig(
        initial_balance=10_000.0,
        broker=broker_cfg,
        execution=exec_cfg,
    )

    strategy = FlowMomentumScalper(
        window_ticks=25,
        momentum_threshold_usd=0.45,
        max_elapsed_seconds=3.0,
        max_spread_usd=0.25,
        take_profit_points=0.85,
        stop_loss_points=0.55,
        max_hold_seconds=60.0,
        volume=0.50,
        allowed_hours_utc={12, 13, 14, 15, 16, 17, 18},  # US / London overlap
    )

    engine = TickBacktestEngine(strategy=strategy, config=config)
    res = engine.run(is_df, snapshot_interval_ticks=2000)

    metrics = MetricsCalculator.calculate(
        res.closed_trades, res.equity_curve, initial_balance=10_000.0
    )
    return metrics


def main():
    console.print("[cyan]Loading real ticks from Parquet storage for In-Sample Research...[/cyan]")
    storage = TickStorageManager()
    ticks_df = storage.load_ticks(symbol="xauusd")

    if ticks_df.is_empty():
        console.print("[red]No ticks found! Run scripts/ingest_ticks.py first.[/red]")
        return

    # Split 70% In-Sample
    total_ticks = len(ticks_df)
    is_count = int(total_ticks * 0.70)
    is_df = ticks_df.slice(0, is_count)
    console.print(f"[green]Total real ticks: {total_ticks:,} | 70% In-Sample: {is_count:,} ticks[/green]")
    console.print(f"[dim]In-Sample Date Range: {is_df['timestamp'].min()} to {is_df['timestamp'].max()}[/dim]")

    # Run Baseline In-Sample Backtest
    console.print("\n[bold cyan]1. Executing Baseline In-Sample Backtest...[/bold cyan]")
    base_metrics = run_sensitivity_scenario(
        is_df,
        scenario_name="Standard Latency",
        latency_min=50,
        latency_max=120,
        slippage_std=0.02,
    )

    reporter = PerformanceReporter()
    reporter.print_tear_sheet(base_metrics, title="In-Sample Baseline Tear-Sheet (Exness XAUUSDm Real Ticks)")

    # Latency Sensitivity Stress-Test
    console.print("\n[bold magenta]2. Running Cost & Latency Sensitivity Stress-Test...[/bold magenta]")
    scenarios = [
        ("Fast VPS (20-50ms)", 20, 50, 0.01),
        ("Standard Fiber (50-120ms)", 50, 120, 0.02),
        ("High Latency (150-300ms)", 150, 300, 0.04),
    ]

    sens_table = Table(
        title="Execution Friction Sensitivity Analysis (In-Sample)",
        header_style="bold cyan",
        border_style="bright_blue",
    )
    sens_table.add_column("Scenario", style="bold")
    sens_table.add_column("Latency Delay", justify="center")
    sens_table.add_column("Trades", justify="right")
    sens_table.add_column("Win Rate", justify="right")
    sens_table.add_column("Profit Factor", justify="right")
    sens_table.add_column("Net Profit", justify="right")
    sens_table.add_column("Max DD (%)", justify="right")
    sens_table.add_column("Sharpe", justify="right")

    for name, lat_min, lat_max, slip in scenarios:
        m = run_sensitivity_scenario(is_df, name, lat_min, lat_max, slip)
        p_color = "green" if m.net_profit >= 0 else "red"
        sens_table.add_row(
            name,
            f"{lat_min}-{lat_max} ms",
            f"{m.total_trades:,}",
            f"{m.win_rate_pct:.1f}%",
            f"{m.profit_factor:.2f}",
            f"[{p_color}]${m.net_profit:,.2f}[/{p_color}]",
            f"{m.max_drawdown_pct:.1f}%",
            f"{m.sharpe_ratio:.2f}",
        )

    console.print(sens_table)


if __name__ == "__main__":
    main()
