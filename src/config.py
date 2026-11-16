"""Centralized Configuration for XAUUSD Tick Research & Reality Simulation."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class PathConfig:
    """Directory and file path management."""
    base_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent)
    data_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data")
    raw_data_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "raw")
    parquet_data_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "data" / "parquet")
    reports_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parent.parent / "reports")
    # Locked MT5 terminal directory for this research project
    mt5_terminal_dir: str = r"C:\MetaTrader 5 - RESEARCH - EA"
    mt5_terminal_path: str = r"C:\MetaTrader 5 - RESEARCH - EA\terminal64.exe"


@dataclass(frozen=True)
class BrokerConfig:
    """Broker-specific contract and cost specifications for XAUUSD."""
    symbol: str = "XAUUSD"
    contract_size: float = 100.0          # 100 troy ounces per 1 standard lot
    point_size: float = 0.01              # Standard 2-digit gold point size ($0.01)
    digits: int = 2                       # Price decimal digits
    min_lot: float = 0.01                 # Minimum volume
    max_lot: float = 100.0                # Maximum volume
    lot_step: float = 0.01                # Volume stepping
    commission_per_lot_round_turn: float = 6.0  # $6.00 per lot ($3 open + $3 close)
    default_leverage: float = 100.0       # 1:100 leverage
    stop_out_level: float = 0.50          # 50% margin level stop-out threshold
    margin_call_level: float = 0.80       # 80% margin call warning


@dataclass(frozen=True)
class ExecutionConfig:
    """Execution reality parameters: latency queue, spread, slippage."""
    # Latency model (queue delay before execution)
    latency_min_ms: int = 50              # Minimum latency (milliseconds)
    latency_max_ms: int = 150             # Maximum latency (milliseconds)
    
    # Dynamic Slippage model
    base_slippage_mean_points: float = 0.01   # Mean adverse slippage ($0.01)
    base_slippage_std_points: float = 0.02    # Std dev of slippage
    volatility_lookback_ticks: int = 50       # Window to measure tick speed
    volatility_penalty_multiplier: float = 2.0 # Penalty during fast market spikes
    
    # Spread filter / safety checks
    max_tolerated_spread_points: float = 0.80 # Skip entry if spread > $0.80


@dataclass
class BacktestConfig:
    """Settings for backtest run."""
    initial_balance: float = 10_000.0     # Default starting capital ($10k)
    broker: BrokerConfig = field(default_factory=BrokerConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    paths: PathConfig = field(default_factory=PathConfig)
