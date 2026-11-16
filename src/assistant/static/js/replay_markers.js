/**
 * Dynamic entry/exit markers + active trade price lines (tickets T-REP-05, T-REP-06).
 *
 * Two responsibilities, both strictly a function of the replay watermark:
 *
 *   1. **Markers** — a green `arrowUp` under the entry candle for BUY (red
 *      `arrowDown` above for SELL), and a `circle`/`cross` at the exit candle
 *      labelled `TP HIT +$x` / `SL HIT -$y` / `EXPIRED ±$z`. Only markers whose
 *      bar has already been replayed are pushed to the series, so the history is
 *      identical whether the user played forward or scrubbed backwards.
 *
 *   2. **Active price lines** — while a trade is open at the watermark: entry
 *      (blue, solid), TP (green, dashed) and SL (red, dashed). They are removed
 *      the moment the trade closes, exactly as specified.
 */
(function (global) {
  'use strict';

  var COLORS = {
    buy: '#26a69a',
    sell: '#ef5350',
    entry: '#38bdf8',
    tp: '#34d399',
    sl: '#f87171',
    exitWin: '#34d399',
    exitLoss: '#ef5350',
    exitNeutral: '#fbbf24',
    text: '#0b0f17'
  };

  function money(value) {
    var abs = Math.abs(value);
    var sign = value < 0 ? '-' : '+';
    return sign + '$' + abs.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }

  function compact(value) {
    return Math.abs(value) >= 1000
      ? (value < 0 ? '-' : '') + (Math.abs(value) / 1000).toFixed(2) + 'k'
      : (value < 0 ? '-' : '') + Math.abs(value).toFixed(0);
  }

  /** One marker per trade, for the bars already shown. */
  function buildMarkers(trades, watermark) {
    var markers = [];
    for (var i = 0; i < trades.length; i += 1) {
      var trade = trades[i];
      if (trade.entryIdx > watermark) break; // trades are sorted by entry index

      var isBuy = trade.side === 'BUY';
      markers.push({
        time: trade.entry_time,
        position: isBuy ? 'belowBar' : 'aboveBar',
        color: isBuy ? COLORS.buy : COLORS.sell,
        shape: isBuy ? 'arrowUp' : 'arrowDown',
        text: (isBuy ? 'BUY ' : 'SELL ') + trade.lot.toFixed(2) + ' @ ' +
          trade.entry_price.toFixed(2),
        size: 1
      });

      if (trade.exitIdx > watermark) continue;

      var win = trade.outcome === 'WIN';
      var loss = trade.outcome === 'LOSS';
      var label;
      if (win) label = 'TP HIT ' + money(trade.pnl);
      else if (loss) label = 'SL HIT ' + money(trade.pnl);
      else label = 'EXPIRED ' + money(trade.pnl);

      markers.push({
        time: trade.exit_time,
        position: win ? 'aboveBar' : (loss ? 'belowBar' : 'aboveBar'),
        color: win ? COLORS.exitWin : (loss ? COLORS.exitLoss : COLORS.exitNeutral),
        shape: win ? 'circle' : 'cross',
        text: label,
        size: 1
      });
    }
    return markers;
  }

  /**
   * @param {object} series  candlestick series (markers + price lines owner)
   * @param {object} api     optional { series } accessor override
   */
  function init(series) {
    if (!series) return null;

    var activeLines = [];
    var activeTradeId = null;
    var markerCount = 0;

    function clearLines() {
      for (var i = 0; i < activeLines.length; i += 1) {
        try {
          series.removePriceLine(activeLines[i]);
        } catch (err) {
          /* already detached by setData/setMarkers */
        }
      }
      activeLines = [];
      activeTradeId = null;
    }

    function addLine(price, color, title, style) {
      if (typeof price !== 'number' || !isFinite(price)) return;
      activeLines.push(series.createPriceLine({
        price: price,
        color: color,
        lineWidth: 2,
        lineStyle: style,
        axisLabelVisible: true,
        title: title
      }));
    }

    /**
     * Paint the whole visual state for one replay snapshot.
     * Idempotent: calling it twice with the same snapshot is a no-op.
     *
     * @param {object} snapshot derived replay state (index, active, ...)
     * @param {Array}  trades   full trade list from the controller
     */
    function render(snapshot, trades) {
      if (!snapshot) return;

      // --- markers -------------------------------------------------------
      var markers = buildMarkers(trades || [], snapshot.index);
      series.setMarkers(markers);
      markerCount = markers.length;

      // --- active price lines -------------------------------------------
      var active = snapshot.active || [];
      if (!active.length) {
        if (activeTradeId !== null) clearLines();
        return;
      }

      var primary = active[0];
      if (activeTradeId === primary.trade.trade_id && activeLines.length === 3) {
        // Same trade still open: nothing to rebuild.
        return;
      }

      clearLines();
      var trade = primary.trade;
      addLine(trade.entry_price, COLORS.entry, 'ENTRY ' + trade.entry_price.toFixed(2), 0);
      addLine(trade.tp_price, COLORS.tp, 'TP ' + trade.tp_price.toFixed(2), 2);
      addLine(trade.sl_price, COLORS.sl, 'SL ' + trade.sl_price.toFixed(2), 2);
      activeTradeId = trade.trade_id;
    }

    return {
      render: render,
      getMarkerCount: function () { return markerCount; },
      getActiveLineCount: function () { return activeLines.length; },
      getActiveTradeId: function () { return activeTradeId; },
      clear: function () {
        clearLines();
        series.setMarkers([]);
        markerCount = 0;
      },
      buildMarkers: buildMarkers,
      money: money,
      compact: compact
    };
  }

  global.SmcReplayMarkers = {
    init: init,
    buildMarkers: buildMarkers,
    money: money,
    compact: compact,
    COLORS: COLORS
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = global.SmcReplayMarkers;
})(typeof window !== 'undefined' ? window : globalThis);
