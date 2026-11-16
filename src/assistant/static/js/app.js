(function (global) {
  'use strict';

  var state = {
    connected: false,
    busy: false,
    busyAction: null,
    lastStatus: null,
    pollError: null,
    actionError: null
  };

  var POLL_INTERVAL_MS = 2000;
  var pollTimer = null;

  var els = {
    statusFeedback: document.getElementById('status-feedback'),
    metaCluster: document.getElementById('meta-cluster'),
    metaAccount: document.getElementById('meta-account'),
    metaLatency: document.getElementById('meta-latency'),
    metaSpread: document.getElementById('meta-spread'),
    lastErrorWrap: document.getElementById('last-error-wrap'),
    lastErrorText: document.getElementById('last-error-text'),
    connectionBadge: document.getElementById('connection-badge'),
    badgeDot: document.getElementById('badge-dot'),
    badgeText: document.getElementById('badge-text'),
    btnToggleMt5: document.getElementById('btn-toggle-mt5')
  };

  function formatSpread(spread) {
    if (!spread) return '—';
    var hasPoints = typeof spread.points === 'number';
    var hasPrice = typeof spread.price === 'number';
    if (hasPoints && hasPrice) {
      return spread.points + ' pts · ' + spread.price;
    }
    if (hasPoints) {
      return spread.points + ' pts';
    }
    return '—';
  }

  function formatLatency(latency) {
    if (typeof latency === 'number' && !isNaN(latency)) {
      return (latency < 10 ? latency.toFixed(1) : Math.round(latency)) + ' ms';
    }
    return '—';
  }

  function formatAccount(account) {
    if (account && account.login != null) {
      return String(account.login);
    }
    return '—';
  }

  function renderFeedback() {
    if (!els.statusFeedback) return;
    var errorMsg = state.actionError || state.pollError;
    if (errorMsg) {
      els.statusFeedback.textContent = errorMsg;
      els.statusFeedback.classList.remove('hidden');
    } else {
      els.statusFeedback.textContent = '';
      els.statusFeedback.classList.add('hidden');
    }
  }

  function renderButton() {
    if (!els.btnToggleMt5) return;
    if (state.busy) {
      els.btnToggleMt5.disabled = true;
      els.btnToggleMt5.textContent = state.busyAction === 'connect'
        ? 'Menghubungkan…'
        : 'Memutuskan…';
      return;
    }

    els.btnToggleMt5.disabled = false;
    if (state.connected) {
      els.btnToggleMt5.textContent = 'Putuskan MT5';
      els.btnToggleMt5.className = 'btn btn-disconnect';
      els.btnToggleMt5.setAttribute('aria-label', 'Putuskan MT5');
    } else {
      els.btnToggleMt5.textContent = 'Sambungkan ke MT5';
      els.btnToggleMt5.className = 'btn btn-connect';
      els.btnToggleMt5.setAttribute('aria-label', 'Sambungkan ke MT5');
    }
  }

  function renderBadge() {
    if (!els.connectionBadge) return;
    if (state.connected) {
      if (els.badgeDot) els.badgeDot.textContent = '🟢';
      if (els.badgeText) els.badgeText.textContent = 'Terhubung';
      els.connectionBadge.className = 'badge badge-connected';
    } else {
      if (els.badgeDot) els.badgeDot.textContent = '🔴';
      if (els.badgeText) els.badgeText.textContent = 'Terputus';
      els.connectionBadge.className = 'badge badge-disconnected';
    }
  }

  function renderMeta() {
    var s = state.lastStatus;
    if (state.connected) {
      if (els.metaAccount) els.metaAccount.textContent = formatAccount(s ? s.account : null);
      if (els.metaLatency) els.metaLatency.textContent = formatLatency(s ? s.latency_ms : null);
      if (els.metaSpread) els.metaSpread.textContent = formatSpread(s ? s.spread : null);
      if (els.metaCluster) els.metaCluster.classList.remove('hidden');
      if (els.lastErrorWrap) els.lastErrorWrap.classList.add('hidden');
      if (els.lastErrorText) {
        els.lastErrorText.textContent = '';
        els.lastErrorText.title = '';
      }
    } else {
      if (els.metaCluster) els.metaCluster.classList.add('hidden');
      var err = s && typeof s.last_error === 'string' ? s.last_error.trim() : '';
      if (err) {
        if (els.lastErrorText) {
          els.lastErrorText.textContent = err;
          els.lastErrorText.title = err;
        }
        if (els.lastErrorWrap) els.lastErrorWrap.classList.remove('hidden');
      } else {
        if (els.lastErrorWrap) els.lastErrorWrap.classList.add('hidden');
        if (els.lastErrorText) {
          els.lastErrorText.textContent = '';
          els.lastErrorText.title = '';
        }
      }
    }
  }

  function render() {
    renderFeedback();
    renderBadge();
    renderButton();
    renderMeta();
  }

  function applyStatus(data) {
    if (!data || typeof data !== 'object') return;
    state.lastStatus = data;
    state.connected = Boolean(data.connected);
  }

  async function pollStatus() {
    try {
      var res = await fetch('/api/mt5/status', {
        method: 'GET',
        headers: { 'Accept': 'application/json' },
        cache: 'no-store'
      });
      if (!res.ok) {
        throw new Error('HTTP ' + res.status);
      }
      var data = await res.json();
      state.pollError = null;
      applyStatus(data);
    } catch (err) {
      state.pollError = 'Server tidak merespons';
    }

    if (!state.busy) {
      render();
    } else {
      renderFeedback();
    }
  }

  async function handleToggleClick() {
    if (state.busy) return;

    var action = state.connected ? 'disconnect' : 'connect';
    var endpoint = action === 'connect' ? '/api/mt5/connect' : '/api/mt5/disconnect';

    state.busy = true;
    state.busyAction = action;
    state.actionError = null;
    render();

    try {
      var res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }
      });
      if (!res.ok) {
        throw new Error('HTTP ' + res.status);
      }
      var data = await res.json();
      if (data && data.ok) {
        state.actionError = null;
        state.pollError = null;
        if (data.status) {
          applyStatus(data.status);
        }
      } else {
        state.actionError = (data && data.message) ? data.message : 'Operasi gagal';
        if (data && data.status) {
          applyStatus(data.status);
        }
      }
    } catch (err) {
      state.actionError = 'Server tidak merespons';
    } finally {
      state.busy = false;
      state.busyAction = null;
      render();
    }
  }

  function initReplay() {
    if (!global.SmcReplay || typeof global.SmcReplay.init !== 'function') return null;
    return global.SmcReplay.init();
  }

  function init() {
    if (els.btnToggleMt5) {
      els.btnToggleMt5.addEventListener('click', handleToggleClick);
    }
    initReplay();
    render();
    pollStatus();
    pollTimer = setInterval(pollStatus, POLL_INTERVAL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})(window);
