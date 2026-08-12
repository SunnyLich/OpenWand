"""Live managed-Chromium exact DOM Rewrite smoke test with screenshots."""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.actions.adapters.browser.adapter import _CdpClient  # noqa: E402
from core.rewrite_browser import BrowserRewriteAdapter, build_browser_rewrite_plan  # noqa: E402


def _capture_page(target, output: Path) -> None:
    """Capture Chromium's rendered page surface through its managed CDP tab."""
    client = _CdpClient(target)
    try:
        client.call("Page.enable")
        payload = client.call(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True, "captureBeyondViewport": False},
        )
    finally:
        client.close()
    output.write_bytes(base64.b64decode(str(payload.get("data") or "")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "outputs" / "rewrite_exact_evidence",
    )
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    session_token = "openwand-rewrite-smoke-20260806-20894"
    port = 20894
    page = (PROJECT_ROOT / "testlab" / "rewrite_browser_smoke.html").resolve().as_uri()
    subprocess.Popen(
        [
            str(chrome),
            f"--remote-debugging-port={port}",
            f"--remote-allow-origins=http://127.0.0.1:{port}",
            f"--openwand-managed-session={session_token}",
            f"--user-data-dir={PROJECT_ROOT / '.tmp' / 'chrome-rewrite-profile-4'}",
            "--no-first-run",
            "--disable-extensions",
            "--new-window",
            page,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    adapter = BrowserRewriteAdapter(session_token=session_token)
    deadline = time.monotonic() + 20.0
    target = None
    while time.monotonic() < deadline:
        try:
            target = adapter._browser.discover(url=page)
            break
        except RuntimeError:
            time.sleep(0.25)
    if target is None:
        raise RuntimeError("The isolated managed Chrome tab did not become available.")
    client = _CdpClient(target)
    try:
        client.evaluate(
            """(() => { const root=document.querySelector('#editor'); root.focus(); const node=root.firstChild;
            const range=document.createRange(); range.setStart(node,2); range.setEnd(node,7);
            const selection=getSelection(); selection.removeAllRanges(); selection.addRange(range); return selection.toString(); })()"""
        )
    finally:
        client.close()
    try:
        _capture_page(target, args.output / "browser_before.png")
        snapshot = adapter.inspect_selection({"browser_url": page, "name": "OpenWand Browser Rewrite Smoke"})
        applied = adapter.apply(build_browser_rewrite_plan(snapshot, "clear"))
        time.sleep(0.5)
        _capture_page(target, args.output / "browser_after.png")
        client = _CdpClient(target)
        try:
            readback = str(client.evaluate("document.querySelector('#editor').textContent") or "")
            client.call("Page.close")
        finally:
            client.close()
        payload = {
            "verified": bool(applied and readback == "A clear sentence."),
            "readback": readback,
            "before": str(args.output / "browser_before.png"),
            "after": str(args.output / "browser_after.png"),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["verified"] else 1
    finally:
        try:
            client = _CdpClient(target)
            client.call("Page.close")
            client.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
