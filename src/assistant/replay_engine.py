"""Replay data aggregation & serialization engine (ticket T-REP-01).

Builds a single, self-contained JSON payload for the browser-side visual replay
engine: every LTF candle, every simulated trade (entry/exit/SL/TP/PnL), the
retest zones and the compounding equity curve.

Design constraints
------------------
1. **Numerical parity with the official benchmark.** Signal generation and trade
   simulation are delegated to the isolated experiment track
   (`experiments_isolated/m15_m5_dual_retest_scalper/`) instead of being
   re-implemented here. `simulate_dual_trades()` is reused verbatim, so replay
   PnL is bit-identical to `reports/LAPORAN_PENGUJIAN_MODE_A_MURNI.md`.
2. **Causality of the bar pair.** Bar loading mirrors `backtest_runner.load_bar_pair`
   (M15->M5 when the M5 cache exists, otherwise H1->M15) so a session never
   mixes execution timeframes inside one chart.
3. **Cheap session discovery.** `/api/replay/sessions` must answer instantly, so
   month discovery only reads parquet *metadata* (row counts) — never the bars.

The payload is cached in-process per (session, strategy, rr) signature: the cold
path costs ~0.15 s per month, the warm path is a dict lookup.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np
import pandas as pd
import polars as pl

from experiments_isolated.m15_m5_dual_retest_scalper.backtest_runner import (
    simulate_dual_trades,
)
from experiments_isolated.m15_m5_dual_retest_scalper.strategy import (
    DualRetestScalperStrategy,
)
from src.config import PathConfig

logger = logging.getLogger(__name__)

CACHE_DIR: Path = PathConfig().base_dir / "data" / "cache_bars"

INITIAL_CAPITAL = 10_000.0
RISK_PCT = 0.015
SPREAD_COST_USD = 0.20
DEFAULT_RR = 1.5

# R:R targets offered by the replay UI.
#
# PARITY NOTE: only `DEFAULT_RR` is pinned to the official benchmark report
# (48 trades / $12,349.84 / DD 4.30% for October 2026 under `mode_a_pure`).
# Any other value re-runs the strategy with a different take-profit and
# therefore produces a *different* trade list, win rate and drawdown — those
# numbers are exploratory and must never be presented as report parity.
# The UI labels this via `is_parity` below rather than hardcoding the rule in JS.
RR_PRESETS: tuple[dict[str, Any], ...] = (
    {"value": 1.0, "label": "1 : 1"},
    {"value": 1.5, "label": "1 : 1.5"},
    {"value": 2.0, "label": "1 : 2"},
    {"value": 2.5, "label": "1 : 2.5"},
    {"value": 3.0, "label": "1 : 3"},
)

# Strategy presets exposed by the API (see SPEC-REPLAY-01 §3).
STRATEGIES: dict[str, dict[str, Any]] = {
    "mode_a_pure": {
        "label": "Mode A Murni (Pro-Trend Retest)",
        "enable_mode_a": True,
        "enable_mode_b": False,
    },
    "dual_mode": {
        "label": "Dual Mode (Retest + Sweep Reversal)",
        "enable_mode_a": True,
        "enable_mode_b": True,
    },
}

# Retest-zone geometry, taken from `continuation_engine.py` so the shaded box is
# the same band the strategy actually tested price against.
RETEST_PROXIMITY_USD = 1.20
RETEST_DEPTH_USD = 1.00
SWEEP_PIERCE_USD = 0.30
SWEEP_CLOSE_BAND_USD = 0.20

MONTH_NAMES_ID = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
}
MONTH_ABBR_ID = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "Mei",
    6: "Jun",
    7: "Jul",
    8: "Agu",
    9: "Sep",
    10: "Okt",
    11: "Nov",
    12: "Des",
}

_BREAK_LEVEL_RE = re.compile(r"@\s*(-?\d+(?:\.\d+)?)")


class ReplaySessionError(ValueError):
    """Unknown session id, or a request the engine cannot honour."""


# --------------------------------------------------------------------------- data


@dataclass(frozen=True)
class MonthSource:
    """One cached month of bars, already resolved to a bar pair."""

    year: int
    month: int
    ltf: str  # execution timeframe: "M5" or "M15"
    htf: str  # macro timeframe: "M15" or "H1"
    bars: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.year, self.month)

    @property
    def label(self) -> str:
        return f"{MONTH_NAMES_ID[self.month]} {self.year}"

    @property
    def iso_start(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-01"


@dataclass(frozen=True)
class ReplaySession:
    """A homogeneous (single execution timeframe) replay range."""

    id: str
    name: str
    timeframe: str
    macro_timeframe: str
    months: tuple[MonthSource, ...]

    @property
    def start_date(self) -> str:
        return self.months[0].iso_start

    @property
    def end_date(self) -> str:
        return self.months[-1].iso_start

    @property
    def total_bars(self) -> int:
        return sum(m.bars for m in self.months)

    def to_dict(self, total_trades: Optional[int] = None) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "timeframe": self.timeframe,
            "macro_timeframe": self.macro_timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_bars": self.total_bars,
            "total_trades": total_trades,
            "months": len(self.months),
        }


# ------------------------------------------------------------------ discovery


def _parquet_rows(path: Path) -> int:
    """Row count from parquet footer only (no column decode)."""
    try:
        import pyarrow.parquet as pq

        return int(pq.ParquetFile(path).metadata.num_rows)
    except Exception:  # corrupt/partial file: treat as unusable
        logger.warning("replay: cannot read parquet metadata for %s", path)
        return 0


def _file_for(kind: str, year: int, month: int, cache_dir: Path) -> Path:
    return cache_dir / f"{kind}_{year}_{month:02d}.parquet"


def scan_months(cache_dir: Optional[Path] = None) -> list[MonthSource]:
    """List every cached month that can serve as a replay bar pair.

    Mirrors `backtest_runner.load_bar_pair`: M5 execution when both M5 and M15
    exist, otherwise M15 execution against H1 macro bars.
    """
    root = Path(cache_dir or CACHE_DIR)
    if not root.exists():
        return []

    found: list[MonthSource] = []
    for path in sorted(root.glob("m15_*.parquet")):
        stem = path.stem  # m15_2026_10
        try:
            _, year_s, month_s = stem.split("_")
            year, month = int(year_s), int(month_s)
        except ValueError:
            continue
        m15_rows = _parquet_rows(path)
        if m15_rows <= 0:
            continue

        m5_path = _file_for("m5", year, month, root)
        h1_path = _file_for("h1", year, month, root)
        if m5_path.exists():
            rows = _parquet_rows(m5_path)
            if rows > 0:
                found.append(MonthSource(year, month, "M5", "M15", rows))
                continue
        if h1_path.exists():
            found.append(MonthSource(year, month, "M15", "H1", m15_rows))

    found.sort(key=lambda m: m.key)
    return found


def _contiguous_runs(months: Sequence[MonthSource]) -> list[list[MonthSource]]:
    """Split months into runs that share an execution timeframe and are adjacent."""
    runs: list[list[MonthSource]] = []
    for month in months:
        if runs:
            tail = runs[-1][-1]
            adjacent = month.year * 12 + month.month == tail.year * 12 + tail.month + 1
            if adjacent and month.ltf == tail.ltf:
                runs[-1].append(month)
                continue
        runs.append([month])
    return runs


def _range_name(months: Sequence[MonthSource]) -> str:
    first, last = months[0], months[-1]
    return (
        f"{MONTH_ABBR_ID[first.month]} {first.year} - "
        f"{MONTH_ABBR_ID[last.month]} {last.year}"
    )


def _session_for(
    months: Sequence[MonthSource], session_id: str, name: str
) -> ReplaySession:
    first = months[0]
    return ReplaySession(
        id=session_id,
        name=name,
        timeframe=first.ltf,
        macro_timeframe=first.htf,
        months=tuple(months),
    )


def build_sessions(cache_dir: Optional[Path] = None) -> list[ReplaySession]:
    """Preset ranges (rolling windows, per-year) followed by per-month sessions."""
    months = scan_months(cache_dir)
    if not months:
        return []

    sessions: list[ReplaySession] = []
    seen: set[str] = set()

    def add(session: ReplaySession) -> None:
        if session.id in seen:
            return
        seen.add(session.id)
        sessions.append(session)

    for run in _contiguous_runs(months):
        ltf = run[0].ltf.lower()
        add(
            _session_for(
                run,
                f"{ltf}_all",
                f"Seluruh arsip {run[0].ltf} ({_range_name(run)})",
            )
        )
        for window in (12, 6):
            if len(run) > window:
                tail = run[-window:]
                add(
                    _session_for(
                        tail,
                        f"{ltf}_{window}m",
                        f"{window} bulan terakhir {run[0].ltf} ({_range_name(tail)})",
                    )
                )

        # Per-calendar-year presets, only when the whole year is homogeneous.
        years = sorted({m.year for m in run})
        for year in years:
            year_months = [m for m in run if m.year == year]
            if len(year_months) < 6:  # partial cache edge (first/last month)
                continue
            add(
                _session_for(
                    year_months,
                    f"{ltf}_{year}",
                    f"Tahun {year} {run[0].ltf} ({_range_name(year_months)})",
                )
            )

    for month in months:
        add(
            _session_for(
                [month],
                f"m_{month.year}_{month.month:02d}",
                f"{month.label} ({month.ltf})",
            )
        )

    return sessions


def default_session_id(sessions: Sequence[ReplaySession]) -> Optional[str]:
    """Prefer the longest M5 preset: the richest dataset the chart can render."""
    for session in sessions:
        if session.id == "m5_all":
            return session.id
    for session in sessions:
        if session.timeframe == "M5":
            return session.id
    return sessions[0].id if sessions else None


def get_session(session_id: str, cache_dir: Optional[Path] = None) -> ReplaySession:
    sessions = build_sessions(cache_dir)
    for session in sessions:
        if session.id == session_id:
            return session
    raise ReplaySessionError(f"Sesi replay tidak dikenal: {session_id}")


# --------------------------------------------------------------------- bar load


def _load_bar_pair(
    source: MonthSource, cache_dir: Path
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load (HTF, LTF) frames for one month, index = naive UTC timestamps.

    Faithful to `backtest_runner.load_bar_pair`; duplicated here only so the web
    server resolves the cache with an absolute path (cwd independent).
    """
    htf_path = _file_for(source.htf.lower(), source.year, source.month, cache_dir)
    ltf_path = _file_for(source.ltf.lower(), source.year, source.month, cache_dir)

    frames: list[pd.DataFrame] = []
    for path in (htf_path, ltf_path):
        frame = pl.read_parquet(path).to_pandas()
        if "timestamp" in frame.columns:
            ts = pd.to_datetime(frame["timestamp"])
        elif "time" in frame.columns:
            ts = pd.to_datetime(frame["time"], unit="s")
        else:
            ts = pd.to_datetime(frame.index)
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_localize(None)
        frame = frame.copy()
        frame.index = ts
        frames.append(frame.sort_index())

    return frames[0], frames[1]


def _epoch_seconds(index: pd.DatetimeIndex) -> np.ndarray:
    """Naive-UTC index -> integer epoch seconds (no local-timezone leakage).

    The cache mixes resolutions (M5 files are ``datetime64[ns]``, M15 files are
    ``datetime64[us]``), so the index must be normalised to nanoseconds before
    the integer view is taken — otherwise M15 timestamps come out 1000x too
    small and every chart/hover label lands in January 1970.
    """
    if getattr(index, "tz", None) is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    nanoseconds = (
        index.as_unit("ns")
        if hasattr(index, "as_unit")
        else index.astype("datetime64[ns]")
    )
    return (nanoseconds.view("int64") // 1_000_000_000).astype("int64")


def _iso_utc(seconds: int) -> str:
    return pd.Timestamp(int(seconds), unit="s").strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------- zone geometry


def _parse_break_level(reason: str) -> Optional[float]:
    match = _BREAK_LEVEL_RE.search(reason or "")
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _zone_for_trade(
    trade: dict[str, Any], entry_bar: pd.Series
) -> Optional[dict[str, Any]]:
    """Shade the retest band a trade was taken from.

    Level comes from the strategy's own reason string (the broken pivot). If it
    cannot be parsed, fall back to the entry candle's rejection extreme so the
    overlay degrades gracefully instead of disappearing.
    """
    level = _parse_break_level(str(trade.get("reason", "")))
    side = trade["side"]
    mode = trade.get("mode")

    if mode == "SWEEP_REVERSAL":
        zone_type = "SWEEP"
        half = SWEEP_PIERCE_USD
        if level is None:
            level = float(entry_bar["high"] if side == "SELL" else entry_bar["low"])
        top, bottom = level + half, level - half
    elif side == "BUY":
        zone_type = "RBS"
        if level is None:
            level = float(entry_bar["low"]) + RETEST_PROXIMITY_USD
        top = level + RETEST_PROXIMITY_USD
        bottom = level - RETEST_DEPTH_USD
    else:
        zone_type = "SBR"
        if level is None:
            level = float(entry_bar["high"]) - RETEST_PROXIMITY_USD
        top = level + RETEST_DEPTH_USD
        bottom = level - RETEST_PROXIMITY_USD

    return {
        "type": zone_type,
        "level": round(level, 2),
        "top": round(max(top, bottom), 2),
        "bottom": round(min(top, bottom), 2),
    }


# --------------------------------------------------------------------- payload


def _candle_rows(df: pd.DataFrame, epochs: np.ndarray) -> Iterable[dict[str, Any]]:
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    if "tick_volume" in df.columns:
        volumes = df["tick_volume"].to_numpy(dtype=float)
    elif "volume" in df.columns:
        volumes = df["volume"].to_numpy(dtype=float)
    else:
        volumes = np.zeros(len(df), dtype=float)

    for i in range(len(df)):
        yield {
            "time": int(epochs[i]),
            "open": round(float(opens[i]), 2),
            "high": round(float(highs[i]), 2),
            "low": round(float(lows[i]), 2),
            "close": round(float(closes[i]), 2),
            "volume": float(volumes[i]),
        }


def _build_payload(
    session: ReplaySession,
    strategy_key: str,
    rr_ratio: float,
    cache_dir: Path,
) -> dict[str, Any]:
    preset = STRATEGIES[strategy_key]
    strat = DualRetestScalperStrategy(
        default_rr=rr_ratio,
        enable_mode_a=bool(preset["enable_mode_a"]),
        enable_mode_b=bool(preset["enable_mode_b"]),
    )

    candles: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    zones: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []

    equity = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    max_dd_pct = 0.0
    bar_offset = 0
    first_epoch: Optional[int] = None

    for source in session.months:
        df_htf, df_ltf = _load_bar_pair(source, cache_dir)
        if df_ltf.empty:
            continue

        epochs = _epoch_seconds(df_ltf.index)
        if first_epoch is None:
            first_epoch = int(epochs[0])
            equity_curve.append(
                {"time": first_epoch, "equity": round(INITIAL_CAPITAL, 2)}
            )

        setups = strat.scan_setups(df_htf, df_ltf, rr_ratio=rr_ratio)
        month_trades, equity, _month_dd = simulate_dual_trades(
            setups=setups,
            df_ltf=df_ltf,
            start_equity=equity,
            risk_pct=RISK_PCT,
            spread_cost_usd=SPREAD_COST_USD,
        )

        candles.extend(_candle_rows(df_ltf, epochs))

        index = df_ltf.index

        for trade in month_trades:
            pnl = float(trade["net_pnl"])
            equity_after = float(trade["equity_after"])
            # Exact by construction: simulate_dual_trades adds net_pnl to equity.
            equity_before = equity_after - pnl

            # The runner keeps full float precision, but the UI only ever shows
            # 2 decimals. Rounding pnl/equity_before/equity_after independently
            # breaks the chain by up to a cent (equity_before + pnl !=
            # equity_after), which makes the HUD balance drift from the report.
            # Publish a cent-exact ledger instead: equity is rounded once and
            # each trade's pnl is the rounded difference of two rounded balances,
            # so the chain reconciles exactly and the running total still lands
            # on the report's final capital.
            equity_after_cents = int(round(equity_after * 100))
            equity_before_cents = int(round(equity_before * 100))
            pnl_cents = equity_after_cents - equity_before_cents
            pnl = pnl_cents / 100.0
            equity_after = equity_after_cents / 100.0
            equity_before = equity_before_cents / 100.0

            entry_idx = int(np.searchsorted(index, trade["timestamp"]))
            exit_idx = int(np.searchsorted(index, trade["exit_time"]))
            entry_idx = min(max(entry_idx, 0), len(df_ltf) - 1)
            exit_idx = min(max(exit_idx, entry_idx), len(df_ltf) - 1)

            exit_reason = str(trade["outcome"])
            if exit_reason == "TP":
                outcome = "WIN"
            elif exit_reason == "SL":
                outcome = "LOSS"
            else:
                outcome = "EXPIRED"

            if equity_after > peak:
                peak = equity_after
            drawdown = (peak - equity_after) / peak * 100.0 if peak > 0 else 0.0
            if drawdown > max_dd_pct:
                max_dd_pct = drawdown

            entry_epoch = int(epochs[entry_idx])
            exit_epoch = int(epochs[exit_idx])
            global_entry = bar_offset + entry_idx
            global_exit = bar_offset + exit_idx

            trades.append(
                {
                    "trade_id": f"T-{len(trades) + 1:03d}",
                    "month": f"{source.year}-{source.month:02d}",
                    "side": str(trade["side"]),
                    "mode": str(trade.get("mode", "")),
                    "entry_idx": global_entry,
                    "entry_time": entry_epoch,
                    "entry_iso": _iso_utc(entry_epoch),
                    "entry_price": round(float(trade["entry_price"]), 2),
                    "sl_price": round(float(trade["sl"]), 2),
                    "tp_price": round(float(trade["tp"]), 2),
                    "sl_dist": round(float(trade["sl_dist"]), 2),
                    "tp_dist": round(float(trade["tp_dist"]), 2),
                    "lot": round(float(trade["lot"]), 2),
                    "exit_idx": global_exit,
                    "exit_time": exit_epoch,
                    "exit_iso": _iso_utc(exit_epoch),
                    "exit_price": round(float(trade["exit_price"]), 2),
                    "exit_reason": exit_reason,
                    "outcome": outcome,
                    "bars_held": int(trade.get("bars_held", 0)),
                    "pnl": round(pnl, 2),
                    "equity_before": round(equity_before, 2),
                    "equity_after": round(equity_after, 2),
                    "reason": str(trade.get("reason", "")),
                }
            )

            zone = _zone_for_trade(trade, df_ltf.iloc[entry_idx])
            if zone is not None:
                zone.update(
                    {
                        "trade_id": trades[-1]["trade_id"],
                        "side": trades[-1]["side"],
                        "start_idx": max(0, global_entry - 2),
                        "end_idx": global_exit,
                        "start_time": int(epochs[max(0, entry_idx - 2)]),
                        "end_time": exit_epoch,
                    }
                )
                zones.append(zone)

            equity_curve.append({"time": exit_epoch, "equity": round(equity_after, 2)})

        bar_offset += len(df_ltf)

    total_trades = len(trades)
    wins = sum(1 for t in trades if t["pnl"] > 0)
    gross_win = sum(t["pnl"] for t in trades if t["pnl"] > 0)
    gross_loss = abs(sum(t["pnl"] for t in trades if t["pnl"] < 0))
    final_capital = float(equity)

    # Trades may overlap, so exits are not emitted in time order. The mini equity
    # chart needs a chronologically sorted series with unique timestamps (two
    # trades can close on the same bar; the later one wins).
    deduped: dict[int, dict[str, Any]] = {}
    for point in equity_curve:
        deduped[int(point["time"])] = point
    equity_curve = [deduped[key] for key in sorted(deduped)]

    meta = {
        "session_id": session.id,
        "name": session.name,
        "symbol": "XAUUSD",
        "timeframe": session.timeframe,
        "macro_timeframe": session.macro_timeframe,
        "strategy": strategy_key,
        "strategy_label": preset["label"],
        "rr_ratio": rr_ratio,
        "start_date": session.start_date,
        "end_date": session.end_date,
        "total_bars": len(candles),
        "total_trades": total_trades,
        "initial_capital": INITIAL_CAPITAL,
        "final_capital": round(final_capital, 2),
        "total_return_pct": round(
            (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100.0, 2
        ),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "win_rate": round(wins / total_trades * 100.0, 2) if total_trades else 0.0,
        "wins": wins,
        "losses": sum(1 for t in trades if t["pnl"] < 0),
        "expired": sum(1 for t in trades if t["outcome"] == "EXPIRED"),
        "profit_factor": (
            round(gross_win / gross_loss, 2)
            if gross_loss > 0
            else (99.0 if gross_win > 0 else 0.0)
        ),
        "risk_pct": RISK_PCT,
        "spread_cost_usd": SPREAD_COST_USD,
    }

    return {
        "meta": meta,
        "candles": candles,
        "trades": trades,
        "zones": zones,
        "equity_curve": equity_curve,
    }


# ------------------------------------------------------------------------ cache

_CACHE_LOCK = threading.Lock()
_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_CACHE_ORDER: list[tuple[Any, ...]] = []
_CACHE_MAX = 4


def _signature(session: ReplaySession, strategy_key: str, rr: float) -> tuple[Any, ...]:
    return (
        session.id,
        tuple(m.key for m in session.months),
        session.timeframe,
        strategy_key,
        round(float(rr), 4),
    )


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()
        _CACHE_ORDER.clear()


def generate_replay_session(
    session_id: str,
    strategy: str = "mode_a_pure",
    rr_ratio: float = DEFAULT_RR,
    cache_dir: Optional[Path] = None,
    session: Optional[ReplaySession] = None,
) -> dict[str, Any]:
    """Full replay payload for one session (cached in-process).

    ``session`` bypasses the id lookup for ad-hoc date ranges built by the API.
    """
    if strategy not in STRATEGIES:
        raise ReplaySessionError(f"Strategi tidak dikenal: {strategy}")
    rr = float(rr_ratio)
    if not (0.5 <= rr <= 5.0):
        raise ReplaySessionError("rr_ratio harus di antara 0.5 dan 5.0")

    if session is None:
        session = get_session(session_id, cache_dir)
    key = _signature(session, strategy, rr)

    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None:
            return cached

    payload = _build_payload(session, strategy, rr, Path(cache_dir or CACHE_DIR))

    with _CACHE_LOCK:
        _CACHE[key] = payload
        _CACHE_ORDER.append(key)
        while len(_CACHE_ORDER) > _CACHE_MAX:
            stale = _CACHE_ORDER.pop(0)
            _CACHE.pop(stale, None)
    logger.info(
        "replay payload built: %s (%d bars, %d trades)",
        session.id,
        len(payload["candles"]),
        len(payload["trades"]),
    )
    return payload


def cached_trade_count(session: ReplaySession) -> Optional[int]:
    """Trade count for a session already materialised, else None."""
    with _CACHE_LOCK:
        for key, payload in _CACHE.items():
            if key[0] == session.id:
                return int(payload["meta"]["total_trades"])
    return None


def list_replay_sessions(cache_dir: Optional[Path] = None) -> dict[str, Any]:
    """Session catalogue for the dashboard picker (fast: parquet metadata only)."""
    sessions = build_sessions(cache_dir)
    return {
        "sessions": [s.to_dict(cached_trade_count(s)) for s in sessions],
        "default_session_id": default_session_id(sessions),
        "strategies": [
            {"id": key, "label": preset["label"]} for key, preset in STRATEGIES.items()
        ],
        # The UI must not hardcode which R:R is "official": it renders the badge
        # from `is_parity` so the rule lives in exactly one place.
        "rr_presets": [
            {**preset, "is_parity": abs(float(preset["value"]) - DEFAULT_RR) < 1e-9}
            for preset in RR_PRESETS
        ],
        "default_rr": DEFAULT_RR,
        "cache_dir": str(cache_dir or CACHE_DIR),
    }


# ------------------------------------------------------- pure price action API
#
# T-PAR-06 / T-PAR-07. The replay terminal is a *pure price action* trainer: the
# browser asks for the candles of one timeframe over one period, and that is all
# it gets. This path deliberately never touches the strategy machinery above —
# no bar pairing, no trade simulation — so an H1 month that has no M15 sibling is
# still replayable, and the payload stays a fraction of the legacy one.

TIMEFRAME_KINDS: dict[str, str] = {"M1": "m1", "M5": "m5", "M15": "m15", "H1": "h1"}
SUPPORTED_TIMEFRAMES: tuple[str, ...] = ("M5", "M15", "H1", "M1")
PERIOD_MODES: tuple[str, ...] = ("month", "year", "multi_month", "custom", "all")

_FILE_RE = re.compile(r"^(m1|m5|m15|h1)_(\d{4})_(\d{2})\.parquet$")


@dataclass(frozen=True)
class MonthFile:
    """One cached month of bars for a *single* timeframe (no pairing)."""

    year: int
    month: int
    timeframe: str
    bars: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.year, self.month)

    @property
    def label(self) -> str:
        return f"{MONTH_NAMES_ID[self.month]} {self.year}"

    @property
    def iso_start(self) -> str:
        return f"{self.year:04d}-{self.month:02d}-01"


_SCAN_LOCK = threading.Lock()
_SCAN_CACHE: dict[tuple[str, float], dict[str, list[MonthFile]]] = {}


def scan_timeframe_files(
    cache_dir: Optional[Path] = None,
) -> dict[str, list[MonthFile]]:
    """Every cached month per timeframe, from parquet footers only.

    Cached against the directory mtime so the catalogue endpoint stays well under
    the spec's 50 ms budget on the warm path: 179 footers cost ~0.5 s cold.
    """
    root = Path(cache_dir or CACHE_DIR)
    result: dict[str, list[MonthFile]] = {tf: [] for tf in SUPPORTED_TIMEFRAMES}
    if not root.exists():
        return result

    try:
        stamp = root.stat().st_mtime
    except OSError:
        stamp = 0.0
    key = (str(root), stamp)

    with _SCAN_LOCK:
        cached = _SCAN_CACHE.get(key)
        if cached is not None:
            return {tf: list(months) for tf, months in cached.items()}

    kind_to_tf = {kind: tf for tf, kind in TIMEFRAME_KINDS.items()}
    for path in sorted(root.glob("*.parquet")):
        match = _FILE_RE.match(path.name)
        if match is None:
            continue
        kind, year_s, month_s = match.groups()
        rows = _parquet_rows(path)
        if rows <= 0:
            continue
        timeframe = kind_to_tf[kind]
        result[timeframe].append(MonthFile(int(year_s), int(month_s), timeframe, rows))

    for months in result.values():
        months.sort(key=lambda m: m.key)

    with _SCAN_LOCK:
        if len(_SCAN_CACHE) > 8:  # cache_dir churn in tests: drop the oldest
            _SCAN_CACHE.clear()
        _SCAN_CACHE[key] = {tf: list(months) for tf, months in result.items()}
    return result


def _last_bar_date(timeframe: str, month: MonthFile, cache_dir: Path) -> Optional[str]:
    """Real date of the newest bar in a month file (one column, one row)."""
    path = _file_for(TIMEFRAME_KINDS[timeframe], month.year, month.month, cache_dir)
    try:
        frame = pl.read_parquet(path, columns=["time"])
    except Exception:
        return None
    if frame.height == 0:
        return None
    last = int(frame["time"].max())
    return _iso_utc(last)[:10]


def timeframe_coverage(
    files: Optional[dict[str, list[MonthFile]]] = None,
    cache_dir: Optional[Path] = None,
) -> dict[str, dict[str, Any]]:
    """Start/end/bar-count per timeframe, using the real last bar date.

    Also reports *density*: the H1 files from 2018-07 to 2021-06 contain ~26 bars
    per month, i.e. daily candles written into an ``h1_*`` file. Claiming "H1 from
    2018" would hand the user 27 daily candles and call it an hourly replay, so
    those months are exposed as ``sparse_months`` and the honest hourly start is
    published separately as ``usable_start_date``.
    """
    root = Path(cache_dir or CACHE_DIR)
    files = files if files is not None else scan_timeframe_files(root)
    coverage: dict[str, dict[str, Any]] = {}
    for timeframe in SUPPORTED_TIMEFRAMES:
        months = files.get(timeframe) or []
        if not months:
            continue
        sparse = sparse_months(files, timeframe)
        usable = [m for m in months if m.key not in sparse]
        coverage[timeframe] = {
            "start_date": months[0].iso_start,
            "end_date": _last_bar_date(timeframe, months[-1], root)
            or months[-1].iso_start,
            "total_bars": sum(m.bars for m in months),
            "months": len(months),
            "years": sorted({m.year for m in months}),
            "available_months": [f"{m.year:04d}-{m.month:02d}" for m in months],
            "median_bars": int(_median([m.bars for m in months])),
            "usable_start_date": usable[0].iso_start if usable else None,
            "sparse_months": [f"{y:04d}-{m:02d}" for y, m in sorted(sparse)],
        }
    return coverage


_DENSITY_RATIO = 0.25


def _median(values: Sequence[int]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def sparse_months(
    files: Optional[dict[str, list[MonthFile]]] = None, timeframe: str = "H1"
) -> set[tuple[int, int]]:
    """Months whose bar count is under 25% of that timeframe's median month.

    A month at a quarter of the median is either a partially ingested month or a
    coarser timeframe stored under the wrong name — neither is a usable replay
    month, and both must be visible rather than silently averaged in.
    """
    files = files if files is not None else scan_timeframe_files()
    months = files.get(timeframe.upper()) or []
    if len(months) < 2:
        return set()
    threshold = _DENSITY_RATIO * _median([m.bars for m in months])
    return {m.key for m in months if m.bars < threshold}


def available_years(files: Optional[dict[str, list[MonthFile]]] = None) -> list[int]:
    files = files if files is not None else scan_timeframe_files()
    return sorted({m.year for months in files.values() for m in months})


def _coverage_hint(timeframe: str, cache_dir: Optional[Path] = None) -> str:
    """Human sentence describing what *is* available, for 404 messages."""
    coverage = timeframe_coverage(cache_dir=cache_dir)
    entry = coverage.get(timeframe)
    if not entry:
        have = ", ".join(coverage) or "tidak ada"
        return f"Timeframe {timeframe} belum punya data sama sekali (tersedia: {have})."
    return (
        f"Data {timeframe} tersedia {entry['start_date']} s/d {entry['end_date']} "
        f"({entry['total_bars']:,} bar dalam {entry['months']} bulan)."
    )


def resolve_period(
    timeframe: str,
    period_mode: str = "month",
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    cache_dir: Optional[Path] = None,
) -> list[MonthFile]:
    """Months of one timeframe that satisfy the requested period.

    Raises ``ReplaySessionError`` with a sentence the UI can show verbatim when
    the request cannot be honoured — never a bare 500.
    """
    timeframe = str(timeframe).upper()
    if timeframe not in TIMEFRAME_KINDS:
        raise ReplaySessionError(
            f"Timeframe tidak dikenal: {timeframe} "
            f"(pilihan: {', '.join(SUPPORTED_TIMEFRAMES)})"
        )
    if period_mode not in PERIOD_MODES:
        raise ReplaySessionError(
            f"period_mode tidak dikenal: {period_mode} "
            f"(pilihan: {', '.join(PERIOD_MODES)})"
        )

    files = scan_timeframe_files(cache_dir)
    available = files.get(timeframe) or []
    if not available:
        raise ReplaySessionError(_coverage_hint(timeframe, cache_dir))

    if period_mode == "month":
        if year is None or month is None:
            raise ReplaySessionError("Mode 'month' butuh year dan month.")
        picked = [m for m in available if m.key == (int(year), int(month))]
        if not picked:
            raise ReplaySessionError(
                f"Tidak ada data {timeframe} pada "
                f"{MONTH_NAMES_ID.get(int(month), month)} {int(year)}. "
                f"{_coverage_hint(timeframe, cache_dir)}"
            )
        return picked

    if period_mode == "year":
        if year is None:
            raise ReplaySessionError("Mode 'year' butuh year.")
        picked = [m for m in available if m.year == int(year)]
        if not picked:
            raise ReplaySessionError(
                f"Tidak ada data {timeframe} pada tahun {int(year)}. "
                f"{_coverage_hint(timeframe, cache_dir)}"
            )
        return picked

    if period_mode == "all":
        return list(available)

    if start_date is None or end_date is None:
        raise ReplaySessionError(f"Mode '{period_mode}' butuh start_date dan end_date.")
    if end_date < start_date:
        raise ReplaySessionError("end_date harus >= start_date")

    # A month belongs to the range iff its calendar span overlaps [start, end].
    picked = [
        m
        for m in available
        if date(m.year, m.month, 1) <= end_date and _month_end(m) >= start_date
    ]
    if not picked:
        raise ReplaySessionError(
            f"Rentang {start_date} s/d {end_date} tidak punya data {timeframe}. "
            f"{_coverage_hint(timeframe, cache_dir)}"
        )
    return picked


def _month_end(month: MonthFile) -> date:
    if month.month == 12:
        next_first = date(month.year + 1, 1, 1)
    else:
        next_first = date(month.year, month.month + 1, 1)
    return date.fromordinal(next_first.toordinal() - 1)


def period_label(
    period_mode: str,
    months: Sequence[MonthFile],
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> str:
    if period_mode == "month" and year is not None and month is not None:
        return f"{MONTH_NAMES_ID.get(int(month), month)} {int(year)}"
    if period_mode == "year" and year is not None:
        return f"Tahun {int(year)}"
    if period_mode in ("custom", "multi_month") and start_date and end_date:
        return f"{start_date} s/d {end_date}"
    first, last = months[0], months[-1]
    if (first.year, first.month) == (last.year, last.month):
        return first.label
    return f"{first.label} - {last.label}"


def load_candles(
    timeframe: str,
    months: Sequence[MonthFile],
    cache_dir: Optional[Path] = None,
) -> list[dict[str, Any]]:
    """OHLCV rows for the given months, source precision preserved.

    Unlike the legacy `_candle_rows`, prices are **not** rounded: tick-derived
    bars carry 3 decimals and rounding them would falsify the chart (see §3.3).
    """
    root = Path(cache_dir or CACHE_DIR)
    kind = TIMEFRAME_KINDS[timeframe.upper()]
    candles: list[dict[str, Any]] = []
    for month in months:
        path = _file_for(kind, month.year, month.month, root)
        frame = pl.read_parquet(path).sort("time")
        if "time" in frame.columns:
            epochs = [int(v) for v in frame["time"].to_list()]
        else:
            epochs = [
                int(v)
                for v in frame["timestamp"]
                .cast(pl.Datetime("ns"))
                .dt.epoch("s")
                .to_list()
            ]
        opens = [float(v) for v in frame["open"].to_list()]
        highs = [float(v) for v in frame["high"].to_list()]
        lows = [float(v) for v in frame["low"].to_list()]
        closes = [float(v) for v in frame["close"].to_list()]
        if "tick_volume" in frame.columns:
            volumes = [float(v) for v in frame["tick_volume"].to_list()]
        elif "volume" in frame.columns:
            volumes = [float(v) for v in frame["volume"].to_list()]
        else:
            volumes = [0.0] * frame.height
        candles.extend(
            {
                "time": epochs[i],
                "open": opens[i],
                "high": highs[i],
                "low": lows[i],
                "close": closes[i],
                "volume": volumes[i],
            }
            for i in range(len(epochs))
        )
    return candles


_PURE_LOCK = threading.Lock()
_PURE_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_PURE_ORDER: list[tuple[Any, ...]] = []
_PURE_MAX = 6


def clear_pure_cache() -> None:
    with _PURE_LOCK:
        _PURE_CACHE.clear()
        _PURE_ORDER.clear()


def _sparse_warnings(
    timeframe: str,
    months: Sequence[MonthFile],
    cache_dir: Optional[Path] = None,
) -> list[str]:
    """Non-blocking data-quality notes for the payload the browser just loaded."""
    files = scan_timeframe_files(cache_dir)
    sparse = sparse_months(files, timeframe)
    hit = [m for m in months if m.key in sparse]
    if not hit:
        return []
    coverage = timeframe_coverage(files, cache_dir).get(timeframe) or {}
    first = hit[0]
    usable = coverage.get("usable_start_date") or "sekarang"
    return [
        f"{first.label} hanya berisi {first.bars} bar {timeframe} "
        f"(bulan normal ~{coverage.get('median_bars', '?')} bar). "
        f"Data {timeframe} yang rapat baru tersedia sejak {usable}."
    ]


def generate_pure_payload(
    timeframe: str = "M5",
    period_mode: str = "month",
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    cache_dir: Optional[Path] = None,
) -> dict[str, Any]:
    """`{"meta": ..., "candles": [...]}` — nothing else (T-PAR-07)."""
    months = resolve_period(
        timeframe,
        period_mode,
        year=year,
        month=month,
        start_date=start_date,
        end_date=end_date,
        cache_dir=cache_dir,
    )
    timeframe = timeframe.upper()
    key = (
        timeframe,
        period_mode,
        year,
        month,
        str(start_date),
        str(end_date),
        tuple(m.key for m in months),
    )

    with _PURE_LOCK:
        cached = _PURE_CACHE.get(key)
        if cached is not None:
            return cached

    candles = load_candles(timeframe, months, cache_dir)

    # Custom ranges are day-granular: trim the partial months at both ends.
    # `tz="UTC"` matters: a bare date is midnight *naive*, and `.timestamp()`
    # would then read it in the machine's local zone and slide the window.
    if period_mode in ("custom", "multi_month") and start_date and end_date:
        lo = int(pd.Timestamp(start_date, tz="UTC").timestamp())
        hi = int(pd.Timestamp(end_date, tz="UTC").timestamp()) + 86_400
        candles = [c for c in candles if lo <= c["time"] < hi]

    if not candles:
        raise ReplaySessionError(
            f"Rentang {start_date} s/d {end_date} tidak berisi satu bar {timeframe} pun. "
            f"{_coverage_hint(timeframe, cache_dir)}"
        )

    meta = {
        "symbol": "XAUUSD",
        "timeframe": timeframe,
        "period_mode": period_mode,
        "period_label": period_label(
            period_mode,
            months,
            year=year,
            month=month,
            start_date=start_date,
            end_date=end_date,
        ),
        "start_date": _iso_utc(candles[0]["time"])[:10],
        "end_date": _iso_utc(candles[-1]["time"])[:10],
        "total_bars": len(candles),
        "first_bar_time": int(candles[0]["time"]),
        "last_bar_time": int(candles[-1]["time"]),
        "months_loaded": len(months),
        "warnings": _sparse_warnings(timeframe, months, cache_dir),
    }
    payload = {"meta": meta, "candles": candles}

    with _PURE_LOCK:
        _PURE_CACHE[key] = payload
        _PURE_ORDER.append(key)
        while len(_PURE_ORDER) > _PURE_MAX:
            stale = _PURE_ORDER.pop(0)
            _PURE_CACHE.pop(stale, None)
    logger.info(
        "pure replay payload built: %s %s (%d bars)",
        timeframe,
        period_mode,
        len(candles),
    )
    return payload
