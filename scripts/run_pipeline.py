"""Main execution runner: Backtests XAUUSD scalping with reality simulator and generates tear-sheet."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from src.analytics.metrics import MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.analytics.validation import WalkForwardValidator
from src.config import BacktestConfig
from src.ingestion.storage import TickStorageManager
from src.simulator.engine import TickBacktestEngine
from src.strategies.micro_momentum import MicroMomentumScalper

console = Console()


def generate_synthetic_tick_sample(n_ticks: int = 50_000) -> "pl.DataFrame":
    """Generate a realistic brownian motion tick sample for pipeline verification."""
    import numpy as np
    import polars as pl
    from src.ingestion.schema import TICK_SCHEMA

    np.random.seed(42)
    t0 = datetime(2024, 10, 1, 8, 0, 0, tzinfo=timezone.utc)
    
    # Generate timestamp increments (average 100ms per tick)
    delta_ms = np.random.exponential(scale=100, size=n_ticks).astype(int)
    delta_ms = np.maximum(delta_ms, 1)
    cum_ms = np.cumsum(delta_ms)
    
    # Generate price path with volatility
    returns = np.random.normal(loc=0.00001, scale=0.05, size=n_ticks)
    mid_prices = 2650.0 + np.cumsum(returns)
    
    # Dynamic spread between $0.15 and $0.35
    spreads = np.clip(np.random.normal(loc=0.22, scale=0.04, size=n_ticks), 0.15, 0.40).round(2)
    bids = (mid_prices - spreads / 2.0).round(2)
    asks = (bids + spreads).round(2)
    volumes = np.random.choice([1.0, 2.0, 5.0, 10.0], size=n_ticks, p=[0.6, 0.25, 0.1, 0.05])
    flags = np.full(n_ticks, 6, dtype=np.uint32)

    # Construct Polars DataFrame
    from datetime import timedelta
    timestamps = [t0 + timedelta(milliseconds=int(ms)) for ms in cum_ms]
    
    df = pl.DataFrame({
        "timestamp": timestamps,
        "bid": bids,
        "ask": asks,
        "spread": spreads,
        "volume": volumes,
        "flags": flags,
    }).cast(TICK_SCHEMA)

    return df


def main():
    parser = argparse.ArgumentParser(description="Run XAUUSD Scalping Reality Simulation.")
    parser.add_argument("--symbol", type=str, default="XAUUSD", help="Symbol to test (default: XAUUSD)")
    parser.add_argument("--use-sample", action="store_true", help="Generate and test on synthetic sample ticks")
    parser.add_argument("--balance", type=float, default=10_000.0, help="Initial cash balance (USD)")
    args = parser.parse_args()

    storage = TickStorageManager()
    ticks_df = storage.load_ticks(symbol=args.symbol)

    if ticks_df.is_empty() or args.use_sample:
        console.print("[yellow]No persisted ticks found in storage (or --use-sample specified).[/yellow]")
        console.print("[cyan]Generating 50,000 realistic synthetic tick events for end-to-end pipeline validation...[/cyan]")
        ticks_df = generate_synthetic_tick_sample(n_ticks=50_000)
        storage.save_ticks(ticks_df, symbol=args.symbol)
        console.print(f"[green]Stored sample ticks to {storage.parquet_dir}[/green]")

    console.print(f"[bold cyan]Running Tick Event-Driven Simulator on {len(ticks_df):,} ticks...[/bold cyan]")
    
    config = BacktestConfig(initial_balance=args.balance)
    strategy = MicroMomentumScalper()
    engine = TickBacktestEngine(strategy=strategy, config=config)

    sim_res = engine.run(ticks_df, snapshot_interval_ticks=500)
    console.print(f"[green]Simulation finished in {sim_res.execution_time_seconds:.2f} seconds ({len(ticks_df) / sim_res.execution_time_seconds:,.0f} ticks/sec)![/green]")

    # Metrics calculation
    metrics = MetricsCalculator.calculate(
        sim_res.closed_trades, sim_res.equity_curve, initial_balance=args.balance
    )

    # Render Tear-sheet
    reporter = PerformanceReporter()
    reporter.print_tear_sheet(metrics, title=f"XAUUSD Scalping Tear-Sheet: {strategy.name}")

    # Export trade log and equity curve
    trade_log_path = reporter.export_trade_log(sim_res.closed_trades, filename="xauusd_trade_log.csv")
    equity_path = reporter.export_equity_curve(sim_res.equity_curve, filename="xauusd_equity_curve.csv")
    console.print(f"[dim]Trade log saved to: {trade_log_path}[/dim]")
    console.print(f"[dim]Equity curve saved to: {equity_path}[/dim]")

    # Walk-Forward Robustness Test
    console.print("\n[bold magenta]Running Walk-Forward Overfitting Validation (70% IS / 30% OOS)...[/bold magenta]")
    validator = WalkForwardValidator(
        strategy_factory=lambda: MicroMomentumScalper(),
        config=config,
        train_ratio=0.70,
    )
    wfa_res = validator.evaluate(ticks_df)
    
    color = "green" if wfa_res.is_robust else "red"
    console.print(f"[{color}]{wfa_res.status_summary}[/{color}]")
    console.print(f" - In-Sample Sharpe: {wfa_res.in_sample_metrics.sharpe_ratio:.2f} | Out-of-Sample Sharpe: {wfa_res.out_of_sample_metrics.sharpe_ratio:.2f}")
    console.print(f" - Sharpe Degradation Ratio: {wfa_res.sharpe_degradation_ratio:.2f}")
    console.print(f" - Out-of-Sample Profit Factor: {wfa_res.out_of_sample_metrics.profit_factor:.2f}")


if __name__ == "__main__":
    main()
