/**
 * Pure Price Action Replay Terminal (Tickets T-PAR-08, T-PAR-09, T-PAR-10).
 *
 * Replaces old benchmark/equity/trade architecture with a pure price action
 * workstation:
 *  - Dynamic period mode & timeframe selector backed by /api/replay/coverage
 *  - Responsive candlestick-only viewport with smart follow & snap
 *  - Floating HUD with UTC/Local time, OHLC & range
 *  - Transport controls & full-featured scrubber with datetime tooltip
 *  - Seamless native Fullscreen (F / Esc)
 */
(function (global) {
  'use strict';

  var FETCH_TIMEOUT_MS = 120000;
  var MAX_SAFE_BARS = 120000;

  var MONTH_NAMES = [
    'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
    'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember'
  ];

  var el = {};
  var controller = null;
  var chartApi = null;
  var canvasApi = null;
  var drawingsApi = null;
  var simulatorApi = null;
  var currentTool = 'cursor';
  var coverage = null;
  var currentPayload = null;
  var loading = false;
  var loadToken = 0;
  var mounted = false;

  var selectedMode = 'month';
  var selectedYear = 2026;
  var selectedMonth = 10;
  var selectedStartDate = '2026-10-01';
  var selectedEndDate = '2026-10-30';
  var selectedTimeframe = 'M5';

  // ------------------------------------------------------------------ helpers

  function $(id) {
    return document.getElementById(id);
  }

  function setText(node, text) {
    if (node && node.textContent !== text) node.textContent = text;
  }

  function show(node, visible) {
    if (!node) return;
    node.classList.toggle('hidden', !visible);
  }

  function pad(n) {
    return n < 10 ? '0' + n : '' + n;
  }

  function formatPrice(val) {
    return typeof val === 'number' && isFinite(val) ? val.toFixed(3) : '—';
  }

  function formatUtc(seconds) {
    if (typeof seconds !== 'number' || !isFinite(seconds)) return '—';
    var d = new Date(seconds * 1000);
    return d.getUTCFullYear() + '-' + pad(d.getUTCMonth() + 1) + '-' + pad(d.getUTCDate()) +
      ' ' + pad(d.getUTCHours()) + ':' + pad(d.getUTCMinutes()) + ' UTC';
  }

  function formatLocal(seconds) {
    if (typeof seconds !== 'number' || !isFinite(seconds)) return '—';
    var d = new Date(seconds * 1000);
    var tz = 'Lokal';
    try {
      var parts = new Intl.DateTimeFormat('id-ID', { timeZoneName: 'short' }).formatToParts(d);
      for (var i = 0; i < parts.length; i += 1) {
        if (parts[i].type === 'timeZoneName') { tz = parts[i].value; break; }
      }
    } catch (e) {}
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()) + ' ' + tz;
  }

  function isTypingTarget(target) {
    if (!target) return false;
    var tag = (target.tagName || '').toLowerCase();
    return tag === 'input' || tag === 'select' || tag === 'textarea' || target.isContentEditable === true;
  }

  function fetchJson(url) {
    var controllerAbort = typeof global.AbortController === 'function' ? new global.AbortController() : null;
    var timer = global.setTimeout(function () {
      if (controllerAbort) controllerAbort.abort();
    }, FETCH_TIMEOUT_MS);

    return fetch(url, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal: controllerAbort ? controllerAbort.signal : undefined
    }).then(function (res) {
      global.clearTimeout(timer);
      if (!res.ok) {
        return res.json().catch(function () { return {}; }).then(function (body) {
          throw new Error(body.detail || ('HTTP ' + res.status));
        });
      }
      return res.json();
    }).catch(function (err) {
      global.clearTimeout(timer);
      throw err;
    });
  }

  // ------------------------------------------------------------- selector logic

  function isTfAvailable(tf) {
    if (!coverage || !coverage.timeframe_coverage) return false;
    var cov = coverage.timeframe_coverage[tf];
    if (!cov) return false;

    if (selectedMode === 'month') {
      var key = selectedYear + '-' + pad(selectedMonth);
      return Array.isArray(cov.available_months) && cov.available_months.indexOf(key) >= 0;
    }

    if (selectedMode === 'year') {
      return Array.isArray(cov.years) && cov.years.indexOf(Number(selectedYear)) >= 0;
    }

    if (selectedMode === 'multi_month' || selectedMode === 'custom') {
      var start = el.dateStart ? el.dateStart.value : selectedStartDate;
      var end = el.dateEnd ? el.dateEnd.value : selectedEndDate;
      if (!start || !end) return true;
      return start <= cov.end_date && end >= cov.start_date;
    }

    if (selectedMode === 'all') {
      return (cov.total_bars || 0) <= MAX_SAFE_BARS;
    }

    return true; // mode 'all'
  }

  function updateTimeframePills() {
    if (!el.timeframes) return;
    var pills = el.timeframes.querySelectorAll('button[data-tf]');
    var currentValid = false;
    var firstValid = null;

    for (var i = 0; i < pills.length; i += 1) {
      var btn = pills[i];
      var tf = btn.getAttribute('data-tf');
      var ok = isTfAvailable(tf);
      var cov = coverage && coverage.timeframe_coverage && coverage.timeframe_coverage[tf];

      btn.disabled = !ok;
      btn.classList.toggle('is-disabled', !ok);
      if (!ok && selectedMode === 'all' && cov && (cov.total_bars || 0) > MAX_SAFE_BARS) {
        btn.title = tf + ' dinonaktifkan: ' + cov.total_bars.toLocaleString('id-ID') +
          ' lilin melebihi batas aman (maks 120.000). Gunakan mode Per Bulan.';
      } else if (!ok) {
        btn.title = 'Data ' + tf + ' tidak tersedia untuk periode terpilih.';
      } else {
        btn.title = tf;
      }

      var isSelected = (tf === selectedTimeframe && ok);
      btn.classList.toggle('is-active', isSelected);
      btn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');

      if (isSelected) currentValid = true;
      if (ok && !firstValid) firstValid = tf;
    }

    // Auto-switch to first available timeframe if current selection was invalidated
    if (!currentValid && firstValid) {
      selectedTimeframe = firstValid;
      for (var j = 0; j < pills.length; j += 1) {
        var b = pills[j];
        var isNow = b.getAttribute('data-tf') === selectedTimeframe;
        b.classList.toggle('is-active', isNow);
        b.setAttribute('aria-pressed', isNow ? 'true' : 'false');
      }
    }
  }

  function setMode(mode) {
    selectedMode = mode;
    if (el.modeToggle) {
      var buttons = el.modeToggle.querySelectorAll('button[data-mode]');
      for (var i = 0; i < buttons.length; i += 1) {
        var b = buttons[i];
        var active = b.getAttribute('data-mode') === mode;
        b.classList.toggle('is-active', active);
        b.setAttribute('aria-pressed', active ? 'true' : 'false');
      }
    }

    // Adjust visibility of period inputs
    if (mode === 'month') {
      show(el.yearWrap, true);
      show(el.monthWrap, true);
      show(el.dateStartWrap, false);
      show(el.dateEndWrap, false);
    } else if (mode === 'year') {
      show(el.yearWrap, true);
      show(el.monthWrap, false);
      show(el.dateStartWrap, false);
      show(el.dateEndWrap, false);
    } else if (mode === 'multi_month' || mode === 'custom') {
      show(el.yearWrap, false);
      show(el.monthWrap, false);
      show(el.dateStartWrap, true);
      show(el.dateEndWrap, true);
    } else { // 'all'
      show(el.yearWrap, false);
      show(el.monthWrap, false);
      show(el.dateStartWrap, false);
      show(el.dateEndWrap, false);
    }

    updateTimeframePills();
  }

  function populateSelectors() {
    if (!coverage) return;

    // Years
    if (el.year) {
      el.year.innerHTML = '';
      var years = coverage.available_years || [];
      for (var y = 0; y < years.length; y += 1) {
        var optY = document.createElement('option');
        optY.value = String(years[y]);
        optY.textContent = String(years[y]);
        el.year.appendChild(optY);
      }
      el.year.value = String(selectedYear);
    }

    // Months
    if (el.month) {
      el.month.innerHTML = '';
      for (var m = 1; m <= 12; m += 1) {
        var optM = document.createElement('option');
        optM.value = String(m);
        optM.textContent = MONTH_NAMES[m - 1];
        el.month.appendChild(optM);
      }
      el.month.value = String(selectedMonth);
    }

    // Date inputs
    if (el.dateStart && selectedStartDate) el.dateStart.value = selectedStartDate;
    if (el.dateEnd && selectedEndDate) el.dateEnd.value = selectedEndDate;

    // Timeframes
    if (el.timeframes) {
      el.timeframes.innerHTML = '';
      var tfs = coverage.timeframes || [];
      for (var t = 0; t < tfs.length; t += 1) {
        var pill = document.createElement('button');
        pill.type = 'button';
        pill.className = 'replay-pill replay-tf-pill';
        pill.setAttribute('data-tf', tfs[t]);
        pill.textContent = tfs[t];
        el.timeframes.appendChild(pill);
      }
    }

    setMode(selectedMode);
  }

  // ------------------------------------------------------------- data loading

  function buildDataUrl() {
    var url = '/api/replay/data?period_mode=' + encodeURIComponent(selectedMode) +
      '&timeframe=' + encodeURIComponent(selectedTimeframe);

    if (selectedMode === 'month') {
      url += '&year=' + encodeURIComponent(selectedYear) +
        '&month=' + encodeURIComponent(selectedMonth);
    } else if (selectedMode === 'year') {
      url += '&year=' + encodeURIComponent(selectedYear);
    } else if (selectedMode === 'multi_month' || selectedMode === 'custom') {
      var s = el.dateStart ? el.dateStart.value : selectedStartDate;
      var e = el.dateEnd ? el.dateEnd.value : selectedEndDate;
      url += '&start_date=' + encodeURIComponent(s) +
        '&end_date=' + encodeURIComponent(e);
    }
    return url;
  }

  function setStatus(message, kind) {
    if (!el.status) return;
    el.status.textContent = message || '';
    el.status.className = 'replay-status' + (kind ? ' is-' + kind : '');
  }

  function loadData() {
    if (selectedMode === 'all' && selectedTimeframe === 'M1') {
      var warnMsg = 'Timeframe M1 pada mode Semua Data berisi 301.877 lilin (~30 MB). Untuk mencegah tab hang, silakan pilih mode Per Bulan atau Rentang Bulan (maksimal 120.000 lilin).';
      if (el.errorText) el.errorText.textContent = warnMsg;
      show(el.errorBanner, true);
      setStatus(warnMsg, 'error');
      return Promise.resolve();
    }

    var token = ++loadToken;
    loading = true;

    if (el.btnLoad) {
      el.btnLoad.disabled = true;
      el.btnLoad.textContent = 'Memuat…';
    }
    show(el.errorBanner, false);
    setStatus('Memuat data replay…', 'loading');

    var url = buildDataUrl();

    return fetchJson(url).then(function (payload) {
      if (token !== loadToken) return;
      currentPayload = payload;
      mountPayload(payload);

      if (el.btnLoad) {
        el.btnLoad.disabled = false;
        el.btnLoad.textContent = 'Muat Replay';
      }
      loading = false;
      var count = (payload.meta && payload.meta.total_bars) || (payload.candles && payload.candles.length) || 0;
      var label = (payload.meta && payload.meta.period_label) || '';
      setStatus('Siap. ' + count.toLocaleString('id-ID') + ' lilin ' +
        payload.meta.timeframe + ' termuat (' + label + ').', 'ready');
    }).catch(function (err) {
      if (token !== loadToken) return;
      loading = false;
      if (el.btnLoad) {
        el.btnLoad.disabled = false;
        el.btnLoad.textContent = 'Muat Replay';
      }
      var msg = (err && err.message) ? err.message : String(err);
      if (el.errorText) el.errorText.textContent = msg;
      show(el.errorBanner, true);
      setStatus('Gagal memuat: ' + msg, 'error');
    });
  }

  function loadCoverage() {
    return fetchJson('/api/replay/coverage').then(function (cov) {
      coverage = cov;
      var def = cov.default_selection || {};
      if (def.period_mode) selectedMode = def.period_mode;
      if (def.year) selectedYear = def.year;
      if (def.month) selectedMonth = def.month;
      if (def.timeframe) selectedTimeframe = def.timeframe;

      var m5Cov = cov.timeframe_coverage && cov.timeframe_coverage.M5;
      if (m5Cov) {
        selectedStartDate = m5Cov.usable_start_date || m5Cov.start_date || '2026-10-01';
        selectedEndDate = m5Cov.end_date || '2026-10-30';
      }

      populateSelectors();
      return loadData();
    }).catch(function (err) {
      setStatus('Gagal memuat cakupan data: ' + (err && err.message ? err.message : err), 'error');
    });
  }

  // ------------------------------------------------------------- chart & HUD

  function syncStorage() {
    if (!global.SmcReplayStorage || !currentPayload) return;
    var meta = currentPayload.meta || {};
    var yr = meta.year || selectedYear;
    var mo = meta.month || selectedMonth;
    var sym = meta.symbol || 'XAUUSD';

    if (drawingsApi) {
      global.SmcReplayStorage.saveDrawings(sym, yr, mo, drawingsApi.getDrawings());
    }
    if (simulatorApi) {
      global.SmcReplayStorage.savePositions(sym, yr, mo, simulatorApi.getPositions());
      var ledger = simulatorApi.getLedger();
      if (ledger) {
        global.SmcReplayStorage.saveLedger(sym, yr, mo, ledger.getSummary());
      }
    }
  }

  function ensureChart() {
    if (chartApi || !el.chartContainer) return chartApi;
    if (!global.SmcReplayChart) return null;

    chartApi = global.SmcReplayChart.init({ container: el.chartContainer });
    if (!chartApi) {
      setStatus('Library chart gagal dimuat.', 'error');
      return null;
    }

    if (global.SmcReplayCanvas && el.canvas && !canvasApi) {
      canvasApi = global.SmcReplayCanvas.init({
        canvas: el.canvas,
        chartApi: chartApi,
        container: el.chartContainer,
        activeTool: currentTool
      });
    }

    if (global.SmcReplayDrawings && canvasApi && !drawingsApi) {
      drawingsApi = global.SmcReplayDrawings.init({
        canvasApi: canvasApi,
        chartApi: chartApi,
        getCandles: function () {
          return (currentPayload && currentPayload.candles) || [];
        },
        onCommit: function (item) {
          selectTool('cursor');
          syncStorage();
        },
        onChange: function () {
          syncStorage();
        }
      });
    }

    if (global.SmcReplaySimulator && canvasApi && !simulatorApi) {
      simulatorApi = global.SmcReplaySimulator.init({
        canvasApi: canvasApi,
        chartApi: chartApi,
        getCandles: function () {
          return (currentPayload && currentPayload.candles) || [];
        },
        getCurrentBar: function () {
          if (!controller) return null;
          var snap = controller.snapshot();
          if (!snap || !snap.candle) return null;
          var bar = snap.candle;
          if (bar.index != null) return bar;
          return {
            index: snap.index,
            time: bar.time,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
            volume: bar.volume
          };
        },
        onCommit: function (item) {
          selectTool('cursor');
          syncStorage();
        },
        onChange: function () {
          syncStorage();
        }
      });
    }

    // When chart follow state changes, update floating button visibility
    chartApi.onFollowChange(function (following) {
      updateFollowButton(following);
    });

    return chartApi;
  }

  function updateFollowButton(following) {
    if (!el.btnFollow || !controller) return;
    var isPlaying = controller.snapshot().state === 'PLAYING';
    show(el.btnFollow, isPlaying && !following);
  }

  function mountPayload(payload) {
    var api = ensureChart();
    if (!api) return;

    show(el.chartEmpty, false);

    // Warnings banner
    var warnings = (payload.meta && payload.meta.warnings) || [];
    if (warnings.length > 0) {
      if (el.warningsText) el.warningsText.textContent = warnings.join(' · ');
      show(el.warningsBanner, true);
    } else {
      show(el.warningsBanner, false);
    }

    // Restore persisted state for this symbol/month BEFORE the controller
    // publishes its first frame. Otherwise a month switch would evaluate the
    // previous month's positions against the new month's first candle.
    if (global.SmcReplayStorage) {
      var meta = payload.meta || {};
      var yr = meta.year || selectedYear;
      var mo = meta.month || selectedMonth;
      var sym = meta.symbol || 'XAUUSD';

      if (drawingsApi && drawingsApi.setDrawings) {
        var savedDrawings = global.SmcReplayStorage.loadDrawings(sym, yr, mo);
        drawingsApi.setDrawings(savedDrawings || []);
      }
      if (simulatorApi && simulatorApi.setPositions) {
        var savedPositions = global.SmcReplayStorage.loadPositions(sym, yr, mo);
        simulatorApi.setPositions(savedPositions || []);
      }
      if (simulatorApi && simulatorApi.restoreLedger) {
        simulatorApi.restoreLedger(global.SmcReplayStorage.loadLedger(sym, yr, mo));
      }
    }

    controller.load(payload);
    api.setData(payload.candles);

    renderScrubberLimits(payload.candles);
    render(controller.snapshot());
    api.snapToActive();
    api.resize();
  }

  function renderScrubberLimits(candles) {
    if (!el.scrubber) return;
    var max = Math.max((candles ? candles.length : 0) - 1, 0);
    el.scrubber.min = '0';
    el.scrubber.max = String(max);
    el.scrubber.step = '1';
    el.scrubber.value = '0';
    el.scrubber.disabled = !candles || candles.length === 0;
  }

  function render(snapshot) {
    if (!snapshot) return;

    // --- chart update --------------------------------------------------
    if (chartApi) {
      chartApi.seekTo(snapshot.index, { follow: chartApi.isFollowing() });
    }

    // --- transport bar -------------------------------------------------
    var isPlaying = snapshot.state === 'PLAYING';
    if (el.play) {
      el.play.textContent = isPlaying ? '⏸ Pause' : '▶ Play';
      el.play.setAttribute('aria-label', isPlaying ? 'Pause replay' : 'Play replay');
      el.play.classList.toggle('is-playing', isPlaying);
    }

    setText(el.state, snapshot.state);
    if (el.state) {
      el.state.className = 'replay-state is-' + String(snapshot.state).toLowerCase();
    }

    var posText = (snapshot.index + 1).toLocaleString('id-ID') + ' / ' +
      snapshot.totalBars.toLocaleString('id-ID');
    setText(el.position, posText);

    if (el.scrubber && document.activeElement !== el.scrubber) {
      el.scrubber.value = String(snapshot.index);
    }
    if (el.scrubberFill) {
      el.scrubberFill.style.width = (snapshot.progress * 100).toFixed(3) + '%';
    }

    renderSpeedPills(snapshot.speed);
    updateFollowButton(chartApi ? chartApi.isFollowing() : true);

    // --- floating HUD --------------------------------------------------
    setText(el.hudStatus, snapshot.state);
    if (el.hudStatus) {
      el.hudStatus.className = 'replay-hud-status is-' + String(snapshot.state).toLowerCase();
    }

    setText(el.hudProgress, (snapshot.progress * 100).toFixed(1) + '%');

    var candle = snapshot.candle;
    if (candle) {
      setText(el.hudTimeUtc, formatUtc(candle.time));
      setText(el.hudTimeLocal, formatLocal(candle.time));
      setText(el.hudOpen, formatPrice(candle.open));
      setText(el.hudHigh, formatPrice(candle.high));
      setText(el.hudLow, formatPrice(candle.low));
      setText(el.hudClose, formatPrice(candle.close));
      var range = Math.max(candle.high - candle.low, 0);
      setText(el.hudRange, '$' + formatPrice(range));
    } else {
      setText(el.hudTimeUtc, '—');
      setText(el.hudTimeLocal, '—');
      setText(el.hudOpen, '—');
      setText(el.hudHigh, '—');
      setText(el.hudLow, '—');
      setText(el.hudClose, '—');
      setText(el.hudRange, '—');
    }
  }

  function renderSpeedPills(speed) {
    if (!el.speeds) return;
    var pills = el.speeds.querySelectorAll('[data-speed]');
    for (var i = 0; i < pills.length; i += 1) {
      var raw = pills[i].getAttribute('data-speed');
      var val = raw === 'max' ? 'max' : Number(raw);
      var active = val === speed;
      pills[i].classList.toggle('is-active', active);
      pills[i].setAttribute('aria-pressed', active ? 'true' : 'false');
    }
  }

  // ------------------------------------------------------------- user actions

  function onPlayToggle() {
    if (!controller || !controller.isLoaded()) return;
    var snap = controller.snapshot();
    if (snap.state !== 'PLAYING') {
      // Snaps back to active candle on starting playback
      if (chartApi) {
        chartApi.snapToActive();
        chartApi.setFollow(true);
      }
    }
    render(controller.toggle());
  }

  function onStep(delta) {
    if (!controller || !controller.isLoaded()) return;
    render(controller.step(delta));
  }

  function onSpeedClick(event) {
    if (!controller) return;
    var raw = event.currentTarget.getAttribute('data-speed');
    controller.setSpeed(raw === 'max' ? 'max' : Number(raw));
    render(controller.snapshot());
  }

  function onScrubInput() {
    if (!controller || !controller.isLoaded()) return;
    var val = Number(el.scrubber.value);
    render(controller.seekToIndex(val));
  }

  function onScrubberMouseMove(e) {
    if (!currentPayload || !currentPayload.candles || !currentPayload.candles.length) return;
    var rect = el.scrubber.getBoundingClientRect();
    var wrapRect = el.scrubberWrap.getBoundingClientRect();
    var ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    var idx = Math.round(ratio * (currentPayload.candles.length - 1));
    var candle = currentPayload.candles[idx];
    if (!candle) return;

    if (el.scrubberTooltip) {
      el.scrubberTooltip.textContent = formatUtc(candle.time) + ' · ' + formatLocal(candle.time);
      var x = e.clientX - wrapRect.left;
      el.scrubberTooltip.style.left = x + 'px';
      show(el.scrubberTooltip, true);
    }
  }

  function onScrubberMouseLeave() {
    show(el.scrubberTooltip, false);
  }

  function onSnapFollow() {
    if (chartApi) {
      chartApi.snapToActive();
      chartApi.setFollow(true);
      show(el.btnFollow, false);
    }
  }

  function toggleFullscreen() {
    var target = el.chartWrap || el.chartContainer;
    if (!target) return;

    if (!document.fullscreenElement && !target.classList.contains('is-fullscreen')) {
      if (target.requestFullscreen) {
        target.requestFullscreen().catch(function () {
          // Fallback if browser denies native fullscreen without user activation
          target.classList.add('is-fullscreen');
          if (el.btnFullscreen) el.btnFullscreen.textContent = '⛶ Normal';
          if (chartApi) chartApi.resize();
        });
      } else if (target.webkitRequestFullscreen) {
        target.webkitRequestFullscreen();
      } else {
        target.classList.add('is-fullscreen');
        if (el.btnFullscreen) el.btnFullscreen.textContent = '⛶ Normal';
        if (chartApi) chartApi.resize();
      }
    } else {
      if (document.fullscreenElement) {
        if (document.exitFullscreen) {
          document.exitFullscreen().catch(function () {});
        } else if (document.webkitExitFullscreen) {
          document.webkitExitFullscreen();
        }
      }
      target.classList.remove('is-fullscreen');
      if (el.btnFullscreen) el.btnFullscreen.textContent = '⛶ Fullscreen';
      if (chartApi) chartApi.resize();
    }
  }

  function onFullscreenChange() {
    var isFs = !!document.fullscreenElement;
    if (el.chartWrap) {
      el.chartWrap.classList.toggle('is-fullscreen', isFs);
    }
    if (el.btnFullscreen) {
      el.btnFullscreen.textContent = isFs ? '⛶ Normal' : '⛶ Fullscreen';
    }
    if (chartApi) {
      chartApi.resize();
    }
  }

  function onHudToggle() {
    if (!el.hud) return;
    var minimized = el.hud.classList.toggle('is-minimized');
    if (el.hudToggle) {
      el.hudToggle.textContent = minimized ? '+' : '—';
      el.hudToggle.setAttribute('title', minimized ? 'Bentangkan HUD (H)' : 'Ciutkan HUD (H)');
      el.hudToggle.setAttribute('aria-label', minimized ? 'Bentangkan HUD' : 'Ciutkan HUD');
    }
  }

  function toggleHud() {
    if (!el.hud) return;
    el.hud.classList.toggle('is-hidden');
  }

  function selectTool(toolName) {
    currentTool = toolName || 'cursor';
    if (el.dock) {
      var buttons = el.dock.querySelectorAll('[data-tool]');
      for (var i = 0; i < buttons.length; i += 1) {
        var isCurrent = buttons[i].getAttribute('data-tool') === currentTool;
        buttons[i].classList.toggle('is-active', isCurrent);
        buttons[i].setAttribute('aria-pressed', isCurrent ? 'true' : 'false');
      }
    }
    if (canvasApi) {
      canvasApi.setTool(currentTool);
    }
  }

  function onClearDrawings() {
    if (drawingsApi) {
      drawingsApi.clearDrawings();
    }
    if (simulatorApi) {
      simulatorApi.clearPositions();
    }
    if (canvasApi) {
      canvasApi.requestRedraw();
    }
    syncStorage();
  }

  function onKeyDown(event) {
    if (event.defaultPrevented) return;
    if (isTypingTarget(event.target)) return;

    // Alt + H -> Horizontal Line tool
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      if (event.key === 'h' || event.key === 'H') {
        event.preventDefault();
        selectTool('hline');
        return;
      }
    }

    if (!event.altKey && !event.ctrlKey && !event.metaKey) {
      if (event.code === 'Space' || event.key === ' ') {
        event.preventDefault();
        onPlayToggle();
        return;
      }
      if (event.key === 'ArrowRight' || event.code === 'ArrowRight') {
        event.preventDefault();
        onStep(1);
        return;
      }
      if (event.key === 'ArrowLeft' || event.code === 'ArrowLeft') {
        event.preventDefault();
        onStep(-1);
        return;
      }
      if (event.key === 'f' || event.key === 'F') {
        event.preventDefault();
        toggleFullscreen();
        return;
      }
      if (event.key === 'h' || event.key === 'H') {
        event.preventDefault();
        toggleHud();
        return;
      }
      if (event.key === 'c' || event.key === 'C') {
        event.preventDefault();
        if (simulatorApi) {
          var snap = controller ? controller.snapshot() : null;
          var candle = snap ? snap.candle : null;
          simulatorApi.closePosition(candle);
          syncStorage();
        }
        return;
      }
      if (event.key === 'v' || event.key === 'V') {
        event.preventDefault();
        if (simulatorApi && simulatorApi.getSelectedId()) {
          simulatorApi.deselect();
        }
        if (drawingsApi && drawingsApi.getSelectedId()) {
          drawingsApi.deselect();
        }
        selectTool('cursor');
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        if (simulatorApi && simulatorApi.getSelectedId()) {
          simulatorApi.deselect();
        }
        if (drawingsApi && drawingsApi.getSelectedId()) {
          drawingsApi.deselect();
        }
        selectTool('cursor');
        return;
      }
      if (event.key === 'r' || event.key === 'R') {
        event.preventDefault();
        selectTool('rect');
        return;
      }
      if (event.key === 't' || event.key === 'T') {
        event.preventDefault();
        selectTool('trendline');
        return;
      }
      if (event.key === 'm' || event.key === 'M') {
        event.preventDefault();
        selectTool('ruler');
        return;
      }
      if (event.key === 'l' || event.key === 'L') {
        event.preventDefault();
        selectTool('long_pos');
        return;
      }
      if (event.key === 's' || event.key === 'S') {
        event.preventDefault();
        selectTool('short_pos');
        return;
      }
      if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault();
        if (simulatorApi && simulatorApi.getSelectedId()) {
          simulatorApi.deleteSelected();
          syncStorage();
        } else if (drawingsApi && drawingsApi.getSelectedId()) {
          drawingsApi.deleteSelected();
          syncStorage();
        } else {
          onClearDrawings();
        }
        return;
      }
    }
  }

  function onResize() {
    if (chartApi) chartApi.resize();
    if (canvasApi) canvasApi.resize();
  }

  // ------------------------------------------------------------- init

  function cacheElements() {
    el.root = $('pane-replay');
    el.heading = $('heading-replay');

    // Selectors
    el.modeToggle = $('replay-mode-toggle');
    el.yearWrap = $('replay-year-wrap');
    el.year = $('replay-year');
    el.monthWrap = $('replay-month-wrap');
    el.month = $('replay-month');
    el.dateStartWrap = $('replay-date-start-wrap');
    el.dateStart = $('replay-date-start');
    el.dateEndWrap = $('replay-date-end-wrap');
    el.dateEnd = $('replay-date-end');
    el.timeframes = $('replay-timeframes');
    el.btnLoad = $('replay-btn-load');
    el.btnFullscreen = $('replay-btn-fullscreen');

    // Banners
    el.warningsBanner = $('replay-warnings-banner');
    el.warningsText = $('replay-warnings-text');
    el.errorBanner = $('replay-error-banner');
    el.errorText = $('replay-error-text');

    // Transport
    el.stepBack = $('replay-step-back');
    el.play = $('replay-play');
    el.stepForward = $('replay-step-forward');
    el.state = $('replay-state');
    el.position = $('replay-position');
    el.speeds = $('replay-speeds');

    // Scrubber
    el.scrubberWrap = $('replay-scrubber-wrap');
    el.scrubberFill = $('replay-scrubber-fill');
    el.scrubber = $('replay-scrubber');
    el.scrubberTooltip = $('replay-scrubber-tooltip');
    el.status = $('replay-status');

    // Chart & HUD
    el.chartWrap = $('replay-chart-wrap');
    el.dock = $('replay-dock');
    el.canvas = $('replay-drawing-canvas');
    el.chartContainer = $('replay-chart');
    el.chartEmpty = $('replay-chart-empty');
    el.btnFollow = $('replay-btn-follow');
    el.hud = $('replay-hud');
    el.hudToggle = $('replay-hud-toggle');
    el.hudStatus = $('replay-hud-status');
    el.hudProgress = $('replay-hud-progress');
    el.hudTimeUtc = $('replay-hud-time-utc');
    el.hudTimeLocal = $('replay-hud-time-local');
    el.hudOpen = $('replay-hud-open');
    el.hudHigh = $('replay-hud-high');
    el.hudLow = $('replay-hud-low');
    el.hudClose = $('replay-hud-close');
    el.hudRange = $('replay-hud-range');
  }

  function bindEvents() {
    if (el.modeToggle) {
      el.modeToggle.addEventListener('click', function (e) {
        var btn = e.target.closest('button[data-mode]');
        if (!btn) return;
        setMode(btn.getAttribute('data-mode'));
      });
    }

    if (el.year) {
      el.year.addEventListener('change', function () {
        selectedYear = Number(el.year.value);
        updateTimeframePills();
      });
    }

    if (el.month) {
      el.month.addEventListener('change', function () {
        selectedMonth = Number(el.month.value);
        updateTimeframePills();
      });
    }

    if (el.dateStart) {
      el.dateStart.addEventListener('change', function () {
        selectedStartDate = el.dateStart.value;
        updateTimeframePills();
      });
    }

    if (el.dateEnd) {
      el.dateEnd.addEventListener('change', function () {
        selectedEndDate = el.dateEnd.value;
        updateTimeframePills();
      });
    }

    if (el.timeframes) {
      el.timeframes.addEventListener('click', function (e) {
        var btn = e.target.closest('button[data-tf]');
        if (!btn || btn.disabled) return;
        selectedTimeframe = btn.getAttribute('data-tf');
        updateTimeframePills();
      });
    }

    if (el.btnLoad) el.btnLoad.addEventListener('click', loadData);
    if (el.btnFullscreen) el.btnFullscreen.addEventListener('click', toggleFullscreen);
    if (el.btnFollow) el.btnFollow.addEventListener('click', onSnapFollow);
    if (el.hudToggle) el.hudToggle.addEventListener('click', onHudToggle);

    if (el.dock) {
      el.dock.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-tool]');
        if (btn) {
          var tool = btn.getAttribute('data-tool');
          selectTool(tool);
          return;
        }
        var actionBtn = e.target.closest('[data-action]');
        if (actionBtn) {
          var action = actionBtn.getAttribute('data-action');
          if (action === 'clear') {
            onClearDrawings();
          }
        }
      });
    }

    if (el.play) el.play.addEventListener('click', onPlayToggle);
    if (el.stepBack) el.stepBack.addEventListener('click', function () { onStep(-1); });
    if (el.stepForward) el.stepForward.addEventListener('click', function () { onStep(1); });

    if (el.speeds) {
      var pills = el.speeds.querySelectorAll('[data-speed]');
      for (var i = 0; i < pills.length; i += 1) {
        pills[i].addEventListener('click', onSpeedClick);
      }
    }

    if (el.scrubber) {
      el.scrubber.addEventListener('input', onScrubInput);
      el.scrubber.addEventListener('change', onScrubInput);
      el.scrubber.addEventListener('mousemove', onScrubberMouseMove);
      el.scrubber.addEventListener('mouseleave', onScrubberMouseLeave);
    }

    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('fullscreenchange', onFullscreenChange);
    global.addEventListener('resize', onResize);
  }

  function createController() {
    if (!global.SmcReplayEngine) return null;
    var ctrl = global.SmcReplayEngine.create();
    ctrl.on('frame', function (snapshot) {
      render(snapshot);
      if (simulatorApi && snapshot && snapshot.candle) {
        var hit = simulatorApi.evaluateCandle(snapshot.candle, snapshot.index);
        if (hit) syncStorage();
      }
      if (canvasApi) canvasApi.requestRedraw();
    });
    ctrl.on('state', function () { render(ctrl.snapshot()); });
    return ctrl;
  }

  function activate() {
    mounted = true;
    if (!controller) controller = createController();
    ensureChart();
    onResize();
    if (!coverage) {
      loadCoverage();
    }
  }

  function init() {
    cacheElements();
    if (!el.root) return null;
    controller = createController();
    if (!controller) {
      setStatus('Modul replay engine tidak tersedia.', 'error');
      return null;
    }
    bindEvents();

    global.SmcDebug = global.SmcDebug || {};
    global.SmcDebug.replay = {
      controller: controller,
      activate: activate,
      loadCoverage: loadCoverage,
      loadData: loadData,
      getChart: function () { return chartApi; },
      getCanvasApi: function () { return canvasApi; },
      getDrawingsApi: function () { return drawingsApi; },
      getSimulatorApi: function () { return simulatorApi; },
      getLedgerApi: function () { return simulatorApi ? simulatorApi.getLedger() : null; },
      getStorageApi: function () { return global.SmcReplayStorage; },
      getActiveTool: function () { return currentTool; },
      selectTool: selectTool,
      snapshot: function () { return controller ? controller.snapshot() : null; },
      setFollow: function (v) { if (chartApi) chartApi.setFollow(v); },
      isFollowing: function () { return chartApi ? chartApi.isFollowing() : false; },
      getCoverage: function () { return coverage; },
      getPayload: function () { return currentPayload; }
    };

    activate();
    return global.SmcDebug.replay;
  }

  global.SmcReplay = { init: init, activate: activate };
})(window);
