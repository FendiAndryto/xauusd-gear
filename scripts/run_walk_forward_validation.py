"""Out-of-Sample Walk-Forward Validation on Real MT5 Ticks (TICK-205)."""

from datetime import datetime
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from src.analytics.metrics import MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.analytics.validation import WalkForwardValidator
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.ingestion.storage import TickStorageManager
from src.simulator.engine import TickBacktestEngine
from src.strategies.flow_momentum_scalper import FlowMomentumScalper

console = Console()


def create_strategy():
    return FlowMomentumScalper(
        window_ticks=25,
        momentum_threshold_usd=0.45,
        max_elapsed_seconds=3.0,
        max_spread_usd=0.25,
        take_profit_points=0.85,
        stop_loss_points=0.55,
        max_hold_seconds=60.0,
        volume=0.50,
        allowed_hours_utc={12, 13, 14, 15, 16, 17, 18},
    )


def main():
    console.print("[cyan]Loading real ticks from Parquet storage for Walk-Forward Validation...[/cyan]")
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
    console.print("\n[bold cyan]=== IN-SAMPLE (70% DATA) PERFORMANCE ===[/bold cyan]")
    reporter.print_tear_sheet(wfa_res.in_sample_metrics, title="In-Sample Results (October 2026)")

    # Out-of-Sample Tear-Sheet
    console.print("\n[bold cyan]=== OUT-OF-SAMPLE (30% BLIND DATA) PERFORMANCE ===[/bold cyan]")
    reporter.print_tear_sheet(wfa_res.out_of_sample_metrics, title="Out-of-Sample Blind Results (November 2026)")

    # WFA Robustness Summary
    console.print("\n" + "=" * 60)
    console.print("[bold yellow]WALK-FORWARD ROBUSTNESS VERDICT[/bold yellow]")
    console.print("=" * 60)
    color = "bold green" if wfa_res.is_robust else "bold red"
    console.print(f"Status: [{color}]{wfa_res.status_summary}[/{color}]")
    console.print(f" - Sharpe Degradation Ratio       : {wfa_res.sharpe_degradation_ratio:.2f}")
    console.print(f" - Profit Factor Degradation Ratio : {wfa_res.profit_factor_degradation_ratio:.2f}")
    console.print(f" - Win Rate Degradation Ratio      : {wfa_res.win_rate_degradation_ratio:.2f}")
    console.print(f" - Out-of-Sample Net Profit        : ${wfa_res.out_of_sample_metrics.net_profit:,.2f}")
    console.print(f" - Out-of-Sample Max Drawdown      : {wfa_res.out_of_sample_metrics.max_drawdown_pct:.2f}%")
    console.print("=" * 60)


if __name__ == "__main__":
    main()
