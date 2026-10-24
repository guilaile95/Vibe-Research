"""Offline, isolated full-app startup and in-process ASGI latency measurements.

This is not a real-network, browser, target-PC, or external-provider benchmark.
No application source is patched. Data is synthetic and exists only in a temporary
owned directory. Native Intel automatic fetching/scheduling is disabled through
existing validation settings; normal app lifespan and portfolio sleeper execute.

Run with the repository's locked development interpreter, for example:
  python tools/performance/local_api_baseline.py --output result.json
The same harness can measure another checkout via --checkout.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import asyncio
import json
import math
import os
from pathlib import Path
import platform
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time

MARKER = "VR_PERFORMANCE_RESULT="
ROUTES = (
    "/api/health", "/api/watchlist", "/api/myreports", "/api/campaigns",
    "/api/campaigns?security_code=600000", "/api/evidence", "/api/thesis",
    "/api/trades", "/api/native-intel/status", "/api/native-intel/items",
    "/api/native-intel/trending", "/api/trades?include_voided=invalid",
)


def distribution(values):
    ordered = sorted(values)
    return {"n": len(values), "p50": statistics.median(ordered),
            "p95": ordered[max(0, math.ceil(len(ordered) * .95) - 1)],
            "min": ordered[0], "max": ordered[-1], "samples": values}


def rss_mib():
    try:
        import resource
        raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return raw / (1024 * 1024 if sys.platform == "darwin" else 1024)
    except (ImportError, AttributeError):
        return None


def io_bytes():
    try:
        return {k: int(v.strip()) for k, v in
                (line.split(":", 1) for line in Path("/proc/self/io").read_text().splitlines())}
    except (OSError, ValueError):
        return None


def install_network_denial():
    attempts = []
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append("connect")
            raise RuntimeError("offline benchmark denied network")
        return original_connect(sock, address)

    def connect_ex(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append("connect_ex")
            raise RuntimeError("offline benchmark denied network")
        return original_connect_ex(sock, address)

    def getaddrinfo(*args, **kwargs):
        attempts.append("getaddrinfo")
        raise RuntimeError("offline benchmark denied DNS")

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    return attempts


def child(args):
    checkout = Path(args.checkout).resolve()
    sys.path.insert(0, str(checkout / "tools"))
    from validation_environment import configure_pytest_environment, legacy_private_inputs_present
    if legacy_private_inputs_present(checkout):
        raise RuntimeError("Benchmark blocked: private legacy checkout inputs exist")
    with tempfile.TemporaryDirectory(prefix="vibe-performance-local-api-") as owned:
        configure_pytest_environment(Path(owned), os.environ)
        os.chdir(checkout / "backend")
        sys.path.insert(0, str(checkout / "backend"))
        attempts = install_network_denial()
        cpu = time.process_time()
        started = time.perf_counter()
        import app
        import_ms = (time.perf_counter() - started) * 1000
        import_cpu_ms = (time.process_time() - cpu) * 1000
        import_rss = rss_mib()

        async def measure():
            import httpx
            result = {"import_ms": import_ms, "import_cpu_ms": import_cpu_ms,
                      "post_import_peak_rss_mib": import_rss,
                      "campaign_rows": args.campaigns, "routes": {}}
            started = time.perf_counter()
            cpu = time.process_time()
            lifespan = app.lifespan(app.app)
            await lifespan.__aenter__()
            result["lifespan_entry_ms"] = (time.perf_counter() - started) * 1000
            result["lifespan_entry_cpu_ms"] = (time.process_time() - cpu) * 1000
            result["threads_after_startup"] = len(threading.enumerate())
            try:
                if args.mode == "api":
                    import campaign_service
                    setup_start = time.perf_counter()
                    for index in range(args.campaigns):
                        campaign_service.create_campaign(f"{600000 + index % 1000:06d}", "SWING")
                    result["fixture_setup_ms"] = (time.perf_counter() - setup_start) * 1000
                    transport = httpx.ASGITransport(app=app.app)
                    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                        for route in ROUTES:
                            result["routes"][route] = {"wall_ms": [], "cpu_ms": [], "response_bytes": [],
                                                        "status_codes": [], "first_request_ms": None}
                        io_before = io_bytes()
                        for iteration in range(args.samples + 1):
                            for route in ROUTES:
                                row = result["routes"][route]
                                cpu = time.process_time()
                                started = time.perf_counter()
                                response = await client.get(route)
                                elapsed = (time.perf_counter() - started) * 1000
                                used_cpu = (time.process_time() - cpu) * 1000
                                expected_status = 422 if route.endswith("include_voided=invalid") else 200
                                if response.status_code != expected_status:
                                    raise RuntimeError(f"Unexpected benchmark response status: {route} {response.status_code}")
                                value = response.json()
                                if route == "/api/campaigns" and len(value["data"]) != args.campaigns:
                                    raise RuntimeError("Synthetic campaign fixture count mismatch")
                                if iteration == 0:
                                    row["first_request_ms"] = elapsed
                                    row["response_type"] = type(value).__name__
                                    if isinstance(value, dict):
                                        row["top_level_keys"] = sorted(value)
                                        row["data_status"] = value.get("status")
                                else:
                                    row["wall_ms"].append(elapsed)
                                    row["cpu_ms"].append(used_cpu)
                                    row["response_bytes"].append(len(response.content))
                                    row["status_codes"].append(response.status_code)
                        io_after = io_bytes()
                        result["request_io_delta"] = ({key: io_after[key] - io_before[key] for key in io_before}
                                                       if io_before and io_after else None)
                        for row in result["routes"].values():
                            for key in ("wall_ms", "cpu_ms", "response_bytes"):
                                row[key] = distribution(row[key])
                            row["status_codes"] = sorted(set(row["status_codes"]))
            finally:
                started = time.perf_counter()
                cpu = time.process_time()
                await lifespan.__aexit__(None, None, None)
                result["lifespan_exit_ms"] = (time.perf_counter() - started) * 1000
                result["lifespan_exit_cpu_ms"] = (time.process_time() - cpu) * 1000
                result["threads_after_lifespan_exit"] = len(threading.enumerate())
            result["peak_rss_mib"] = rss_mib()
            result["network_attempts"] = attempts
            if attempts:
                raise RuntimeError("Unexpected network attempt during offline benchmark")
            return result

        result = asyncio.run(measure())
        print(MARKER + json.dumps(result, ensure_ascii=False))


def source_identity(checkout):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(checkout), *args], text=True).strip()
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "source_dirty": bool(git("status", "--porcelain", "--", "backend", "frontend", "agent-runtime"))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkout", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--startup-runs", type=int, default=7)
    parser.add_argument("--samples", type=int, default=40)
    parser.add_argument("--measurement-label", default="unqualified-local-run")
    parser.add_argument("--scales", default="0,100,1000")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=("startup", "api"), default="api", help=argparse.SUPPRESS)
    parser.add_argument("--campaigns", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.samples < 1 or args.startup_runs < 1:
        parser.error("sample and startup counts must be positive")
    if args.child:
        child(args)
        return
    if args.output is None:
        parser.error("--output is required")
    checkout = Path(args.checkout).resolve()
    scales = [int(x) for x in args.scales.split(",")]
    if any(x < 0 or x > 10000 for x in scales):
        parser.error("synthetic scales must be within 0..10000")
    sys.path.insert(0, str(checkout / "tools"))
    from validation_environment import unsafe_inherited_name
    env = {k: v for k, v in os.environ.items() if not unsafe_inherited_name(k)
           and k not in {"PYTHONPATH", "PYTHONHOME"}}
    env.update({"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"})
    result = {"schema": "local_api_performance.v1", "source": source_identity(checkout),
              "measurement_label": args.measurement_label,
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "harness_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
                              "cpu_count": os.cpu_count(), "numerical_library_threads": 1,
                              "dependencies": {name: importlib.metadata.version(name)
                                               for name in ("fastapi", "httpx", "duckdb", "numpy")}},
              "limits": ["In-process ASGI, no TCP/server/browser/target-machine timing.",
                         "Synthetic data only; no live market or model providers.",
                         "Fresh Python process is not cold OS page cache or fresh dependency installation.",
                         "Real lifespan; automatic Native Intel fetch and scheduler disabled through existing validation policy.",
                         "Portfolio daemon sleeper executes but no 30-minute periodic tick is measured.",
                         "API first request occurs after lifespan and synthetic fixture setup, not cold application startup.",
                         "Latency samples are interleaved serial requests at concurrency 1.",
                         "Campaign count scales; other local stores remain empty/initialized."],
              "startup": [], "api": []}
    jobs = [("startup", 0)] * args.startup_runs + [("api", scale) for scale in scales]
    for mode, count in jobs:
        command = [sys.executable, str(Path(__file__).resolve()), "--child", "--checkout", str(checkout),
                   "--mode", mode, "--campaigns", str(count), "--samples", str(args.samples)]
        started = time.perf_counter()
        completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=240)
        if completed.returncode:
            # Inputs are synthetic and inherited credentials removed. Keep stack errors
            # for diagnosability without copying environment values into the artifact.
            sys.stderr.write(completed.stderr[-10000:])
            raise RuntimeError(f"Benchmark child failed: mode={mode}, rows={count}, exit={completed.returncode}")
        line = next((line for line in reversed(completed.stdout.splitlines()) if line.startswith(MARKER)), None)
        if line is None:
            raise RuntimeError("Missing benchmark child result")
        row = json.loads(line[len(MARKER):])
        row["child_wall_ms"] = (time.perf_counter() - started) * 1000
        result[mode].append(row)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    result["finished_utc"] = datetime.now(timezone.utc).isoformat()
    result["startup_summary"] = {
        key: distribution([row[key] for row in result["startup"]])
        for key in ("import_ms", "import_cpu_ms", "lifespan_entry_ms", "lifespan_exit_ms", "child_wall_ms")}
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"source": result["source"], "startup_summary": result["startup_summary"],
                      "api_scenarios": len(result["api"])}, indent=2))


if __name__ == "__main__":
    main()
