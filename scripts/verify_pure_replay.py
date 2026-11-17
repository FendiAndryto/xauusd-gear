"""End-to-end verification for the pure price action replay workstation.

Ticket T-PAR-11. Replaces `verify_replay_ui.py`, which asserted the retired
benchmark UI (session picker, R:R presets, trade drawer, equity HUD).

What this checks, in order:

1. The API contract the UI consumes (`/coverage`, `/data`, gzip, 404 wording).
2. The DOM the selector is generated from — timeframe pills are *data driven*,
   so a hardcoded pill list would silently hide M1 or offer M5 in 2019.
3. Replay mechanics: auto-load, step, play/pause, max speed, scrubber.
4. The chart's own follow state machine: manual pan must break follow, the
   floating button must appear, and clicking it must snap back.
5. Fullscreen entry/exit via the `F` shortcut and the toolbar button, with no
   page scroll and no chart distortion.
6. Data-quality honesty: H1 2019-01 must show 27 bars *and* a warning banner.

Run against a live server:

    .venv\\Scripts\\python.exe scripts/verify_pure_replay.py

Exit code is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from typing import Any, Optional

# Windows consoles default to cp1252, which cannot encode glyphs this report
# prints (e.g. the "⛶" fullscreen button label). Reconfigure once so the run
# never dies mid-suite with UnicodeEncodeError before reporting the result.
for _stream in (sys.stdout, sys.stderr):
    _reconfigure = getattr(_stream, "reconfigure", None)
    if _reconfigure is not None:
        _reconfigure(encoding="utf-8", errors="replace")

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


class CDP:
    """Minimal Chrome DevTools Protocol client over a raw WebSocket.

    Unsolicited events (console errors, exceptions, log entries) are buffered in
    ``self.events`` so the checks can assert that the page stayed clean. The
    previous suite discarded them, which is why a silent JS crash could still
    produce a green run.
    """

    def __init__(self, ws_url: str) -> None:
        self.ws_url = ws_url
        self._id = 0
        self._sock = None
        self._buffer = b""
        self.events: list[dict[str, Any]] = []

    def connect(self) -> None:
        # Hand-rolled handshake keeps this dependency-free.
        import base64
        import socket
        from urllib.parse import urlparse

        parsed = urlparse(self.ws_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path + (("?" + parsed.query) if parsed.query else "")
        sock = socket.create_connection((host, port), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        sock.sendall(request.encode())
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = sock.recv(4096)
            if not chunk:
                raise RuntimeError("websocket handshake failed")
            header += chunk
        if b"101" not in header.split(b"\r\n")[0]:
            raise RuntimeError(f"websocket rejected: {header[:200]!r}")
        self._sock = sock
        self._buffer = header.split(b"\r\n\r\n", 1)[1]

    def _send_frame(self, payload: str) -> None:
        import struct

        data = payload.encode()
        mask = os.urandom(4)
        header = bytearray([0x81])
        length = len(data)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        self._sock.sendall(bytes(header) + masked)

    def _read_frame(self) -> Optional[str]:
        import struct

        def need(n: int) -> bytes:
            while len(self._buffer) < n:
                chunk = self._sock.recv(1 << 20)
                if not chunk:
                    raise RuntimeError("socket closed")
                self._buffer += chunk
            out, self._buffer = self._buffer[:n], self._buffer[n:]
            return out

        head = need(2)
        opcode = head[0] & 0x0F
        length = head[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", need(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", need(8))[0]
        payload = need(length) if length else b""
        if opcode == 0x8:
            raise RuntimeError("websocket closed")
        if opcode == 0x9:  # ping
            return None
        return payload.decode("utf-8", "replace")

    def call(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        timeout: float = 120.0,
    ) -> dict[str, Any]:
        self._id += 1
        msg_id = self._id
        self._send_frame(
            json.dumps({"id": msg_id, "method": method, "params": params or {}})
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            frame = self._read_frame()
            if frame is None:
                continue
            try:
                payload = json.loads(frame)
            except json.JSONDecodeError:
                continue
            if payload.get("id") == msg_id:
                if "error" in payload:
                    raise RuntimeError(f"{method}: {payload['error']}")
                return payload.get("result", {})
            if "method" in payload:
                self.events.append(payload)
        raise TimeoutError(f"{method} timed out")

    def evaluate(self, expression: str, timeout: float = 120.0) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            text = details.get("text") or ""
            exception = details.get("exception") or {}
            raise RuntimeError(f"JS error: {text} {exception.get('description', '')}")
        return result.get("result", {}).get("value")

    def close(self) -> None:
        try:
            if self._sock:
                self._sock.close()
        finally:
            self._sock = None


def find_browser() -> str:
    override = os.environ.get("REPLAY_CHROME")
    if override and os.path.exists(override):
        return override
    for candidate in CHROME_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    raise SystemExit("No Chrome/Edge found; set REPLAY_CHROME=/path/to/browser")


def launch(url: str) -> tuple[subprocess.Popen, CDP]:
    browser = find_browser()
    profile = tempfile.mkdtemp(prefix="pure-replay-cdp-")
    port = 9333
    proc = subprocess.Popen(
        [
            browser,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--hide-scrollbars",
            f"--user-data-dir={profile}",
            f"--remote-debugging-port={port}",
            "--window-size=1600,1000",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list", timeout=2
            ) as res:
                targets = json.loads(res.read())
            pages = [
                t
                for t in targets
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl")
            ]
            if pages:
                cdp = CDP(pages[0]["webSocketDebuggerUrl"])
                cdp.connect()
                return proc, cdp
        except Exception:
            pass
        time.sleep(0.4)

    proc.kill()
    raise SystemExit("browser did not expose a debuggable page")


# --------------------------------------------------------------------- checks

CHECKS: list[str] = []


def check(label: str, condition: Any, detail: Any = "") -> None:
    ok = bool(condition)
    CHECKS.append(label)
    status = "PASS" if ok else "FAIL"
    suffix = f"  ({detail})" if detail != "" else ""
    print(f"[{status}] {label}{suffix}")
    if not ok:
        raise SystemExit(f"check failed: {label}")


def http_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=120) as res:
        return json.loads(res.read())


class Page:
    """Small convenience layer over the CDP client."""

    def __init__(self, cdp: CDP) -> None:
        self.cdp = cdp

    def js(self, expression: str, timeout: float = 120.0) -> Any:
        return self.cdp.evaluate(expression, timeout=timeout)

    def wait_until(self, expression: str, timeout: float = 45.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.js(expression):
                    return True
            except RuntimeError:
                pass  # execution context is being replaced (reload)
            time.sleep(0.2)
        return False

    def snapshot(self) -> dict[str, Any]:
        return self.js("SmcDebug.replay.snapshot()")

    def press_key(self, key: str, code: str, virtual_key: int, text: str = "") -> None:
        """Send a real key press through CDP so focus and typing guards apply.

        Synthetic ``KeyboardEvent`` dispatch bypasses the browser's focus model,
        which means a shortcut can look green even if it fires while the user is
        typing inside an input. This routes through Input.dispatchKeyEvent.
        """
        base = {
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": virtual_key,
            "nativeVirtualKeyCode": virtual_key,
        }
        down = dict(base, type="keyDown")
        if text:
            down["text"] = text
        self.cdp.call("Input.dispatchKeyEvent", down)
        self.cdp.call("Input.dispatchKeyEvent", dict(base, type="keyUp"))

    def meta(self) -> dict[str, Any]:
        return self.js("SmcDebug.replay.getPayload().meta")

    def status_text(self) -> str:
        return self.js("document.getElementById('replay-status').textContent")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    # ---------------------------------------------------------------- 1. API
    health = http_json(f"{base}/api/health")
    check("health endpoint answers", health.get("status") == "ok", health)

    coverage = http_json(f"{base}/api/replay/coverage")
    for key in (
        "available_years",
        "timeframes",
        "period_modes",
        "timeframe_coverage",
        "default_selection",
    ):
        check(f"/coverage exposes {key}", key in coverage)

    check(
        "timeframes are discovered, not hardcoded (M5,M15,H1,M1)",
        coverage["timeframes"] == ["M5", "M15", "H1", "M1"],
        coverage["timeframes"],
    )
    check(
        "every timeframe publishes available_months",
        all(
            "available_months" in cov for cov in coverage["timeframe_coverage"].values()
        ),
    )
    h1 = coverage["timeframe_coverage"]["H1"]
    check(
        "H1 publishes the honest hourly start (2021-07-01)",
        h1["usable_start_date"] == "2021-07-01",
        h1["usable_start_date"],
    )
    check(
        "H1 marks the 36 daily-bar months as sparse",
        len(h1["sparse_months"]) == 36,
        len(h1["sparse_months"]),
    )
    check(
        "default selection is a complete month (M5 2026-10)",
        coverage["default_selection"]
        == {"period_mode": "month", "year": 2026, "month": 10, "timeframe": "M5"},
        coverage["default_selection"],
    )

    pure_url = (
        f"{base}/api/replay/data?period_mode=month&timeframe=M5&year=2026&month=10"
    )
    pure = http_json(pure_url)
    check(
        "pure payload keys are exactly meta+candles",
        sorted(pure) == ["candles", "meta"],
        sorted(pure),
    )
    check(
        "prices keep 3 decimals (no rounding)",
        pure["candles"][0]["open"] == 4156.244,
        pure["candles"][0]["open"],
    )
    check(
        "6048 M5 bars for October 2026",
        pure["meta"]["total_bars"] == 6048,
        pure["meta"]["total_bars"],
    )
    check(
        "dense month has no warnings",
        pure["meta"]["warnings"] == [],
        pure["meta"]["warnings"],
    )

    # Gzip is what actually shrinks the transfer (the "40% smaller" claim was false).
    request = urllib.request.Request(pure_url, headers={"Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=120) as res:
        raw_size = len(res.read())
    gz = subprocess.run(
        [
            "curl.exe" if os.name == "nt" else "curl",
            "-s",
            "-H",
            "Accept-Encoding: gzip",
            "-o",
            os.devnull,
            "-w",
            "%{size_download}",
            pure_url,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    gzip_size = int(gz.stdout or 0)
    check(
        "gzip cuts the payload by >70%",
        gzip_size and gzip_size < raw_size * 0.3,
        f"{raw_size:,} -> {gzip_size:,} bytes",
    )

    try:
        http_json(
            f"{base}/api/replay/data?period_mode=month&timeframe=M5&year=2019&month=1"
        )
        check("missing month returns 404", False)
    except urllib.error.HTTPError as exc:
        body = json.loads(exc.read())
        check(
            "missing month 404 names the real coverage",
            exc.code == 404 and "2025-06-01" in body.get("detail", ""),
            body.get("detail", "")[:90],
        )

    # ------------------------------------------------------------ 2. browser
    proc, cdp = launch(base)
    page = Page(cdp)
    try:
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Log.enable")
        page.wait_until("!!(window.SmcDebug && SmcDebug.replay)")
        cdp.call("Page.reload", {"ignoreCache": True})
        ready = page.wait_until(
            "!!(window.SmcDebug && SmcDebug.replay && SmcDebug.replay.snapshot()"
            " && SmcDebug.replay.snapshot().totalBars > 0)",
            timeout=60,
        )
        check("workstation boots and auto-loads a payload", ready)

        check(
            "no legacy modules are loaded",
            page.js(
                "[typeof SmcStream, typeof SmcSetups, typeof SmcEvaluation,"
                " typeof SmcReplayMarkers].every(function(t){return t==='undefined';})"
            ),
        )

        dom = page.js(
            "({modes: document.querySelectorAll('#replay-mode-toggle [data-mode]').length,"
            " tfs: [].map.call(document.querySelectorAll('#replay-timeframes [data-tf]'),"
            "   function(b){return b.getAttribute('data-tf');}),"
            " years: document.querySelectorAll('#replay-year option').length,"
            " months: document.querySelectorAll('#replay-month option').length,"
            " speeds: document.querySelectorAll('#replay-speeds [data-speed]').length,"
            " ids: document.getElementById('replay-chart') ? 1 : 0})"
        )
        check("five period modes are offered", dom["modes"] == 5, dom["modes"])
        check(
            "timeframe pills come from coverage (M5,M15,H1,M1)",
            dom["tfs"] == ["M5", "M15", "H1", "M1"],
            dom["tfs"],
        )
        check("year options cover 2018-2026", dom["years"] == 9, dom["years"])
        check("month options use Indonesian names", dom["months"] == 12, dom["months"])
        check("eight speed presets including Max", dom["speeds"] == 8, dom["speeds"])

        meta = page.meta()
        check(
            "auto-loaded the advertised default (M5 2026-10)",
            meta["timeframe"] == "M5" and meta["period_label"] == "Oktober 2026",
            meta["period_label"],
        )
        check(
            "transport reports 1 / 6048 on load",
            page.js("document.getElementById('replay-position').textContent")
            == "1 / 6.048",
            page.js("document.getElementById('replay-position').textContent"),
        )
        check(
            "HUD shows the first bar in UTC",
            page.js("document.getElementById('replay-hud-time-utc').textContent")
            == "2026-10-01 00:00 UTC",
            page.js("document.getElementById('replay-hud-time-utc').textContent"),
        )
        check(
            "HUD shows local time as well",
            re.match(
                r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} ",
                page.js("document.getElementById('replay-hud-time-local').textContent"),
            )
            is not None,
            page.js("document.getElementById('replay-hud-time-local').textContent"),
        )
        check(
            "HUD prints 3-decimal OHLC of the active bar",
            page.js("document.getElementById('replay-hud-open').textContent")
            == "4156.244"
            and page.js("document.getElementById('replay-hud-close').textContent")
            == "4151.117",
            page.js(
                "[document.getElementById('replay-hud-open').textContent,"
                " document.getElementById('replay-hud-close').textContent].join(' / ')"
            ),
        )
        hud_box = page.js(
            "(() => {"
            "  const hud = document.getElementById('replay-hud').getBoundingClientRect();"
            "  const wrap = document.getElementById('replay-chart-wrap').getBoundingClientRect();"
            "  const plot = document.getElementById('replay-chart').getBoundingClientRect();"
            "  const tsWidth = window.SmcDebug.replay.getChart().chart.timeScale().width();"
            "  return { left: hud.left - wrap.left, top: hud.top - wrap.top,"
            "           right: hud.right - plot.left, plotWidth: tsWidth, width: hud.width };"
            "})()"
        )
        check(
            "HUD sits in the top-left corner",
            45 <= hud_box["left"] <= 70 and 0 <= hud_box["top"] <= 20,
            hud_box,
        )
        check(
            "HUD clears the right price scale",
            hud_box["right"]
            <= hud_box["plotWidth"] - (120 if hud_box["plotWidth"] >= 1200 else 40),
            hud_box,
        )
        check("HUD keeps a compact single-row width", hud_box["width"] <= 900, hud_box)
        page.js("document.getElementById('replay-hud-toggle').click()")
        minimized = page.js(
            "document.getElementById('replay-hud').classList.contains('is-minimized')"
        )
        check("HUD minimize button collapses the body", minimized)
        page.js("document.getElementById('replay-hud-toggle').click()")
        restored = not page.js(
            "document.getElementById('replay-hud').classList.contains('is-minimized')"
        )
        check("HUD toggle button restores the body", restored)

        page.js("document.body.focus()")
        page.press_key("h", "KeyH", 72, "h")
        hidden = page.js(
            "document.getElementById('replay-hud').classList.contains('is-hidden')"
        )
        check("pressing 'h' hides the HUD", hidden)
        page.press_key("h", "KeyH", 72, "h")
        shown = not page.js(
            "document.getElementById('replay-hud').classList.contains('is-hidden')"
        )
        check("pressing 'h' again unhides the HUD", shown)

        page.js("document.getElementById('replay-scrubber').focus()")
        page.press_key("h", "KeyH", 72, "h")
        typing_safe = not page.js(
            "document.getElementById('replay-hud').classList.contains('is-hidden')"
        )
        check("'h' is ignored while a form field has focus", typing_safe)
        page.js("document.getElementById('replay-scrubber').blur()")

        # --- Fase 2: Vertical Dock & Canvas Overlay (T-SIM-03 & T-SIM-04) ---
        dock_info = page.js(
            "(() => {"
            "  const dock = document.getElementById('replay-dock');"
            "  if (!dock) return null;"
            "  const style = window.getComputedStyle(dock);"
            "  const rect = dock.getBoundingClientRect();"
            "  const buttons = dock.querySelectorAll('.replay-dock-btn').length;"
            "  return { position: style.position, width: Math.round(rect.width), buttons: buttons };"
            "})()"
        )
        check(
            "vertical dock exists as flex child (width ~48px, 8 buttons)",
            dock_info is not None
            and dock_info["position"] != "absolute"
            and 44 <= dock_info["width"] <= 52
            and dock_info["buttons"] == 8,
            dock_info,
        )

        tool_state = page.js(
            "(() => {"
            "  const btn = document.getElementById('tool-cursor');"
            "  const canvas = document.getElementById('replay-drawing-canvas');"
            "  const style = window.getComputedStyle(canvas);"
            "  return { active: btn ? btn.classList.contains('is-active') : false, pointerEvents: style.pointerEvents };"
            "})()"
        )
        check(
            "cursor tool is active on start and canvas has pointer-events: none",
            tool_state["active"] and tool_state["pointerEvents"] == "none",
            tool_state,
        )

        page.js("document.getElementById('tool-rect').click()")
        rect_state = page.js(
            "(() => {"
            "  const btn = document.getElementById('tool-rect');"
            "  const curBtn = document.getElementById('tool-cursor');"
            "  const canvas = document.getElementById('replay-drawing-canvas');"
            "  const style = window.getComputedStyle(canvas);"
            "  return {"
            "    rectActive: btn.classList.contains('is-active'),"
            "    curActive: curBtn.classList.contains('is-active'),"
            "    isDrawing: canvas.classList.contains('is-drawing'),"
            "    pointerEvents: style.pointerEvents"
            "  };"
            "})()"
        )
        check(
            "clicking rect tool activates drawing mode with pointer-events: auto",
            rect_state["rectActive"]
            and not rect_state["curActive"]
            and rect_state["pointerEvents"] == "auto",
            rect_state,
        )

        page.press_key("v", "KeyV", 86, "v")
        cur_switched = page.js(
            "document.getElementById('tool-cursor').classList.contains('is-active')"
            " && window.getComputedStyle(document.getElementById('replay-drawing-canvas')).pointerEvents === 'none'"
        )
        check(
            "pressing 'v' restores cursor tool and pointer-events: none", cur_switched
        )

        chart_api_check = page.js(
            "(() => {"
            "  const chart = window.SmcDebug.replay.getChart();"
            "  return {"
            "    hasGetChart: typeof chart.getChart === 'function',"
            "    hasGetSeries: typeof chart.getSeries === 'function',"
            "    hasTimeToCoord: typeof chart.timeToCoordinate === 'function',"
            "    hasPriceToCoord: typeof chart.priceToCoordinate === 'function',"
            "    hasSubscribeRange: typeof chart.subscribeRange === 'function',"
            "    hasSubscribeClick: typeof chart.subscribeClick === 'function'"
            "  };"
            "})()"
        )
        check(
            "official chartApi handle methods are fully exposed",
            all(chart_api_check.values()),
            chart_api_check,
        )

        tooltip = page.js(
            "(() => {"
            "  const b = document.getElementById('tool-rect');"
            "  const s = window.getComputedStyle(b, '::after');"
            "  const r = b.getBoundingClientRect();"
            "  return { content: s.content, position: s.position,"
            "           left: parseFloat(s.left), buttonWidth: r.width };"
            "})()"
        )
        check(
            "dock buttons carry a right-floating CSS tooltip",
            tooltip["content"] not in ("none", "normal", "", "auto", '""')
            and tooltip["position"] == "absolute"
            and tooltip["left"] >= tooltip["buttonWidth"],
            tooltip,
        )

        # The overlay canvas is a child of #replay-chart, which owns the chart
        # pan gesture listener. Prove that drawing mode stops the bubble instead
        # of silently arming a chart drag.
        page.js(
            "window.__chartPointerDown = 0;"
            " document.getElementById('replay-chart').addEventListener('pointerdown',"
            " function () { window.__chartPointerDown += 1; });"
        )
        canvas_center = page.js(
            "(() => {"
            "  const r = document.getElementById('replay-drawing-canvas').getBoundingClientRect();"
            "  return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };"
            "})()"
        )

        def click_at(point: dict[str, Any]) -> None:
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": point["x"], "y": point["y"], "buttons": 0},
            )
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": point["x"],
                    "y": point["y"],
                    "button": "left",
                    "buttons": 1,
                    "clickCount": 1,
                },
            )
            time.sleep(0.05)
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": point["x"],
                    "y": point["y"],
                    "button": "left",
                    "buttons": 0,
                    "clickCount": 1,
                },
            )

        page.js("document.getElementById('tool-rect').click()")
        click_at(canvas_center)
        draw_hits = page.js("window.__chartPointerDown")
        check(
            "drawing mode keeps pointerdown away from the chart gesture layer",
            draw_hits == 0,
            {"containerPointerDowns": draw_hits},
        )

        page.press_key("v", "KeyV", 86, "v")
        click_at(canvas_center)
        cursor_hits = page.js("window.__chartPointerDown")
        check(
            "cursor mode still lets pointerdown reach the chart",
            cursor_hits >= 1,
            {"containerPointerDowns": cursor_hits},
        )

        # Price-scale changes (autoscale / axis drag) do not fire
        # subscribeVisibleLogicalRangeChange, so the overlay needs its own
        # renderer-driven scale watch.
        old_margins = page.js(
            "window.SmcDebug.replay.getChart().getChart()"
            ".priceScale('right').options().scaleMargins"
        )
        page.js(
            "window.__renders = 0;"
            " window.__r = function () { window.__renders += 1; };"
            " window.SmcDebug.replay.getCanvasApi().registerRenderer(window.__r);"
        )
        page.wait_until("window.__renders > 0", timeout=6)  # consume the initial paint
        renders_before = page.js("window.__renders")
        page.js(
            "window.SmcDebug.replay.getChart().getChart()"
            ".priceScale('right').applyOptions({ scaleMargins: { top: 0.3, bottom: 0.3 } })"
        )
        repainted = page.wait_until("window.__renders > %d" % renders_before, timeout=6)
        check(
            "price-scale change repaints the overlay without a range change",
            repainted,
            {
                "rendersBefore": renders_before,
                "rendersAfter": page.js("window.__renders"),
            },
        )
        page.js(
            "window.SmcDebug.replay.getCanvasApi().unregisterRenderer(window.__r);"
            " window.SmcDebug.replay.getChart().getChart()"
            ".priceScale('right').applyOptions({ scaleMargins: %s })"
            % json.dumps(old_margins)
        )

        redraws_before = page.js(
            "window.SmcDebug.replay.getCanvasApi().getRedrawCount()"
        )
        page.press_key("ArrowRight", "ArrowRight", 39)
        advanced = page.wait_until(
            "window.SmcDebug.replay.getCanvasApi().getRedrawCount() > %d"
            % redraws_before,
            timeout=6,
        )
        check(
            "canvas repaints when the replay advances",
            advanced,
            {
                "before": redraws_before,
                "after": page.js(
                    "window.SmcDebug.replay.getCanvasApi().getRedrawCount()"
                ),
            },
        )

        # --- Fase 3: Core Drawing Tools (T-SIM-05A, 05B, 05C) ---
        drawings_api_check = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  if (!api) return null;"
            "  return {"
            "    hasGetDrawings: typeof api.getDrawings === 'function',"
            "    hasAddDrawing: typeof api.addDrawing === 'function',"
            "    hasRemoveDrawing: typeof api.removeDrawing === 'function',"
            "    hasClearDrawings: typeof api.clearDrawings === 'function',"
            "    hasSelectDrawing: typeof api.selectDrawing === 'function',"
            "    hasDeselect: typeof api.deselect === 'function',"
            "    hasDeleteSelected: typeof api.deleteSelected === 'function'"
            "  };"
            "})()"
        )
        check(
            "drawingsApi engine is instantiated and fully exposed",
            drawings_api_check is not None and all(drawings_api_check.values()),
            drawings_api_check,
        )

        def cdp_drag(p1: dict[str, int], p2: dict[str, int]) -> None:
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": p1["x"], "y": p1["y"]},
            )
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mousePressed",
                    "x": p1["x"],
                    "y": p1["y"],
                    "button": "left",
                    "clickCount": 1,
                },
            )
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {"type": "mouseMoved", "x": p2["x"], "y": p2["y"], "button": "left"},
            )
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseReleased",
                    "x": p2["x"],
                    "y": p2["y"],
                    "button": "left",
                    "clickCount": 1,
                },
            )

        c_box = page.js(
            "(() => {"
            "  const r = document.getElementById('replay-drawing-canvas').getBoundingClientRect();"
            "  return { left: Math.round(r.left), top: Math.round(r.top), width: Math.round(r.width), height: Math.round(r.height) };"
            "})()"
        )
        cx = int(c_box["left"])
        cy = int(c_box["top"])

        # 1. H-Line tool (T-SIM-05A)
        page.js("document.getElementById('tool-hline').click()")
        click_at({"x": cx + 300, "y": cy + 200})
        hline_state = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const list = api ? api.getDrawings() : [];"
            "  const tool = window.SmcDebug.replay.getActiveTool();"
            "  return { count: list.length, lastType: list.length ? list[list.length - 1].type : null, tool: tool };"
            "})()"
        )
        check(
            "H-Line tool places line and auto-switches to cursor",
            hline_state["count"] == 1
            and hline_state["lastType"] == "hline"
            and hline_state["tool"] == "cursor",
            hline_state,
        )

        # 2. Rectangle tool (T-SIM-05A)
        page.press_key("r", "KeyR", 82, "r")
        cdp_drag({"x": cx + 150, "y": cy + 150}, {"x": cx + 350, "y": cy + 280})
        rect_state_check = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const list = api ? api.getDrawings() : [];"
            "  const tool = window.SmcDebug.replay.getActiveTool();"
            "  const d = list.length ? list[list.length - 1] : null;"
            "  const ts = window.SmcDebug.replay.getChart().getChart().timeScale();"
            "  return { count: list.length, lastType: d ? d.type : null, tool: tool,"
            "           x1: d ? ts.timeToCoordinate(d.t1) : null,"
            "           x2: d ? ts.timeToCoordinate(d.t2) : null };"
            "})()"
        )
        check(
            "Rectangle tool places a visible zone box and auto-switches to cursor",
            rect_state_check["count"] == 2
            and rect_state_check["lastType"] == "rect"
            and rect_state_check["tool"] == "cursor"
            and rect_state_check["x1"] is not None
            and rect_state_check["x2"] is not None,
            rect_state_check,
        )

        # 3. Trendline tool (T-SIM-05B)
        page.press_key("t", "KeyT", 84, "t")
        cdp_drag({"x": cx + 200, "y": cy + 120}, {"x": cx + 420, "y": cy + 260})
        trend_state_check = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const list = api ? api.getDrawings() : [];"
            "  const tool = window.SmcDebug.replay.getActiveTool();"
            "  const d = list.length ? list[list.length - 1] : null;"
            "  const ts = window.SmcDebug.replay.getChart().getChart().timeScale();"
            "  return { count: list.length, lastType: d ? d.type : null, tool: tool,"
            "           x1: d ? ts.timeToCoordinate(d.t1) : null,"
            "           x2: d ? ts.timeToCoordinate(d.t2) : null };"
            "})()"
        )
        check(
            "Trendline tool places a visible diagonal line and auto-switches to cursor",
            trend_state_check["count"] == 3
            and trend_state_check["lastType"] == "trendline"
            and trend_state_check["tool"] == "cursor"
            and trend_state_check["x1"] is not None
            and trend_state_check["x2"] is not None,
            trend_state_check,
        )

        # 4. Ruler tool (T-SIM-05B)
        page.press_key("m", "KeyM", 77, "m")
        cdp_drag({"x": cx + 250, "y": cy + 180}, {"x": cx + 400, "y": cy + 300})
        ruler_state_check = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  return { count: api ? api.getDrawings().length : 0 };"
            "})()"
        )
        check(
            "Ruler tool is transient (drawings count unchanged)",
            ruler_state_check["count"] == 3,
            ruler_state_check,
        )
        page.press_key("Escape", "Escape", 27)

        # 5. Object selection via chart click (T-SIM-05C)
        # The click goes through CDP into the real chart canvas; no direct
        # handler call is allowed here, because that would mask a broken
        # subscribeClick wiring.
        click_at({"x": cx + 300, "y": cy + 200})
        selection_state = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const canvasApi = window.SmcDebug.replay.getCanvasApi();"
            "  const selId = api ? api.getSelectedId() : null;"
            "  const selItem = selId ? api.getDrawingById(selId) : null;"
            "  return {"
            "    hasSelection: Boolean(selId),"
            "    selectedType: selItem ? selItem.type : null,"
            "    isSelectionActive: canvasApi ? canvasApi.isSelectionActive() : false"
            "  };"
            "})()"
        )
        check(
            "real chart click selects drawing object and arms handles",
            selection_state["hasSelection"]
            and selection_state["selectedType"] == "hline"
            and selection_state["isSelectionActive"],
            selection_state,
        )

        # 5b. Moving a selected object must persist on pointerup.
        before_move = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const selId = api.getSelectedId();"
            "  return selId ? api.getDrawingById(selId).price : null;"
            "})()"
        )
        cdp_drag({"x": cx + 300, "y": cy + 200}, {"x": cx + 300, "y": cy + 260})
        move_state = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const selId = api.getSelectedId();"
            "  const item = selId ? api.getDrawingById(selId) : null;"
            "  const raw = localStorage.getItem('xauusd_replay_drawings_v1_XAUUSD_2026_10');"
            "  const stored = raw ? JSON.parse(raw) : [];"
            "  const saved = stored.filter(function (d) { return d.id === selId; })[0];"
            "  return { price: item ? item.price : null, savedPrice: saved ? saved.price : null };"
            "})()"
        )
        check(
            "moving a drawing persists the new price on pointerup",
            before_move is not None
            and move_state["price"] != before_move
            and move_state["savedPrice"] is not None
            and abs(move_state["savedPrice"] - move_state["price"]) < 1e-6,
            {"before": before_move, "after": move_state},
        )

        # 6. Delete key deletes selected object (T-SIM-05C)
        page.press_key("Delete", "Delete", 46)
        delete_check = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const canvasApi = window.SmcDebug.replay.getCanvasApi();"
            "  return {"
            "    count: api ? api.getDrawings().length : 0,"
            "    selId: api ? api.getSelectedId() : null,"
            "    isSelectionActive: canvasApi ? canvasApi.isSelectionActive() : false"
            "  };"
            "})()"
        )
        check(
            "Delete key removes selected drawing and resets selection mode",
            delete_check["count"] == 2
            and delete_check["selId"] is None
            and not delete_check["isSelectionActive"],
            delete_check,
        )

        # 7. Clear button clears all drawings (T-SIM-05C)
        page.js("document.getElementById('tool-clear').click()")
        clear_check = page.js(
            "window.SmcDebug.replay.getDrawingsApi().getDrawings().length"
        )
        check(
            "dock Clear button clears all drawings from canvas",
            clear_check == 0,
            {"remainingDrawings": clear_check},
        )

        # ------------------------------------------------------ 6. Fase 4 Strategy Simulator & Ledger (T-SIM-06 & T-SIM-07)
        sim_api_check = page.js(
            "(() => {"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const ledger = window.SmcDebug.replay.getLedgerApi();"
            "  return {"
            "    hasSim: Boolean(sim),"
            "    hasLedger: Boolean(ledger),"
            "    hasAddPosition: typeof (sim && sim.addPosition) === 'function',"
            "    hasClosePosition: typeof (sim && sim.closePosition) === 'function',"
            "    hasEvaluateCandle: typeof (sim && sim.evaluateCandle) === 'function',"
            "    hasGetPositions: typeof (sim && sim.getPositions) === 'function'"
            "  };"
            "})()"
        )
        check(
            "simulatorApi and ledgerApi are instantiated and exposed",
            sim_api_check is not None and all(sim_api_check.values()),
            sim_api_check,
        )

        # Long position placement (T-SIM-06)
        page.js("document.getElementById('tool-long').click()")
        click_at({"x": cx + 320, "y": cy + 220})
        long_pos_check = page.js(
            "(() => {"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const active = sim ? sim.getActivePosition() : null;"
            "  const tool = window.SmcDebug.replay.getActiveTool();"
            "  return {"
            "    hasActive: Boolean(active),"
            "    side: active ? active.side : null,"
            "    status: active ? active.status : null,"
            "    lot: active ? active.lot : null,"
            "    tool: tool"
            "  };"
            "})()"
        )
        check(
            "Long position tool places BUY box with auto-switch to cursor",
            long_pos_check["hasActive"]
            and long_pos_check["side"] == "BUY"
            and long_pos_check["status"] == "ACTIVE"
            and long_pos_check["tool"] == "cursor",
            long_pos_check,
        )

        # Immediate handle reachability and dragging right after placement
        pos_handle_check = page.js(
            "(() => {"
            "  const canvasApi = window.SmcDebug.replay.getCanvasApi();"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const chart = window.SmcDebug.replay.getChart();"
            "  const p = sim ? sim.getActivePosition() : null;"
            "  if (!p) return null;"
            "  const x1 = chart.timeToCoordinate(p.entryTime);"
            "  const x2 = chart.timeToCoordinate(p.targetTime);"
            "  const midX = (x1 != null && x2 != null) ? (x1 + x2) / 2 : null;"
            "  const yTp = chart.priceToCoordinate(p.tp);"
            "  return {"
            "    selectionActive: canvasApi.isSelectionActive(),"
            "    midX: midX,"
            "    yTp: yTp,"
            "    tp: p.tp"
            "  };"
            "})()"
        )
        check(
            "Long position keeps selectionActive armed after cursor auto-switch",
            pos_handle_check is not None and pos_handle_check["selectionActive"],
            pos_handle_check,
        )
        if pos_handle_check and pos_handle_check.get("midX") is not None:
            hx = cx + int(pos_handle_check["midX"])
            hy = cy + int(pos_handle_check["yTp"])
            cdp_drag({"x": hx, "y": hy}, {"x": hx, "y": hy - 25})
            after_tp = page.js(
                "(() => {"
                "  const p = window.SmcDebug.replay.getSimulatorApi().getActivePosition();"
                "  return p ? p.tp : null;"
                "})()"
            )
            check(
                "Position TP handle is immediately draggable right after placement",
                after_tp is not None and after_tp != pos_handle_check["tp"],
                {"before": pos_handle_check["tp"], "after": after_tp},
            )

        # Manual Close via 'c' key (T-SIM-07)
        page.press_key("c", "KeyC", 67, "c")
        manual_close_check = page.js(
            "(() => {"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const ledger = window.SmcDebug.replay.getLedgerApi();"
            "  const active = sim ? sim.getActivePosition() : null;"
            "  const summary = ledger ? ledger.getSummary() : null;"
            "  return {"
            "    activeIsNull: active === null,"
            "    totalTrades: summary ? summary.totalTrades : 0,"
            "    lastReason: summary && summary.trades.length ? summary.trades[summary.trades.length - 1].reason : null"
            "  };"
            "})()"
        )
        check(
            "pressing 'c' manually closes active position and records into paper ledger",
            manual_close_check["activeIsNull"]
            and manual_close_check["totalTrades"] >= 1
            and "MANUAL_CLOSE" in (manual_close_check["lastReason"] or ""),
            manual_close_check,
        )

        # Short position placement via shortcut 's' (T-SIM-06)
        page.press_key("s", "KeyS", 83, "s")
        click_at({"x": cx + 340, "y": cy + 210})
        short_pos_check = page.js(
            "(() => {"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const active = sim ? sim.getActivePosition() : null;"
            "  return {"
            "    hasActive: Boolean(active),"
            "    side: active ? active.side : null,"
            "    status: active ? active.status : null"
            "  };"
            "})()"
        )
        check(
            "Short position tool places SELL box",
            short_pos_check["hasActive"]
            and short_pos_check["side"] == "SELL"
            and short_pos_check["status"] == "ACTIVE",
            short_pos_check,
        )

        # The R:R / TP / SL card used to be drawn at the box centre, hiding the
        # TP and SL zones. It must sit outside the box, in the left gutter, and
        # stay small enough to read. Measured from the real canvas pixels.
        page.js("document.getElementById('tool-clear').click()")
        page.js(
            "(function(){var s=document.getElementById('replay-scrubber');"
            " s.value='100'; s.dispatchEvent(new Event('input',{bubbles:true}));})()"
        )
        page.js("document.getElementById('tool-long').click()")
        click_at({"x": cx + 600, "y": cy + 250})
        card_layout = page.js(
            "(() => {"
            "  const chart = window.SmcDebug.replay.getChart();"
            "  const p = window.SmcDebug.replay.getSimulatorApi().getPositions()[0];"
            "  if (!p) return null;"
            "  const x1 = chart.timeToCoordinate(p.entryTime);"
            "  const x2 = chart.timeToCoordinate(p.targetTime);"
            "  const yE = chart.priceToCoordinate(p.entryPrice);"
            "  const yS = chart.priceToCoordinate(p.sl);"
            "  const yT = chart.priceToCoordinate(p.tp);"
            "  if (x1 == null || yE == null || yS == null || yT == null) return null;"
            "  const left = Math.min(x1, x2 == null ? x1 + 180 : x2);"
            "  const right = Math.max(x1, x2 == null ? x1 + 180 : x2);"
            "  const c = document.getElementById('replay-drawing-canvas');"
            "  const ctx = c.getContext('2d');"
            "  const dpr = c.width / c.clientWidth;"
            "  const w = c.width, h = c.height;"
            "  const data = ctx.getImageData(0, 0, w, h).data;"
            "  /* The card is a solid filled block; handles are small dots. Keep only"
            "     pixels whose 5x5 neighbourhood is fully opaque, then take the"
            "     largest connected component so handles cannot extend its bbox. */"
            "  const core = new Uint8Array(w * h);"
            "  for (let yy = 2; yy < h - 2; yy += 1) {"
            "    for (let xx = 2; xx < w - 2; xx += 1) {"
            "      let ok = 1;"
            "      for (let dy = -2; dy <= 2 && ok; dy += 1) {"
            "        for (let dx = -2; dx <= 2; dx += 1) {"
            "          if (data[((yy + dy) * w + (xx + dx)) * 4 + 3] < 200) { ok = 0; break; }"
            "        }"
            "      }"
            "      if (ok) core[yy * w + xx] = 1;"
            "    }"
            "  }"
            "  const seen = new Uint8Array(w * h);"
            "  let best = null;"
            "  for (let yy = 0; yy < h; yy += 1) {"
            "    for (let xx = 0; xx < w; xx += 1) {"
            "      const start = yy * w + xx;"
            "      if (!core[start] || seen[start]) continue;"
            "      const stack = [start];"
            "      seen[start] = 1;"
            "      let n = 0, minX = xx, maxX = xx, minY = yy, maxY = yy;"
            "      while (stack.length) {"
            "        const idx = stack.pop();"
            "        const px = idx % w;"
            "        const py = (idx - px) / w;"
            "        n += 1;"
            "        if (px < minX) minX = px;"
            "        if (px > maxX) maxX = px;"
            "        if (py < minY) minY = py;"
            "        if (py > maxY) maxY = py;"
            "        const nb = [[px - 1, py], [px + 1, py], [px, py - 1], [px, py + 1]];"
            "        for (let k = 0; k < 4; k += 1) {"
            "          const nx = nb[k][0], ny = nb[k][1];"
            "          if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;"
            "          const ni = ny * w + nx;"
            "          if (core[ni] && !seen[ni]) { seen[ni] = 1; stack.push(ni); }"
            "        }"
            "      }"
            "      if (!best || n > best.px) {"
            "        best = { px: n, left: minX / dpr, top: minY / dpr,"
            "                 right: maxX / dpr, bottom: maxY / dpr,"
            "                 w: (maxX - minX) / dpr, h: (maxY - minY) / dpr };"
            "      }"
            "    }"
            "  }"
            "  const card = (best && best.px > 200) ? best : null;"
            "  return { box: { left: left, right: right,"
            "                  top: Math.min(yE, yS, yT),"
            "                  bottom: Math.max(yE, yS, yT) },"
            "           card: card };"
            "})()"
        )
        check(
            "position R:R card renders outside the box, not on top of TP/SL zones",
            card_layout is not None
            and card_layout["card"] is not None
            and card_layout["card"]["right"] <= card_layout["box"]["left"] - 2
            and card_layout["card"]["w"] <= 170
            and card_layout["card"]["h"] <= 60,
            card_layout,
        )

        # Clear positions via dock Clear button (T-SIM-06/07)
        page.js("document.getElementById('tool-clear').click()")
        sim_clear_check = page.js(
            "window.SmcDebug.replay.getSimulatorApi().getPositions().length"
        )
        check(
            "dock Clear button clears positions from simulator",
            sim_clear_check == 0,
            {"remainingPositions": sim_clear_check},
        )

        # ------------------------------------------------------ 7. Fase 5 Storage Persistence (T-SIM-08)
        storage_api_check = page.js(
            "(() => {"
            "  const storage = window.SmcDebug.replay.getStorageApi();"
            "  return {"
            "    hasStorage: Boolean(storage),"
            "    hasFormatKey: typeof (storage && storage.formatKey) === 'function',"
            "    hasSaveDrawings: typeof (storage && storage.saveDrawings) === 'function',"
            "    hasLoadDrawings: typeof (storage && storage.loadDrawings) === 'function'"
            "  };"
            "})()"
        )
        check(
            "storageApi is instantiated and exposed",
            storage_api_check is not None and all(storage_api_check.values()),
            storage_api_check,
        )

        # Place a drawing, test that it is saved under the canonical month:02d key
        page.js("document.getElementById('tool-hline').click()")
        click_at({"x": cx + 300, "y": cy + 200})
        saved_key_check = page.js(
            "(() => {"
            "  const k = 'xauusd_replay_drawings_v1_XAUUSD_2026_10';"
            "  const val = localStorage.getItem(k);"
            "  return { keyExists: Boolean(val), raw: val ? JSON.parse(val) : [] };"
            "})()"
        )
        check(
            "drawings are automatically persisted to localStorage under canonical key",
            saved_key_check["keyExists"] and len(saved_key_check["raw"]) >= 1,
            saved_key_check,
        )

        # ---------------------------------------------- 8. Fase 4/5 integration
        # The checks above exercise each module in isolation. The following
        # drive the real wiring: the frame hook, localStorage restore, and the
        # per-month lifecycle.
        page.js(
            "(function(){var s=document.getElementById('replay-scrubber');"
            " s.value='100'; s.dispatchEvent(new Event('input',{bubbles:true}));})()"
        )

        # 8a. Manual close must exit at the live candle close, not the entry.
        page.js("document.getElementById('tool-long').click()")
        click_at({"x": cx + 320, "y": cy + 260})
        manual_setup = page.js(
            "(() => {"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const p = sim.getActivePosition();"
            "  const snap = window.SmcDebug.replay.snapshot();"
            "  if (!p || !snap.candle) return null;"
            "  p.entryPrice = snap.candle.close + 25;"
            "  p.sl = p.entryPrice - 1000;"
            "  p.tp = p.entryPrice + 1000;"
            "  return { entryPrice: p.entryPrice, close: snap.candle.close, index: snap.index };"
            "})()"
        )
        page.press_key("c", "KeyC", 67, "c")
        manual_exit = page.js(
            "(() => {"
            "  const summary = window.SmcDebug.replay.getLedgerApi().getSummary();"
            "  const t = summary.trades[summary.trades.length - 1];"
            "  return { exitPrice: t.exitPrice, entryPrice: t.entryPrice, reason: t.reason };"
            "})()"
        )
        check(
            "manual close exits at the live candle close, not the entry price",
            manual_setup is not None
            and abs(manual_exit["exitPrice"] - manual_setup["close"]) < 1e-6
            and abs(manual_exit["entryPrice"] - manual_setup["close"]) > 1,
            {"setup": manual_setup, "trade": manual_exit},
        )

        # 8b. TP/SL evaluation through the real frame hook (not a direct call).
        trades_before_auto = page.js(
            "window.SmcDebug.replay.getLedgerApi().getSummary().totalTrades"
        )
        page.js("document.getElementById('tool-long').click()")
        click_at({"x": cx + 320, "y": cy + 240})
        auto_setup = page.js(
            "(() => {"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const p = sim.getActivePosition();"
            "  const snap = window.SmcDebug.replay.snapshot();"
            "  if (!p || !snap.candle) return null;"
            "  p.tp = snap.candle.low - 5;"
            "  p.sl = 0.01;"
            "  return { entryBarIndex: p.entryBarIndex, index: snap.index, status: p.status };"
            "})()"
        )
        check(
            "position records the live bar index (anti look-ahead anchor)",
            auto_setup is not None
            and auto_setup["entryBarIndex"] == auto_setup["index"],
            auto_setup,
        )

        # Re-publish a frame at the SAME index: the entry bar must be skipped.
        page.js(
            "(function(){var s=document.getElementById('replay-scrubber');"
            " s.value=String(window.SmcDebug.replay.snapshot().index);"
            " s.dispatchEvent(new Event('input',{bubbles:true}));})()"
        )
        same_bar = page.js(
            "(() => {"
            "  const sim = window.SmcDebug.replay.getSimulatorApi();"
            "  const p = sim.getActivePosition();"
            "  return { status: p ? p.status : null,"
            "           totalTrades: window.SmcDebug.replay.getLedgerApi().getSummary().totalTrades };"
            "})()"
        )
        check(
            "entry bar is excluded from TP/SL evaluation (anti look-ahead)",
            same_bar["status"] == "ACTIVE"
            and same_bar["totalTrades"] == trades_before_auto,
            same_bar,
        )

        page.js("document.getElementById('replay-step-forward').click()")
        closed = page.wait_until(
            "window.SmcDebug.replay.getSimulatorApi().getActivePosition() === null",
            timeout=10,
        )
        auto_hit = page.js(
            "(() => {"
            "  const summary = window.SmcDebug.replay.getLedgerApi().getSummary();"
            "  const t = summary.trades[summary.trades.length - 1];"
            "  const raw = localStorage.getItem('xauusd_replay_ledger_v1_XAUUSD_2026_10');"
            "  const stored = raw ? JSON.parse(raw) : null;"
            "  return { totalTrades: summary.totalTrades, reason: t ? t.reason : null,"
            "           storedTrades: stored ? stored.totalTrades : -1 };"
            "})()"
        )
        check(
            "playback closes the position bar-by-bar via the frame hook",
            closed
            and auto_hit["totalTrades"] == trades_before_auto + 1
            and "TP_HIT" in (auto_hit["reason"] or ""),
            auto_hit,
        )
        check(
            "TP/SL hit is persisted to localStorage immediately",
            auto_hit["storedTrades"] == auto_hit["totalTrades"],
            auto_hit,
        )

        # 8b2. Regression: a rectangle started in whitespace (left of the first
        # revealed bar) must snap to a real bar and stay painted. The old
        # fallback anchored such shapes to the month's last bar, which is
        # off-screen during replay, so timeToCoordinate() returned null and the
        # committed box silently vanished.
        drawings_before_ws = page.js(
            "window.SmcDebug.replay.getDrawingsApi().getDrawings().length"
        )
        page.js("document.getElementById('tool-rect').click()")
        cdp_drag({"x": cx + 100, "y": cy + 150}, {"x": cx + 1200, "y": cy + 280})
        ws_rect = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const list = api ? api.getDrawings() : [];"
            "  const d = list.length ? list[list.length - 1] : null;"
            "  const ts = window.SmcDebug.replay.getChart().getChart().timeScale();"
            "  return { count: list.length,"
            "           x1: d ? ts.timeToCoordinate(d.t1) : null,"
            "           x2: d ? ts.timeToCoordinate(d.t2) : null,"
            "           distinct: d ? d.t1 !== d.t2 : false };"
            "})()"
        )
        check(
            "rectangle started in whitespace stays visible after commit",
            ws_rect["count"] == drawings_before_ws + 1
            and ws_rect["x1"] is not None
            and ws_rect["x2"] is not None
            and ws_rect["distinct"],
            ws_rect,
        )

        # Resolvable coordinates are only a proxy: assert the overlay actually
        # painted pixels inside the committed shape's box.
        ws_paint = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const d = api.getDrawings().slice(-1)[0];"
            "  const h = api.getAnchorHandles(d, 1466, 598);"
            "  if (!h.length) return { painted: 0, sampled: 0 };"
            "  const xs = h.map(function (k) { return k.x; });"
            "  const ys = h.map(function (k) { return k.y; });"
            "  const c = document.getElementById('replay-drawing-canvas');"
            "  const ctx = c.getContext('2d');"
            "  const dpr = c.width / c.clientWidth;"
            "  const left = Math.max(0, Math.floor(Math.min.apply(null, xs) * dpr));"
            "  const top = Math.max(0, Math.floor(Math.min.apply(null, ys) * dpr));"
            "  const w = Math.max(1, Math.floor((Math.max.apply(null, xs) - Math.min.apply(null, xs)) * dpr));"
            "  const hh = Math.max(1, Math.floor((Math.max.apply(null, ys) - Math.min.apply(null, ys)) * dpr));"
            "  const data = ctx.getImageData(left, top, w, hh).data;"
            "  let painted = 0;"
            "  for (let i = 3; i < data.length; i += 4) { if (data[i] > 0) painted += 1; }"
            "  return { sampled: data.length / 4, painted: painted };"
            "})()"
        )
        check(
            "committed rectangle actually paints pixels on the overlay canvas",
            ws_paint["sampled"] > 100 and ws_paint["painted"] > 0,
            ws_paint,
        )

        # 8b3. Regression: a rectangle dragged into the right whitespace (past
        # the newest revealed bar) must extrapolate forward and stay painted.
        page.js("document.getElementById('tool-rect').click()")
        geo = page.js(
            "(() => {"
            "  const chart = window.SmcDebug.replay.getChart();"
            "  const ts = chart.timeScale();"
            "  const wm = chart.getWatermark();"
            "  return { wmX: ts.logicalToCoordinate(wm) };"
            "})()"
        )
        wm_x = int(geo["wmX"])
        cdp_drag(
            {"x": cx + wm_x - 200, "y": cy + 180}, {"x": cx + wm_x + 80, "y": cy + 260}
        )
        forward_rect = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const d = api.getDrawings().slice(-1)[0];"
            "  const chart = window.SmcDebug.replay.getChart();"
            "  const wm = chart.getWatermark();"
            "  const candles = window.SmcDebug.replay.getPayload().candles;"
            "  return {"
            "    type: d ? d.type : null,"
            "    t2: d ? d.t2 : null,"
            "    lastBarTime: candles[wm].time,"
            "    extendsPastLastBar: Boolean(d && d.t2 > candles[wm].time)"
            "  };"
            "})()"
        )
        check(
            "rectangle dragged into right whitespace extrapolates time past newest candle",
            forward_rect["type"] == "rect" and forward_rect["extendsPastLastBar"],
            forward_rect,
        )

        # 8c. Full reload: drawings, positions and the paper ledger must restore.
        pre_reload = page.js(
            "(() => {"
            "  const summary = window.SmcDebug.replay.getLedgerApi().getSummary();"
            "  return {"
            "    drawings: window.SmcDebug.replay.getDrawingsApi().getDrawings().length,"
            "    positions: window.SmcDebug.replay.getSimulatorApi().getPositions().length,"
            "    balance: summary.balance,"
            "    totalTrades: summary.totalTrades"
            "  };"
            "})()"
        )
        cdp.call("Page.reload", {"ignoreCache": True})
        reloaded = page.wait_until(
            "!!(window.SmcDebug && SmcDebug.replay && SmcDebug.replay.snapshot()"
            " && SmcDebug.replay.snapshot().totalBars > 0)",
            timeout=60,
        )
        post_reload = page.js(
            "(() => {"
            "  const summary = window.SmcDebug.replay.getLedgerApi().getSummary();"
            "  return {"
            "    drawings: window.SmcDebug.replay.getDrawingsApi().getDrawings().length,"
            "    positions: window.SmcDebug.replay.getSimulatorApi().getPositions().length,"
            "    balance: summary.balance,"
            "    totalTrades: summary.totalTrades"
            "  };"
            "})()"
        )
        check(
            "drawings survive a full page reload",
            reloaded
            and pre_reload["drawings"] >= 1
            and post_reload["drawings"] == pre_reload["drawings"],
            {"before": pre_reload, "after": post_reload},
        )
        check(
            "position boxes survive a full page reload",
            reloaded and post_reload["positions"] == pre_reload["positions"],
            {"before": pre_reload, "after": post_reload},
        )
        check(
            "paper ledger balance and trade count survive a reload",
            reloaded
            and abs(post_reload["balance"] - pre_reload["balance"]) < 0.01
            and post_reload["totalTrades"] == pre_reload["totalTrades"],
            {"before": pre_reload, "after": post_reload},
        )

        # 8d. Same month, different timeframe: objects must follow the trader.
        page.js(
            "[].forEach.call(document.querySelectorAll('#replay-timeframes [data-tf]'),"
            " function(b){ if(b.getAttribute('data-tf')==='M15') b.click(); });"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        tf_ok = page.wait_until(
            "SmcDebug.replay.getPayload().meta.timeframe === 'M15'"
            " && SmcDebug.replay.snapshot().totalBars > 0",
            timeout=60,
        )
        tf_state = page.js(
            "(() => {"
            "  const summary = window.SmcDebug.replay.getLedgerApi().getSummary();"
            "  return {"
            "    drawings: window.SmcDebug.replay.getDrawingsApi().getDrawings().length,"
            "    positions: window.SmcDebug.replay.getSimulatorApi().getPositions().length,"
            "    balance: summary.balance"
            "  };"
            "})()"
        )
        check(
            "drawings and positions persist across a timeframe switch",
            tf_ok
            and tf_state["drawings"] == pre_reload["drawings"]
            and tf_state["positions"] == pre_reload["positions"],
            tf_state,
        )
        check(
            "paper ledger persists across a timeframe switch",
            tf_ok and abs(tf_state["balance"] - pre_reload["balance"]) < 0.01,
            {"stored": pre_reload["balance"], "after": tf_state["balance"]},
        )

        # Drawings must not merely survive as data — they must still project to
        # pixels on the new series. M5 anchors are usually not M15 bar times, so
        # timeToCoordinate() returns null for them; without the interpolation
        # fallback the shapes silently disappear after the switch (spec §4.3).
        tf_projection = page.js(
            "(() => {"
            "  const api = window.SmcDebug.replay.getDrawingsApi();"
            "  const list = api.getDrawings();"
            "  const ts = window.SmcDebug.replay.getChart().getChart().timeScale();"
            "  const c = window.SmcDebug.replay.getPayload().candles;"
            "  const times = new Set(c.map(function (x) { return x.time; }));"
            "  const shapes = list.filter(function (d) { return d.type !== 'hline'; });"
            "  return {"
            "    shapes: shapes.length,"
            "    exact: shapes.filter(function (d) {"
            "      return times.has(d.t1) && times.has(d.t2);"
            "    }).length,"
            "    projected: shapes.filter(function (d) {"
            "      return api.getAnchorHandles(d, 1466, 598).length > 0;"
            "    }).length,"
            "    rawNull: shapes.filter(function (d) {"
            "      return ts.timeToCoordinate(d.t1) === null"
            "          || ts.timeToCoordinate(d.t2) === null;"
            "    }).length"
            "  };"
            "})()"
        )
        check(
            "time-anchored drawings still project after a timeframe switch",
            tf_ok
            and tf_projection["shapes"] >= 1
            and tf_projection["projected"] == tf_projection["shapes"],
            tf_projection,
        )

        # Back to M5 so the rest of the suite keeps its assumptions.
        page.js(
            "[].forEach.call(document.querySelectorAll('#replay-timeframes [data-tf]'),"
            " function(b){ if(b.getAttribute('data-tf')==='M5') b.click(); });"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        page.wait_until(
            "SmcDebug.replay.getPayload().meta.timeframe === 'M5'"
            " && SmcDebug.replay.snapshot().totalBars > 0",
            timeout=60,
        )

        # 8e. Different month: no state may leak across month keys.
        page.js(
            "(function(){var m=document.getElementById('replay-month');"
            " m.value='9'; m.dispatchEvent(new Event('change',{bubbles:true}));})()"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        other_month_ok = page.wait_until(
            "SmcDebug.replay.getPayload().meta.start_date.indexOf('2026-09') === 0"
            " && SmcDebug.replay.snapshot().totalBars > 0",
            timeout=60,
        )
        other_month = page.js(
            "(() => {"
            "  const summary = window.SmcDebug.replay.getLedgerApi().getSummary();"
            "  return {"
            "    drawings: window.SmcDebug.replay.getDrawingsApi().getDrawings().length,"
            "    positions: window.SmcDebug.replay.getSimulatorApi().getPositions().length,"
            "    balance: summary.balance,"
            "    totalTrades: summary.totalTrades"
            "  };"
            "})()"
        )
        check(
            "switching month clears the previous month's drawings and positions",
            other_month_ok
            and other_month["drawings"] == 0
            and other_month["positions"] == 0,
            other_month,
        )
        check(
            "switching month resets the paper ledger to its initial balance",
            other_month_ok
            and other_month["totalTrades"] == 0
            and abs(other_month["balance"] - 10000.0) < 0.01,
            other_month,
        )

        # Return to October so the following checks see the original month.
        page.js(
            "(function(){var m=document.getElementById('replay-month');"
            " m.value='10'; m.dispatchEvent(new Event('change',{bubbles:true}));})()"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        back_ok = page.wait_until(
            "SmcDebug.replay.getPayload().meta.start_date.indexOf('2026-10') === 0"
            " && SmcDebug.replay.snapshot().totalBars > 0",
            timeout=60,
        )
        back_state = page.js(
            "(() => {"
            "  const summary = window.SmcDebug.replay.getLedgerApi().getSummary();"
            "  return {"
            "    drawings: window.SmcDebug.replay.getDrawingsApi().getDrawings().length,"
            "    positions: window.SmcDebug.replay.getSimulatorApi().getPositions().length,"
            "    balance: summary.balance"
            "  };"
            "})()"
        )
        check(
            "returning to the month restores its drawings, positions and ledger",
            back_ok
            and back_state["drawings"] == pre_reload["drawings"]
            and back_state["positions"] == pre_reload["positions"]
            and abs(back_state["balance"] - pre_reload["balance"]) < 0.01,
            back_state,
        )

        # Clear to clean up
        page.js("document.getElementById('tool-clear').click()")
        check(
            "no warning banner on a dense month",
            page.js(
                "document.getElementById('replay-warnings-banner').classList.contains('hidden')"
            ),
        )

        # ------------------------------------------------- 3. transport & scrubber
        before = page.snapshot()["index"]
        page.js("document.getElementById('replay-step-forward').click()")
        after = page.snapshot()["index"]
        check(
            "step forward advances exactly one bar",
            after == before + 1,
            f"{before} -> {after}",
        )
        page.js("document.getElementById('replay-step-back').click()")
        check("step back returns to the same bar", page.snapshot()["index"] == before)

        page.js("document.getElementById('replay-play').click()")
        page.wait_until("SmcDebug.replay.snapshot().index > 5", timeout=20)
        playing = page.snapshot()
        check("play advances the replay", playing["index"] > 5, playing["index"])
        check(
            "state badge reads PLAYING", playing["state"] == "PLAYING", playing["state"]
        )

        # ------------------------------------------- 4. follow state machine
        follow = page.js(
            "new Promise(function(resolve){"
            " var c = SmcDebug.replay.getChart();"
            " var ts = c.timeScale();"
            " var r = ts.getVisibleLogicalRange();"
            " ts.setVisibleLogicalRange({from: r.from - 400, to: r.to - 400});"
            " setTimeout(function(){"
            "   resolve({following: c.isFollowing(),"
            "     buttonHidden: document.getElementById('replay-btn-follow').classList.contains('hidden')});"
            " }, 120);"
            "})"
        )
        check(
            "dragging into the past breaks auto-follow",
            follow["following"] is False,
            follow,
        )
        check(
            "floating 'Ikuti Lilin Terbaru' button appears",
            follow["buttonHidden"] is False,
        )
        page.js("document.getElementById('replay-btn-follow').click()")
        check(
            "clicking the follow button restores follow mode",
            page.js("SmcDebug.replay.isFollowing()") is True,
        )

        # Zoom while playing must not break follow (span changes, right edge pinned).
        zoom = page.js(
            "new Promise(function(resolve){"
            " var c = SmcDebug.replay.getChart();"
            " var ts = c.timeScale();"
            " var r = ts.getVisibleLogicalRange();"
            " var span = Math.max(20, (r.to - r.from) / 2);"
            " ts.setVisibleLogicalRange({from: r.to - span, to: r.to});"
            " setTimeout(function(){"
            "   var pinned = c.getWatermark() + 6;"
            "   var now = ts.getVisibleLogicalRange();"
            "   resolve({following: c.isFollowing(), atEdge: Math.abs(now.to - pinned) < 12,"
            "     watermark: c.getWatermark(), to: now.to});"
            " }, 200);"
            "})"
        )
        check(
            "zooming while playing keeps auto-follow", zoom["following"] is True, zoom
        )
        check(
            "zoom keeps the right edge pinned to the active bar", zoom["atEdge"], zoom
        )

        # Real mouse-wheel zoom while playing must preserve follow and stay glued to edge.
        chart_box = page.js(
            "(() => {"
            " var el = document.getElementById('replay-chart');"
            " var rect = el.getBoundingClientRect();"
            " return {"
            "   x: Math.round(rect.left + rect.width / 2),"
            "   y: Math.round(rect.top + rect.height / 2)"
            " };"
            "})()"
        )
        for dy in (-120, -120, 120):
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseWheel",
                    "x": chart_box["x"],
                    "y": chart_box["y"],
                    "deltaX": 0,
                    "deltaY": dy,
                },
            )
            time.sleep(0.05)
        time.sleep(0.1)

        wheel_zoom = page.js(
            "(() => {"
            " var c = SmcDebug.replay.getChart();"
            " var ts = c.timeScale();"
            " var r = ts.getVisibleLogicalRange();"
            " var pinned = c.getWatermark() + 6;"
            " return {"
            "   following: c.isFollowing(),"
            "   atEdge: r ? Math.abs(r.to - pinned) < 1.0 : false,"
            "   watermark: c.getWatermark(),"
            "   to: r ? r.to : null"
            " };"
            "})()"
        )
        check(
            "wheel zoom while playing preserves follow mode",
            wheel_zoom["following"] is True,
            wheel_zoom,
        )
        check(
            "wheel zoom leaves right edge pinned to active bar",
            wheel_zoom["atEdge"] is True,
            wheel_zoom,
        )

        # Gesture C: predominantly vertical drag with incidental horizontal drift must preserve follow
        cx, cy = chart_box["x"], chart_box["y"]
        page.cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": cx,
                "y": cy,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
        )
        for i in range(1, 11):
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": cx + 30 * i // 10,
                    "y": cy - 120 * i // 10,
                    "button": "left",
                    "buttons": 1,
                },
            )
            time.sleep(0.02)
        page.cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": cx + 30,
                "y": cy - 120,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        )
        time.sleep(0.1)

        vert_drag = page.js(
            "(() => {"
            " var c = SmcDebug.replay.getChart();"
            " var ts = c.timeScale();"
            " var r = ts.getVisibleLogicalRange();"
            " var pinned = c.getWatermark() + 6;"
            " return {"
            "   following: c.isFollowing(),"
            "   atEdge: r ? Math.abs(r.to - pinned) < 1.0 : false,"
            "   watermark: c.getWatermark(),"
            "   to: r ? r.to : null"
            " };"
            "})()"
        )
        check(
            "vertical drag with incidental drift preserves follow mode",
            vert_drag["following"] is True,
            vert_drag,
        )
        check(
            "vertical drag leaves right edge pinned to active bar",
            vert_drag["atEdge"] is True,
            vert_drag,
        )

        # Genuinely horizontal drag to past must still break follow mode
        page.cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mousePressed",
                "x": cx,
                "y": cy,
                "button": "left",
                "buttons": 1,
                "clickCount": 1,
            },
        )
        for i in range(1, 11):
            page.cdp.call(
                "Input.dispatchMouseEvent",
                {
                    "type": "mouseMoved",
                    "x": cx + 120 * i // 10,
                    "y": cy,
                    "button": "left",
                    "buttons": 1,
                },
            )
            time.sleep(0.02)
        page.cdp.call(
            "Input.dispatchMouseEvent",
            {
                "type": "mouseReleased",
                "x": cx + 120,
                "y": cy,
                "button": "left",
                "buttons": 0,
                "clickCount": 1,
            },
        )
        time.sleep(0.1)

        horiz_drag = page.js(
            "(() => {"
            " var c = SmcDebug.replay.getChart();"
            " return {"
            "   following: c.isFollowing(),"
            "   buttonHidden: document.getElementById('replay-btn-follow').classList.contains('hidden')"
            " };"
            "})()"
        )
        check(
            "horizontal drag to past breaks follow mode",
            horiz_drag["following"] is False and horiz_drag["buttonHidden"] is False,
            horiz_drag,
        )

        # Restore follow mode for subsequent checks
        page.js("document.getElementById('replay-btn-follow').click()")
        time.sleep(0.1)

        # Playing pan: dragging backward while playing must scroll along once the
        # active candle reaches the right edge, rather than letting it walk off-screen.
        pan_check = page.js(
            "new Promise(function(resolve){"
            " var c = SmcDebug.replay.getChart();"
            " var ts = c.timeScale();"
            " var r = ts.getVisibleLogicalRange();"
            " var w = c.getWatermark();"
            " var span = r.to - r.from;"
            " var targetTo = w + 1;"
            " ts.setVisibleLogicalRange({from: targetTo - span, to: targetTo});"
            " var parkedTo = targetTo;"
            " var timer = setTimeout(function(){"
            "   clearInterval(interval);"
            "   var now = ts.getVisibleLogicalRange();"
            "   var cur = c.getWatermark();"
            "   resolve({"
            "     watermark: cur,"
            "     from: now ? now.from : 0,"
            "     to: now ? now.to : 0,"
            "     inView: now ? (cur >= now.from && cur <= now.to) : false,"
            "     following: c.isFollowing(),"
            "     state: SmcDebug.replay.snapshot().state,"
            "     timedOut: true"
            "   });"
            " }, 5000);"
            " var interval = setInterval(function(){"
            "   var cur = c.getWatermark();"
            "   if (cur >= parkedTo + 1) {"
            "     clearInterval(interval);"
            "     clearTimeout(timer);"
            "     var now = ts.getVisibleLogicalRange();"
            "     resolve({"
            "       watermark: cur,"
            "       from: now ? now.from : 0,"
            "       to: now ? now.to : 0,"
            "       inView: now ? (cur >= now.from && cur <= now.to) : false,"
            "       following: c.isFollowing(),"
            "       state: SmcDebug.replay.snapshot().state,"
            "       timedOut: false"
            "     });"
            "   }"
            " }, 50);"
            "})"
        )
        check(
            "candle stays in view and scrolls along when playback reaches edge",
            pan_check["inView"] is True
            and pan_check["state"] == "PLAYING"
            and not pan_check.get("timedOut"),
            pan_check,
        )

        page.js("document.getElementById('replay-play').click()")
        paused = page.snapshot()
        check("pause freezes the replay", paused["state"] == "PAUSED", paused["state"])

        # Paused means *no* forced movement: park the viewport in the past and make
        # sure nothing drags it back to the edge on its own. The 150 ms settle
        # matters: the pause click lands while the previous zoom check may still
        # have one follow tick queued, and that tick would otherwise be measured
        # as drift.
        parked = page.js(
            "new Promise(function(resolve){"
            " var ts = SmcDebug.replay.getChart().timeScale();"
            " setTimeout(function(){"
            "   var r = ts.getVisibleLogicalRange();"
            "   ts.setVisibleLogicalRange({from: r.from - 600, to: r.to - 600});"
            "   setTimeout(function(){"
            "     var first = ts.getVisibleLogicalRange();"
            "     setTimeout(function(){"
            "       var second = ts.getVisibleLogicalRange();"
            "       resolve({drift: Math.abs(second.to - first.to),"
            "         following: SmcDebug.replay.isFollowing()});"
            "     }, 500);"
            "   }, 50);"
            " }, 150);"
            "})"
        )
        check(
            "paused viewport stays exactly where the user put it",
            parked["drift"] < 1.0,
            parked,
        )

        page.js("document.querySelector('#replay-speeds [data-speed=\"max\"]').click()")
        check("Max speed preset is wired", page.snapshot()["speed"] == "max")
        page.js("document.getElementById('replay-play').click()")
        finished = page.wait_until(
            "SmcDebug.replay.snapshot().state === 'COMPLETED'", timeout=30
        )
        check(
            "Max speed sweeps the session to COMPLETED",
            finished,
            page.snapshot()["state"],
        )
        check(
            "position reaches the last bar",
            page.snapshot()["index"] == page.snapshot()["totalBars"] - 1,
        )

        page.js(
            "(function(){var s=document.getElementById('replay-scrubber');"
            " s.value='3000'; s.dispatchEvent(new Event('input',{bubbles:true}));})()"
        )
        check("scrubber seeks to an arbitrary bar", page.snapshot()["index"] == 3000)

        # M15 playback: the catalogue's second execution timeframe must replay too.
        page.js(
            "[].forEach.call(document.querySelectorAll('#replay-timeframes [data-tf]'),"
            " function(b){ if(b.getAttribute('data-tf')==='M15') b.click(); });"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        page.wait_until(
            "SmcDebug.replay.getPayload().meta.timeframe === 'M15'", timeout=45
        )
        m15 = page.meta()
        check(
            "M15 October 2026 loads its own bar series",
            1000 < m15["total_bars"] < 6048,
            m15["total_bars"],
        )
        page.js("document.getElementById('replay-step-forward').click()")
        page.js("document.getElementById('replay-step-forward').click()")
        m15_pos = page.snapshot()
        check(
            "M15 steps forward bar by bar",
            m15_pos["index"] == 2 and m15_pos["totalBars"] == m15["total_bars"],
            m15_pos["index"],
        )

        # ---------------------------------------------- 5. selector behaviour
        page.js("document.getElementById('replay-mode-month').click()")
        page.js(
            "(function(){var y=document.getElementById('replay-year');"
            " y.value='2019'; y.dispatchEvent(new Event('change',{bubbles:true}));"
            " var m=document.getElementById('replay-month');"
            " m.value='1'; m.dispatchEvent(new Event('change',{bubbles:true}));})()"
        )
        disabled = page.js(
            "{var o={}; [].forEach.call(document.querySelectorAll('#replay-timeframes [data-tf]'),"
            " function(b){o[b.getAttribute('data-tf')]=b.disabled;}); o;}"
        )
        check(
            "2019-01 disables M5 (data starts 2025-06)",
            disabled["M5"] is True,
            disabled,
        )
        check(
            "2019-01 disables M15 (data starts 2022-11)",
            disabled["M15"] is True,
            disabled,
        )
        check(
            "2019-01 keeps H1 selectable (sparse, not absent)",
            disabled["H1"] is False,
            disabled,
        )

        page.js(
            "[].forEach.call(document.querySelectorAll('#replay-timeframes [data-tf]'),"
            " function(b){ if(b.getAttribute('data-tf')==='H1') b.click(); });"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        page.wait_until(
            "SmcDebug.replay.getPayload().meta.timeframe === 'H1'", timeout=45
        )
        sparse_meta = page.meta()
        check(
            "H1 2019-01 loads 27 bars",
            sparse_meta["total_bars"] == 27,
            sparse_meta["total_bars"],
        )
        check(
            "sparse month raises exactly one warning",
            len(sparse_meta["warnings"]) == 1,
            sparse_meta["warnings"],
        )
        check(
            "warning banner is visible",
            page.js(
                "!document.getElementById('replay-warnings-banner').classList.contains('hidden')"
            ),
        )

        page.js("document.getElementById('replay-mode-year').click()")
        page.js(
            "(function(){var y=document.getElementById('replay-year');"
            " y.value='2022'; y.dispatchEvent(new Event('change',{bubbles:true}));})()"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        page.wait_until(
            "SmcDebug.replay.getPayload().meta.period_mode === 'year'", timeout=60
        )
        year_meta = page.meta()
        check(
            "yearly mode loads 12 months of H1 2022",
            year_meta["months_loaded"] == 12,
            year_meta["months_loaded"],
        )
        check(
            "dense year carries no warnings (banner cleared)",
            year_meta["warnings"] == []
            and page.js(
                "document.getElementById('replay-warnings-banner').classList.contains('hidden')"
            ),
            year_meta["warnings"],
        )

        page.js("document.getElementById('replay-mode-custom').click()")
        page.js(
            "(function(){var s=document.getElementById('replay-date-start');"
            " s.value='2026-10-05'; s.dispatchEvent(new Event('change',{bubbles:true}));"
            " var e=document.getElementById('replay-date-end');"
            " e.value='2026-10-07'; e.dispatchEvent(new Event('change',{bubbles:true}));})()"
        )
        page.js(
            "[].forEach.call(document.querySelectorAll('#replay-timeframes [data-tf]'),"
            " function(b){ if(b.getAttribute('data-tf')==='M5') b.click(); });"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        page.wait_until(
            "SmcDebug.replay.getPayload().meta.period_mode === 'custom'", timeout=45
        )
        custom_meta = page.meta()
        check(
            "custom range trims to the day (828 bars, not 864)",
            custom_meta["total_bars"] == 828,
            custom_meta["total_bars"],
        )

        page.js(
            "(function(){var s=document.getElementById('replay-date-start');"
            " s.value='2026-10-31'; s.dispatchEvent(new Event('change',{bubbles:true}));"
            " var e=document.getElementById('replay-date-end');"
            " e.value='2026-10-01'; e.dispatchEvent(new Event('change',{bubbles:true}));})()"
        )
        page.js("document.getElementById('replay-btn-load').click()")
        page.wait_until(
            "!document.getElementById('replay-error-banner').classList.contains('hidden')",
            timeout=30,
        )
        error_text = page.js("document.getElementById('replay-error-text').textContent")
        check(
            "inverted range surfaces the backend 404 wording",
            "end_date harus >= start_date" in error_text,
            error_text[:80],
        )

        # ---------------------------------------------------- 6. layout/scroll
        layout = page.js(
            "({scroll: document.documentElement.scrollHeight,"
            " view: window.innerHeight,"
            " chart: document.getElementById('replay-chart').clientHeight,"
            " overflow: getComputedStyle(document.body).overflowY})"
        )
        check(
            "page never scrolls (single viewport)",
            layout["scroll"] <= layout["view"] + 2,
            f"{layout['scroll']} vs {layout['view']}",
        )
        check("body is pinned", layout["overflow"] == "hidden", layout["overflow"])
        check("chart fills the panel", layout["chart"] > 400, f"{layout['chart']}px")

        # ------------------------------------------------------ 7. fullscreen
        page.js("document.body.focus()")
        page.js(
            "document.dispatchEvent(new KeyboardEvent('keydown',{key:'f',code:'KeyF',bubbles:true}))"
        )
        page.wait_until(
            "document.getElementById('replay-btn-fullscreen').textContent.includes('Normal')",
            timeout=15,
        )
        fs = page.js(
            "({native: !!document.fullscreenElement,"
            " css: document.getElementById('replay-chart-wrap').classList.contains('is-fullscreen'),"
            " label: document.getElementById('replay-btn-fullscreen').textContent.trim(),"
            " chart: document.getElementById('replay-chart').clientHeight})"
        )
        check("F enters fullscreen", fs["native"] or fs["css"], fs)
        check(
            "fullscreen button reflects the state", "Normal" in fs["label"], fs["label"]
        )
        check("chart still fills the screen", fs["chart"] > 400, f"{fs['chart']}px")

        fs_hud = page.js(
            "(() => {"
            "  const hud = document.getElementById('replay-hud').getBoundingClientRect();"
            "  const wrap = document.getElementById('replay-chart-wrap').getBoundingClientRect();"
            "  const plot = document.getElementById('replay-chart').getBoundingClientRect();"
            "  const tsWidth = window.SmcDebug.replay.getChart().chart.timeScale().width();"
            "  return { left: hud.left - wrap.left, top: hud.top - wrap.top,"
            "           right: hud.right - plot.left, plotWidth: tsWidth };"
            "})()"
        )
        check(
            "HUD keeps its top-left anchor in fullscreen",
            45 <= fs_hud["left"] <= 70 and 0 <= fs_hud["top"] <= 20,
            fs_hud,
        )
        check(
            "HUD still clears the price scale in fullscreen",
            fs_hud["right"]
            <= fs_hud["plotWidth"] - (120 if fs_hud["plotWidth"] >= 1200 else 40),
            fs_hud,
        )

        page.js(
            "document.exitFullscreen ? document.exitFullscreen() : Promise.resolve()"
        )
        page.wait_until(
            "document.getElementById('replay-btn-fullscreen').textContent.includes('Fullscreen')",
            timeout=15,
        )
        back = page.js(
            "({label: document.getElementById('replay-btn-fullscreen').textContent.trim(),"
            " chart: document.getElementById('replay-chart').clientHeight,"
            " scroll: document.documentElement.scrollHeight,"
            " view: window.innerHeight})"
        )
        check(
            "exiting fullscreen restores the layout",
            "Fullscreen" in back["label"],
            back["label"],
        )
        check(
            "chart resizes back without page scroll", back["scroll"] <= back["view"] + 2
        )
        check(
            "chart height survives the round trip",
            back["chart"] > 400,
            f"{back['chart']}px",
        )

        # ------------------------------------------------------- 8. cleanliness
        errors: list[str] = []
        for event in cdp.events:
            method = event.get("method")
            params = event.get("params", {})
            if method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails", {})
                errors.append(
                    str(
                        details.get("exception", {}).get("description")
                        or details.get("text")
                    )
                )
            elif method == "Runtime.consoleAPICalled" and params.get("type") == "error":
                args_ = params.get("args", [])
                errors.append(
                    " ".join(
                        str(a.get("value", a.get("description", ""))) for a in args_
                    )
                )
            elif method == "Log.entryAdded":
                entry = params.get("entry", {})
                if entry.get("level") == "error":
                    text = str(entry.get("text", ""))
                    url = str(entry.get("url", ""))
                    # The inverted-range probe below *intends* to earn a 404; the
                    # browser logs it as a failed resource with the query string.
                    if "start_date=" in url and "end_date=" in url:
                        continue
                    errors.append(f"{text} [{url}]" if url else text)
        check("no uncaught page errors", not errors, errors[:2])
    finally:
        try:
            cdp.close()
        finally:
            proc.kill()

    print(f"\nAll {len(CHECKS)} pure-replay checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
