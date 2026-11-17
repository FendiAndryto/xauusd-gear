/**
 * Unit tests for SmcReplayDrawings price action tools engine (Fase 3: T-SIM-05A, 05B, 05C).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const SmcReplayDrawings = require('../../src/assistant/static/js/replay_drawings.js');

function mockCanvasApi() {
  let activeTool = 'cursor';
  let selectionActive = false;
  let cursor = 'default';
  let redrawCount = 0;
  const toolListeners = [];
  const pointerListeners = [];
  const renderers = [];

  return {
    getActiveTool: () => activeTool,
    setTool: (t) => {
      activeTool = t;
      toolListeners.forEach((fn) => fn(t));
    },
    onToolChange: (fn) => toolListeners.push(fn),
    onPointer: (fn) => pointerListeners.push(fn),
    setSelectionActive: (act) => { selectionActive = act; },
    isSelectionActive: () => selectionActive,
    setCursor: (c) => { cursor = c; },
    getCursor: () => cursor,
    requestRedraw: () => { redrawCount += 1; },
    getRedrawCount: () => redrawCount,
    registerRenderer: (r) => renderers.push(r),
    unregisterRenderer: (r) => {
      const idx = renderers.indexOf(r);
      if (idx !== -1) renderers.splice(idx, 1);
    },
    getCanvas: () => ({ width: 1000, height: 600 }),
    _emitPointer: (payload) => {
      pointerListeners.forEach((fn) => fn(payload));
    }
  };
}

function mockChartApi() {
  const clickListeners = [];
  return {
    timeToCoordinate: (t) => t * 0.1,
    coordinateToTime: (x) => x * 10,
    priceToCoordinate: (p) => (3000 - p) * 2,
    coordinateToPrice: (y) => 3000 - y / 2,
    subscribeClick: (fn) => clickListeners.push(fn),
    _emitClick: (param) => clickListeners.forEach((fn) => fn(param))
  };
}

test('drawing collection CRUD operations', () => {
  const canvasApi = mockCanvasApi();
  const chartApi = mockChartApi();
  const drawingsApi = SmcReplayDrawings.init({ canvasApi, chartApi });

  assert.deepEqual(drawingsApi.getDrawings(), []);

  const d1 = drawingsApi.addDrawing({
    type: 'hline',
    price: 2740.500
  });
  assert.ok(d1.id);
  assert.equal(d1.type, 'hline');
  assert.equal(drawingsApi.getDrawings().length, 1);
  assert.equal(drawingsApi.getDrawingById(d1.id), d1);

  const d2 = drawingsApi.addDrawing({
    type: 'rect',
    t1: 1000,
    p1: 2750.0,
    t2: 2000,
    p2: 2740.0
  });
  assert.equal(drawingsApi.getDrawings().length, 2);

  const removed = drawingsApi.removeDrawing(d1.id);
  assert.equal(removed.id, d1.id);
  assert.equal(drawingsApi.getDrawings().length, 1);
  assert.equal(drawingsApi.getDrawingById(d1.id), null);

  const clearedCount = drawingsApi.clearDrawings();
  assert.equal(clearedCount, 1);
  assert.deepEqual(drawingsApi.getDrawings(), []);
  drawingsApi.destroy();
});

test('T-SIM-05A: H-Line single-click commits at price and triggers onCommit', () => {
  const canvasApi = mockCanvasApi();
  const chartApi = mockChartApi();
  const committed = [];

  const drawingsApi = SmcReplayDrawings.init({
    canvasApi,
    chartApi,
    onCommit: (item) => committed.push(item)
  });

  canvasApi.setTool('hline');

  // Hover move
  canvasApi._emitPointer({ type: 'pointermove', x: 250, y: 300, time: 2500, price: 2850.1234 });
  assert.equal(drawingsApi.getDrawings().length, 0);

  // Click down
  canvasApi._emitPointer({ type: 'pointerdown', x: 250, y: 300, time: 2500, price: 2850.1234 });
  assert.equal(drawingsApi.getDrawings().length, 1);
  assert.equal(committed.length, 1);
  assert.equal(committed[0].type, 'hline');
  assert.equal(committed[0].price, 2850.123);
  drawingsApi.destroy();
});

test('T-SIM-05A: Rectangle drag commits normalized zone box with rubber-band preview', () => {
  const canvasApi = mockCanvasApi();
  const chartApi = mockChartApi();
  const committed = [];

  const drawingsApi = SmcReplayDrawings.init({
    canvasApi,
    chartApi,
    onCommit: (item) => committed.push(item)
  });

  canvasApi.setTool('rect');

  // Drag start
  canvasApi._emitPointer({ type: 'pointerdown', x: 100, y: 200, time: 1000, price: 2900.0 });
  // Drag move
  canvasApi._emitPointer({ type: 'pointermove', x: 250, y: 350, time: 2500, price: 2825.0 });
  // Drag end
  canvasApi._emitPointer({ type: 'pointerup', x: 250, y: 350, time: 2500, price: 2825.0 });

  assert.equal(drawingsApi.getDrawings().length, 1);
  assert.equal(committed.length, 1);
  const rect = committed[0];
  assert.equal(rect.type, 'rect');
  assert.equal(rect.t1, 1000);
  assert.equal(rect.t2, 2500);
  assert.equal(rect.p1, 2900.0);
  assert.equal(rect.p2, 2825.0);
  drawingsApi.destroy();
});

test('T-SIM-05B: Trendline 2-click commits diagonal trendline', () => {
  const canvasApi = mockCanvasApi();
  const chartApi = mockChartApi();
  const committed = [];

  const drawingsApi = SmcReplayDrawings.init({
    canvasApi,
    chartApi,
    onCommit: (item) => committed.push(item)
  });

  canvasApi.setTool('trendline');

  // 1st click
  canvasApi._emitPointer({ type: 'pointerdown', x: 100, y: 200, time: 1000, price: 2900.0 });
  canvasApi._emitPointer({ type: 'pointerup', x: 100, y: 200, time: 1000, price: 2900.0 });
  assert.equal(drawingsApi.getDrawings().length, 0, 'pending second click');

  // Move
  canvasApi._emitPointer({ type: 'pointermove', x: 300, y: 150, time: 3000, price: 2925.0 });

  // 2nd click
  canvasApi._emitPointer({ type: 'pointerdown', x: 300, y: 150, time: 3000, price: 2925.0 });
  assert.equal(drawingsApi.getDrawings().length, 1);
  assert.equal(committed.length, 1);
  const trend = committed[0];
  assert.equal(trend.type, 'trendline');
  assert.equal(trend.t1, 1000);
  assert.equal(trend.p1, 2900.0);
  assert.equal(trend.t2, 3000);
  assert.equal(trend.p2, 2925.0);
  drawingsApi.destroy();
});

test('T-SIM-05B: Transient ruler does not add to drawings and clears on subsequent click', () => {
  const canvasApi = mockCanvasApi();
  const chartApi = mockChartApi();

  const drawingsApi = SmcReplayDrawings.init({
    canvasApi,
    chartApi,
    getCandles: () => [
      { time: 1000 }, { time: 1300 }, { time: 1600 }, { time: 1900 }, { time: 2200 }
    ]
  });

  canvasApi.setTool('ruler');

  canvasApi._emitPointer({ type: 'pointerdown', x: 100, y: 200, time: 1000, price: 2900.0 });
  canvasApi._emitPointer({ type: 'pointermove', x: 220, y: 100, time: 2200, price: 2950.0 });
  canvasApi._emitPointer({ type: 'pointerup', x: 220, y: 100, time: 2200, price: 2950.0 });

  // Ruler is transient: drawings array remains empty
  assert.equal(drawingsApi.getDrawings().length, 0);

  // Subsequent click clears ruler
  canvasApi._emitPointer({ type: 'pointerdown', x: 50, y: 50, time: 500, price: 2975.0 });
  assert.equal(drawingsApi.getDrawings().length, 0);
  drawingsApi.destroy();
});

test('T-SIM-05C: Hit testing, selection via subscribeClick, move and Delete key', () => {
  const canvasApi = mockCanvasApi();
  const chartApi = mockChartApi();

  const drawingsApi = SmcReplayDrawings.init({ canvasApi, chartApi });

  const hline = drawingsApi.addDrawing({
    type: 'hline',
    price: 2800.0 // priceToCoordinate = (3000 - 2800) * 2 = 400
  });

  canvasApi.setTool('cursor');
  assert.equal(canvasApi.isSelectionActive(), false);
  assert.equal(drawingsApi.getSelectedId(), null);

  // Click far away: no selection
  chartApi._emitClick({ point: { x: 500, y: 200 } });
  assert.equal(drawingsApi.getSelectedId(), null);
  assert.equal(canvasApi.isSelectionActive(), false);

  // Click near hline at y=402 (tolerance is 8px)
  chartApi._emitClick({ point: { x: 500, y: 402 } });
  assert.equal(drawingsApi.getSelectedId(), hline.id);
  assert.equal(canvasApi.isSelectionActive(), true);

  // Anchor handles exist
  const handles = drawingsApi.getAnchorHandles(hline, 1000, 600);
  assert.ok(handles.length >= 3);
  assert.equal(handles[0].y, 400);

  // Move selected hline via pointer drag
  canvasApi._emitPointer({
    type: 'pointerdown',
    x: 500,
    y: 400,
    time: 5000,
    price: 2800.0
  });
  canvasApi._emitPointer({
    type: 'pointermove',
    x: 500,
    y: 380, // moved up 20px -> coordinateToPrice(380) = 3000 - 190 = 2810.0
    time: 5000,
    price: 2810.0
  });
  canvasApi._emitPointer({ type: 'pointerup', x: 500, y: 380 });

  assert.equal(hline.price, 2810.0);

  // Delete selected drawing
  const deletedId = drawingsApi.deleteSelected();
  assert.equal(deletedId, hline.id);
  assert.equal(drawingsApi.getDrawings().length, 0);
  assert.equal(drawingsApi.getSelectedId(), null);
  assert.equal(canvasApi.isSelectionActive(), false);
  drawingsApi.destroy();
});
