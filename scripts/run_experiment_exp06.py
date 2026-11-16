"""Execution & Benchmarking Runner for EXP-06 (News Release & Afternoon Churn Blackout Engine)."""

from datetime import datetime
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl
from rich.console import Console
from rich.table import Table

from src.analytics.metrics import MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.ingestion.storage import TickStorageManager
from src.simulator.engine import TickBacktestEngine
from src.strategies.range_sweep_scalper_v5 import RangeSweepScalperV5

console = Console()


def create_strategy():
    return RangeSweepScalperV5(
        name="RangeSweepScalperV5",
        lookback_minutes=30,
        min_range_usd=3.0,                 # Restored sweet spot: $3.00 minimum
        max_range_usd=10.0,                # Restored sweet spot: $10.00 maximum
        min_sweep_usd=0.75,                # $0.75 min penetration
        max_sweep_usd=2.00,                # $2.00 max penetration
        hard_sl_offset_usd=1.20,           # $1.20 buffer
        layer_spacing_usd=0.50,            # Layer spacing
        layer_volumes=[0.05, 0.10, 0.15],  # 3-layer sizing
        max_spread_usd=0.25,               # Spread gate
        cooldown_seconds=1200.0,           # 20-minute breakout cooldown
        be_policy="STEP_LOCK",             # Optimal Breakeven architecture
        blackout_hours_utc={12, 19, 21, 22},  # News (12), Churn (19), Rollover (21, 22)
    )


def print_hourly_breakdown(trades, title: str):
    if not trades:
        return
    rows = []
    for t in trades:
        rows.append({
            "open_time": str(t.open_time),
            "pnl_net": t.pnl_net,
        })
    df = pl.DataFrame(rows)
    h = df.with_columns(pl.col("open_time").str.slice(11, 2).cast(pl.Int32).alias("hour"))
    summary = h.group_by("hour").agg([
        pl.len().alias("trades"),
        (pl.col("pnl_net") > 0).sum().alias("wins"),
        (pl.col("pnl_net") < 0).sum().alias("losses"),
        pl.col("pnl_net").sum().round(2).alias("net_pnl")
    ]).sort("hour")

    tbl = Table(title=title, border_style="magenta")
    tbl.add_column("Hour UTC", justify="center")
    tbl.add_column("Trades", justify="right")
    tbl.add_column("Win / Loss", justify="center")
    tbl.add_column("Win Rate", justify="right")
    tbl.add_column("Net PnL ($)", justify="right")

    for r in summary.to_dicts():
        wr = (r["wins"] / max(1, r["trades"])) * 100.0
        color = "green" if r["net_pnl"] > 0 else "red"
        tbl.add_row(
            f"{r['hour']:02d}:00",
            f"{r['trades']}",
            f"{r['wins']}W / {r['losses']}L",
            f"{wr:.1f}%",
            f"[{color}]${r['net_pnl']:+8.2f}[/{color}]"
        )
    console.print(tbl)


def main():
    console.print("[bold cyan]=== RUNNING EXPERIMENT EXP-06: NEWS & CHURN BLACKOUT ENGINE ===[/bold cyan]")
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

    exp_dir = Path("reports/experiments/EXP-06")
    exp_dir.mkdir(parents=True, exist_ok=True)

    n_ticks = len(ticks_df)
    train_split_idx = int(n_ticks * 0.70)
    train_ticks = ticks_df.slice(0, train_split_idx)
    test_ticks = ticks_df.slice(train_split_idx)

    console.print(f"[cyan]Dataset Partition: {n_ticks:,} total ticks[/cyan]")
    console.print(f"  - In-Sample (Train 70%): {len(train_ticks):,} ticks")
    console.print(f"  - Out-of-Sample (Blind 30%): {len(test_ticks):,} ticks\n")

    # 1. Run In-Sample
    console.print("[yellow]Running In-Sample Simulation (October 2026)...[/yellow]")
    is_strat = create_strategy()
    is_engine = TickBacktestEngine(strategy=is_strat, config=config)
    res_is = is_engine.run(train_ticks)
    m_is = MetricsCalculator.calculate(res_is.closed_trades, res_is.equity_curve, 10_000.0)

    is_dir = exp_dir / "in_sample"
    rep_is = PerformanceReporter(output_dir=is_dir)
    rep_is.print_tear_sheet(m_is, title="EXP-06 IN-SAMPLE PERFORMANCE (October 2026)")
    rep_is.export_trade_log(res_is.closed_trades)
    rep_is.export_equity_curve(res_is.equity_curve)

    # 2. Run Out-of-Sample
    console.print("\n[yellow]Running Out-of-Sample Blind Simulation (November 2026)...[/yellow]")
    oos_strat = create_strategy()
    oos_engine = TickBacktestEngine(strategy=oos_strat, config=config)
    res_oos = oos_engine.run(test_ticks)
    m_oos = MetricsCalculator.calculate(res_oos.closed_trades, res_oos.equity_curve, 10_000.0)

    oos_dir = exp_dir / "out_of_sample"
    rep_oos = PerformanceReporter(output_dir=oos_dir)
    rep_oos.print_tear_sheet(m_oos, title="EXP-06 OUT-OF-SAMPLE PERFORMANCE (November 2026 - Blind)")
    rep_oos.export_trade_log(res_oos.closed_trades)
    rep_oos.export_equity_curve(res_oos.equity_curve)

    # 3. Print Hourly Microstructure Breakdown for Out-of-Sample
    print_hourly_breakdown(res_oos.closed_trades, "EXP-06 Out-of-Sample Hourly Microstructure Performance")

    # 4. Print WFA Summary Table
    table = Table(title="EXP-06 Walk-Forward Validation Summary", border_style="cyan")
    table.add_column("Evaluation Metric", style="dim")
    table.add_column("In-Sample (Train 70%)", justify="right")
    table.add_column("Out-of-Sample (Blind 30%)", justify="right", style="bold")
    table.add_column("Degradation / WFA Ratio", justify="right")

    pf_deg = round(m_oos.profit_factor / max(0.01, m_is.profit_factor), 2)
    wr_deg = round(m_oos.win_rate_pct / max(0.01, m_is.win_rate_pct), 2)
    sharpe_deg = round(m_oos.sharpe_ratio / max(0.01, m_is.sharpe_ratio), 2) if m_is.sharpe_ratio > 0 else 0.0

    table.add_row("Total Executed Trades", f"{m_is.total_trades:,}", f"{m_oos.total_trades:,}", f"{m_oos.total_trades / max(1, m_is.total_trades):.2f}x")
    table.add_row("Win Rate (%)", f"{m_is.win_rate_pct:.1f}%", f"{m_oos.win_rate_pct:.1f}%", f"{wr_deg:.2f}")
    table.add_row("Win / Loss Ratio", f"{m_is.win_loss_ratio:.2f}x", f"{m_oos.win_loss_ratio:.2f}x", f"{m_oos.win_loss_ratio / max(0.01, m_is.win_loss_ratio):.2f}")
    table.add_row("Profit Factor", f"{m_is.profit_factor:.2f}", f"{m_oos.profit_factor:.2f}", f"{pf_deg:.2f}")
    table.add_row("Sharpe Ratio", f"{m_is.sharpe_ratio:.2f}", f"{m_oos.sharpe_ratio:.2f}", f"{sharpe_deg:.2f}")
    table.add_row("Max Drawdown (%)", f"{m_is.max_drawdown_pct:.2f}%", f"{m_oos.max_drawdown_pct:.2f}%", "-")
    table.add_row("Net Profit ($)", f"${m_is.net_profit:,.2f}", f"${m_oos.net_profit:,.2f}", f"{'PROFITABLE' if m_oos.net_profit > 0 else 'LOSS'}")

    console.print(table)

    is_robust = m_oos.net_profit > 0 and m_oos.profit_factor >= 1.0
    pass_status = "[bold green]PASS (NET PROFITABLE)[/bold green]" if is_robust else "[bold red]FAIL[/bold red]"
    console.print(f"\n[bold]Walk-Forward Validation Status: {pass_status}[/bold]")
    console.print(f"[cyan]Detailed reports and trade logs saved to: {exp_dir}[/cyan]")


if __name__ == "__main__":
    main()
