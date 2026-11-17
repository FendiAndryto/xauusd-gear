const test = require('node:test');
const assert = require('node:assert/strict');

const SmcReplayStorage = require('../../src/assistant/static/js/replay_storage.js');

test('T-SIM-08 Storage: formatKey enforces strict month:02d zero-padding', () => {
  assert.equal(
    SmcReplayStorage.formatKey('xauusd_replay_drawings_v1_', 'XAUUSD', 2026, 10),
    'xauusd_replay_drawings_v1_XAUUSD_2026_10'
  );
  assert.equal(
    SmcReplayStorage.formatKey('xauusd_replay_drawings_v1_', 'XAUUSD', 2026, 1),
    'xauusd_replay_drawings_v1_XAUUSD_2026_01'
  );
  assert.equal(
    SmcReplayStorage.formatKey('xauusd_replay_drawings_v1_', 'xauusd', '2025', '7'),
    'xauusd_replay_drawings_v1_XAUUSD_2025_07'
  );
});

test('T-SIM-08 Storage: Safe get/set operations with mock localStorage', () => {
  const store = {};
  global.localStorage = {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; }
  };

  const sampleDrawings = [
    { id: 'draw_1', type: 'hline', price: 4000.5 },
    { id: 'draw_2', type: 'rect', t1: 1000, p1: 4000, t2: 2000, p2: 4010 }
  ];

  // Save & Load Drawings
  const saveOk = SmcReplayStorage.saveDrawings('XAUUSD', 2026, 10, sampleDrawings);
  assert.equal(saveOk, true);

  const loaded = SmcReplayStorage.loadDrawings('XAUUSD', 2026, 10);
  assert.equal(loaded.length, 2);
  assert.equal(loaded[0].price, 4000.5);

  // Different month returns empty array
  const emptyOtherMonth = SmcReplayStorage.loadDrawings('XAUUSD', 2026, 9);
  assert.deepEqual(emptyOtherMonth, []);

  // Save & Load Positions
  const samplePositions = [
    { id: 'pos_1', side: 'BUY', entryPrice: 4000.0, sl: 3998.0, tp: 4004.0, lot: 0.10 }
  ];
  SmcReplayStorage.savePositions('XAUUSD', 2026, 10, samplePositions);
  const loadedPos = SmcReplayStorage.loadPositions('XAUUSD', 2026, 10);
  assert.equal(loadedPos.length, 1);
  assert.equal(loadedPos[0].side, 'BUY');

  // Clear all
  SmcReplayStorage.clearAll('XAUUSD', 2026, 10);
  assert.deepEqual(SmcReplayStorage.loadDrawings('XAUUSD', 2026, 10), []);
  assert.deepEqual(SmcReplayStorage.loadPositions('XAUUSD', 2026, 10), []);
});

test('T-SIM-08 Storage: Gracefully degrades when localStorage throws', () => {
  global.localStorage = {
    getItem: () => { throw new Error('SecurityError: localStorage blocked'); },
    setItem: () => { throw new Error('QuotaExceededError'); },
    removeItem: () => { throw new Error('Blocked'); }
  };

  assert.doesNotThrow(() => {
    const res = SmcReplayStorage.loadDrawings('XAUUSD', 2026, 10);
    assert.deepEqual(res, []);
  });

  assert.doesNotThrow(() => {
    const saved = SmcReplayStorage.saveDrawings('XAUUSD', 2026, 10, [{ type: 'hline' }]);
    assert.equal(saved, false);
  });
});
