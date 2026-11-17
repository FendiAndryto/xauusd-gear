const test = require('node:test');
const assert = require('node:assert/strict');

const SmcReplayLedger = require('../../src/assistant/static/js/replay_ledger.js');
const SmcReplaySimulator = require('../../src/assistant/static/js/replay_simulator.js');

function createMockChartApi() {
  const timeCoords = { 1000: 50, 1300: 100, 1600: 150, 1900: 200, 2200: 250 };
  const priceCoords = { 4000: 300, 4004: 260, 3998: 320, 4010: 200, 3990: 400 };

  return {
    timeToCoordinate: (t) => timeCoords[t] ?? (50 + (t - 1000) * 0.166),
    coordinateToTime: (x) => 1000 + Math.round((x - 50) / 0.166),
    priceToCoordinate: (p) => priceCoords[p] ?? (300 - (p - 4000) * 10),
    coordinateToPrice: (y) => 4000 - (y - 300) / 10,
    subscribeClick: () => {}
  };
}

function createMockCanvasApi() {
  let tool = 'cursor';
  let selectionActive = false;
  let cursor = 'default';
  let redrawCount = 0;
  const renderers = [];
  const pointerListeners = [];
  const toolListeners = [];

  return {
    getActiveTool: () => tool,
    setTool: (t) => {
      tool = t;
      toolListeners.forEach((fn) => fn(t));
    },
    setSelectionActive: (s) => { selectionActive = s; },
    isSelectionActive: () => selectionActive,
    setCursor: (c) => { cursor = c; },
    getCursor: () => cursor,
    registerRenderer: (r) => { renderers.push(r); },
    unregisterRenderer: (r) => {
      const idx = renderers.indexOf(r);
      if (idx !== -1) renderers.splice(idx, 1);
    },
    onPointer: (fn) => { pointerListeners.push(fn); },
    onToolChange: (fn) => { toolListeners.push(fn); },
    requestRedraw: () => { redrawCount += 1; },
    getRedrawCount: () => redrawCount,
    emitPointer: (payload) => { pointerListeners.forEach((fn) => fn(payload)); }
  };
}

test('T-SIM-07 Ledger: Lot validation and constraints', () => {
  assert.equal(SmcReplayLedger.validateLot(0.10), 0.10);
  assert.equal(SmcReplayLedger.validateLot(0.01), 0.01);
  assert.equal(SmcReplayLedger.validateLot(5.00), 5.00);
  assert.equal(SmcReplayLedger.validateLot(2.555), 2.56);

  // Outside valid range (0.01 to 5.00)
  assert.equal(SmcReplayLedger.validateLot(0.005), null);
  assert.equal(SmcReplayLedger.validateLot(0), null);
  assert.equal(SmcReplayLedger.validateLot(-1), null);
  assert.equal(SmcReplayLedger.validateLot(5.01), null);
  assert.equal(SmcReplayLedger.validateLot(10.0), null);
  assert.equal(SmcReplayLedger.validateLot(NaN), null);
  assert.equal(SmcReplayLedger.validateLot('0.10'), null);
});

test('T-SIM-07 Ledger: Financial math dimensions for BUY & SELL with spread deduction', () => {
  // BUY: Entry 4000, Exit 4004 (+4.00), Lot 0.10, Spread $0.20/oz
  // Gross = 4.00 * 0.10 * 100 = $40.00
  // Spread = 0.20 * 0.10 * 100 = $2.00
  // Net = $38.00, Pips = 40.0
  const buyPnl = SmcReplayLedger.calculatePnl({
    side: 'BUY',
    entryPrice: 4000.0,
    exitPrice: 4004.0,
    lot: 0.10,
    spreadPerOz: 0.20
  });
  assert.equal(buyPnl.priceDiff, 4.0);
  assert.equal(buyPnl.grossPnl, 40.0);
  assert.equal(buyPnl.spreadCost, 2.0);
  assert.equal(buyPnl.netPnl, 38.0);
  assert.equal(buyPnl.pips, 40.0);

  // SELL: Entry 4000, Exit 4004 (-4.00), Lot 0.10, Spread $0.20/oz
  // Gross = -4.00 * 0.10 * 100 = -$40.00
  // Spread = $2.00
  // Net = -$42.00, Pips = -40.0
  const sellPnl = SmcReplayLedger.calculatePnl({
    side: 'SELL',
    entryPrice: 4000.0,
    exitPrice: 4004.0,
    lot: 0.10,
    spreadPerOz: 0.20
  });
  assert.equal(sellPnl.priceDiff, -4.0);
  assert.equal(sellPnl.grossPnl, -40.0);
  assert.equal(sellPnl.spreadCost, 2.0);
  assert.equal(sellPnl.netPnl, -42.0);
  assert.equal(sellPnl.pips, -40.0);

  // Risk/Reward ratio calculation:
  // Entry 4000, SL 3998 (Risk 2.00), TP 4004 (Reward 4.00), Lot 0.10
  const rr = SmcReplayLedger.calculateRiskReward({
    side: 'BUY',
    entryPrice: 4000.0,
    sl: 3998.0,
    tp: 4004.0,
    lot: 0.10
  });
  assert.equal(rr.riskUsd, 20.0);
  assert.equal(rr.rewardUsd, 40.0);
  assert.equal(rr.riskPips, 20.0);
  assert.equal(rr.rewardPips, 40.0);
  assert.equal(rr.ratio, 2.0);
});

test('T-SIM-07 Ledger: Compounding equity, peak tracking, and max drawdown', () => {
  const ledger = SmcReplayLedger.create({ initialBalance: 10000.0, spreadPerOz: 0.20 });
  assert.equal(ledger.getBalance(), 10000.0);
  assert.equal(ledger.getEquity(), 10000.0);

  // Win 1: +$38.00 Net
  ledger.recordTrade({
    side: 'BUY',
    entryPrice: 4000.0,
    exitPrice: 4004.0,
    lot: 0.10,
    sl: 3998.0,
    tp: 4004.0
  });
  assert.equal(ledger.getBalance(), 10038.0);
  assert.equal(ledger.getEquity(), 10038.0);

  // Loss 1: -$22.00 Net (Loss 2.00 * 10 + 2 spread)
  ledger.recordTrade({
    side: 'BUY',
    entryPrice: 4000.0,
    exitPrice: 3998.0,
    lot: 0.10,
    sl: 3998.0,
    tp: 4004.0
  });
  assert.equal(ledger.getBalance(), 10016.0);
  assert.equal(ledger.getEquity(), 10016.0);

  const summary = ledger.getSummary();
  assert.equal(summary.totalTrades, 2);
  assert.equal(summary.winningTrades, 1);
  assert.equal(summary.losingTrades, 1);
  assert.equal(summary.winRate, 50.0);
  assert.equal(summary.grossProfit, 38.0);
  assert.equal(summary.grossLoss, 22.0);
  assert.equal(summary.netProfit, 16.0);
  assert.equal(summary.profitFactor, 1.73);
  // Max DD from peak $10038 to $10016 = (22 / 10038) * 100 = 0.22%
  assert.equal(summary.maxDrawdownPct, 0.22);
});

test('T-SIM-06 Simulator: Placement of Long and Short position boxes with auto R:R', () => {
  const chartApi = createMockChartApi();
  const canvasApi = createMockCanvasApi();
  const sim = SmcReplaySimulator.init({
    chartApi,
    canvasApi,
    getCandles: () => [
      { time: 1000, open: 4000, high: 4002, low: 3999, close: 4001 },
      { time: 1300, open: 4001, high: 4003, low: 4000, close: 4002 }
    ],
    getCurrentBar: () => ({ index: 1, time: 1300, close: 4002 })
  });

  // Switch to long_pos tool and click
  canvasApi.setTool('long_pos');
  canvasApi.emitPointer({ type: 'pointerdown', x: 100, y: 300, time: 1300, price: 4000.0 });

  const active = sim.getActivePosition();
  assert.ok(active);
  assert.equal(active.side, 'BUY');
  assert.equal(active.status, 'ACTIVE');
  assert.equal(active.entryPrice, 4000.0);
  assert.equal(active.sl, 3998.0);
  assert.equal(active.tp, 4004.0);
  assert.equal(active.lot, 0.10);
  assert.equal(active.entryBarIndex, 1);

  // Position is selected and selectionActive is armed
  assert.equal(sim.getSelectedId(), active.id);
  assert.equal(canvasApi.isSelectionActive(), true);
});

test('T-SIM-07 Simulator: Anti Look-Ahead prevention', () => {
  const chartApi = createMockChartApi();
  const canvasApi = createMockCanvasApi();
  const sim = SmcReplaySimulator.init({
    chartApi,
    canvasApi,
    getCurrentBar: () => ({ index: 5, time: 2000, close: 4000.0 })
  });

  const pos = sim.addPosition({
    side: 'BUY',
    status: 'ACTIVE',
    entryPrice: 4000.0,
    sl: 3998.0,
    tp: 4004.0,
    lot: 0.10,
    entryTime: 2000,
    entryBarIndex: 5,
    targetTime: 2600
  });

  // Candle at barIndex 5 (same candle where trade was opened while paused)
  // Even if high reaches 4010 and low hits 3990, it must be ignored by Anti Look-Ahead
  const res1 = sim.evaluateCandle({ time: 2000, open: 4000, high: 4010, low: 3990, close: 4005 }, 5);
  assert.equal(res1, null);
  assert.equal(pos.status, 'ACTIVE');

  // Next candle at barIndex 6 is evaluated normally!
  const res2 = sim.evaluateCandle({ time: 2300, open: 4000, high: 4005, low: 3999, close: 4004 }, 6);
  assert.ok(res2);
  assert.equal(pos.status, 'TP_HIT');
  assert.equal(pos.exitPrice, 4004.0);
});

test('T-SIM-07 Simulator: Normal TP Hit and SL Hit', () => {
  const chartApi = createMockChartApi();
  const canvasApi = createMockCanvasApi();
  const sim = SmcReplaySimulator.init({ chartApi, canvasApi });

  // 1. Long TP Hit
  const pos1 = sim.addPosition({
    side: 'BUY',
    status: 'ACTIVE',
    entryPrice: 4000.0,
    sl: 3998.0,
    tp: 4004.0,
    lot: 0.10,
    entryTime: 1000,
    entryBarIndex: 0,
    targetTime: 2000
  });

  sim.evaluateCandle({ time: 1300, high: 4004.5, low: 3999.0, close: 4004.0 }, 1);
  assert.equal(pos1.status, 'TP_HIT');
  assert.equal(pos1.exitPrice, 4004.0);
  assert.equal(sim.getActivePosition(), null);

  // 2. Short SL Hit
  const pos2 = sim.addPosition({
    side: 'SELL',
    status: 'ACTIVE',
    entryPrice: 4000.0,
    sl: 4002.0,
    tp: 3996.0,
    lot: 0.10,
    entryTime: 2000,
    entryBarIndex: 2,
    targetTime: 3000
  });

  sim.evaluateCandle({ time: 2300, high: 4003.0, low: 3999.0, close: 4002.5 }, 3);
  assert.equal(pos2.status, 'SL_HIT');
  assert.equal(pos2.exitPrice, 4002.0);
  assert.equal(sim.getActivePosition(), null);
});

test('T-SIM-07 Simulator: Pessimistic Tie-Break strictly executes SL HIT (Loss)', () => {
  const chartApi = createMockChartApi();
  const canvasApi = createMockCanvasApi();
  const sim = SmcReplaySimulator.init({ chartApi, canvasApi });

  // BUY position: Entry 4000, SL 3998, TP 4004
  const buyPos = sim.addPosition({
    side: 'BUY',
    status: 'ACTIVE',
    entryPrice: 4000.0,
    sl: 3998.0,
    tp: 4004.0,
    lot: 0.10,
    entryTime: 1000,
    entryBarIndex: 0,
    targetTime: 2000
  });

  // Candle spans High 4005 (>= TP) AND Low 3997 (<= SL)
  const tieBreakCandle = { time: 1300, open: 4000, high: 4005.0, low: 3997.0, close: 4001.0 };
  const res = sim.evaluateCandle(tieBreakCandle, 1);

  assert.ok(res);
  assert.equal(buyPos.status, 'SL_HIT');
  assert.equal(buyPos.exitPrice, 3998.0);
  assert.ok(buyPos.exitReason.includes('TIE_BREAK_PESSIMISTIC'));
  assert.equal(sim.getActivePosition(), null);

  // SELL position: Entry 4000, SL 4002, TP 3996
  const sellPos = sim.addPosition({
    side: 'SELL',
    status: 'ACTIVE',
    entryPrice: 4000.0,
    sl: 4002.0,
    tp: 3996.0,
    lot: 0.10,
    entryTime: 2000,
    entryBarIndex: 2,
    targetTime: 3000
  });

  // Candle spans High 4003 (>= SL) AND Low 3995 (<= TP)
  const resSell = sim.evaluateCandle({ time: 2300, open: 4000, high: 4003.0, low: 3995.0, close: 3998.0 }, 3);
  assert.ok(resSell);
  assert.equal(sellPos.status, 'SL_HIT');
  assert.equal(sellPos.exitPrice, 4002.0);
  assert.ok(sellPos.exitReason.includes('TIE_BREAK_PESSIMISTIC'));
});

test('T-SIM-07 Simulator: Manual Close via closePosition / key C', () => {
  const chartApi = createMockChartApi();
  const canvasApi = createMockCanvasApi();
  const sim = SmcReplaySimulator.init({ chartApi, canvasApi });

  const pos = sim.addPosition({
    side: 'BUY',
    status: 'ACTIVE',
    entryPrice: 4000.0,
    sl: 3990.0,
    tp: 4020.0,
    lot: 0.10,
    entryTime: 1000,
    entryBarIndex: 0,
    targetTime: 2000
  });

  // Current active candle is at 4003.50
  const candle = { time: 1500, close: 4003.50 };
  const closed = sim.closePosition(candle);

  assert.ok(closed);
  assert.equal(closed.status, 'WIN_MANUAL');
  assert.equal(closed.exitPrice, 4003.50);
  assert.ok(closed.exitReason.includes('MANUAL_CLOSE'));
  assert.equal(sim.getActivePosition(), null);

  // Ledger contains the realized trade with net PnL: +3.50 * 10 - $2 = $33.00
  const summary = sim.getLedger().getSummary();
  assert.equal(summary.totalTrades, 1);
  assert.equal(summary.trades[0].netPnl, 33.0);
});
