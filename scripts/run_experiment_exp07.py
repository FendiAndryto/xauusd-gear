"""Execution & Benchmarking Runner for EXP-07 (Multi-Month Macro Benchmark across 33.15M Ticks).

Evaluates RangeSweepScalperV5 (Champion Model from EXP-06) across:
1. Continuous 4-Month Macro Backtest (July 1 to November 6, 2026).
2. Walk-Forward Analysis (70% In-Sample / 30% Out-of-Sample Blind Test).
3. Month-by-Month Regime Stability Audit (Months 07, 08, 09, 10, 11).
"""

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


def get_default_config():
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
    return BacktestConfig(
        initial_balance=10_000.0,
        broker=broker_cfg,
        execution=exec_cfg,
    )


def run_month_eval(month_num: int, ticks_slice: pl.DataFrame, exp_dir: Path):
    month_name = {7: "July 2026", 8: "August 2026", 9: "September 2026", 10: "October 2026", 11: "November 2026"}.get(month_num, f"Month {month_num}")
    strat = create_strategy()
    engine = TickBacktestEngine(strategy=strat, config=get_default_config())
    res = engine.run(ticks_slice)
    m = MetricsCalculator.calculate(res.closed_trades, res.equity_curve, 10_000.0)

    out_dir = exp_dir / f"month_{month_num:02d}"
    rep = PerformanceReporter(output_dir=out_dir)
    rep.export_trade_log(res.closed_trades)
    rep.export_equity_curve(res.equity_curve)

    return {
        "month_num": month_num,
        "name": month_name,
        "ticks": len(ticks_slice),
        "trades": m.total_trades,
        "wins": m.winning_trades,
        "losses": m.losing_trades,
        "win_rate": m.win_rate_pct,
        "win_loss_ratio": m.win_loss_ratio,
        "profit_factor": m.profit_factor,
        "max_dd_pct": m.max_drawdown_pct,
        "net_profit": m.net_profit,
        "return_pct": m.net_return_pct,
    }


def main():
    console.print("[bold cyan]=== RUNNING EXPERIMENT EXP-07: MACRO 4-MONTH BENCHMARK (33.15M TICKS) ===[/bold cyan]")
    storage = TickStorageManager()
    ticks_df = storage.load_ticks(symbol="xauusd")

    if ticks_df.is_empty():
        console.print("[red]No ticks found! Run scripts/ingest_ticks.py first.[/red]")
        return

    n_ticks = len(ticks_df)
    min_date = ticks_df["timestamp"].min()
    max_date = ticks_df["timestamp"].max()

    console.print(f"[cyan]Dataset Span: {n_ticks:,} total ticks[/cyan]")
    console.print(f"  - Range: {min_date} to {max_date}\n")

    exp_dir = Path("reports/experiments/EXP-07")
    exp_dir.mkdir(parents=True, exist_ok=True)

    # =========================================================================
    # Part 1: Month-by-Month Breakdown
    # =========================================================================
    console.print("[bold yellow]Part 1: Running Month-by-Month Regime Audits...[/bold yellow]")
    months = sorted(ticks_df["timestamp"].dt.month().unique().to_list())
    month_results = []

    for m in months:
        m_slice = ticks_df.filter(pl.col("timestamp").dt.month() == m)
        console.print(f"  -> Simulating Month {m:02d} ({len(m_slice):,} ticks)...")
        res_m = run_month_eval(m, m_slice, exp_dir)
        month_results.append(res_m)

    # Print Month-by-Month Table
    tbl_month = Table(title="EXP-07 Month-by-Month Performance Stability", border_style="green")
    tbl_month.add_column("Period", style="cyan")
    tbl_month.add_column("Ticks", justify="right")
    tbl_month.add_column("Trades", justify="right")
    tbl_month.add_column("Win / Loss", justify="center")
    tbl_month.add_column("Win Rate", justify="right")
    tbl_month.add_column("W/L Ratio", justify="right")
    tbl_month.add_column("Profit Factor", justify="right", style="bold")
    tbl_month.add_column("Max DD (%)", justify="right")
    tbl_month.add_column("Net Profit ($)", justify="right")

    total_net = sum(r["net_profit"] for r in month_results)
    total_trades = sum(r["trades"] for r in month_results)

    for r in month_results:
        color = "green" if r["net_profit"] > 0 else "red"
        tbl_month.add_row(
            r["name"],
            f"{r['ticks']:,}",
            f"{r['trades']:,}",
            f"{r['wins']}W / {r['losses']}L",
            f"{r['win_rate']:.1f}%",
            f"{r['win_loss_ratio']:.2f}x",
            f"{r['profit_factor']:.2f}",
            f"{r['max_dd_pct']:.2f}%",
            f"[{color}]${r['net_profit']:+9.2f}[/{color}]"
        )
    console.print(tbl_month)

    # =========================================================================
    # Part 2: Macro Walk-Forward Analysis (70% Train / 30% Blind Test)
    # =========================================================================
    console.print("\n[bold yellow]Part 2: Running Macro Walk-Forward Analysis (70% IS / 30% OOS)...[/bold yellow]")
    train_split_idx = int(n_ticks * 0.70)
    train_ticks = ticks_df.slice(0, train_split_idx)
    test_ticks = ticks_df.slice(train_split_idx)

    console.print(f"  - In-Sample (Train 70%): {len(train_ticks):,} ticks ({train_ticks['timestamp'].min().strftime('%Y-%m-%d')} -> {train_ticks['timestamp'].max().strftime('%Y-%m-%d')})")
    console.print(f"  - Out-of-Sample (Blind 30%): {len(test_ticks):,} ticks ({test_ticks['timestamp'].min().strftime('%Y-%m-%d')} -> {test_ticks['timestamp'].max().strftime('%Y-%m-%d')})\n")

    # In-Sample Run
    console.print("  -> Executing In-Sample Simulation...")
    is_strat = create_strategy()
    is_engine = TickBacktestEngine(strategy=is_strat, config=get_default_config())
    res_is = is_engine.run(train_ticks)
    m_is = MetricsCalculator.calculate(res_is.closed_trades, res_is.equity_curve, 10_000.0)

    is_dir = exp_dir / "in_sample_wfa"
    rep_is = PerformanceReporter(output_dir=is_dir)
    rep_is.print_tear_sheet(m_is, title="EXP-07 MACRO IN-SAMPLE PERFORMANCE (70% Data)")
    rep_is.export_trade_log(res_is.closed_trades)
    rep_is.export_equity_curve(res_is.equity_curve)

    # Out-of-Sample Run
    console.print("\n  -> Executing Out-of-Sample Blind Simulation (30% Data)...")
    oos_strat = create_strategy()
    oos_engine = TickBacktestEngine(strategy=oos_strat, config=get_default_config())
    res_oos = oos_engine.run(test_ticks)
    m_oos = MetricsCalculator.calculate(res_oos.closed_trades, res_oos.equity_curve, 10_000.0)

    oos_dir = exp_dir / "out_of_sample_wfa"
    rep_oos = PerformanceReporter(output_dir=oos_dir)
    rep_oos.print_tear_sheet(m_oos, title="EXP-07 MACRO OUT-OF-SAMPLE PERFORMANCE (30% Blind Data)")
    rep_oos.export_trade_log(res_oos.closed_trades)
    rep_oos.export_equity_curve(res_oos.equity_curve)

    # Print WFA Summary
    table_wfa = Table(title="EXP-07 Macro Walk-Forward Validation Summary", border_style="cyan")
    table_wfa.add_column("Evaluation Metric", style="dim")
    table_wfa.add_column("In-Sample (Train 70%)", justify="right")
    table_wfa.add_column("Out-of-Sample (Blind 30%)", justify="right", style="bold")
    table_wfa.add_column("Degradation / WFA Ratio", justify="right")

    pf_deg = round(m_oos.profit_factor / max(0.01, m_is.profit_factor), 2)
    wr_deg = round(m_oos.win_rate_pct / max(0.01, m_is.win_rate_pct), 2)

    table_wfa.add_row("Total Executed Trades", f"{m_is.total_trades:,}", f"{m_oos.total_trades:,}", f"{m_oos.total_trades / max(1, m_is.total_trades):.2f}x")
    table_wfa.add_row("Win Rate (%)", f"{m_is.win_rate_pct:.1f}%", f"{m_oos.win_rate_pct:.1f}%", f"{wr_deg:.2f}")
    table_wfa.add_row("Win / Loss Ratio", f"{m_is.win_loss_ratio:.2f}x", f"{m_oos.win_loss_ratio:.2f}x", f"{m_oos.win_loss_ratio / max(0.01, m_is.win_loss_ratio):.2f}")
    table_wfa.add_row("Profit Factor", f"{m_is.profit_factor:.2f}", f"{m_oos.profit_factor:.2f}", f"{pf_deg:.2f}")
    table_wfa.add_row("Sharpe Ratio", f"{m_is.sharpe_ratio:.2f}", f"{m_oos.sharpe_ratio:.2f}", "-")
    table_wfa.add_row("Max Drawdown (%)", f"{m_is.max_drawdown_pct:.2f}%", f"{m_oos.max_drawdown_pct:.2f}%", "-")
    table_wfa.add_row("Net Profit ($)", f"${m_is.net_profit:,.2f}", f"${m_oos.net_profit:,.2f}", f"{'PROFITABLE' if m_oos.net_profit > 0 else 'LOSS'}")

    console.print(table_wfa)
    console.print(f"\n[cyan]All detailed trade logs and equity curves saved to: {exp_dir}[/cyan]")


if __name__ == "__main__":
    main()
