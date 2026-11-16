/**
 * Headless tests for the replay state machine (ticket T-REP-03).
 *
 * Runs under `node --test` with no browser and no chart library: the controller
 * accepts an injected clock, so playback can be advanced deterministically with
 * `pump(ms)` instead of waiting on real animation frames.
 *
 *   node --test tests/js/
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const engine = require('../../src/assistant/static/js/replay_engine.js');

const STATES = engine.STATES;
const START = 1_730_419_200; // 2024-11-01T00:00:00Z
const STEP = 300; // M5

/** 40 flat bars with one BUY trade from bar 10 to bar 14 (TP) and a SELL 20->26. */
function makePayload() {
  const candles = [];
  for (let i = 0; i < 40; i += 1) {
    candles.push({
      time: START + i * STEP,
      open: 2000 + i,
      high: 2002 + i,
      low: 1998 + i,
      close: 2001 + i,
      volume: 10
    });
  }

  const trades = [
    {
      trade_id: 'T-001',
      side: 'BUY',
      mode: 'RETEST_CONTINUATION',
      entry_idx: 10,
      entry_time: candles[10].time,
      entry_iso: '2024-11-01 00:50',
      entry_price: 2011,
      sl_price: 2008,
      tp_price: 2015.5,
      sl_dist: 3,
      tp_dist: 4.5,
      lot: 1.0,
      exit_idx: 14,
      exit_time: candles[14].time,
      exit_iso: '2024-11-01 01:10',
      exit_price: 2015.5,
      exit_reason: 'TP',
      outcome: 'WIN',
      bars_held: 4,
      pnl: 430,
      equity_before: 10000,
      equity_after: 10430,
      reason: 'M15 Bullish Expansion + Retest Broken Resistance @ 2010.00'
    },
    {
      trade_id: 'T-002',
      side: 'SELL',
      mode: 'RETEST_CONTINUATION',
      entry_idx: 20,
      entry_time: candles[20].time,
      entry_iso: '2024-11-01 01:40',
      entry_price: 2021,
      sl_price: 2024,
      tp_price: 2016.5,
      sl_dist: 3,
      tp_dist: 4.5,
      lot: 1.0,
      exit_idx: 26,
      exit_time: candles[26].time,
      exit_iso: '2024-11-01 02:10',
      exit_price: 2024,
      exit_reason: 'SL',
      outcome: 'LOSS',
      bars_held: 6,
      pnl: -320,
      equity_before: 10430,
      equity_after: 10110,
      reason: 'M15 Bearish Expansion + Retest Broken Support @ 2022.00'
    }
  ];

  return {
    meta: {
      session_id: 'test',
      symbol: 'XAUUSD',
      timeframe: 'M5',
      initial_capital: 10000,
      final_capital: 10110,
      total_trades: 2
    },
    candles,
    trades,
    zones: [
      {
        type: 'RBS',
        trade_id: 'T-001',
        level: 2010,
        top: 2011.2,
        bottom: 2009,
        start_idx: 8,
        end_idx: 14,
        start_time: candles[8].time,
        end_time: candles[14].time
      }
    ],
    equity_curve: [
      { time: candles[0].time, equity: 10000 },
      { time: candles[14].time, equity: 10430 },
      { time: candles[26].time, equity: 10110 }
    ]
  };
}

function controller() {
  return engine.create({ raf: () => 0, cancelRaf: () => {}, now: () => 0 });
}

// ------------------------------------------------------------------ lifecycle

test('starts STOPPED and reports an empty snapshot before load', () => {
  const ctrl = controller();
  assert.equal(ctrl.getState(), STATES.STOPPED);
  assert.equal(ctrl.isLoaded(), false);
  const snap = ctrl.snapshot();
  assert.equal(snap.loaded, false);
  assert.equal(snap.totalBars, 0);
});

test('load resets to the first bar and derives opening state', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  const snap = ctrl.snapshot();
  assert.equal(ctrl.getState(), STATES.STOPPED);
  assert.equal(snap.loaded, true);
  assert.equal(snap.index, 0);
  assert.equal(snap.totalBars, 40);
  assert.equal(snap.closedTrades, 0);
  assert.equal(snap.openTrades, 0);
  assert.equal(snap.balance, 10000);
  assert.equal(snap.time, START);
});

test('play -> pause -> play toggles without losing position', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.play();
  assert.equal(ctrl.getState(), STATES.PLAYING);
  ctrl.pump(1000); // 1x = 1 bar/second
  const after = ctrl.getIndex();
  assert.equal(after, 1);
  ctrl.pause();
  assert.equal(ctrl.getState(), STATES.PAUSED);
  assert.equal(ctrl.getIndex(), after);
  ctrl.play();
  assert.equal(ctrl.getState(), STATES.PLAYING);
  assert.equal(ctrl.getIndex(), after);
});

test('step forward/back moves exactly one bar and pauses', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.seekToIndex(5);
  ctrl.step(1);
  assert.equal(ctrl.getIndex(), 6);
  assert.equal(ctrl.getState(), STATES.PAUSED);
  ctrl.step(-1);
  assert.equal(ctrl.getIndex(), 5);
  assert.equal(ctrl.getState(), STATES.PAUSED);
});

test('step is clamped at both ends of the dataset', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.step(-5);
  assert.equal(ctrl.getIndex(), 0);
  ctrl.seekToIndex(39);
  ctrl.step(5);
  assert.equal(ctrl.getIndex(), 39);
});

test('playing to the last bar completes and reports COMPLETED', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  let completed = null;
  ctrl.on('complete', (snap) => { completed = snap; });
  ctrl.play();
  ctrl.pump(100_000);
  assert.equal(ctrl.getState(), STATES.COMPLETED);
  assert.equal(ctrl.getIndex(), 39);
  assert.ok(completed, 'complete event fired');
  assert.equal(completed.index, 39);
});

test('play after COMPLETED restarts from the beginning', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.play();
  ctrl.pump(100_000);
  assert.equal(ctrl.getState(), STATES.COMPLETED);
  ctrl.play();
  assert.equal(ctrl.getState(), STATES.PLAYING);
  assert.equal(ctrl.getIndex(), 0);
});

test('reset returns to STOPPED at bar 0', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.seekToIndex(12);
  ctrl.reset();
  assert.equal(ctrl.getState(), STATES.STOPPED);
  assert.equal(ctrl.getIndex(), 0);
});

// --------------------------------------------------------------------- speeds

test('speed multiplier scales bars per second', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.setSpeed(10);
  ctrl.play();
  ctrl.pump(1000); // 10 bars in one second
  assert.equal(ctrl.getIndex(), 10);
});

test('0.5x advances one bar per two seconds', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.setSpeed(0.5);
  ctrl.play();
  ctrl.pump(1000);
  assert.equal(ctrl.getIndex(), 0);
  ctrl.pump(1000);
  assert.equal(ctrl.getIndex(), 1);
});

test('max speed covers the whole dataset within a few frames', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.setSpeed('max');
  ctrl.play();
  let frames = 0;
  while (ctrl.getState() === STATES.PLAYING && frames < 50) {
    ctrl.pump(16);
    frames += 1;
  }
  assert.equal(ctrl.getIndex(), 39);
  assert.equal(ctrl.getState(), STATES.COMPLETED);
  // A tiny 40-bar set legitimately advances one bar per frame; what matters is
  // that it never needs more frames than bars.
  assert.ok(frames <= 39, 'max speed took ' + frames + ' frames');
});

test('max speed chunks large datasets so a 100k-bar replay stays responsive', () => {
  const payload = makePayload();
  const big = [];
  for (let i = 0; i < 3000; i += 1) {
    big.push({
      time: START + i * STEP, open: 2000, high: 2001, low: 1999, close: 2000, volume: 1
    });
  }
  payload.candles = big;
  payload.trades = [];
  payload.zones = [];
  payload.equity_curve = [];

  const ctrl = controller();
  ctrl.load(payload);
  ctrl.setSpeed('max');
  ctrl.play();
  let frames = 0;
  while (ctrl.getState() === STATES.PLAYING && frames < 1000) {
    ctrl.pump(16);
    frames += 1;
  }
  assert.equal(ctrl.getIndex(), 2999);
  // Max is "as fast as the renderer allows", not "one frame": the dataset is
  // consumed in bounded chunks (~4 s at 60 FPS), never in a single jump.
  assert.ok(frames > 1, 'max speed must not teleport in one frame');
  assert.ok(frames <= 260, 'max speed took ' + frames + ' frames for 3000 bars');
});

test('max speed pacing follows wall-clock time, not the frame count', () => {
  // Regression: the chunk used to be a fixed 1/totalBars of the session per
  // frame, so a slow renderer (headless Chrome fires rAF ~8x/second) stretched
  // a 60k-bar sweep to ~40 s instead of the intended few seconds. Drive the
  // same dataset with 16 ms and 125 ms frames and compare elapsed wall time.
  function sweep(frameMs) {
    const payload = makePayload();
    const big = [];
    for (let i = 0; i < 6000; i += 1) {
      big.push({
        time: START + i * STEP, open: 2000, high: 2001, low: 1999, close: 2000, volume: 1
      });
    }
    payload.candles = big;
    payload.trades = [];
    payload.zones = [];
    payload.equity_curve = [];

    const ctrl = controller();
    ctrl.load(payload);
    ctrl.setSpeed('max');
    ctrl.play();
    let elapsed = 0;
    let frames = 0;
    while (ctrl.getState() === STATES.PLAYING && frames < 5000) {
      ctrl.pump(frameMs);
      elapsed += frameMs;
      frames += 1;
    }
    assert.equal(ctrl.getIndex(), 5999);
    return { elapsed, frames };
  }

  const fast = sweep(16);
  const slow = sweep(125);
  // Both finish inside the 4 s sweep budget plus one frame of slack.
  assert.ok(fast.elapsed <= 4000 + 16, 'fast sweep took ' + fast.elapsed + ' ms');
  assert.ok(slow.elapsed <= 4000 + 125, 'slow sweep took ' + slow.elapsed + ' ms');
  // The slow renderer needs far fewer frames for the same wall-clock budget.
  assert.ok(
    slow.frames < fast.frames,
    'slow renderer used ' + slow.frames + ' frames vs ' + fast.frames
  );
});

test('invalid speed values are ignored', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.setSpeed(5);
  assert.equal(ctrl.setSpeed(0), 5);
  assert.equal(ctrl.setSpeed(-2), 5);
  assert.equal(ctrl.setSpeed('nope'), 5);
  assert.equal(ctrl.getSpeed(), 5);
});

// -------------------------------------------------------------------- seeking

test('seekToRatio maps 0..1 onto the bar range', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  assert.equal(ctrl.seekToRatio(0).index, 0);
  assert.equal(ctrl.seekToRatio(0.5).index, 20);
  assert.equal(ctrl.seekToRatio(1).index, 39);
  assert.equal(ctrl.getState(), STATES.PAUSED);
});

test('seekToTime snaps to the bar containing the timestamp', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  const snap = ctrl.seekToTime(START + 5 * STEP + 30); // mid-bar
  assert.equal(snap.index, 5);
  assert.equal(snap.candle.time, START + 5 * STEP);
});

// --------------------------------------------------------- trade navigation

test('nextTrade jumps to the first entry after the cursor', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  // Payload trades enter at bars 10 and 20.
  assert.equal(ctrl.nextTrade().index, 10);
  assert.equal(ctrl.nextTrade().index, 20);
  // Already at the last entry: no further jump, cursor unchanged.
  assert.equal(ctrl.nextTrade().index, 20);
});

test('prevTrade rewinds to the previous entry, not the current one', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.seekToIndex(20); // sitting on T-002's entry bar
  const back = ctrl.prevTrade();
  assert.equal(back.index, 10, 'must step back to T-001, not stay on T-002');
  // Before the first entry there is nothing to rewind to.
  assert.equal(ctrl.prevTrade().index, 10);
});

test('prevTrade from a mid-hold bar lands on that trade entry', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.seekToIndex(24); // inside T-002's hold (20..26)
  assert.equal(ctrl.prevTrade().index, 20);
});

test('seekToTrade accepts a trade id, object and index', () => {
  const ctrl = controller();
  const payload = makePayload();
  ctrl.load(payload);
  assert.equal(ctrl.seekToTrade('T-002').index, 20);
  assert.equal(ctrl.seekToTrade(payload.trades[0]).index, 10);
  assert.equal(ctrl.seekToTrade(1).index, 20);
  // Unknown ids are a no-op rather than a jump to bar 0.
  assert.equal(ctrl.seekToTrade('T-999').index, 20);
});

test('trade navigation skips idle bars entirely', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  const seen = [];
  for (let i = 0; i < 2; i += 1) seen.push(ctrl.nextTrade().index);
  // Two trades -> exactly two hops, regardless of the 40-bar span.
  assert.deepEqual(seen, [10, 20]);
  assert.equal(ctrl.getState(), STATES.PAUSED);
});

test('snapshot exposes nextTrade and prevTrade around the cursor', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.seekToIndex(15); // between the two entries
  let snap = ctrl.snapshot();
  assert.equal(snap.prevTrade.trade_id, 'T-001');
  assert.equal(snap.nextTrade.trade_id, 'T-002');

  ctrl.seekToIndex(0); // before any entry
  snap = ctrl.snapshot();
  assert.equal(snap.prevTrade, null);
  assert.equal(snap.nextTrade.trade_id, 'T-001');

  ctrl.seekToIndex(39); // after both entries
  snap = ctrl.snapshot();
  assert.equal(snap.prevTrade.trade_id, 'T-002');
  assert.equal(snap.nextTrade, null);
});

test('seeking backwards rewinds derived state exactly', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.seekToIndex(30);
  assert.equal(ctrl.snapshot().closedTrades, 2);
  ctrl.seekToIndex(15);
  const snap = ctrl.snapshot();
  assert.equal(snap.closedTrades, 1);
  assert.equal(snap.openTrades, 0);
  assert.equal(snap.balance, 10430);
  assert.equal(snap.realizedPnl, 430);
});

test('seeking while playing keeps playing', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.play();
  ctrl.seekToIndex(8);
  assert.equal(ctrl.getState(), STATES.PLAYING);
});

// ------------------------------------------------------------ derived metrics

test('floating PnL tracks the active trade and disappears on exit', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  ctrl.seekToIndex(11);
  let snap = ctrl.snapshot();
  assert.equal(snap.openTrades, 1);
  const trade = snap.active[0].trade;
  assert.equal(trade.trade_id, 'T-001');
  // close at bar 11 = 2012, entry 2011, 1.0 lot, 100 oz -> +100 gross, -20 spread
  assert.ok(Math.abs(snap.active[0].floating - 80) < 1e-6);
  assert.equal(snap.equity, snap.balance + snap.floatingPnl);

  ctrl.seekToIndex(14);
  snap = ctrl.snapshot();
  assert.equal(snap.openTrades, 0);
  assert.equal(snap.floatingPnl, 0);
});

test('closed trades, win rate and drawdown accumulate in exit order', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  let snap = ctrl.snapshot();
  snap = ctrl.seekToIndex(14);
  assert.equal(snap.closedTrades, 1);
  assert.equal(snap.wins, 1);
  assert.equal(snap.winRate, 100);
  assert.equal(snap.balance, 10430);

  snap = ctrl.seekToIndex(26);
  assert.equal(snap.closedTrades, 2);
  assert.equal(snap.wins, 1);
  assert.equal(snap.winRate, 50);
  assert.equal(snap.balance, 10110);
  assert.ok(snap.maxDrawdownPct > 3.0 && snap.maxDrawdownPct < 3.2);
});

test('entry bar shows only the spread cost as floating PnL', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  // The trade fills at the close of its entry bar, so at bar 10 the position is
  // open but has zero price excursion: only the round-turn spread is deducted.
  const snap = ctrl.seekToIndex(10);
  assert.equal(snap.openTrades, 1);
  assert.ok(Math.abs(snap.active[0].floating + 20) < 1e-6);
  assert.equal(snap.closedTrades, 0);
});

test('lastClosed exposes the most recent exit for the HUD', () => {
  const ctrl = controller();
  ctrl.load(makePayload());
  const snap = ctrl.seekToIndex(20);
  assert.equal(snap.lastClosed.trade_id, 'T-001');
  assert.equal(snap.lastClosed.outcome, 'WIN');
});

test('utc timestamps format without local-timezone drift', () => {
  assert.equal(engine.formatUtc(0), '1970-01-01 00:00 UTC');
  assert.equal(engine.formatUtc(START), '2024-11-01 00:00 UTC');
});

// -------------------------------------------------------------------- events

test('frame events fire on every index change', () => {
  const ctrl = controller();
  const frames = [];
  ctrl.on('frame', (snap) => frames.push(snap.index));
  ctrl.load(makePayload());
  const initial = frames.length;
  ctrl.step(1);
  ctrl.step(1);
  assert.equal(frames.length, initial + 2);
});

test('state events announce transitions', () => {
  const ctrl = controller();
  const seen = [];
  ctrl.on('state', (payload) => seen.push(payload.state));
  ctrl.load(makePayload());
  ctrl.play();
  ctrl.pause();
  assert.deepEqual(seen, [STATES.PLAYING, STATES.PAUSED]);
});

test('unsubscribe stops delivery', () => {
  const ctrl = controller();
  let calls = 0;
  const off = ctrl.on('frame', () => { calls += 1; });
  ctrl.load(makePayload());
  const baseline = calls;
  off();
  ctrl.step(1);
  assert.equal(calls, baseline);
});

test('a throwing listener cannot break the clock', () => {
  const ctrl = controller();
  const originalError = console.error;
  console.error = () => {};
  ctrl.on('frame', () => { throw new Error('boom'); });
  try {
    ctrl.load(makePayload());
    ctrl.step(1);
    assert.equal(ctrl.getIndex(), 1);
  } finally {
    console.error = originalError;
  }
});

// ------------------------------------------------------------ trade-level math

test('tradePnlAt respects side, lot size and spread cost', () => {
  const buy = { side: 'BUY', entry_price: 2000, lot: 1 };
  assert.equal(engine.tradePnlAt(buy, 2001), 80); // +100 gross, -20 spread
  const sell = { side: 'SELL', entry_price: 2000, lot: 0.5 };
  assert.equal(engine.tradePnlAt(sell, 1999), 40); // +50 gross, -10 spread
});
