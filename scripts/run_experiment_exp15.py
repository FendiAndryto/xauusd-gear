"""Execution & Longitudinal Benchmarking Runner for EXP-15 (Fase N).

Evaluates PureShieldScalper across 53.54M real Exness ticks (April - November 2026):
1. Single Engine Model: 100% Engine A (Range Sweep Scalper V8), 0% Engine B.
2. In-Line Wasit ORB Shield (London 07:00 UTC anchor, $4.00 threshold).
3. Monday Mode: OFF (slashes -$1,277 weekend gap losses).
4. Extended Blackout Hours: {0, 1, 2, 8, 12, 19, 21, 22} UTC.
5. Anti-Burst Cooldown: 60s layer spacing protection.
6. Daily Circuit Breaker: -$150.00 daily loss kill-switch.
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
from src.simulator.engine import TickBacktestEngine
from src.strategies.pure_shield_scalper import PureShieldScalper

console = Console()


def create_exp15_strategy(monday_mode: str = "OFF"):
    return PureShieldScalper(
        name="PureShieldScalper_EXP15",
        lookback_minutes=30,
        min_range_usd=3.0,
        max_range_usd=10.0,
        min_sweep_usd=0.75,
        max_sweep_usd=2.00,
        hard_sl_offset_usd=1.20,
        layer_spacing_usd=0.50,
        layer_volumes=[0.05, 0.10, 0.15],
        max_spread_usd=0.25,
        cooldown_seconds=1200.0,
        be_policy="STEP_LOCK",
        monday_mode=monday_mode,
        blackout_hours_utc={0, 1, 2, 8, 12, 19, 21, 22},
        orb_start_hour_utc=7,
        orb_duration_hours=1,
        orb_threshold_usd=4.00,
        macro_fast_hours=8,
        macro_slow_hours=24,
        macro_threshold_usd=2.50,
        max_daily_loss_usd=150.0,
        layer_cooldown_seconds=60.0,
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


def run_month_eval(month_num: int, ticks_slice: pl.DataFrame, exp_dir: Path, monday_mode: str = "OFF"):
    month_names = {
        4: "April 2026 (Spring Highs)",
        5: "Mei 2026 (Peak Consolidation)",
        6: "Juni 2026 (Q2 Rebalancing)",
        7: "Juli 2026 (Summer Chop)",
        8: "Agustus 2026 (Parabolic +$678 Surge)",
        9: "September 2026 (Post-Surge Correction)",
        10: "Oktober 2026 (Pre-Election Trend Run)",
        11: "November 2026 (Sideway / Consolidation)"
    }
    month_name = month_names.get(month_num, f"Month {month_num}")
    strat = create_exp15_strategy(monday_mode=monday_mode)
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


def compute_continuous_equity_table(month_results, initial_capital: float = 10_000.0):
    current_equity = initial_capital
    all_time_peak = initial_capital
    max_dd_cum = 0.0

    table = Table(title="EXP-15: CONTINUOUS MULTI-MONTH EQUITY CURVE (PURE SHIELD SCALPER)", border_style="cyan")
    table.add_column("Bulan", style="white bold")
    table.add_column("Start Equity ($)", justify="right")
    table.add_column("Net PnL ($)", justify="right")
    table.add_column("End Equity ($)", justify="right", style="bold")
    table.add_column("Return Bln (%)", justify="right")
    table.add_column("Return Kumulatif (%)", justify="right")
    table.add_column("Intra DD (%)", justify="right")
    table.add_column("Cum Max DD (%)", justify="right")
    table.add_column("Trades (W/L)", justify="center")
    table.add_column("WR (%)", justify="right")
    table.add_column("PF", justify="right")

    for r in month_results:
        start_eq = current_equity
        net_pnl = r["net_pnl"]
        end_eq = start_eq + net_pnl

        if end_eq > all_time_peak:
            all_time_peak = end_eq

        month_ret_pct = ((end_eq - start_eq) / start_eq * 100.0) if start_eq > 0 else 0.0
        cum_ret_pct = ((end_eq - initial_capital) / initial_capital * 100.0)

        dd_at_end = (all_time_peak - end_eq) / all_time_peak * 100.0
        if dd_at_end > max_dd_cum:
            max_dd_cum = dd_at_end

        current_equity = end_eq
        pnl_color = "green" if net_pnl > 0 else ("red" if net_pnl < 0 else "white")

        table.add_row(
            r["name"].split(" (")[0],
            f"${start_eq:,.2f}",
            f"[{pnl_color}]${net_pnl:+,.2f}[/{pnl_color}]",
            f"${end_eq:,.2f}",
            f"{month_ret_pct:+.2f}%",
            f"{cum_ret_pct:+.2f}%",
            f"{r['max_dd']:.2f}%",
            f"{max_dd_cum:.2f}%",
            f"{r['trades']} ({r['wins']}W/{r['losses']}L)",
            f"{r['win_rate']:.1f}%",
            f"{r['pf']:.2f}",
        )

    return table, current_equity, max_dd_cum, all_time_peak


def main():
    exp_dir = Path("reports/experiments/EXP-15")
    exp_dir.mkdir(parents=True, exist_ok=True)

    console.print("[bold cyan]========================================================================[/bold cyan]")
    console.print("[bold cyan]   EXP-15: PURE ASYMMETRIC SHIELD SCALPER (53.54M REAL TICKS)          [/bold cyan]")
    console.print("[bold cyan]   Single Engine A | Wasit ORB Shield | Monday OFF | Extended Blackout [/bold cyan]")
    console.print("[bold cyan]========================================================================[/bold cyan]")

    month_results = []
    months = [4, 5, 6, 7, 8, 9, 10, 11]

    console.print("\n[bold yellow]Part 1: Running Individual Monthly Regime Audits (April - November 2026)...[/bold yellow]")
    for m in months:
        p_pattern = f"data/parquet/xauusd/year=2026/month={m:02d}/*.parquet"
        df_month = pl.read_parquet(p_pattern).sort("timestamp")
        console.print(f" -> Simulating Month {m:02d} ({len(df_month):,} ticks)...")

        res = run_month_eval(m, df_month, exp_dir, monday_mode="OFF")
        month_results.append(res)
        console.print(
            f"    [green]Done:[/green] Trades: {res['trades']} | WR: {res['win_rate']:.1f}% | "
            f"PF: {res['pf']:.2f} | Net: ${res['net_pnl']:+,.2f} | Max DD: {res['max_dd']:.2f}% | W/L: {res['win_loss_ratio']:.2f}x"
        )
        del df_month
        gc.collect()

    # Print Continuous Table
    console.print("\n")
    cont_table, final_eq, final_dd, peak_eq = compute_continuous_equity_table(month_results, 10_000.0)
    console.print(cont_table)

    net_tot = final_eq - 10000.0
    console.print(f"\n[bold green]EXP-15 Final Continuous Result: Modal Awal: $10,000.00 -> Equity Akhir: ${final_eq:,.2f} ({net_tot/100:+.2f}%)[/bold green]")
    console.print(f"[bold green]Total Net Profit: ${net_tot:+,.2f} | Peak Equity: ${peak_eq:,.2f} | Max Drawdown Kumulatif: {final_dd:.2f}%[/bold green]")


if __name__ == "__main__":
    main()
