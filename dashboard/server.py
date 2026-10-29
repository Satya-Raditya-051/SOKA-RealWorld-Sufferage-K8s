#!/usr/bin/env python3
"""Web server dashboard SOKA Real-World Sufferage (Python stdlib saja).

Menyajikan dashboard/index.html pada http://localhost:8090 dan mengekspos API:

  GET  /                     -> dashboard/index.html
  GET  /api/status           -> kubectl nodes/pods + health 4 worker (real-time)
  GET  /api/results          -> isi results/realworld_summary.json (mentah)
  GET  /api/summary          -> ringkasan hasil untuk keperluan chart/tabel
  POST /api/run?scenario=paper|gocj|all&trials=N
                             -> jalankan run_benchmark.py di background (async)
  GET  /api/run/status       -> status + log streaming proses benchmark
  POST /api/run/stop         -> hentikan proses benchmark yang sedang berjalan
  GET  /api/export/csv?type=summary|allocations
                             -> unduhan CSV hasil benchmark

Tidak ada dependensi pihak ketiga (mengikuti konvensi repo ini).
"""
from __future__ import annotations

import csv
import io
import json
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DIR = ROOT / "dashboard"
RESULTS_PATH = ROOT / "results" / "realworld_summary.json"
HOST = "127.0.0.1"
PORT = 8090
WORKER_PORTS = (30081, 30082, 30083, 30084)
VALID_SCENARIOS = ("paper", "gocj", "all")
MAX_LOG_LINES = 2000


class BenchmarkJob:
    """Menjalankan run_benchmark.py di background dengan log streaming."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._log: list[str] = []
        self._cmd: list[str] = []
        self._running = False
        self._returncode: int | None = None
        self._started_at: str | None = None
        self._finished_at: str | None = None
        self._reader: threading.Thread | None = None

    def start(self, scenario: str, trials: int) -> tuple[bool, str]:
        with self._lock:
            if self._running:
                return False, "Benchmark sudah berjalan; tunggu sampai selesai."
            cmd = [
                sys.executable,
                "run_benchmark.py",
                "--scenario",
                scenario,
                "--trials",
                str(trials),
            ]
            self._cmd = cmd
            self._log = [
                f"$ {' '.join(cmd)}",
                f"[dashboard] cwd={ROOT}",
                "[dashboard] menyiapkan koneksi ke 4 worker Kubernetes...",
            ]
            self._returncode = None
            self._started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            self._finished_at = None
            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=ROOT,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                self._running = False
                return False, f"Gagal menjalankan benchmark: {exc}"
            self._running = True
            self._reader = threading.Thread(target=self._read_output, daemon=True)
            self._reader.start()
            return True, "Benchmark dimulai."

    def _read_output(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None
        for line in process.stdout:
            self._append(line.rstrip("\n"))
        returncode = process.wait()
        with self._lock:
            self._running = False
            self._returncode = returncode
            self._finished_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        # _append mengambil self._lock sendiri; jangan dipanggil di dalam blok lock
        # (threading.Lock bukan reentrant -> deadlock).
        if returncode == 0:
            self._append("[dashboard] benchmark selesai; hasil diperbarui.")
        else:
            self._append(f"[dashboard] benchmark gagal (exit={returncode}).")

    def _append(self, line: str) -> None:
        with self._lock:
            self._log.append(line)
            if len(self._log) > MAX_LOG_LINES:
                del self._log[: len(self._log) - MAX_LOG_LINES]

    def stop(self) -> tuple[bool, str]:
        with self._lock:
            process = self._process
            if not self._running or process is None:
                return False, "Tidak ada benchmark yang berjalan."
            process.terminate()
        self._append("[dashboard] proses benchmark dihentikan oleh pengguna.")
        return True, "Benchmark dihentikan."

    def status(self) -> dict[str, object]:
        with self._lock:
            return {
                "running": self._running,
                "returncode": self._returncode,
                "cmd": self._cmd,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "log": list(self._log),
            }


JOB = BenchmarkJob()


def run_kubectl(args: list[str], timeout: float = 8.0) -> dict[str, object]:
    """Jalankan kubectl dan kembalikan JSON-nya (atau pesan error)."""
    try:
        proc = subprocess.run(
            ["kubectl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=ROOT,
        )
    except FileNotFoundError:
        return {"ok": False, "error": "kubectl tidak ditemukan di PATH"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"kubectl {' '.join(args)} timeout"}
    if proc.returncode != 0:
        return {"ok": False, "error": (proc.stderr.strip() or "kubectl gagal")[:500]}
    try:
        return {"ok": True, "data": json.loads(proc.stdout)}
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": f"JSON tidak valid dari kubectl: {exc}"}


def fetch_worker_health(port: int, timeout: float = 3.0) -> dict[str, object]:
    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        payload["port"] = port
        payload["endpoint"] = url
        payload["reachable"] = True
        return payload
    except Exception as exc:  # noqa: BLE001 - semua kegagalan jaringan dilaporkan
        return {
            "port": port,
            "endpoint": url,
            "reachable": False,
            "error": str(exc)[:200],
        }


def build_status() -> dict[str, object]:
    nodes_payload = run_kubectl(["get", "nodes", "-o", "json"])
    pods_payload = run_kubectl(["get", "pods", "-n", "soka-cloud", "-o", "json"])

    nodes: list[dict[str, object]] = []
    if nodes_payload.get("ok"):
        for item in nodes_payload["data"].get("items", []):
            labels = item.get("metadata", {}).get("labels", {})
            status = item.get("status", {})
            conditions = {c.get("type"): c.get("status") for c in status.get("conditions", [])}
            address = next(
                (a.get("address") for a in status.get("addresses", []) if a.get("type") == "InternalIP"),
                None,
            )
            nodes.append(
                {
                    "name": item.get("metadata", {}).get("name"),
                    "ready": conditions.get("Ready") == "True",
                    "roles": list(item.get("metadata", {}).get("labels", {}).keys()),
                    "host_id": labels.get("soka.its.ac.id/host-id", ""),
                    "host_name": labels.get("soka.its.ac.id/host-name", ""),
                    "datacenter": labels.get("soka.its.ac.id/datacenter", ""),
                    "kubelet_version": status.get("nodeInfo", {}).get("kubeletVersion", ""),
                    "internal_ip": address,
                }
            )

    pods: list[dict[str, object]] = []
    if pods_payload.get("ok"):
        for item in pods_payload["data"].get("items", []):
            spec = item.get("spec", {})
            status = item.get("status", {})
            ready = all(
                c.get("ready") for c in status.get("containerStatuses", []) if c.get("ready") is not None
            ) and bool(status.get("containerStatuses"))
            resources = (spec.get("containers") or [{}])[0].get("resources", {})
            pods.append(
                {
                    "name": item.get("metadata", {}).get("name"),
                    "ready": ready,
                    "phase": status.get("phase", ""),
                    "node": spec.get("nodeName", ""),
                    "pod_ip": status.get("podIP", ""),
                    "restarts": sum(
                        c.get("restartCount", 0) for c in status.get("containerStatuses", [])
                    ),
                    "cpu_limit": (resources.get("limits") or {}).get("cpu", ""),
                    "memory_limit": (resources.get("limits") or {}).get("memory", ""),
                }
            )

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(WORKER_PORTS)) as pool:
        workers = list(pool.map(fetch_worker_health, WORKER_PORTS))

    return {
        "cluster": {
            "name": "soka-datacenter",
            "context": "kind-soka-datacenter",
            "namespace": "soka-cloud",
            "nodes": nodes,
            "pods": pods,
            "kubectl_ok": bool(nodes_payload.get("ok") and pods_payload.get("ok")),
            "kubectl_error": nodes_payload.get("error") or pods_payload.get("error"),
        },
        "workers": workers,
        "benchmark_running": JOB.status()["running"],
        "server_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def load_results() -> tuple[dict[str, object] | None, str | None]:
    if not RESULTS_PATH.exists():
        return None, (
            "Hasil benchmark belum ada. Jalankan benchmark terlebih dahulu "
            "(tombol Run pada terminal, atau: python3 run_benchmark.py)."
        )
    try:
        return json.loads(RESULTS_PATH.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"Gagal membaca {RESULTS_PATH.name}: {exc}"


def build_summary(results: dict[str, object]) -> dict[str, object]:
    """Ringkasan ringan untuk chart/tabel frontend."""
    summary = results.get("summary", {})
    method = results.get("method", {})
    environment = results.get("environment", {})
    trials = results.get("trials", [])

    scenario_stats: dict[str, object] = {}
    for scenario, algorithms in summary.items():
        entries = []
        for algorithm, payload in algorithms.items():
            entries.append(
                {
                    "algorithm": algorithm,
                    "trials": payload.get("trials"),
                    "planning_time_s": payload.get("planning_time_s", {}),
                    "metrics": payload.get("metrics", {}),
                }
            )
        # Trial pertama tiap algoritma dipakai untuk Gantt & distribusi host.
        gantt_trials = {}
        for trial in trials:
            if trial.get("scenario") != scenario:
                continue
            gantt_trials.setdefault(trial.get("algorithm"), []).append(
                {
                    "trial": trial.get("trial"),
                    "allocations": [
                        {
                            "task_id": a.get("task_id"),
                            "task_name": a.get("task_name"),
                            "vm_id": a.get("vm_id"),
                            "vm_name": a.get("vm_name"),
                            "host_id": a.get("host_id"),
                            "predicted_start_s": a.get("predicted_start_s"),
                            "predicted_finish_s": a.get("predicted_finish_s"),
                            "actual_start_s": a.get("actual_dispatch_start_s"),
                            "actual_finish_s": a.get("actual_finish_s"),
                            "modeled_cost": a.get("modeled_cost"),
                        }
                        for a in trial.get("allocations", [])
                    ],
                }
            )
        scenario_stats[scenario] = {"algorithms": entries, "gantt": gantt_trials}

    return {
        "scenarios": scenario_stats,
        "method": method,
        "environment": {
            "created_at": environment.get("created_at"),
            "git_commit": environment.get("git_commit"),
            "git_worktree_dirty": environment.get("git_worktree_dirty"),
            "platform": environment.get("platform"),
            "topology_note": environment.get("topology_note"),
        },
    }


def build_csv(kind: str) -> tuple[str, str] | tuple[None, str]:
    results, error = load_results()
    if results is None:
        return None, error or "Hasil tidak tersedia."

    buffer = io.StringIO()
    if kind == "summary":
        writer = csv.writer(buffer)
        summary = results.get("summary", {})
        metric_names: list[str] = []
        for algorithms in summary.values():
            for payload in algorithms.values():
                metric_names = list(payload.get("metrics", {}).keys())
                break
            if metric_names:
                break
        header = ["scenario", "algorithm", "trials", "planning_time_s_median"]
        for name in metric_names:
            header += [f"{name}_median", f"{name}_min", f"{name}_max"]
        writer.writerow(header)
        for scenario, algorithms in summary.items():
            for algorithm, payload in algorithms.items():
                metrics = payload.get("metrics", {})
                row = [
                    scenario,
                    algorithm,
                    payload.get("trials"),
                    payload.get("planning_time_s", {}).get("median"),
                ]
                for name in metric_names:
                    stat = metrics.get(name, {})
                    row += [stat.get("median"), stat.get("min"), stat.get("max")]
                writer.writerow(row)
        return buffer.getvalue(), "soka_summary.csv"

    if kind == "allocations":
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "scenario",
                "trial",
                "algorithm",
                "task_id",
                "task_name",
                "source_mi",
                "cpu_work",
                "input_mbit",
                "vm_id",
                "vm_name",
                "host_id",
                "predicted_start_s",
                "predicted_service_s",
                "predicted_finish_s",
                "modeled_cost",
                "actual_dispatch_start_s",
                "actual_finish_s",
                "client_elapsed_s",
                "worker_waiting_s",
                "worker_service_s",
                "worker_cpu_s",
                "cgroup_cpu_s",
                "cgroup_throttled_s",
                "proof_checksum",
            ]
        )
        for trial in results.get("trials", []):
            for a in trial.get("allocations", []):
                writer.writerow(
                    [
                        trial.get("scenario"),
                        trial.get("trial"),
                        trial.get("algorithm"),
                        a.get("task_id"),
                        a.get("task_name"),
                        a.get("source_mi"),
                        a.get("cpu_work"),
                        a.get("input_mbit"),
                        a.get("vm_id"),
                        a.get("vm_name"),
                        a.get("host_id"),
                        a.get("predicted_start_s"),
                        a.get("predicted_service_s"),
                        a.get("predicted_finish_s"),
                        a.get("modeled_cost"),
                        a.get("actual_dispatch_start_s"),
                        a.get("actual_finish_s"),
                        a.get("client_elapsed_s"),
                        a.get("worker_waiting_s"),
                        a.get("worker_service_s"),
                        a.get("worker_cpu_s"),
                        a.get("cgroup_cpu_s"),
                        a.get("cgroup_throttled_s"),
                        a.get("proof_checksum"),
                    ]
                )
        return buffer.getvalue(), "soka_allocations.csv"

    return None, f"Jenis CSV tidak dikenal: {kind}"


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "SOKADashboard/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # noqa: A003
        # Log server dibungkam agar terminal tidak berisik; log benchmark tetap
        # terlihat lewat /api/run/status.
        if getattr(self.server, "verbose", False):
            super().log_message(fmt, *args)

    # ------------------------------------------------------------------ utils
    def _send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status)

    def _send_bytes(
        self, body: bytes, content_type: str, status: int = 200, extra: dict[str, str] | None = None
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "not found"}, 404)
            return
        content_type = "text/html; charset=utf-8"
        if path.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif path.suffix == ".css":
            content_type = "text/css; charset=utf-8"
        elif path.suffix == ".png":
            content_type = "image/png"
        elif path.suffix == ".ico":
            content_type = "image/x-icon"
        self._send_bytes(path.read_bytes(), content_type)

    # ------------------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._send_file(DASHBOARD_DIR / "index.html")
            return
        if path == "/api/status":
            self._send_json(build_status())
            return
        if path == "/api/results":
            results, error = load_results()
            if results is None:
                self._send_json({"error": error}, 404)
            else:
                self._send_json(results)
            return
        if path == "/api/summary":
            results, error = load_results()
            if results is None:
                self._send_json({"error": error}, 404)
            else:
                self._send_json(build_summary(results))
            return
        if path == "/api/run/status":
            self._send_json(JOB.status())
            return
        if path == "/api/export/csv":
            kind = (query.get("type") or ["summary"])[0]
            content, filename = build_csv(kind)
            if content is None:
                self._send_json({"error": filename}, 400)
                return
            self._send_bytes(
                content.encode("utf-8"),
                "text/csv; charset=utf-8",
                200,
                {"Content-Disposition": f'attachment; filename="{filename}"'},
            )
            return
        if path.startswith("/api/"):
            self._send_json({"error": "endpoint tidak dikenal"}, 404)
            return
        # File statis lain di folder dashboard/
        candidate = (DASHBOARD_DIR / path.lstrip("/")).resolve()
        if DASHBOARD_DIR in candidate.parents or candidate == DASHBOARD_DIR.resolve():
            self._send_file(candidate)
        else:
            self._send_json({"error": "forbidden"}, 403)

    # ------------------------------------------------------------------ POST
    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/api/run":
            scenario = (query.get("scenario") or ["all"])[0]
            trials_raw = (query.get("trials") or ["3"])[0]
            if scenario not in VALID_SCENARIOS:
                self._send_json(
                    {"error": f"scenario tidak dikenal: {scenario}", "valid": list(VALID_SCENARIOS)},
                    400,
                )
                return
            try:
                trials = int(trials_raw)
                if not 1 <= trials <= 50:
                    raise ValueError
            except ValueError:
                self._send_json({"error": "trials harus integer 1..50"}, 400)
                return
            ok, message = JOB.start(scenario, trials)
            self._send_json(
                {"status": "started" if ok else "busy", "message": message, "scenario": scenario, "trials": trials},
                200 if ok else 409,
            )
            return
        if path == "/api/run/stop":
            ok, message = JOB.stop()
            self._send_json({"status": "stopped" if ok else "idle", "message": message}, 200 if ok else 409)
            return
        self._send_json({"error": "endpoint tidak dikenal"}, 404)


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    server.daemon_threads = True
    server.verbose = False
    print(f"SOKA dashboard berjalan di http://localhost:{PORT}")
    print(f"  root    : {ROOT}")
    print(f"  results : {RESULTS_PATH}")
    print("  tekan Ctrl+C untuk berhenti")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBerhenti.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
