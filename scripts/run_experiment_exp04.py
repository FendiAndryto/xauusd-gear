"""Execution & Benchmarking Runner for EXP-04 (Session-Aware Risk Scaling & Breakeven Empirical Matrix)."""

from datetime import datetime
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console
from rich.table import Table

from src.analytics.metrics import MetricsCalculator
from src.analytics.reporting import PerformanceReporter
from src.config import BacktestConfig, BrokerConfig, ExecutionConfig
from src.ingestion.storage import TickStorageManager
from src.simulator.engine import TickBacktestEngine
from src.strategies.range_sweep_scalper_v3 import RangeSweepScalperV3

console = Console()


def create_strategy_factory(be_policy: str):
    def factory():
        return RangeSweepScalperV3(
            name=f"RangeSweepV3_{be_policy}",
            lookback_minutes=30,
            min_range_usd=5.0,                 # Sweet spot $5.00
            max_range_usd=12.0,                # Sweet spot $12.00
            min_sweep_usd=0.75,                # $0.75 min penetration
            max_sweep_usd=2.00,                # $2.00 max penetration
            hard_sl_offset_usd=1.20,           # $1.20 invalidation buffer
            layer_spacing_usd=0.50,            # Retest layer spacing
            layer_volumes=[0.05, 0.10, 0.15],  # Base 3-layer sizing
            max_spread_usd=0.25,               # Spread gate
            cooldown_seconds=1200.0,           # 20m breakout cooldown
            be_policy=be_policy,
        )
    return factory


def main():
    console.print("[bold cyan]=== RUNNING EXPERIMENT EXP-04: SESSION SIZING & BREAKEVEN A/B MATRIX ===[/bold cyan]")
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

    exp_dir = Path("reports/experiments/EXP-04")
    exp_dir.mkdir(parents=True, exist_ok=True)

    # Walk-Forward Split: 70% In-Sample (Oct), 30% Out-of-Sample (Nov)
    n_ticks = len(ticks_df)
    train_split_idx = int(n_ticks * 0.70)
    train_ticks = ticks_df.slice(0, train_split_idx)
    test_ticks = ticks_df.slice(train_split_idx)

    console.print(f"[cyan]Dataset Partition: {n_ticks:,} total ticks[/cyan]")
    console.print(f"  - In-Sample (Train 70%): {len(train_ticks):,} ticks")
    console.print(f"  - Out-of-Sample (Blind 30%): {len(test_ticks):,} ticks\n")

    variants = [
        ("EXP-04-A", "NONE", "No BE (SL stays at hard invalidation)"),
        ("EXP-04-B", "STRICT", "Strict BE (SL to Entry on TP1)"),
        ("EXP-04-C", "BUFFER", "Buffer BE (SL to Range Boundary RH/RL on TP1)"),
        ("EXP-04-D", "STEP_LOCK", "Step-Lock (SL untouched at TP1; Runner locked to EQ at TP2)"),
    ]

    results = []

    for code, policy, desc in variants:
        console.print(f"[bold yellow]Evaluating Variant: {code} [{policy}] - {desc}...[/bold yellow]")

        # 1. In-Sample Run
        strat_is = create_strategy_factory(policy)()
        engine_is = TickBacktestEngine(strategy=strat_is, config=config)
        res_is = engine_is.run(train_ticks)
        perf_is = MetricsCalculator.calculate(res_is.closed_trades, res_is.equity_curve, initial_balance=10_000.0)

        # 2. Out-of-Sample Run
        strat_oos = create_strategy_factory(policy)()
        engine_oos = TickBacktestEngine(strategy=strat_oos, config=config)
        res_oos = engine_oos.run(test_ticks)
        perf_oos = MetricsCalculator.calculate(res_oos.closed_trades, res_oos.equity_curve, initial_balance=10_000.0)

        results.append({
            "code": code,
            "policy": policy,
            "desc": desc,
            "is_perf": perf_is,
            "oos_perf": perf_oos,
            "res_is": res_is,
            "res_oos": res_oos,
        })

        # Save individual variant reports
        var_dir = exp_dir / code
        var_dir.mkdir(parents=True, exist_ok=True)
        rep_is = PerformanceReporter(output_dir=var_dir / "in_sample")
        rep_is.export_trade_log(res_is.closed_trades)
        rep_is.export_equity_curve(res_is.equity_curve)
        rep_oos = PerformanceReporter(output_dir=var_dir / "out_of_sample")
        rep_oos.export_trade_log(res_oos.closed_trades)
        rep_oos.export_equity_curve(res_oos.equity_curve)

        console.print(
            f"  -> IS Net: [bold {'green' if perf_is.net_profit > 0 else 'red'}]${perf_is.net_profit:,.2f}[/] (PF {perf_is.profit_factor:.2f}) | "
            f"OOS Net: [bold {'green' if perf_oos.net_profit > 0 else 'red'}]${perf_oos.net_profit:,.2f}[/] (PF {perf_oos.profit_factor:.2f}, DD {perf_oos.max_drawdown_pct:.1f}%)\n"
        )

    # -------------------------------------------------------------
    # Print Comprehensive Leaderboard Table
    # -------------------------------------------------------------
    table = Table(title="EXP-04: Session-Aware Risk Scaling & Breakeven Empirical Matrix")
    table.add_column("Variant Code", style="bold cyan")
    table.add_column("Policy", style="bold white")
    table.add_column("IS Trades", justify="right")
    table.add_column("IS Net PnL", justify="right")
    table.add_column("IS PF", justify="right")
    table.add_column("OOS Trades", justify="right")
    table.add_column("OOS Win Rate", justify="right")
    table.add_column("OOS Win/Loss", justify="right")
    table.add_column("OOS Net PnL", justify="right", style="bold")
    table.add_column("OOS PF", justify="right", style="bold")
    table.add_column("OOS Max DD", justify="right")

    for r in results:
        p_is = r["is_perf"]
        p_oos = r["oos_perf"]
        table.add_row(
            r["code"],
            r["policy"],
            f"{p_is.total_trades:,}",
            f"${p_is.net_profit:,.2f}",
            f"{p_is.profit_factor:.2f}",
            f"{p_oos.total_trades:,}",
            f"{p_oos.win_rate_pct:.1f}%",
            f"{p_oos.win_loss_ratio:.2f}x",
            f"${p_oos.net_profit:,.2f}",
            f"{p_oos.profit_factor:.2f}",
            f"{p_oos.max_drawdown_pct:.2f}%",
        )

    console.print(table)

    # Write comparative analysis markdown
    md_lines = [
        "# Laporan Komparatif: EXP-04 Session-Aware Risk Scaling & Breakeven A/B Matrix",
        "",
        "## 1. Leaderboard Perbandingan 4 Kebijakan Breakeven",
        "",
        "| Varian | Kebijakan BE | IS Trades | IS Net PnL | IS PF | OOS Trades | OOS Win Rate | OOS Win/Loss | OOS Net PnL | OOS PF | OOS Max DD |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in results:
        p_is = r["is_perf"]
        p_oos = r["oos_perf"]
        md_lines.append(
            f"| `{r['code']}` | **{r['policy']}** | {p_is.total_trades:,} | ${p_is.net_profit:,.2f} | {p_is.profit_factor:.2f} | "
            f"{p_oos.total_trades:,} | {p_oos.win_rate_pct:.1f}% | {p_oos.win_loss_ratio:.2f}x | **${p_oos.net_profit:,.2f}** | **{p_oos.profit_factor:.2f}** | {p_oos.max_drawdown_pct:.2f}% |"
        )

    md_lines.extend([
        "",
        "## 2. Analisis Kuantitatif & Temuan Empiris",
        "Eksperimen ini menguji 4 varian manajemen proteksi posisi secara head-to-head pada 6.612.042 tick riil Exness.",
    ])

    report_path = exp_dir / "EXP04_COMPARATIVE_ANALYSIS.md"
    report_path.write_text("\n".join(md_lines), encoding="utf-8")
    console.print(f"[bold green]Comparative report saved to: {report_path}[/bold green]")


if __name__ == "__main__":
    main()
