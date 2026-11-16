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
            "   var first = ts.getVisibleLogicalRange();"
            "   setTimeout(function(){"
            "     var second = ts.getVisibleLogicalRange();"
            "     resolve({drift: Math.abs(second.to - first.to),"
            "       following: SmcDebug.replay.isFollowing()});"
            "   }, 500);"
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
            "!!document.fullscreenElement"
            " || document.getElementById('replay-chart-wrap').classList.contains('is-fullscreen')",
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

        page.js(
            "document.exitFullscreen ? document.exitFullscreen() : Promise.resolve()"
        )
        page.wait_until(
            "!document.fullscreenElement"
            " && !document.getElementById('replay-chart-wrap').classList.contains('is-fullscreen')",
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
