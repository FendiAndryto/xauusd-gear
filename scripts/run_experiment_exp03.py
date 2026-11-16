"""Execution & Benchmarking Runner for EXP-03 (Calibrated Range Boundary Sweep v2.0)."""

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
from src.strategies.range_sweep_scalper_v2 import RangeSweepScalperV2

console = Console()


def create_strategy():
    return RangeSweepScalperV2(
        lookback_minutes=30,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,                # $0.75 min penetration
        max_sweep_usd=2.00,                # $2.00 max penetration
        hard_sl_offset_usd=1.20,           # $1.20 buffer
        layer_spacing_usd=0.50,            # Layer spacing
        layer_volumes=[0.05, 0.10, 0.15],  # 3-layer sizing
        max_spread_usd=0.25,               # Spread gate
        cooldown_seconds=1200.0,           # 20-minute breakout cooldown
        allowed_hours_utc=set(range(0, 21)),
    )


def main():
    console.print("[bold cyan]=== RUNNING EXPERIMENT EXP-03: RANGE SWEEP SCALPER V2.0 ===[/bold cyan]")
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

    exp_dir = Path("reports/experiments/EXP-03")
    exp_dir.mkdir(parents=True, exist_ok=True)
    reporter = PerformanceReporter(output_dir=exp_dir)

    console.print(f"[green]Executing Walk-Forward Analysis across {len(ticks_df):,} real MT5 ticks...[/green]")
    validator = WalkForwardValidator(
        strategy_factory=create_strategy,
        config=config,
        train_ratio=0.70,
        min_sharpe_degradation=0.60,
    )

    wfa_res = validator.evaluate(ticks_df)

    # In-Sample Report
    console.print("\n[bold cyan]=== EXP-03 IN-SAMPLE (70% DATA, OKTOBER 2026) ===[/bold cyan]")
    reporter.print_tear_sheet(wfa_res.in_sample_metrics, title="EXP-03 In-Sample Results (v2.0)")

    # Out-of-Sample Report
    console.print("\n[bold cyan]=== EXP-03 OUT-OF-SAMPLE (30% BLIND DATA, NOVEMBER 2026) ===[/bold cyan]")
    reporter.print_tear_sheet(wfa_res.out_of_sample_metrics, title="EXP-03 Out-of-Sample Results (v2.0)")

    # Print summary verdict
    console.print("\n" + "=" * 65)
    console.print("[bold yellow]EXP-03 BENCHMARK SUMMARY[/bold yellow]")
    console.print("=" * 65)
    console.print(f"Total Trades (IS / OOS)           : {wfa_res.in_sample_metrics.total_trades:,} / {wfa_res.out_of_sample_metrics.total_trades:,}")
    console.print(f"Win Rate (IS / OOS)               : {wfa_res.in_sample_metrics.win_rate_pct:.1f}% / {wfa_res.out_of_sample_metrics.win_rate_pct:.1f}%")
    console.print(f"Win/Loss Ratio (IS / OOS)         : {wfa_res.in_sample_metrics.win_loss_ratio:.2f} / {wfa_res.out_of_sample_metrics.win_loss_ratio:.2f}")
    console.print(f"Profit Factor (IS / OOS)          : {wfa_res.in_sample_metrics.profit_factor:.2f} / {wfa_res.out_of_sample_metrics.profit_factor:.2f}")
    console.print(f"WFA Consistency Ratio (OOS / IS)  : {wfa_res.profit_factor_degradation_ratio:.2f}")
    console.print(f"Net Profit (IS / OOS)             : ${wfa_res.in_sample_metrics.net_profit:,.2f} / ${wfa_res.out_of_sample_metrics.net_profit:,.2f}")
    console.print("=" * 65)


if __name__ == "__main__":
    main()
