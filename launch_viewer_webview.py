# launch_viewer_webview.py
# -*- coding: utf-8 -*-
"""
Created on Sun Oct 12 02:26:25 2025
Trace Timeline Viewer Launcher (final)

@author: RaazRishi

Robust launcher: starts an HTTP server serving a bundled or local 'viewer' folder,
launches a dedicated Chromium-like browser in a new console with an ephemeral profile,
waits for that process to exit, then stops the server and cleans up lock/profile.

Features:
- Finds a free port starting at DEFAULT_PORT
- Detects PyInstaller frozen execution (serves from sys._MEIPASS/viewer)
- Uses CREATE_NEW_CONSOLE on Windows so browser appears in a separate terminal
- Launches Chromium/Edge/Brave with --app and --user-data-dir for a dedicated process
- Falls back to default browser + polling when dedicated browser not available
- Robust lock acquisition that removes stale lock files
- Safe cleanup with retries for profile removal
- Command-line help and version support
- Signal handling for graceful shutdown
- Adds CLI flags: --port to force port, --no-new-console for CI
- Exposes /health endpoint returning 200 JSON
- Prints machine-friendly VIEWER_URL=... line on startup for easy parsing
- Uses argparse for robust CLI handling and help text
- Launches Chromium-like browser in a new console (Windows) with ephemeral profile
- Falls back to system browser + polling when dedicated browser is unavailable
- Clean lock file handling, signal handling, and profile cleanup
"""
from __future__ import annotations

import os
import sys
import json
import time
import signal
import socket
import shutil
import tempfile
import threading
import subprocess
import urllib.request
from http.server import HTTPServer, SimpleHTTPRequestHandler
from typing import Optional, Tuple
from functools import partial

# Version info
__version__ = "1.2.0"

# Constants
CREATE_NEW_CONSOLE = 0x00000010  # Windows subprocess flag
HOST = "127.0.0.1"
DEFAULT_PORT = 8080
PORT_SEARCH_RANGE = 200
SERVER_START_TIMEOUT = 3.0
FALLBACK_POLL_TIMEOUT = 300
PROFILE_CLEANUP_RETRIES = 3
PROFILE_CLEANUP_DELAY = 0.2

# Global shutdown flag for signal handling
_shutdown_requested = False

# ---- Utilities -------------------------------------------------------------

def log(*args, **kwargs):
    print(*args, **kwargs, flush=True)


def find_free_port(start_port: int = DEFAULT_PORT, max_attempts: int = PORT_SEARCH_RANGE) -> int:
    for port in range(start_port, start_port + max_attempts):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((HOST, port))
                return port
        except OSError:
            continue
    raise RuntimeError(f"No free port found in range {start_port}-{start_port + max_attempts - 1}")

# ---- Signal handling -------------------------------------------------------

def signal_handler(signum, frame):
    global _shutdown_requested
    log(f"Received signal {signum}; requesting shutdown.")
    _shutdown_requested = True


def setup_signal_handlers():
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal_handler)
    except Exception as e:
        log("Warning: failed to setup signal handlers:", e)


# Web server handler with /health
class ViewerRequestHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            payload = {"status": "ok"}
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

# ---- Stoppable HTTP server wrapper ----------------------------------------

class StoppableHTTPServer(HTTPServer):
    def run(self):
        try:
            self.serve_forever()
        except Exception:
            pass

    def stop(self):
        try:
            self.shutdown()
        finally:
            try:
                self.server_close()
            except Exception:
                pass


def start_server(serve_dir: str, preferred_port: Optional[int]) -> Tuple[StoppableHTTPServer, threading.Thread, int]:
    # Determine port
    if preferred_port:
        try:
            port = find_free_port(preferred_port, 1)
        except Exception:
            raise RuntimeError(f"Preferred port {preferred_port} unavailable")
    else:
        port = find_free_port(DEFAULT_PORT)

    # Use handler factory that serves from serve_dir without changing cwd
    handler_cls = partial(ViewerRequestHandler, directory=serve_dir)
    server = StoppableHTTPServer((HOST, port), handler_cls)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for server socket to accept connections
    deadline = time.time() + SERVER_START_TIMEOUT
    while time.time() < deadline and not _shutdown_requested:
        try:
            with socket.create_connection((HOST, port), timeout=0.5):
                break
        except (ConnectionRefusedError, OSError):
            time.sleep(0.05)
    else:
        if _shutdown_requested:
            raise KeyboardInterrupt("Shutdown requested during server startup")
        raise RuntimeError("Server failed to start within timeout")

    return server, thread, port

# ---- Browser launch helpers -----------------------------------------------

def find_chrome_like() -> Optional[str]:
    candidates = [
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        r"C:\Program Files\Chromium\Application\chrome.exe",
        # Add Linux/macOS paths
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def cleanup_profile(profile_dir: Optional[str]) -> None:
    if not profile_dir:
        return
    for attempt in range(PROFILE_CLEANUP_RETRIES):
        try:
            if os.path.isdir(profile_dir):
                shutil.rmtree(profile_dir)
            return
        except Exception:
            if attempt < PROFILE_CLEANUP_RETRIES - 1:
                time.sleep(PROFILE_CLEANUP_DELAY)
    log(f"Warning: could not remove profile directory {profile_dir}")


def launch_browser_in_new_terminal(url: str, use_new_console: bool) -> Tuple[Optional[subprocess.Popen], Optional[str]]:
    exe = find_chrome_like()
    if not exe:
        try:
            import webbrowser
            webbrowser.open(url, new=2) # new=2 = new window
            log("Opened in system default browser (fallback).")
            return None, None
        except Exception as e:
            log("Fallback open failed:", e)
            return None, None

    profile = tempfile.mkdtemp(prefix="viewer-profile-")
    cmd = [
        exe,
        f'--app={url}',
        f'--user-data-dir={profile}',
        '--no-first-run',
        '--no-default-browser-check',
        '--disable-extensions',
    ]
    try:
        if os.name == "nt" and use_new_console:
            proc = subprocess.Popen(cmd, creationflags=CREATE_NEW_CONSOLE)
        else:
            proc = subprocess.Popen(cmd)
        log(f"Launched browser: {exe} (pid={proc.pid}) profile={profile}")
        return proc, profile
    except Exception as e:
        log("Failed to launch browser executable:", e)
        cleanup_profile(profile)
        return None, None

# ---- Lock file management -------------------------------------------------

def _windows_process_exists(pid: int) -> bool:
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    except Exception:
        return False


def _posix_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def acquire_lock(lock_path: str) -> bool:
    if os.path.exists(lock_path):
        try:
            with open(lock_path, "r") as f:
                raw = f.read().strip()
            old_pid = int(raw)
        except Exception:
            # corrupted lock; remove it
            try:
                os.remove(lock_path)
                log("Removed corrupted lock file.")
            except Exception:
                pass
            old_pid = None

        if old_pid:
            alive = _windows_process_exists(old_pid) if os.name == "nt" else _posix_pid_alive(old_pid)
            if alive:
                log(f"Another instance appears to be running (PID {old_pid}). Aborting.")
                return False
            else:
                log(f"Removing stale lock file for PID {old_pid}.")
                try:
                    os.remove(lock_path)
                except Exception:
                    pass

    try:
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
        return True
    except Exception as e:
        log("Failed to create lock file:", e)
        return False


def release_lock(lock_path: str) -> None:
    try:
        if os.path.exists(lock_path):
            os.remove(lock_path)
    except Exception as e:
        log("Warning: failed to remove lock file:", e)

# ---- Main run logic ------------------------------------------------------

def run_and_block(serve_dir: str, lock_path: Optional[str], preferred_port: Optional[int], use_new_console: bool) -> bool:
    if lock_path and not acquire_lock(lock_path):
        return False

    server = None
    profile = None
    proc = None

    try:
        log(f"Starting HTTP server for directory: {serve_dir}")
        server, thread, port = start_server(serve_dir, preferred_port)
        url = f"http://{HOST}:{port}/timeline_viewer.html"

        # Print machine-friendly line for integration tests to parse
        print(f"VIEWER_URL={url}", flush=True)
        log(f"Server started at {url}")

        if _shutdown_requested:
            return False

        proc, profile = launch_browser_in_new_terminal(url, use_new_console)

        try:
            if proc:
                log("Waiting for browser process to exit...")
                while proc.poll() is None and not _shutdown_requested:
                    time.sleep(0.1)
                if _shutdown_requested:
                    log("Shutdown requested; terminating browser process...")
                    try:
                        proc.terminate()
                        proc.wait(timeout=5)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                else:
                    log("Browser process exited.")
            else:
                log("Fallback: polling /health until unreachable or timeout.")
                deadline = time.time() + FALLBACK_POLL_TIMEOUT
                while time.time() < deadline and not _shutdown_requested:
                    try:
                        urllib.request.urlopen(f"http://{HOST}:{port}/health", timeout=1.0)
                        time.sleep(0.5)
                    except Exception:
                        log("Detected server unreachable; assuming browser/tab closed.")
                        break
                else:
                    if _shutdown_requested:
                        log("Shutdown requested during fallback polling.")
                    else:
                        log("Fallback poll timed out; continuing to shutdown.")
        finally:
            log("Stopping HTTP server...")
            if server:
                try:
                    server.stop()
                except Exception as e:
                    log("Error stopping server:", e)
            cleanup_profile(profile)

    except KeyboardInterrupt:
        log("Interrupted by user.")
        return False
    except Exception as e:
        log("Error during execution:", e)
        return False
    finally:
        if lock_path:
            release_lock(lock_path)

    return not _shutdown_requested

# ---- Serve directory detection (local vs frozen) --------------------------

def get_serve_dir() -> str:
    """Detect serve directory for both local development and frozen execution."""
    # If frozen by PyInstaller, serve from the bundled viewer folder in _MEIPASS
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            candidate = os.path.join(base, "viewer")
            if os.path.isdir(candidate):
                return candidate
            # Fallback: if viewer was placed at top-level of _MEIPASS, use that
            return base
    # Otherwise serve from local project viewer folder
    local_candidate = os.path.join(os.getcwd(), "viewer")
    if os.path.isdir(local_candidate):
        return local_candidate
    raise FileNotFoundError(f"Viewer directory not found at {local_candidate}")


def parse_args(argv: Optional[list] = None):
    import argparse
    p = argparse.ArgumentParser(description="Trace Timeline Viewer Launcher")
    p.add_argument("--port", type=int, help="Preferred port to bind the server to")
    p.add_argument("--no-new-console", action="store_true", help="Do not create a new console for the browser (useful for CI/headless)")
    p.add_argument("-v", "--version", action="store_true", help="Show version and exit")
    return p.parse_args(argv)


def main(argv: Optional[list] = None) -> int:
    args = parse_args(argv)

    if args.version:
        print(__version__)
        return 0

    setup_signal_handlers()

    try:
        serve_dir = get_serve_dir()
    except Exception as e:
        log("Error locating serve_dir:", e)
        return 2
    
    # Fail fast if serve_dir is missing or not a directory (clearer than FileNotFoundError later)
    if not os.path.isdir(serve_dir):
        log("ERROR: viewer directory not found at %s" % serve_dir)
        return 2

    # Prefer lock next to EXE when frozen, otherwise next to project
    lock_path = os.path.normpath(os.path.join(serve_dir, "..", "viewer.lock"))
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        lock_path = os.path.normpath(os.path.join(exe_dir, "viewer.lock"))

    log(f"Trace Timeline Viewer Launcher v{__version__}")
    log(f"Serving from: {serve_dir}")
    log(f"Lock path: {lock_path}")
    if args.port:
        log(f"Requested port: {args.port}")
    log(f"Use new console for browser: {not args.no_new_console}")

    ok = run_and_block(serve_dir, lock_path=lock_path, preferred_port=args.port, use_new_console=not args.no_new_console)
    if ok:
        log("Viewer session finished successfully.")
        return 0
    else:
        log("Viewer session failed or was interrupted.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
