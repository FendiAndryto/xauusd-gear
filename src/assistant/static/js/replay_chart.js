/**
 * Pure Price Action Candlestick Renderer for TradingView Lightweight Charts (T-PAR-09).
 *
 * Exclusively renders candlesticks with 3-decimal precision for XAUUSD.
 * Viewport interaction:
 *  - When PLAYING: pins right edge to active bar (follow mode).
 *  - Zooming (barSpacing) does not break follow mode.
 *  - Dragging to past pauses follow mode and notifies listeners (floating button).
 *  - When PAUSED: user has free pan/zoom without forced movement.
 *  - Step forward/backward steps viewport precisely by one bar when following.
 */
(function (global) {
  'use strict';

  var THEME = {
    background: '#0b0f17',
    panel: '#131b2a',
    text: '#94a3b8',
    grid: 'rgba(30, 41, 59, 0.55)',
    border: '#1e293b',
    up: '#26a69a',
    down: '#ef5350',
    crosshair: '#38bdf8'
  };

  var DEFAULT_VISIBLE_BARS = 120;
  var RIGHT_OFFSET = 6;
  var MAX_INCREMENTAL_STEPS = 8;

  function toBar(candle) {
    return {
      time: candle.time,
      open: candle.open,
      high: candle.high,
      low: candle.low,
      close: candle.close
    };
  }

  function formatPrice(value) {
    return typeof value === 'number' && isFinite(value) ? value.toFixed(3) : '—';
  }

  function createChart(container, chartLib) {
    var lib = chartLib || global.LightweightCharts;
    var chart = lib.createChart(container, {
      layout: {
        background: { type: 'solid', color: THEME.background },
        textColor: THEME.text,
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
      },
      grid: {
        vertLines: { color: THEME.grid },
        horzLines: { color: THEME.grid }
      },
      rightPriceScale: {
        borderColor: THEME.border,
        scaleMargins: { top: 0.1, bottom: 0.1 }
      },
      timeScale: {
        borderColor: THEME.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: RIGHT_OFFSET,
        barSpacing: 7,
        shiftVisibleRangeOnNewBar: false
      },
      crosshair: {
        mode: lib.CrosshairMode ? lib.CrosshairMode.Normal : 0,
        vertLine: { color: THEME.crosshair, width: 1, style: 3, labelBackgroundColor: '#1d4ed8' },
        horzLine: { color: THEME.crosshair, width: 1, style: 3, labelBackgroundColor: '#1d4ed8' }
      },
      localization: { priceFormatter: formatPrice },
      handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true }
    });

    var candlesSeries = chart.addCandlestickSeries({
      upColor: THEME.up,
      downColor: THEME.down,
      borderUpColor: THEME.up,
      borderDownColor: THEME.down,
      wickUpColor: THEME.up,
      wickDownColor: THEME.down,
      priceFormat: { type: 'price', precision: 3, minMove: 0.001 },
      priceLineVisible: false,
      lastValueVisible: true
    });

    return { chart: chart, series: candlesSeries };
  }

  function init(options) {
    options = options || {};
    var container = options.container;
    if (!container) return null;

    var chartSetup = createChart(container, options.chartLib);
    var chart = chartSetup.chart;
    var series = chartSetup.series;

    var candles = [];
    var watermark = -1;
    var isFollowing = true;
    var isProgrammaticScroll = false;
    var lastVisibleSpan = DEFAULT_VISIBLE_BARS;
    var followChangeCallbacks = [];

    function emitFollowChange(following) {
      for (var i = 0; i < followChangeCallbacks.length; i += 1) {
        try {
          followChangeCallbacks[i](following);
        } catch (e) {
          if (global.console) global.console.error(e);
        }
      }
    }

    function setFollow(val) {
      var next = Boolean(val);
      if (isFollowing === next) return;
      isFollowing = next;
      emitFollowChange(isFollowing);
    }

    function snapToActive(animated) {
      if (watermark < 0) return;
      var span = lastVisibleSpan > 0 ? lastVisibleSpan : DEFAULT_VISIBLE_BARS;
      var targetTo = watermark + RIGHT_OFFSET;
      var targetFrom = targetTo - span;

      isProgrammaticScroll = true;
      try {
        chart.timeScale().setVisibleLogicalRange({ from: targetFrom, to: targetTo });
      } finally {
        setTimeout(function () {
          isProgrammaticScroll = false;
        }, 0);
      }
      setFollow(true);
    }

    // Subscribe to visible range changes to detect manual user pan vs zoom
    chart.timeScale().subscribeVisibleLogicalRangeChange(function (newRange) {
      if (!newRange) return;
      if (isProgrammaticScroll) return;

      var currentSpan = newRange.to - newRange.from;
      var spanDelta = Math.abs(currentSpan - lastVisibleSpan);

      if (spanDelta > 0.8) {
        // Zoom action: bar count / barSpacing changed, preserve follow state
        lastVisibleSpan = currentSpan;
        return;
      }

      // Pan action: span is virtually constant
      lastVisibleSpan = currentSpan;

      if (watermark >= 0) {
        var expectedTo = watermark + RIGHT_OFFSET;
        if (expectedTo - newRange.to > 2.5) {
          // User dragged backward to inspect past bars
          setFollow(false);
        } else if (newRange.to >= expectedTo - 0.5) {
          // User dragged back to latest bars
          setFollow(true);
        }
      }
    });

    function keepViewportAtEdge() {
      if (!isFollowing || watermark < 0) return;
      var span = lastVisibleSpan > 0 ? lastVisibleSpan : DEFAULT_VISIBLE_BARS;
      var targetTo = watermark + RIGHT_OFFSET;
      var targetFrom = targetTo - span;

      isProgrammaticScroll = true;
      try {
        chart.timeScale().setVisibleLogicalRange({ from: targetFrom, to: targetTo });
      } finally {
        setTimeout(function () {
          isProgrammaticScroll = false;
        }, 0);
      }
    }

    function setData(candlesList) {
      candles = (candlesList || []).slice();
      watermark = -1;
      isFollowing = true;
      series.setData([]);
      emitFollowChange(true);
    }

    function seekTo(target, cfg) {
      cfg = cfg || {};
      if (!candles.length) return -1;
      target = Math.max(0, Math.min(target | 0, candles.length - 1));

      if (target === watermark && !cfg.force) return watermark;

      if (watermark >= 0 && target > watermark) {
        var steps = target - watermark;
        if (steps <= MAX_INCREMENTAL_STEPS) {
          for (var i = watermark + 1; i <= target; i += 1) {
            series.update(toBar(candles[i]));
          }
        } else {
          series.setData(candles.slice(0, target + 1).map(toBar));
        }
      } else {
        // Backward move or first paint
        series.setData(candles.slice(0, target + 1).map(toBar));
      }

      var advanced = target !== watermark;
      watermark = target;

      if (advanced && isFollowing && cfg.follow !== false) {
        keepViewportAtEdge();
      }
      return watermark;
    }

    function appendBar(index) {
      return seekTo(index == null ? watermark + 1 : index, { follow: isFollowing });
    }

    function resize() {
      var width = container.clientWidth || container.offsetWidth || 0;
      var height = container.clientHeight || container.offsetHeight || 0;
      if (width > 0 && height > 0) {
        chart.applyOptions({ width: width, height: height });
      }
    }

    if (global.ResizeObserver) {
      var observer = new global.ResizeObserver(resize);
      observer.observe(container);
    } else {
      global.addEventListener('resize', resize);
    }
    resize();

    return {
      chart: chart,
      series: series,
      setData: setData,
      seekTo: seekTo,
      appendBar: appendBar,
      resize: resize,
      fitAll: function () {
        if (watermark >= 0) chart.timeScale().fitContent();
      },
      snapToActive: snapToActive,
      setFollow: setFollow,
      isFollowing: function () { return isFollowing; },
      onFollowChange: function (fn) {
        if (typeof fn === 'function') followChangeCallbacks.push(fn);
      },
      getWatermark: function () { return watermark; },
      getVisibleBars: function () { return watermark < 0 ? 0 : watermark + 1; },
      timeScale: function () { return chart.timeScale(); }
    };
  }

  global.SmcReplayChart = {
    init: init,
    THEME: THEME,
    VISIBLE_BARS: DEFAULT_VISIBLE_BARS
  };
})(window);
