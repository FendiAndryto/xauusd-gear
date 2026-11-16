"""Unit tests for Session-Aware Dynamic Risk and Regime Manager (TICK-401)."""

from datetime import datetime, timezone
import pytest

from src.strategies.session_manager import SessionRegimeManager


def test_session_regime_classification():
    mgr = SessionRegimeManager()

    # 1. Rollover Blackout (21:00 and 22:00 UTC)
    dt_rollover = datetime(2026, 10, 15, 21, 30, tzinfo=timezone.utc)
    regime = mgr.get_regime(dt_rollover)
    assert regime.regime_name == "ROLLOVER_BLACKOUT"
    assert not regime.allow_new_entries
    assert regime.is_rollover
    assert regime.max_layers == 0
    assert regime.lot_multiplier == 0.0

    # 2. Asian Regime (e.g. 02:00 UTC / 09:00 WIB)
    dt_asian = datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc)
    regime = mgr.get_regime(dt_asian)
    assert regime.regime_name == "ASIAN_SCALED"
    assert regime.allow_new_entries
    assert not regime.is_rollover
    assert regime.lot_multiplier == 0.50
    assert regime.max_layers == 2

    # 3. London / NY Prime Regime (e.g. 14:00 UTC / 21:00 WIB)
    dt_prime = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
    regime = mgr.get_regime(dt_prime)
    assert regime.regime_name == "LONDON_NY_PRIME"
    assert regime.allow_new_entries
    assert not regime.is_rollover
    assert regime.lot_multiplier == 1.00
    assert regime.max_layers == 3
