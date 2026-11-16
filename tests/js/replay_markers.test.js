/**
 * Headless tests for the marker / price-line manager (tickets T-REP-05, T-REP-06).
 *
 * The series is a stub that records what the manager asks of it, which is enough
 * to assert the two contracts that matter:
 *   - markers never appear for bars that have not been replayed yet;
 *   - the three active lines exist only while a trade is open.
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const markers = require('../../src/assistant/static/js/replay_markers.js');

const START = 1_730_419_200;
const STEP = 300;

function stubSeries() {
  const state = { markers: [], lines: [], removed: 0 };
  return {
    state,
    setMarkers(list) {
      state.markers = list.slice();
    },
    createPriceLine(options) {
      const line = { options };
      state.lines.push(line);
      return line;
    },
    removePriceLine(line) {
      state.removed += 1;
      const at = state.lines.indexOf(line);
      if (at >= 0) state.lines.splice(at, 1);
    }
  };
}

const TRADES = [
  {
    trade_id: 'T-001',
    side: 'BUY',
    entryIdx: 10,
    entry_idx: 10,
    entry_time: START + 10 * STEP,
    entry_price: 2011,
    sl_price: 2008,
    tp_price: 2015.5,
    lot: 0.5,
    exitIdx: 14,
    exit_idx: 14,
    exit_time: START + 14 * STEP,
    exit_reason: 'TP',
    outcome: 'WIN',
    pnl: 215
  },
  {
    trade_id: 'T-002',
    side: 'SELL',
    entryIdx: 20,
    entry_idx: 20,
    entry_time: START + 20 * STEP,
    entry_price: 2021,
    sl_price: 2024,
    tp_price: 2016.5,
    lot: 0.25,
    exitIdx: 26,
    exit_idx: 26,
    exit_time: START + 26 * STEP,
    exit_reason: 'SL',
    outcome: 'LOSS',
    pnl: -85.5
  }
];

function snapshot(index, active) {
  return { index, active: active || [] };
}

// ------------------------------------------------------------------- markers

test('no markers before the first entry bar', () => {
  const list = markers.buildMarkers(TRADES, 9);
  assert.equal(list.length, 0);
});

test('entry marker appears on the entry bar and names side, lot and price', () => {
  const list = markers.buildMarkers(TRADES, 10);
  assert.equal(list.length, 1);
  assert.equal(list[0].time, TRADES[0].entry_time);
  assert.equal(list[0].shape, 'arrowUp');
  assert.equal(list[0].position, 'belowBar');
  assert.equal(list[0].text, 'BUY 0.50 @ 2011.00');
  assert.equal(list[0].color, markers.COLORS.buy);
});

test('sell entries point down from above the bar', () => {
  const list = markers.buildMarkers(TRADES, 20);
  const sell = list[list.length - 1];
  assert.equal(sell.shape, 'arrowDown');
  assert.equal(sell.position, 'aboveBar');
  assert.equal(sell.color, markers.COLORS.sell);
  assert.ok(sell.text.startsWith('SELL 0.25 @'));
});

test('exit marker only appears once its bar is replayed', () => {
  const mid = markers.buildMarkers(TRADES, 12);
  assert.equal(mid.length, 1, 'entry only, still open');
  assert.ok(!mid.some((m) => m.text.indexOf('TP HIT') === 0));

  const closed = markers.buildMarkers(TRADES, 14);
  assert.equal(closed.length, 2);
  const exit = closed[1];
  assert.equal(exit.shape, 'circle');
  assert.equal(exit.text, 'TP HIT +$215.00');
  assert.equal(exit.color, markers.COLORS.exitWin);
});

test('loss exits use a cross and a negative PnL label', () => {
  const list = markers.buildMarkers(TRADES, 26);
  const exit = list[list.length - 1];
  assert.equal(exit.shape, 'cross');
  assert.equal(exit.text, 'SL HIT -$85.50');
  assert.equal(exit.color, markers.COLORS.exitLoss);
});

test('expired trades are labelled EXPIRED rather than a win or loss', () => {
  const trade = Object.assign({}, TRADES[0], { outcome: 'EXPIRED', exit_reason: 'EXPIRED', pnl: -12.5 });
  const list = markers.buildMarkers([trade], 14);
  assert.equal(list[1].text, 'EXPIRED -$12.50');
  assert.equal(list[1].color, markers.COLORS.exitNeutral);
});

test('marker history is identical whether reached forward or backward', () => {
  const forward = [];
  for (let i = 0; i <= 30; i += 1) forward.push(markers.buildMarkers(TRADES, i).length);
  const backward = [];
  for (let i = 30; i >= 0; i -= 1) backward.unshift(markers.buildMarkers(TRADES, i).length);
  assert.deepEqual(forward, backward);
});

test('money formatter keeps the sign and two decimals', () => {
  assert.equal(markers.money(1234.5), '+$1,234.50');
  assert.equal(markers.money(-0.5), '-$0.50');
  assert.equal(markers.money(0), '+$0.00');
});

// --------------------------------------------------------------- price lines

test('three price lines exist only while a trade is open', () => {
  const series = stubSeries();
  const manager = markers.init(series);

  manager.render(snapshot(12, [{ trade: TRADES[0], floating: 40 }]), TRADES);
  assert.equal(series.state.lines.length, 3);
  const prices = series.state.lines.map((line) => line.options.price).sort((a, b) => a - b);
  assert.deepEqual(prices, [2008, 2011, 2015.5]);
  assert.equal(manager.getActiveTradeId(), 'T-001');

  const entryLine = series.state.lines.find((l) => l.options.title.indexOf('ENTRY') === 0);
  const tpLine = series.state.lines.find((l) => l.options.title.indexOf('TP') === 0);
  const slLine = series.state.lines.find((l) => l.options.title.indexOf('SL') === 0);
  assert.equal(entryLine.options.color, markers.COLORS.entry);
  assert.equal(tpLine.options.color, markers.COLORS.tp);
  assert.equal(slLine.options.color, markers.COLORS.sl);
  assert.notEqual(tpLine.options.lineStyle, entryLine.options.lineStyle);
  assert.notEqual(slLine.options.lineStyle, entryLine.options.lineStyle);
});

test('lines are removed the moment the trade closes', () => {
  const series = stubSeries();
  const manager = markers.init(series);
  manager.render(snapshot(12, [{ trade: TRADES[0], floating: 40 }]), TRADES);
  assert.equal(series.state.lines.length, 3);

  manager.render(snapshot(15, []), TRADES);
  assert.equal(series.state.lines.length, 0);
  assert.equal(manager.getActiveLineCount(), 0);
  assert.equal(manager.getActiveTradeId(), null);
  assert.equal(series.state.removed, 3);
});

test('re-rendering the same open trade does not churn price lines', () => {
  const series = stubSeries();
  const manager = markers.init(series);
  const active = [{ trade: TRADES[0], floating: 40 }];
  manager.render(snapshot(12, active), TRADES);
  const created = series.state.lines.length;
  manager.render(snapshot(13, active), TRADES);
  assert.equal(series.state.lines.length, created);
  assert.equal(series.state.removed, 0);
});

test('switching straight from one trade to another replaces the lines', () => {
  const series = stubSeries();
  const manager = markers.init(series);
  manager.render(snapshot(12, [{ trade: TRADES[0] }]), TRADES);
  manager.render(snapshot(21, [{ trade: TRADES[1] }]), TRADES);
  assert.equal(series.state.lines.length, 3);
  assert.equal(manager.getActiveTradeId(), 'T-002');
  const prices = series.state.lines.map((l) => l.options.price).sort((a, b) => a - b);
  assert.deepEqual(prices, [2016.5, 2021, 2024]);
});

test('clear() wipes markers and lines', () => {
  const series = stubSeries();
  const manager = markers.init(series);
  manager.render(snapshot(12, [{ trade: TRADES[0] }]), TRADES);
  manager.clear();
  assert.equal(series.state.lines.length, 0);
  assert.equal(series.state.markers.length, 0);
  assert.equal(manager.getMarkerCount(), 0);
});

test('init rejects a missing series', () => {
  assert.equal(markers.init(null), null);
});
