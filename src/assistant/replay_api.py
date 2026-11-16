"""FastAPI routes for the visual backtest replay engine (ticket T-REP-02).

Two endpoints, both pure reads over the parquet bar cache:

* ``GET /api/replay/sessions`` — catalogue for the picker (parquet metadata only).
* ``GET /api/replay/data``     — the whole replay payload in one response.

Endpoints are declared with ``def`` (not ``async def``) on purpose: building a
100k-bar payload is CPU-bound, and FastAPI runs sync handlers in its threadpool
so the MT5 polling loop and the WebSocket broadcaster are never starved.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from src.assistant import replay_engine
from src.assistant.replay_engine import (
    DEFAULT_RR,
    STRATEGIES,
    ReplaySession,
    ReplaySessionError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/replay", tags=["replay"])


def _parse_date(value: Optional[str], field: str) -> Optional[date]:
    if value is None or value == "":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"{field} harus berformat YYYY-MM-DD"
        ) from exc


def _custom_session(
    start: date, end: date, cache_dir: Optional[str] = None
) -> ReplaySession:
    """Session spanning every cached month inside [start, end] with one timeframe."""
    if end < start:
        raise HTTPException(status_code=400, detail="end_date harus >= start_date")
    months = [
        m
        for m in replay_engine.scan_months(cache_dir)
        if start <= date(m.year, m.month, 1) <= end
    ]
    if not months:
        raise HTTPException(
            status_code=404,
            detail="Tidak ada cache bar pada rentang tanggal tersebut.",
        )
    timeframe = months[-1].ltf
    months = [m for m in months if m.ltf == timeframe]
    first, last = months[0], months[-1]
    return ReplaySession(
        id=f"custom_{first.year}_{first.month:02d}_{last.year}_{last.month:02d}",
        name=f"Rentang kustom {first.label} - {last.label} ({timeframe})",
        timeframe=first.ltf,
        macro_timeframe=first.htf,
        months=tuple(months),
    )


@router.get("/sessions")
def replay_sessions() -> dict[str, Any]:
    """Replay catalogue: legacy session presets + real per-timeframe coverage.

    The legacy keys (`sessions`, `default_session_id`, `strategies`, `rr_presets`)
    feed the benchmark-parity picker. The T-PAR-06 keys (`available_years`,
    `timeframe_coverage`, `default_selection`) feed the pure price action period
    selector, and are derived from parquet footers only.
    """
    try:
        catalogue = replay_engine.list_replay_sessions()
        files = replay_engine.scan_timeframe_files()
        coverage = replay_engine.timeframe_coverage(files)
        catalogue.update(
            {
                "available_years": replay_engine.available_years(files),
                "timeframe_coverage": coverage,
                "timeframes": list(coverage),
                "period_modes": list(replay_engine.PERIOD_MODES),
                "default_selection": _default_selection(files, coverage),
            }
        )
        return catalogue
    except Exception:  # cache dir missing / unreadable parquet
        logger.exception("replay session catalogue failed")
        raise HTTPException(status_code=500, detail="Gagal memindai cache bar.")


def _default_selection(
    files: dict[str, list[Any]], coverage: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Newest *usable* month of the richest timeframe.

    Two things are skipped on purpose: sparse months (a partially ingested month,
    or daily candles stored under an ``h1_*`` name) and the newest month in
    general, because it is usually still being written by the ingestion job.
    """
    for timeframe in ("M5", "M15", "H1", "M1"):
        months = files.get(timeframe) or []
        if not months:
            continue
        sparse = replay_engine.sparse_months(files, timeframe)
        usable = [m for m in months if m.key not in sparse]
        if not usable:
            continue
        chosen = usable[-1]
        return {
            "period_mode": "month",
            "year": chosen.year,
            "month": chosen.month,
            "timeframe": timeframe,
        }
    return {"period_mode": "month", "year": None, "month": None, "timeframe": "M5"}


@router.get("/data")
def replay_data(
    session_id: Optional[str] = Query(default=None),
    strategy: str = Query(default="mode_a_pure"),
    rr_ratio: float = Query(default=DEFAULT_RR),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    period_mode: Optional[str] = Query(default=None),
    timeframe: Optional[str] = Query(default=None),
    year: Optional[int] = Query(default=None),
    month: Optional[int] = Query(default=None),
) -> dict[str, Any]:
    """Replay payload, in one of two shapes.

    * **Pure price action** (``period_mode`` supplied): ``{"meta", "candles"}``
      only — no trades, no zones, no equity curve. This is the shape the
      dedicated workstation consumes (T-PAR-07).
    * **Legacy session** (no ``period_mode``): the full benchmark payload with
      trades/zones/equity, kept until the parity picker is retired.
    """
    if period_mode is not None:
        return _pure_data(
            timeframe or "M5",
            period_mode,
            year=year,
            month=month,
            start_date=_parse_date(start_date, "start_date"),
            end_date=_parse_date(end_date, "end_date"),
        )

    if strategy not in STRATEGIES:
        raise HTTPException(
            status_code=400,
            detail=f"strategi tidak dikenal: {strategy} "
            f"(pilihan: {', '.join(STRATEGIES)})",
        )
    if not (0.5 <= float(rr_ratio) <= 5.0):
        raise HTTPException(status_code=400, detail="rr_ratio harus 0.5 - 5.0")

    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")

    try:
        if start is not None and end is not None:
            session = _custom_session(start, end)
            session_id = session.id
            # Materialise the ad-hoc range through the same cached builder.
            payload = replay_engine.generate_replay_session(
                session.id,
                strategy=strategy,
                rr_ratio=rr_ratio,
                session=session,
            )
        else:
            if not session_id:
                catalogue = replay_engine.list_replay_sessions()
                session_id = catalogue.get("default_session_id")
                if not session_id:
                    raise HTTPException(
                        status_code=404, detail="Belum ada cache bar untuk replay."
                    )
            payload = replay_engine.generate_replay_session(
                session_id, strategy=strategy, rr_ratio=rr_ratio
            )
    except ReplaySessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception:
        logger.exception("replay payload build failed (session=%s)", session_id)
        raise HTTPException(status_code=500, detail="Gagal menyiapkan data replay.")

    return payload


def _pure_data(
    timeframe: str,
    period_mode: str,
    *,
    year: Optional[int],
    month: Optional[int],
    start_date: Optional[date],
    end_date: Optional[date],
) -> dict[str, Any]:
    """Candles-only payload (T-PAR-07)."""
    try:
        return replay_engine.generate_pure_payload(
            timeframe,
            period_mode,
            year=year,
            month=month,
            start_date=start_date,
            end_date=end_date,
        )
    except ReplaySessionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        logger.exception(
            "pure replay payload failed (timeframe=%s period=%s)",
            timeframe,
            period_mode,
        )
        raise HTTPException(status_code=500, detail="Gagal menyiapkan data replay.")


# The picker's selectors are pure reads over parquet footers; keep them warm so a
# page load never pays the 0.5 s footer scan twice.
@router.get("/coverage")
def replay_coverage() -> dict[str, Any]:
    """Availability only — cheap enough for a selector to poll."""
    try:
        files = replay_engine.scan_timeframe_files()
        coverage = replay_engine.timeframe_coverage(files)
        return {
            "available_years": replay_engine.available_years(files),
            "timeframe_coverage": coverage,
            "timeframes": list(coverage),
            "period_modes": list(replay_engine.PERIOD_MODES),
            "default_selection": _default_selection(files, coverage),
        }
    except Exception:
        logger.exception("replay coverage failed")
        raise HTTPException(status_code=500, detail="Gagal memindai cache bar.")
