"""Execution & Benchmarking Runner for EXP-10 (8-Month Longitudinal Macro Stress Test).

Evaluates RangeSweepScalperV6 across:
1. All 8 Individual Monthly Regimes (April to November 2026, 53.54M ticks).
2. Longitudinal Walk-Forward Analysis (70% In-Sample / 30% Out-of-Sample Blind Test).
3. Memory-safe partitioned execution architecture.
"""

from datetime import datetime
import gc
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
from src.strategies.range_sweep_scalper_v6 import RangeSweepScalperV6

console = Console()


def create_strategy():
    return RangeSweepScalperV6(
        name="RangeSweepScalperV6",
        lookback_minutes=30,
        min_range_usd=3.0,                 # Sweet spot: $3.00 minimum
        max_range_usd=10.0,                # Sweet spot: $10.00 maximum
        min_sweep_usd=0.75,                # $0.75 min penetration
        max_sweep_usd=2.00,                # $2.00 max penetration
        hard_sl_offset_usd=1.20,           # $1.20 buffer
        layer_spacing_usd=0.50,            # Layer spacing
        layer_volumes=[0.05, 0.10, 0.15],  # 3-layer sizing
        max_spread_usd=0.25,               # Spread gate
        cooldown_seconds=1200.0,           # 20-minute breakout cooldown
        be_policy="STEP_LOCK",             # Optimal Breakeven architecture
        blackout_hours_utc={12, 19, 21, 22},  # News (12), Churn (19), Rollover (21, 22)
        macro_fast_hours=8,                # Macro Fast EMA (8 hours)
        macro_slow_hours=24,               # Macro Slow EMA (24 hours = 1 day)
        macro_threshold_usd=2.50,          # Macro Trend separation threshold ($2.50)
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
    month_names = {
        4: "April 2026 (Spring Volatility)",
        5: "Mei 2026 (Pre-Summer)",
        6: "Juni 2026 (Q2 Rebalancing)",
        7: "Juli 2026 (Summer Chop)",
        8: "Agustus 2026 (Parabolic +$678 Surge)",
        9: "September 2026 (Post-Surge Correction)",
        10: "Oktober 2026 (Pre-Election Bull Run)",
        11: "November 2026 (Sideway / Consolidation)"
    }
    month_name = month_names.get(month_num, f"Month {month_num}")
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
        "pf": m.profit_factor,
        "net_pnl": m.net_profit,
        "max_dd": m.max_drawdown_pct,
    }


def main():
    exp_dir = Path("reports/experiments/EXP-10")
    exp_dir.mkdir(parents=True, exist_ok=True)

    console.print("[bold yellow]========================================================================[/bold yellow]")
    console.print("[bold yellow]   EXP-10: 8-MONTH LONGITUDINAL MACRO STRESS TEST (53.54M TICKS)       [/bold yellow]")
    console.print("[bold yellow]   Model: RangeSweepScalperV6 (Asymmetric Directional Shield)          [/bold yellow]")
    console.print("[bold yellow]========================================================================[/bold yellow]")

    # 1. Month-by-Month Longitudinal Audit (Memory-Safe: 1 Month at a time)
    month_results = []
    months = [4, 5, 6, 7, 8, 9, 10, 11]

    console.print("\n[bold cyan]Part 1: Running Individual Monthly Regime Audits (Months 04 - 11)...[/bold cyan]")
    for m in months:
        p_pattern = f"data/parquet/xauusd/year=2026/month={m:02d}/*.parquet"
        df_month = pl.read_parquet(p_pattern).sort("timestamp")
        console.print(f" -> Simulating Month {m:02d} ({len(df_month):,} ticks)...")

        res = run_month_eval(m, df_month, exp_dir)
        month_results.append(res)
        console.print(
            f"    [green]Done:[/green] Trades: {res['trades']} | WR: {res['win_rate']:.1f}% | "
            f"PF: {res['pf']:.2f} | Net: ${res['net_pnl']:+,.2f} | Max DD: {res['max_dd']:.2f}% | W/L: {res['win_loss_ratio']:.2f}x"
        )
        del df_month
        gc.collect()

    # 2. Print Month-by-Month Table
    m_table = Table(title="EXP-10: 8-Month Longitudinal Stability Audit (Month-by-Month)", border_style="green")
    m_table.add_column("Month", style="cyan")
    m_table.add_column("Market Regime Description", style="white")
    m_table.add_column("Ticks", justify="right")
    m_table.add_column("Trades", justify="right")
    m_table.add_column("W / L", justify="center")
    m_table.add_column("Win Rate", justify="right")
    m_table.add_column("W/L Ratio", justify="right")
    m_table.add_column("PF", justify="right", style="bold")
    m_table.add_column("Net PnL ($)", justify="right", style="bold")
    m_table.add_column("Max DD (%)", justify="right")

    for r in month_results:
        pnl_color = "green" if r["net_pnl"] > 0 else "red"
        m_table.add_row(
            f"Month {r['month_num']:02d}",
            r["name"],
            f"{r['ticks']:,}",
            str(r["trades"]),
            f"{r['wins']}W / {r['losses']}L",
            f"{r['win_rate']:.1f}%",
            f"{r['win_loss_ratio']:.2f}x",
            f"{r['pf']:.2f}",
            f"[{pnl_color}]${r['net_pnl']:+9.2f}[/{pnl_color}]",
            f"{r['max_dd']:.2f}%"
        )
    console.print("\n")
    console.print(m_table)

    # 3. Longitudinal Walk-Forward Analysis (70% IS / 30% OOS across 53.54M ticks)
    console.print("\n[bold yellow]Part 2: Running Longitudinal Walk-Forward Analysis (70% IS / 30% OOS)...[/bold yellow]")
    
    # Calculate exact 70% split
    # Total ticks: 53,541,349. 70% = 37,478,944 ticks.
    # Month 04 to 08 cumsum = 33,589,979 ticks.
    # Remainder to reach 70% in Month 09: 3,888,965 ticks.
    console.print("  -> Loading In-Sample dataset (Months 04-08 + 70% split of Month 09)...")
    is_dfs = []
    for m in [4, 5, 6, 7, 8]:
        is_dfs.append(pl.read_parquet(f"data/parquet/xauusd/year=2026/month={m:02d}/*.parquet"))
    
    df_m09 = pl.read_parquet("data/parquet/xauusd/year=2026/month=09/*.parquet").sort("timestamp")
    split_m09 = 37_478_944 - 33_589_979
    is_dfs.append(df_m09.slice(0, split_m09))
    
    df_is = pl.concat(is_dfs).sort("timestamp")
    del is_dfs
    gc.collect()

    console.print(f"  -> In-Sample: {len(df_is):,} ticks ({df_is['timestamp'].min()} -> {df_is['timestamp'].max()})")
    console.print("  -> Executing In-Sample Simulation (70% Train)...")
    
    is_strat = create_strategy()
    is_engine = TickBacktestEngine(strategy=is_strat, config=get_default_config())
    is_res = is_engine.run(df_is)
    is_metrics = MetricsCalculator.calculate(is_res.closed_trades, is_res.equity_curve, 10_000.0)

    is_dir = exp_dir / "in_sample_wfa"
    is_rep = PerformanceReporter(output_dir=is_dir)
    is_rep.print_tear_sheet(is_metrics, title="EXP-10 LONGITUDINAL IN-SAMPLE (70% Data: April - Mid September 2026)")
    is_rep.export_trade_log(is_res.closed_trades)
    is_rep.export_equity_curve(is_res.equity_curve)

    # Release IS memory before loading OOS
    del df_is
    del is_engine
    del is_res
    gc.collect()

    # Load Out-of-Sample dataset (Remainder of Month 09 + Month 10 + Month 11)
    console.print("\n  -> Loading Out-of-Sample dataset (Remainder of Month 09 + Months 10-11)...")
    oos_dfs = [df_m09.slice(split_m09)]
    del df_m09
    gc.collect()

    for m in [10, 11]:
        oos_dfs.append(pl.read_parquet(f"data/parquet/xauusd/year=2026/month={m:02d}/*.parquet"))

    df_oos = pl.concat(oos_dfs).sort("timestamp")
    del oos_dfs
    gc.collect()

    console.print(f"  -> Out-of-Sample (Blind 30%): {len(df_oos):,} ticks ({df_oos['timestamp'].min()} -> {df_oos['timestamp'].max()})")
    console.print("  -> Executing Out-of-Sample Simulation (30% Blind Test)...")

    oos_strat = create_strategy()
    oos_engine = TickBacktestEngine(strategy=oos_strat, config=get_default_config())
    oos_res = oos_engine.run(df_oos)
    oos_metrics = MetricsCalculator.calculate(oos_res.closed_trades, oos_res.equity_curve, 10_000.0)

    oos_dir = exp_dir / "out_of_sample_wfa"
    oos_rep = PerformanceReporter(output_dir=oos_dir)
    oos_rep.print_tear_sheet(oos_metrics, title="EXP-10 LONGITUDINAL OUT-OF-SAMPLE BLIND TEST (30% Data: Mid September - November 2026)")
    oos_rep.export_trade_log(oos_res.closed_trades)
    oos_rep.export_equity_curve(oos_res.equity_curve)

    # Print Final WFA Summary
    table_wfa = Table(title="EXP-10: 8-Month Longitudinal Walk-Forward Analysis Summary", border_style="cyan")
    table_wfa.add_column("Evaluation Metric", style="dim")
    table_wfa.add_column("In-Sample (Train 70%: 37.48M Ticks)", justify="right")
    table_wfa.add_column("Out-of-Sample (Blind 30%: 16.06M Ticks)", justify="right", style="bold")
    table_wfa.add_column("Stability / WFA Ratio", justify="right")

    pf_deg = round(oos_metrics.profit_factor / max(0.01, is_metrics.profit_factor), 2)
    wr_deg = round(oos_metrics.win_rate_pct / max(0.01, is_metrics.win_rate_pct), 2)
    wl_deg = round(oos_metrics.win_loss_ratio / max(0.01, is_metrics.win_loss_ratio), 2)

    table_wfa.add_row("Total Ticks Processed", f"{37_478_944:,}", f"{len(df_oos):,}", "100.0%")
    table_wfa.add_row("Total Trades", str(is_metrics.total_trades), str(oos_metrics.total_trades), f"{oos_metrics.total_trades / max(1, is_metrics.total_trades):.2f}x")
    table_wfa.add_row("Win Rate", f"{is_metrics.win_rate_pct:.1f}%", f"{oos_metrics.win_rate_pct:.1f}%", f"{wr_deg:.2f}x")
    table_wfa.add_row("Win / Loss Ratio", f"{is_metrics.win_loss_ratio:.2f}x", f"{oos_metrics.win_loss_ratio:.2f}x", f"{wl_deg:.2f}x")
    table_wfa.add_row("Profit Factor", f"{is_metrics.profit_factor:.2f}", f"{oos_metrics.profit_factor:.2f}", f"{pf_deg:.2f}x")
    table_wfa.add_row("Net Return ($ / %)", f"${is_metrics.net_profit:+,.2f} ({is_metrics.net_return_pct:+.1f}%)", f"${oos_metrics.net_profit:+,.2f} ({oos_metrics.net_return_pct:+.1f}%)", "-")
    table_wfa.add_row("Max Drawdown", f"{is_metrics.max_drawdown_pct:.2f}%", f"{oos_metrics.max_drawdown_pct:.2f}%", "-")
    table_wfa.add_row("Sharpe Ratio", f"{is_metrics.sharpe_ratio:.2f}", f"{oos_metrics.sharpe_ratio:.2f}", "-")

    console.print("\n")
    console.print(table_wfa)
    console.print("[bold green]EXP-10 8-Month Longitudinal Benchmark Completed Successfully![/bold green]")


if __name__ == "__main__":
    main()
