"""CLI tool to ingest XAUUSD ticks from MT5 directly or from exported CSV."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

from src.config import PathConfig
from src.ingestion.csv_importer import MT5CSVImporter
from src.ingestion.mt5_collector import MT5TickCollector
from src.ingestion.storage import TickStorageManager
from src.ingestion.validator import TickDataValidator

console = Console()


def main():
    paths = PathConfig()
    parser = argparse.ArgumentParser(description="Ingest XAUUSD tick data into partitioned Parquet.")
    parser.add_argument("--source", choices=["mt5", "csv"], default="mt5", help="Data source: 'mt5' or 'csv'")
    parser.add_argument("--csv-file", type=str, help="Path to CSV file (if source is csv)")
    parser.add_argument("--symbol", type=str, default="XAUUSD", help="Symbol to fetch (default: XAUUSD)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--chunk-days", type=int, default=7, help="Days per fetch chunk (default: 7)")
    parser.add_argument("--terminal-path", type=str, default=paths.mt5_terminal_path, help="Path to MT5 terminal64.exe")
    args = parser.parse_args()

    storage = TickStorageManager()

    if args.source == "csv":
        if not args.csv_file:
            console.print("[red]Error: --csv-file is required when --source is 'csv'.[/red]")
            return
        csv_path = Path(args.csv_file)
        console.print(f"[cyan]Parsing CSV from: {csv_path}...[/cyan]")
        importer = MT5CSVImporter(storage_manager=storage)
        df = importer.import_csv(csv_path, symbol=args.symbol, save_to_parquet=True)
        console.print(f"[green]Successfully imported {len(df):,} ticks to Parquet![/green]")

        # Run Validator on imported df
        console.print("[yellow]Running data integrity validation...[/yellow]")
        validator = TickDataValidator()
        report = validator.validate(df)
        report.print_summary()

    elif args.source == "mt5":
        start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc) if args.start else None
        end_dt = datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end else None
        console.print(f"[cyan]Connecting to MetaTrader 5 (Path: {args.terminal_path}) to pull ticks for {args.symbol}...[/cyan]")
        
        collector = MT5TickCollector(terminal_path=args.terminal_path, storage_manager=storage)
        with collector:
            # Stream directly to Parquet to keep memory footprint under 50 MB
            collector.fetch_ticks(
                symbol=args.symbol,
                start=start_dt,
                end=end_dt,
                save_to_parquet=True,
                chunk_days=args.chunk_days,
                return_dataframe=False,
            )

        # Inspect resulting parquet storage
        canonical_symbol = "xauusd" if "xau" in args.symbol.lower() else args.symbol.lower()
        lazy_df = storage.scan_ticks(symbol=canonical_symbol)
        total_stored = len(storage.load_ticks(symbol=canonical_symbol))
        console.print(f"[bold green]Successfully synchronized ticks! Total ticks in storage: {total_stored:,}[/bold green]")


if __name__ == "__main__":
    main()
