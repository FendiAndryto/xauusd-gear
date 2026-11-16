"""CLI script to run market microstructure profiling on ingested real tick data."""

from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from src.analytics.microstructure import MicrostructureProfiler
from src.ingestion.storage import TickStorageManager

console = Console()


def main():
    console.print("[cyan]Loading real ticks from Parquet storage for microstructure analysis...[/cyan]")
    storage = TickStorageManager()
    ticks_df = storage.load_ticks(symbol="xauusd")

    if ticks_df.is_empty():
        console.print("[red]No ticks found in Parquet storage. Run scripts/ingest_ticks.py first![/red]")
        return

    console.print(f"[green]Loaded {len(ticks_df):,} real ticks. Profiling hourly spread & liquidity regimes...[/green]")
    
    profiler = MicrostructureProfiler()
    profiles = profiler.profile(ticks_df)
    
    # Render table in console
    profiler.print_profile_table(profiles)
    
    # Export CSV
    csv_path = profiler.export_csv(profiles)
    console.print(f"\n[bold green]Microstructure profile exported successfully to: {csv_path}[/bold green]")


if __name__ == "__main__":
    main()
