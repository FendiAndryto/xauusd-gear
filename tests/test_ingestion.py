"""Tests for data ingestion: storage, CSV parser, and validator."""

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import polars as pl
import pytest

from src.ingestion.csv_importer import MT5CSVImporter
from src.ingestion.schema import TICK_SCHEMA
from src.ingestion.storage import TickStorageManager
from src.ingestion.validator import TickDataValidator


@pytest.fixture
def sample_ticks_df():
    """Generates a small valid tick DataFrame."""
    return pl.DataFrame({
        "timestamp": [
            datetime(2024, 10, 1, 10, 0, 0, 100_000, tzinfo=timezone.utc),
            datetime(2024, 10, 1, 10, 0, 0, 250_000, tzinfo=timezone.utc),
            datetime(2024, 10, 1, 10, 0, 0, 500_000, tzinfo=timezone.utc),
            datetime(2024, 11, 2, 12, 0, 0, 0, tzinfo=timezone.utc),
        ],
        "bid": [2650.10, 2650.15, 2650.20, 2680.00],
        "ask": [2650.35, 2650.40, 2650.45, 2680.25],
        "spread": [0.25, 0.25, 0.25, 0.25],
        "volume": [1.0, 2.0, 1.5, 3.0],
        "flags": [6, 6, 6, 6],
    }).cast(TICK_SCHEMA)


def test_storage_save_and_load(tmp_path, sample_ticks_df):
    manager = TickStorageManager(base_dir=tmp_path)
    saved = manager.save_ticks(sample_ticks_df, symbol="XAUUSD")
    
    assert len(saved) == 2  # October 2024 and November 2024 partitions
    
    # Load all
    loaded = manager.load_ticks("XAUUSD")
    assert len(loaded) == 4
    assert loaded["bid"].to_list() == [2650.10, 2650.15, 2650.20, 2680.00]

    # Filter with start/end
    filtered = manager.load_ticks(
        "XAUUSD",
        start=datetime(2024, 11, 1, tzinfo=timezone.utc)
    )
    assert len(filtered) == 1
    assert filtered["bid"][0] == 2680.00


def test_csv_importer(tmp_path):
    csv_file = tmp_path / "xauusd_ticks.csv"
    csv_content = (
        "<DATE>\t<TIME>\t<BID>\t<ASK>\t<LAST>\t<VOLUME>\t<FLAGS>\n"
        "2024.10.01\t14:30:00.123\t2645.50\t2645.75\t0\t1\t6\n"
        "2024.10.01\t14:30:00.456\t2645.60\t2645.85\t0\t2\t6\n"
    )
    csv_file.write_text(csv_content, encoding="utf-8")

    importer = MT5CSVImporter(storage_manager=TickStorageManager(base_dir=tmp_path / "parquet"))
    df = importer.import_csv(csv_file, symbol="XAUUSD", save_to_parquet=True)

    assert len(df) == 2
    assert "spread" in df.columns
    assert df["spread"].to_list() == [0.25, 0.25]
    assert df["bid"].to_list() == [2645.50, 2645.60]


def test_validator_on_valid_data(sample_ticks_df):
    validator = TickDataValidator()
    report = validator.validate(sample_ticks_df)
    assert report.is_valid is True
    assert report.negative_or_zero_spread_count == 0
    assert report.out_of_order_timestamp_count == 0


def test_validator_detects_bad_spread():
    bad_df = pl.DataFrame({
        "timestamp": [datetime(2024, 10, 1, 10, 0, 0, tzinfo=timezone.utc)],
        "bid": [2650.50],
        "ask": [2650.10],  # Ask < Bid anomaly!
        "spread": [-0.40],
        "volume": [1.0],
        "flags": [6],
    }).cast(TICK_SCHEMA)

    validator = TickDataValidator()
    report = validator.validate(bad_df)
    assert report.is_valid is False
    assert report.negative_or_zero_spread_count == 1
