"""Out-of-Sample Walk-Forward Validation for Range Boundary Sweep Scalper (TICK-305)."""

from datetime import datetime
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from src.analytics.reporting import PerformanceReporter
from src.analytics.validation import WalkForwardValidator
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.ingestion.storage import TickStorageManager
from src.strategies.range_sweep_scalper import RangeSweepScalper

console = Console()


def create_strategy():
    return RangeSweepScalper(
        lookback_minutes=30,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.45,
        max_sweep_usd=1.50,
        hard_sl_offset_usd=1.00,
        layer_spacing_usd=0.40,
        layer_volumes=[0.05, 0.10, 0.15],
        max_spread_usd=0.25,
        allowed_hours_utc=set(range(0, 21)),
    )


def main():
    console.print("[cyan]Loading real ticks from Parquet storage for WFA (TICK-305)...[/cyan]")
    storage = TickStorageManager()
    ticks_df = storage.load_ticks(symbol="xauusd")

    if ticks_df.is_empty():
        console.print("[red]No ticks found! Run scripts/ingest_ticks.py first.[/red]")
        return

    broker_cfg = BrokerConfig(
        symbol="XAUUSDm",
        contract_size=100.0,
        point_size=0.001,
        digits=3,
        commission_per_lot_round_turn=0.0,
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

    console.print(f"[green]Total real ticks: {len(ticks_df):,}. Initiating 70% IS / 30% OOS Validation...[/green]")

    validator = WalkForwardValidator(
        strategy_factory=create_strategy,
        config=config,
        train_ratio=0.70,
        min_sharpe_degradation=0.60,
    )

    wfa_res = validator.evaluate(ticks_df)
    reporter = PerformanceReporter()

    # In-Sample Tear-Sheet
    console.print("\n[bold cyan]=== IN-SAMPLE (70% DATA, OKTOBER 2026) ===[/bold cyan]")
    reporter.print_tear_sheet(wfa_res.in_sample_metrics, title="In-Sample Results: Range Boundary Sweep Scalper")

    # Out-of-Sample Tear-Sheet
    console.print("\n[bold cyan]=== OUT-OF-SAMPLE (30% BLIND DATA, NOVEMBER 2026) ===[/bold cyan]")
    reporter.print_tear_sheet(wfa_res.out_of_sample_metrics, title="Out-of-Sample Results: Range Boundary Sweep Scalper")

    # WFA Robustness Summary
    console.print("\n" + "=" * 60)
    console.print("[bold yellow]WALK-FORWARD ROBUSTNESS VERDICT[/bold yellow]")
    console.print("=" * 60)
    color = "bold green" if wfa_res.is_robust else "bold red"
    console.print(f"Status: [{color}]{wfa_res.status_summary}[/{color}]")
    console.print(f" - In-Sample Profit Factor        : {wfa_res.in_sample_metrics.profit_factor:.2f}")
    console.print(f" - Out-of-Sample Profit Factor     : {wfa_res.out_of_sample_metrics.profit_factor:.2f}")
    console.print(f" - Profit Factor Degradation Ratio : {wfa_res.profit_factor_degradation_ratio:.2f}")
    console.print(f" - Out-of-Sample Win Rate          : {wfa_res.out_of_sample_metrics.win_rate_pct:.1f}%")
    console.print(f" - Out-of-Sample Win/Loss Ratio    : {wfa_res.out_of_sample_metrics.win_loss_ratio:.2f}")
    console.print(f" - Out-of-Sample Net Profit        : ${wfa_res.out_of_sample_metrics.net_profit:,.2f}")
    console.print("=" * 60)


if __name__ == "__main__":
    main()
