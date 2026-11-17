/**
 * Unit tests for SmcReplayCanvas overlay manager (T-SIM-04).
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const SmcReplayCanvas = require('../../src/assistant/static/js/replay_canvas.js');

function mockElement(tag) {
  const classList = new Set();
  const handlers = {};
  return {
    tagName: tag || 'div',
    handlers,
    classList: {
      add: (c) => classList.add(c),
      remove: (c) => classList.delete(c),
      contains: (c) => classList.has(c)
    },
    style: {},
    addEventListener: (type, fn) => { handlers[type] = fn; },
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    getBoundingClientRect: () => ({ width: 1000, height: 600, top: 0, left: 0 }),
    parentElement: null,
    getContext: () => ({
      clearRect: () => {},
      setTransform: () => {},
      scale: () => {}
    })
  };
}

test('initializes with default tool cursor and pointer-events none', () => {
  const canvas = mockElement('canvas');
  const container = mockElement('div');
  canvas.parentElement = container;

  const api = SmcReplayCanvas.init({ canvas, container });
  assert.equal(api.getActiveTool(), 'cursor');
  assert.equal(canvas.style.pointerEvents, 'none');
  assert.equal(canvas.classList.contains('is-drawing'), false);
  api.destroy();
});

test('switching tool changes active tool and pointer-events', () => {
  const canvas = mockElement('canvas');
  const container = mockElement('div');
  const events = [];

  const api = SmcReplayCanvas.init({ canvas, container });
  api.onToolChange((tool) => events.push(tool));

  api.setTool('rect');
  assert.equal(api.getActiveTool(), 'rect');
  assert.equal(canvas.style.pointerEvents, 'auto');
  assert.equal(canvas.style.touchAction, 'none');
  assert.equal(canvas.classList.contains('is-drawing'), true);
  assert.deepEqual(events, ['rect']);

  api.setTool('cursor');
  assert.equal(api.getActiveTool(), 'cursor');
  assert.equal(canvas.style.pointerEvents, 'none');
  assert.equal(canvas.style.touchAction, '');
  assert.equal(canvas.classList.contains('is-drawing'), false);
  assert.deepEqual(events, ['rect', 'cursor']);
  api.destroy();
});

test('forwards coordinate conversion to chartApi', () => {
  const canvas = mockElement('canvas');
  const container = mockElement('div');
  const chartApi = {
    timeToCoordinate: (t) => t * 2,
    coordinateToTime: (x) => x / 2,
    priceToCoordinate: (p) => 1000 - p,
    coordinateToPrice: (y) => 1000 - y,
    subscribeRange: () => {}
  };

  const api = SmcReplayCanvas.init({ canvas, container, chartApi });
  assert.equal(api.timeToCoordinate(50), 100);
  assert.equal(api.coordinateToTime(100), 50);
  assert.equal(api.priceToCoordinate(250), 750);
  assert.equal(api.coordinateToPrice(750), 250);
  api.destroy();
});

test('accepts an initial tool so a pre-load selection is not lost', () => {
  const canvas = mockElement('canvas');
  const container = mockElement('div');

  const api = SmcReplayCanvas.init({ canvas, container, activeTool: 'rect' });
  assert.equal(api.getActiveTool(), 'rect');
  assert.equal(canvas.style.pointerEvents, 'auto');
  assert.equal(canvas.classList.contains('is-drawing'), true);
  api.destroy();
});

test('stops pointerdown propagation only while a drawing tool is active', () => {
  const canvas = mockElement('canvas');
  const container = mockElement('div');
  const api = SmcReplayCanvas.init({ canvas, container });
  const seen = [];
  api.onPointer((payload) => seen.push(payload.type));

  const makeEvent = () => ({
    clientX: 10,
    clientY: 20,
    button: 0,
    pointerId: 1,
    stopped: false,
    stopPropagation() { this.stopped = true; }
  });

  const cursorEvent = makeEvent();
  canvas.handlers.pointerdown(cursorEvent);
  assert.equal(cursorEvent.stopped, false, 'cursor mode must stay passthrough');
  assert.deepEqual(seen, []);

  api.setTool('rect');
  const drawEvent = makeEvent();
  canvas.handlers.pointerdown(drawEvent);
  assert.equal(drawEvent.stopped, true, 'drawing mode must not reach the chart gesture');
  assert.deepEqual(seen, ['pointerdown']);
  api.destroy();
});

test('selection active enables pointer events in cursor mode and emits pointer events', () => {
  const canvas = mockElement('canvas');
  const container = mockElement('div');
  const seen = [];
  const api = SmcReplayCanvas.init({ canvas, container });

  assert.equal(api.isSelectionActive(), false);
  assert.equal(canvas.style.pointerEvents, 'none');

  api.onPointer((payload) => seen.push(payload.type));
  api.setSelectionActive(true);

  assert.equal(api.isSelectionActive(), true);
  assert.equal(canvas.style.pointerEvents, 'auto');
  assert.equal(canvas.style.touchAction, 'none');
  assert.equal(canvas.classList.contains('is-selecting'), true);

  const selEvent = {
    clientX: 100,
    clientY: 100,
    button: 0,
    pointerId: 1,
    stopped: false,
    stopPropagation() { this.stopped = true; }
  };
  canvas.handlers.pointerdown(selEvent);
  assert.equal(selEvent.stopped, true);
  assert.deepEqual(seen, ['pointerdown']);

  api.setCursor('nwse-resize');
  assert.equal(canvas.style.cursor, 'nwse-resize');

  api.setSelectionActive(false);
  assert.equal(api.isSelectionActive(), false);
  assert.equal(canvas.style.pointerEvents, 'none');
  assert.equal(canvas.classList.contains('is-selecting'), false);
  api.destroy();
});

test('setTool(cursor) retains selectionActive if armed; other tools reset it', () => {
  const canvas = mockElement('canvas');
  const container = mockElement('div');
  const api = SmcReplayCanvas.init({ canvas, container });

  api.setTool('rect');
  assert.equal(api.getActiveTool(), 'rect');

  api.setSelectionActive(true);
  assert.equal(api.isSelectionActive(), true);

  // Switching back to cursor (as happens on commit) must NOT disarm selectionActive
  api.setTool('cursor');
  assert.equal(api.getActiveTool(), 'cursor');
  assert.equal(api.isSelectionActive(), true, 'cursor switch must keep selectionActive armed');
  assert.equal(canvas.style.pointerEvents, 'auto');

  // Switching to a drawing tool must reset selectionActive
  api.setTool('hline');
  assert.equal(api.getActiveTool(), 'hline');
  assert.equal(api.isSelectionActive(), false, 'non-cursor tool must reset selectionActive');
  assert.equal(canvas.style.pointerEvents, 'auto'); // active drawing tool has pointer-events: auto
  api.destroy();
});
