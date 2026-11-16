"""Test configuration initialization and defaults."""

from src.config import BacktestConfig, BrokerConfig, ExecutionConfig, PathConfig


def test_default_config():
    config = BacktestConfig()
    
    # Test broker defaults
    assert config.broker.symbol == "XAUUSD"
    assert config.broker.contract_size == 100.0
    assert config.broker.point_size == 0.01
    assert config.broker.commission_per_lot_round_turn == 6.0
    assert config.broker.default_leverage == 100.0
    
    # Test execution reality defaults
    assert config.execution.latency_min_ms == 50
    assert config.execution.latency_max_ms == 150
    assert config.execution.base_slippage_mean_points == 0.01
    
    # Test paths
    assert config.paths.parquet_data_dir.name == "parquet"
    assert config.paths.raw_data_dir.name == "raw"
