# integration_test.py
# -*- coding: utf-8 -*-
"""
Created on Wed Oct 15 01:40:44 2025

Integration test for Trace Timeline Viewer Launcher

@author: RaazRishi
"""
"""
Integration test for Trace Timeline Viewer Launcher

This test validates the complete launcher workflow:
- Starts the built EXE (or python script) in background
- Extracts the VIEWER_URL from launcher output
- Tests both /health endpoint and main timeline viewer page
- Kills browser process (if spawned) and verifies EXE exits cleanly
- Collects comprehensive logs to ./integration_test_artifacts/

Usage:
  python integration_test.py --exe path/to/dist/launch_viewer_webview.exe
  python integration_test.py --exe python --script launch_viewer_webview.py --no-new-console
"""
import os
import sys
import time
import json
import signal
import shutil
import argparse
import subprocess
import urllib.request
import threading
import re

# Test configuration
ARTIFACT_DIR = os.path.abspath("integration_test_artifacts")
POLL_TIMEOUT = 30.0
POLL_INTERVAL = 0.25
URL_DETECTION_TIMEOUT = 15.0
BROWSER_KILL_TIMEOUT = 5.0
LAUNCHER_EXIT_TIMEOUT = 10.0

def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def dump_diagnostics(exe_path, log_file):
    print("\n" + "="*50)
    print("DIAGNOSTIC INFORMATION")
    print("="*50)
    print(f"Working directory: {os.getcwd()}")
    print(f"EXE path: {exe_path}")
    print(f"EXE exists: {os.path.exists(exe_path)}")
    print(f"EXE size: {os.path.getsize(exe_path) if os.path.exists(exe_path) else 'N/A'} bytes")
    if os.path.exists(log_file):
        print(f"Log file: {log_file}")
        print(f"Log file size: {os.path.getsize(log_file)} bytes")
    else:
        print(f"Log file not found: {log_file}")
    print("="*50 + "\n")

def test_health_endpoint(base_url, timeout=5.0):
    health_url = f"{base_url}/health"
    try:
        print(f"Testing health endpoint: {health_url}")
        resp = urllib.request.urlopen(health_url, timeout=timeout)
        if resp.status == 200:
            data = json.loads(resp.read().decode())
            status_ok = data.get("status") == "ok"
            print(f"Health endpoint status: {data.get('status', 'unknown')}")
            return status_ok
        else:
            print(f"Health endpoint returned status {resp.status}")
            return False
    except Exception as e:
        print(f"Health endpoint test failed: {e}")
        return False

def wait_for_http_ok(url, timeout=POLL_TIMEOUT):
    base_url = url.rsplit('/', 1)[0]
    health_url = f"{base_url}/health"
    print(f"Waiting for HTTP endpoints (timeout: {timeout}s)")
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            health_resp = urllib.request.urlopen(health_url, timeout=2.0)
            if health_resp.status == 200:
                health_data = json.loads(health_resp.read().decode())
                if health_data.get("status") == "ok":
                    main_resp = urllib.request.urlopen(url, timeout=2.0)
                    if main_resp.status == 200:
                        print("✓ Both endpoints OK")
                        return True
                    last_error = f"Main page returned {main_resp.status}"
                else:
                    last_error = f"Health returned invalid status: {health_data}"
            else:
                last_error = f"Health returned {health_resp.status}"
        except Exception as e:
            last_error = str(e)
        time.sleep(POLL_INTERVAL)
    print(f"✗ HTTP endpoints failed within {timeout}s. Last error: {last_error}")
    return False

def extract_url_from_logs(log_file, timeout=URL_DETECTION_TIMEOUT):
    print(f"Scanning logs for viewer URL (timeout: {timeout}s)")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if not os.path.exists(log_file):
                time.sleep(0.1)
                continue
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            for pattern, label in [
                (r"VIEWER_URL=(http://127\.0\.0\.1:\d+/timeline_viewer\.html)", "VIEWER_URL line"),
                (r"Server started at (http://127\.0\.0\.1:\d+/timeline_viewer\.html)", "'Server started at' line"),
                (r"(http://127\.0\.0\.1:\d+/timeline_viewer\.html)", "generic pattern"),
            ]:
                m = re.search(pattern, txt)
                if m:
                    url = m.group(1)
                    print(f"✓ Found URL via {label}: {url}")
                    return url
        except Exception as e:
            print(f"Error reading log file: {e}")
        time.sleep(0.2)
    print("✗ Failed to locate viewer URL in logs")
    return None

def extract_browser_pid_from_logs(log_file):
    try:
        if not os.path.exists(log_file):
            return None
        with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.search(r"Launched browser:.*?\(pid=(\d+)\)", line)
                if m:
                    pid = int(m.group(1))
                    print(f"✓ Found browser PID: {pid}")
                    return pid
        print("✗ No browser PID found")
        return None
    except Exception as e:
        print(f"Error extracting browser PID: {e}")
        return None

def kill_browser_process(browser_pid):
    if not browser_pid:
        return False
    print(f"Killing browser process {browser_pid}")
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/F", "/PID", str(browser_pid)],
                capture_output=True, text=True, timeout=BROWSER_KILL_TIMEOUT
            )
            if result.returncode == 0:
                print("✓ Browser killed")
                return True
            print(f"✗ taskkill failed: {result.stderr.strip()}")
            return False
        else:
            os.kill(browser_pid, signal.SIGTERM)
            time.sleep(1)
            try:
                os.kill(browser_pid, 0)
                os.kill(browser_pid, signal.SIGKILL)
                print("✓ Browser force-killed")
            except ProcessLookupError:
                print("✓ Browser terminated gracefully")
            return True
    except Exception as e:
        print(f"✗ Failed to kill browser: {e}")
        return False

def stream_output_to_file(process, log_file):
    try:
        if process.stdout is None:
            return
        with open(log_file, "w", encoding="utf-8") as f:
            for line in iter(process.stdout.readline, ''):
                if line == "" and process.poll() is not None:
                    break
                if line:
                    f.write(line)
                    f.flush()
                    print(f"[LAUNCHER] {line.rstrip()}")
    except Exception as e:
        print(f"Error streaming output: {e}")

def build_launcher_command(args):
    if args.script:
        return [args.exe, "-u", args.script] + (["--no-new-console"] if args.no_new_console else []) + (["--port", str(args.port)] if args.port else [])
    cmd = [args.exe] + (["--no-new-console"] if args.no_new_console else []) + (["--port", str(args.port)] if args.port else [])
    return cmd

def main():
    parser = argparse.ArgumentParser(description="Integration test for Trace Timeline Viewer Launcher")
    parser.add_argument("--exe", required=True, help="Path to launcher exe or python interp")
    parser.add_argument("--script", help="Path to python script when --exe is python")
    parser.add_argument("--no-new-console", action="store_true", help="Pass --no-new-console")
    parser.add_argument("--port", type=int, help="Force specific port")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    ensure_dir(ARTIFACT_DIR)
    exe_path = os.path.abspath(args.exe)
    log_file = os.path.join(ARTIFACT_DIR, "launcher_stdout.txt")

    if not os.path.exists(exe_path):
        print(f"✗ Executable not found: {exe_path}")
        sys.exit(2)

    cmd = build_launcher_command(args)
    print("Starting launcher:", " ".join(cmd))
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    except Exception as e:
        print(f"✗ Failed to start launcher: {e}")
        dump_diagnostics(exe_path, log_file)
        sys.exit(2)

    threading.Thread(target=stream_output_to_file, args=(proc, log_file), daemon=True).start()

    final_exit_code = 1
    try:
        url = extract_url_from_logs(log_file, URL_DETECTION_TIMEOUT)
        if not url:
            dump_diagnostics(exe_path, log_file)
            print("="*50, "LAUNCHER OUTPUT", "="*50)
            try:
                with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                    print(f.read())
            except:
                print("Could not read log file")
            proc.terminate(); proc.wait(timeout=5)
            sys.exit(3)

        if not test_health_endpoint(url.rsplit('/',1)[0]):
            print("⚠ Health endpoint test failed, but continuing...")
        if not wait_for_http_ok(url):
            print("✗ Viewer did not respond")
            dump_diagnostics(exe_path, log_file)
            proc.terminate(); proc.wait(timeout=5)
            sys.exit(4)

        print("✓ HTTP connectivity successful")
        browser_pid = extract_browser_pid_from_logs(log_file)
        browser_killed = kill_browser_process(browser_pid) if browser_pid else False
        if not browser_killed:
            proc.terminate()

        try:
            exit_code = proc.wait(timeout=LAUNCHER_EXIT_TIMEOUT)
            print(f"✓ Launcher exited with code: {exit_code}")
            final_exit_code = 0 if exit_code in (0,1) else 1
        except subprocess.TimeoutExpired:
            print("✗ Launcher did not exit, killing")
            proc.kill(); proc.wait(timeout=5)
            final_exit_code = 1

    except KeyboardInterrupt:
        print("✗ Test interrupted")
        proc.terminate(); proc.wait(timeout=5)
        final_exit_code = 130

    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        dump_diagnostics(exe_path, log_file)
        proc.terminate(); proc.wait(timeout=5)
        final_exit_code = 1

    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait(timeout=2)

    print(f"\nArtifacts in: {ARTIFACT_DIR}\nLog file: {log_file}")
    print("🎉 Test passed!" if final_exit_code == 0 else "💥 Test failed!")
    sys.exit(final_exit_code)

if __name__ == "__main__":
    main()
