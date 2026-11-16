"""In-Sample Backtest & Calibration Runner for Range Boundary Sweep Scalper (TICK-304)."""

from datetime import datetime
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from src.analytics.metrics import MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.ingestion.storage import TickStorageManager
from src.simulator.engine import TickBacktestEngine
from src.strategies.range_sweep_scalper import RangeSweepScalper

console = Console()


def main():
    console.print("[cyan]Loading real ticks from Parquet storage for Range Sweep Backtest...[/cyan]")
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

    broker_cfg = BrokerConfig(
        symbol="XAUUSDm",
        contract_size=100.0,
        point_size=0.001,
        digits=3,
        commission_per_lot_round_turn=0.0,  # Exness Standard: spread $0.24
    )
    exec_cfg = ExecutionConfig(
        latency_min_ms=50,
        latency_max_ms=120,
        base_slippage_mean_points=0.01,
        base_slippage_std_points=0.02,
    )
    config = BacktestConfig(
        initial_balance=10_000.0,
        broker=broker_cfg,
        execution=exec_cfg,
    )

    console.print("[bold cyan]Initializing RangeSweepScalper with 3-Layer Management...[/bold cyan]")
    strategy = RangeSweepScalper(
        lookback_minutes=30,          # 30-minute rolling consolidation window
        min_range_usd=3.0,            # Min $3.00 range width
        max_range_usd=10.0,           # Max $10.00 range width
        min_sweep_usd=0.45,           # Penetration $0.45 beyond range boundary
        max_sweep_usd=1.50,           # Past $1.50 is real breakout
        hard_sl_offset_usd=1.00,      # Invalidation SL $1.00 beyond sweep peak
        layer_spacing_usd=0.40,       # Retest spacing for Layer 2 & 3
        layer_volumes=[0.05, 0.10, 0.15], # Controlled sizing
        max_spread_usd=0.25,          # Spread gate
        allowed_hours_utc=set(range(0, 21)), # Active all day except rollover (21-23 UTC)
    )

    engine = TickBacktestEngine(strategy=strategy, config=config)
    
    console.print(f"[yellow]Running tick-by-tick simulation on {len(is_df):,} real ticks...[/yellow]")
    sim_res = engine.run(is_df, snapshot_interval_ticks=2000)

    console.print(f"[green]Simulation completed in {sim_res.execution_time_seconds:.2f} seconds ({len(is_df) / sim_res.execution_time_seconds:,.0f} ticks/sec)![/green]")

    # Metrics calculation
    metrics = MetricsCalculator.calculate(
        sim_res.closed_trades, sim_res.equity_curve, initial_balance=10_000.0
    )

    # Render Tear-sheet
    reporter = PerformanceReporter()
    reporter.print_tear_sheet(metrics, title="In-Sample Results: Range Boundary Sweep & 3-Layer Scalper")

    # Export trade log and equity curve
    trade_log_path = reporter.export_trade_log(sim_res.closed_trades, filename="range_sweep_trades.csv")
    equity_path = reporter.export_equity_curve(sim_res.equity_curve, filename="range_sweep_equity.csv")
    console.print(f"[dim]Trade log saved to: {trade_log_path}[/dim]")
    console.print(f"[dim]Equity curve saved to: {equity_path}[/dim]")


if __name__ == "__main__":
    main()
