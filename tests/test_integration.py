# tests/test_integration.py

import os
import sys
import time
import json
import subprocess
import urllib.request
import threading
import re
import pytest

# ---------------- CONFIG ----------------
POLL_TIMEOUT = 30.0
POLL_INTERVAL = 0.25
URL_DETECTION_TIMEOUT = 15.0


# ---------------- HELPERS ----------------
def is_headless():
    return (
        os.environ.get("CI") == "true"
        or (sys.platform.startswith("linux") and not os.environ.get("DISPLAY"))
    )


def stream_output(process, lines):
    for line in iter(process.stdout.readline, ''):
        if line:
            lines.append(line)
            print(f"[LAUNCHER] {line.rstrip()}")
        if process.poll() is not None:
            break


def extract_url(lines):
    text = "".join(lines)

    patterns = [
        r"VIEWER_URL=(http://127\.0\.0\.1:\d+/timeline_viewer\.html)",
        r"Server started at (http://127\.0\.0\.1:\d+/timeline_viewer\.html)",
    ]

    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1)

    return None


def extract_browser_pid(lines):
    for line in lines:
        m = re.search(r"pid=(\d+)", line)
        if m:
            return int(m.group(1))
    return None


def wait_for_http_ok(url):
    base = url.rsplit("/", 1)[0]
    deadline = time.time() + POLL_TIMEOUT

    while time.time() < deadline:
        try:
            resp = urllib.request.urlopen(f"{base}/health", timeout=2)
            if resp.status == 200:
                data = json.loads(resp.read().decode())
                if data.get("status") == "ok":
                    return True
        except Exception:
            pass

        time.sleep(POLL_INTERVAL)

    return False


# ---------------- TEST ----------------
@pytest.mark.integration
def test_launcher_integration():

    port = 60000 + (int(os.environ.get("GITHUB_RUN_NUMBER", "1")) % 1000)

    cmd = [
        sys.executable,
        "launch_viewer_webview.py",
        "--port",
        str(port),
        "--no-new-console",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines = []
    threading.Thread(target=stream_output, args=(proc, lines), daemon=True).start()

    # --- wait for URL ---
    deadline = time.time() + URL_DETECTION_TIMEOUT
    url = None

    while time.time() < deadline:
        url = extract_url(lines)
        if url:
            break
        time.sleep(0.2)

    assert url, "Failed to detect VIEWER_URL from launcher output"

    # --- test HTTP ---
    assert wait_for_http_ok(url), "Health endpoint failed"

    print("[OK] HTTP connectivity successful")

    # --- browser handling ---
    browser_pid = extract_browser_pid(lines)

    if browser_pid:
        print(f"[OK] Found browser PID: {browser_pid}")
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/PID", str(browser_pid)])
            else:
                os.kill(browser_pid, 15)
        except Exception:
            pass
    else:
        if is_headless():
            print("[OK] No browser PID (headless mode)")
        else:
            pytest.fail("Browser PID not found in non-headless environment")

    # --- shutdown ---
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()

    assert proc.returncode in (0, 1), f"Unexpected exit code: {proc.returncode}"
