"""Standalone Asian Close Range-Scaled Breakout Strategy (v2: HTF Structure Risk Scaling).

Purely isolated from other strategies.
Logic:
1. Track Asian Session High & Low during 23:00 - 06:59 UTC (06:00 - 13:59 WIB).
2. Track causal H1 EMA(50) & EMA(200) incrementally from completed H1 bars (zero lookahead).
3. After Asian close (07:00 - 15:59 UTC / 14:00 - 22:59 WIB):
   - Require valid Asian session (>= 1000 ticks) and Asian Range within [min_range, max_range].
   - On first breakout of Asian High + buffer (BUY) or Asian Low - buffer (SELL):
     - SL = 0.50 * Asian Range (structurally placed at Asian EQ / midpoint).
     - TP = 1.00 * Asian Range (2:1 Reward-to-Risk).
     - HTF Structure Risk Scaling:
       - Aligned with H1 EMA(50) vs EMA(200): aligned_risk_pct (default 1.25%).
       - Counter to H1 EMA(50) vs EMA(200): counter_risk_pct (default 0.35%).
   - Maximum 1 trade per trading day.
4. Close any open position at 20:55 UTC before rollover spread spike.
"""

from datetime import date, datetime, timedelta
from typing import Optional

from src.simulator.execution import OrderRequest
from src.strategies.base import BaseStrategy, TickEvent


class AsianCloseBreakoutStrategy(BaseStrategy):
    """Standalone Asian Session Close Breakout Strategy with HTF Structure Risk Scaling."""

    ASIAN_HOURS_UTC = {23, 0, 1, 2, 3, 4, 5, 6}

    def __init__(
        self,
        buffer_usd: float = 1.0,
        sl_range_mult: float = 0.50,
        tp_range_mult: Optional[float] = None,  # None means NO TP (session close exit)
        risk_per_trade_pct: float = 0.01,
        htf_filter_enabled: bool = True,
        aligned_risk_pct: float = 0.0125,
        counter_risk_pct: float = 0.0035,
        min_asian_range: float = 5.0,
        max_asian_range: float = 120.0,
        entry_start_hour_utc: int = 7,
        entry_end_hour_utc: int = 16,
        session_close_hour_utc: int = 20,
        session_close_minute_utc: int = 55,
        min_asian_ticks: int = 1000,
    ):
        super().__init__(name="AsianCloseBreakout")
        self.buffer_usd = buffer_usd
        self.sl_range_mult = sl_range_mult
        self.tp_range_mult = tp_range_mult
        self.risk_per_trade_pct = risk_per_trade_pct
        self.htf_filter_enabled = htf_filter_enabled
        self.aligned_risk_pct = aligned_risk_pct
        self.counter_risk_pct = counter_risk_pct
        self.min_asian_range = min_asian_range
        self.max_asian_range = max_asian_range
        self.entry_start_hour_utc = entry_start_hour_utc
        self.entry_end_hour_utc = entry_end_hour_utc
        self.session_close_hour_utc = session_close_hour_utc
        self.session_close_minute_utc = session_close_minute_utc
        self.min_asian_ticks = min_asian_ticks

        # Daily state
        self._current_trading_day: Optional[date] = None
        self._asian_high: Optional[float] = None
        self._asian_low: Optional[float] = None
        self._asian_ticks: int = 0
        self._traded_today: bool = False
        self._close_emitted_today: bool = False

        # Incremental H1 EMA(50) & EMA(200) state
        self._current_h1_bucket: Optional[datetime] = None
        self._current_h1_close: Optional[float] = None
        self._ema50: Optional[float] = None
        self._ema200: Optional[float] = None
        self._h1_bars_count: int = 0

    def seed_ema_state(self, ema50: Optional[float], ema200: Optional[float], h1_bars_count: int):
        """Carry over causal H1 EMA state across monthly runs."""
        self._ema50 = ema50
        self._ema200 = ema200
        self._h1_bars_count = h1_bars_count

    def get_ema_state(self) -> tuple[Optional[float], Optional[float], int]:
        return self._ema50, self._ema200, self._h1_bars_count

    def _update_h1_ema(self, ts: datetime, bid: float):
        bucket = ts.replace(minute=0, second=0, microsecond=0)
        if self._current_h1_bucket is None:
            self._current_h1_bucket = bucket
            self._current_h1_close = bid
            return
        if bucket != self._current_h1_bucket:
            # Finalize previous H1 bar
            c = self._current_h1_close
            if c is not None:
                a50 = 2.0 / 51.0
                a200 = 2.0 / 201.0
                self._ema50 = c if self._ema50 is None else (a50 * c + (1.0 - a50) * self._ema50)
                self._ema200 = c if self._ema200 is None else (a200 * c + (1.0 - a200) * self._ema200)
                self._h1_bars_count += 1
            self._current_h1_bucket = bucket
        self._current_h1_close = bid

    def _get_trading_day(self, tick: TickEvent) -> date:
        if tick.timestamp.hour >= 23:
            return (tick.timestamp + timedelta(hours=1)).date()
        return tick.timestamp.date()

    def _reset_day(self, trading_day: date):
        self._current_trading_day = trading_day
        self._asian_high = None
        self._asian_low = None
        self._asian_ticks = 0
        self._traded_today = False
        self._close_emitted_today = False

    def _get_trade_risk_pct(self, side: str) -> float:
        if not self.htf_filter_enabled or self._ema50 is None or self._ema200 is None or self._h1_bars_count < 50:
            return self.risk_per_trade_pct
        is_bull = self._ema50 > self._ema200
        aligned = (side == "BUY" and is_bull) or (side == "SELL" and not is_bull)
        return self.aligned_risk_pct if aligned else self.counter_risk_pct

    def _compute_lot_size(self, sl_dist: float, risk_pct: float) -> float:
        if self.portfolio is None or sl_dist <= 0 or risk_pct <= 0:
            return 0.0
        equity = max(self.portfolio.balance, 100.0)
        risk_usd = equity * risk_pct
        raw_lots = risk_usd / (sl_dist * 100.0)
        lots = round(raw_lots, 2)
        return max(0.01, min(5.00, lots))

    def on_tick(self, tick: TickEvent) -> Optional[OrderRequest]:
        self._update_h1_ema(tick.timestamp, tick.bid)

        t_day = self._get_trading_day(tick)
        if t_day != self._current_trading_day:
            self._reset_day(t_day)

        hour = tick.timestamp.hour
        minute = tick.timestamp.minute

        # 1. Accumulate Asian Session High / Low (23:00 - 06:59 UTC)
        if hour in self.ASIAN_HOURS_UTC:
            if self._asian_high is None or tick.bid > self._asian_high:
                self._asian_high = tick.bid
            if self._asian_low is None or tick.bid < self._asian_low:
                self._asian_low = tick.bid
            self._asian_ticks += 1
            return None

        # 2. Session Close Exit (No TP mode / Rollover Protect)
        if (hour > self.session_close_hour_utc or (hour == self.session_close_hour_utc and minute >= self.session_close_minute_utc)):
            if not self._close_emitted_today and self.portfolio and self.portfolio.open_positions:
                pos = next(iter(self.portfolio.open_positions.values()))
                self._close_emitted_today = True
                close_side = "SELL" if pos.side == "BUY" else "BUY"
                return OrderRequest(
                    order_type="CLOSE",
                    side=close_side,
                    volume=pos.volume,
                    signal_time=tick.timestamp,
                    target_position_id=pos.position_id,
                    reason="SESSION_CLOSE_EXIT",
                )
            return None

        # 3. Post-Asian Entry Window (07:00 - 15:59 UTC)
        if self._traded_today:
            return None
        if not (self.entry_start_hour_utc <= hour < self.entry_end_hour_utc):
            return None
        if self.portfolio and self.portfolio.open_positions:
            return None
        if self._asian_high is None or self._asian_low is None or self._asian_ticks < self.min_asian_ticks:
            return None

        asian_range = self._asian_high - self._asian_low
        if not (self.min_asian_range <= asian_range <= self.max_asian_range):
            return None

        sl_dist = self.sl_range_mult * asian_range
        tp_dist = (self.tp_range_mult * asian_range) if self.tp_range_mult is not None else None

        # BUY Breakout: bid crosses above Asian High + buffer
        if tick.bid >= self._asian_high + self.buffer_usd:
            self._traded_today = True
            rk = self._get_trade_risk_pct("BUY")
            lots = self._compute_lot_size(sl_dist, rk)
            if lots <= 0:
                return None
            tp_price = round(tick.ask + tp_dist, 3) if tp_dist is not None else None
            return OrderRequest(
                order_type="OPEN",
                side="BUY",
                volume=lots,
                signal_time=tick.timestamp,
                sl=round(tick.ask - sl_dist, 3),
                tp=tp_price,
                reason="ASIAN_HIGH_BREAKOUT",
            )

        # SELL Breakout: bid crosses below Asian Low - buffer
        if tick.bid <= self._asian_low - self.buffer_usd:
            self._traded_today = True
            rk = self._get_trade_risk_pct("SELL")
            lots = self._compute_lot_size(sl_dist, rk)
            if lots <= 0:
                return None
            tp_price = round(tick.bid - tp_dist, 3) if tp_dist is not None else None
            return OrderRequest(
                order_type="OPEN",
                side="SELL",
                volume=lots,
                signal_time=tick.timestamp,
                sl=round(tick.bid + sl_dist, 3),
                tp=tp_price,
                reason="ASIAN_LOW_BREAKOUT",
            )

        return None
