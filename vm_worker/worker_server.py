#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VM_ID = int(os.environ.get("VM_ID", "1"))
VM_NAME = os.environ.get("VM_NAME", "VM1_Small")
HOST_ID = os.environ.get("HOST_ID", "host-1")
NOMINAL_MIPS = float(os.environ.get("MIPS", "50.0"))
NOMINAL_BANDWIDTH_MBPS = float(os.environ.get("BW_MBPS", "100.0"))
COST_PER_MI = float(os.environ.get("COST_PER_MI", "0.03"))
CPU_LIMIT_MILLICORES = int(os.environ.get("CPU_LIMIT_MILLICORES", "250"))
CPU_WORKERS = max(1, int(os.environ.get("CPU_WORKERS", "2")))

EXECUTION_LOCK = threading.Lock()
STATS_LOCK = threading.Lock()
CPU_POOL = ThreadPoolExecutor(max_workers=CPU_WORKERS)
VM_STATS = {
    "tasks_completed": 0,
    "queue_length": 0,
    "total_service_s": 0.0,
    "total_cpu_work": 0,
    "total_payload_bytes": 0,
}


def read_cgroup_cpu() -> dict[str, int]:
    try:
        fields: dict[str, int] = {}
        with open("/sys/fs/cgroup/cpu.stat", encoding="utf-8") as handle:
            for line in handle:
                key, value = line.split()
                fields[key] = int(value)
        return fields
    except (FileNotFoundError, OSError, ValueError):
        return {}


def _cpu_chunk(iterations: int, task_id: int, chunk_id: int) -> bytes:
    seed = f"soka-task:{task_id}:chunk:{chunk_id}".encode()
    salt = hashlib.sha256(seed).digest()
    return hashlib.pbkdf2_hmac("sha256", seed, salt, iterations)


def run_cpu_work(cpu_work: int, task_id: int) -> str:
    if cpu_work == 0:
        return hashlib.sha256(f"soka-task:{task_id}:no-cpu".encode()).hexdigest()
    workers = min(CPU_WORKERS, cpu_work)
    base, remainder = divmod(cpu_work, workers)
    futures = [
        CPU_POOL.submit(_cpu_chunk, base + (chunk_id < remainder), task_id, chunk_id)
        for chunk_id in range(workers)
    ]
    combined = hashlib.sha256()
    for future in futures:
        combined.update(future.result())
    return combined.hexdigest()


class WorkerHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


class VMWorkerHandler(BaseHTTPRequestHandler):
    server_version = "SokaWorker/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, status_code: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, separators=(",", ":")).encode()
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _required_header(self, name: str) -> str:
        value = self.headers.get(name)
        if value is None:
            raise ValueError(
                "[worker_server.VMWorkerHandler._required_header.MISSING_HEADER] "
                f"Header wajib {name} tidak ditemukan"
            )
        return value

    def _required_int_header(self, name: str) -> int:
        value = self._required_header(name)
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(
                "[worker_server.VMWorkerHandler._required_int_header.INVALID_INTEGER_HEADER] "
                f"Nilai header {name} harus berupa bilangan bulat"
            ) from exc

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(
                404,
                {
                    "error": (
                        "[worker_server.VMWorkerHandler.do_GET.ROUTE_NOT_FOUND] "
                        "Rute tidak ditemukan"
                    )
                },
            )
            return
        with STATS_LOCK:
            stats = dict(VM_STATS)
        self._send_json(
            200,
            {
                "status": "ready",
                "vm_id": VM_ID,
                "vm_name": VM_NAME,
                "host_id": HOST_ID,
                "pod_hostname": socket.gethostname(),
                "nominal_mips": NOMINAL_MIPS,
                "nominal_bandwidth_mbps": NOMINAL_BANDWIDTH_MBPS,
                "cost_per_mi": COST_PER_MI,
                "cpu_limit_millicores": CPU_LIMIT_MILLICORES,
                "cpu_workers": CPU_WORKERS,
                "stats": stats,
            },
        )

    def do_POST(self) -> None:
        if self.path == "/reset":
            with STATS_LOCK:
                VM_STATS.update(
                    tasks_completed=0,
                    queue_length=0,
                    total_service_s=0.0,
                    total_cpu_work=0,
                    total_payload_bytes=0,
                )
            self._send_json(200, {"reset": True, "vm_id": VM_ID})
            return
        if self.path != "/execute":
            self._send_json(
                404,
                {
                    "error": (
                        "[worker_server.VMWorkerHandler.do_POST.ROUTE_NOT_FOUND] "
                        "Rute tidak ditemukan"
                    )
                },
            )
            return

        try:
            task_id = self._required_int_header("X-Soka-Task-Id")
            task_name = self._required_header("X-Soka-Task-Name")
            cpu_work = self._required_int_header("X-Soka-CPU-Work")
            content_length = self._required_int_header("Content-Length")
            calibration = self.headers.get("X-Soka-Calibration", "0") == "1"
            if cpu_work < 0 or content_length < 0:
                raise ValueError(
                    "[worker_server.VMWorkerHandler.do_POST.NEGATIVE_WORKLOAD] "
                    "Beban CPU dan Content-Length tidak boleh negatif"
                )
            if not task_name or len(task_name) > 128:
                raise ValueError(
                    "[worker_server.VMWorkerHandler.do_POST.INVALID_TASK_NAME] "
                    "Nama tugas tidak valid"
                )
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        arrival_ns = time.perf_counter_ns()
        with STATS_LOCK:
            VM_STATS["queue_length"] += 1

        try:
            with EXECUTION_LOCK:
                start_ns = time.perf_counter_ns()
                cgroup_before = read_cgroup_cpu()

                payload_start_ns = time.perf_counter_ns()
                payload_hash = hashlib.sha256()
                remaining = content_length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError(
                            "[worker_server.VMWorkerHandler.do_POST.INCOMPLETE_BODY] "
                            "Badan permintaan berakhir sebelum mencapai Content-Length"
                        )
                    payload_hash.update(chunk)
                    remaining -= len(chunk)
                payload_finish_ns = time.perf_counter_ns()

                cpu_start_ns = time.perf_counter_ns()
                cpu_checksum = run_cpu_work(cpu_work, task_id)
                cpu_finish_ns = time.perf_counter_ns()

                cgroup_after = read_cgroup_cpu()
                finish_ns = time.perf_counter_ns()
        except ValueError as exc:
            with STATS_LOCK:
                VM_STATS["queue_length"] -= 1
            self._send_json(400, {"error": str(exc)})
            return
        except (BrokenPipeError, ConnectionError, OSError):
            with STATS_LOCK:
                VM_STATS["queue_length"] -= 1
            self._send_json(
                400,
                {
                    "error": (
                        "[worker_server.VMWorkerHandler.do_POST.EXECUTION_FAILED] "
                        "Eksekusi worker gagal"
                    )
                },
            )
            return

        wait_s = (start_ns - arrival_ns) / 1_000_000_000
        payload_read_s = (payload_finish_ns - payload_start_ns) / 1_000_000_000
        cpu_s = (cpu_finish_ns - cpu_start_ns) / 1_000_000_000
        service_s = (finish_ns - start_ns) / 1_000_000_000
        cgroup_cpu_s = (
            cgroup_after.get("usage_usec", 0) - cgroup_before.get("usage_usec", 0)
        ) / 1_000_000
        cgroup_throttled_s = (
            cgroup_after.get("throttled_usec", 0)
            - cgroup_before.get("throttled_usec", 0)
        ) / 1_000_000
        proof = hashlib.sha256(
            f"{task_id}:{cpu_checksum}:{payload_hash.hexdigest()}".encode()
        ).hexdigest()

        with STATS_LOCK:
            VM_STATS["queue_length"] -= 1
            if not calibration:
                VM_STATS["tasks_completed"] += 1
                VM_STATS["total_service_s"] += service_s
                VM_STATS["total_cpu_work"] += cpu_work
                VM_STATS["total_payload_bytes"] += content_length

        self._send_json(
            200,
            {
                "task_id": task_id,
                "task_name": task_name,
                "vm_id": VM_ID,
                "vm_name": VM_NAME,
                "host_id": HOST_ID,
                "pod_hostname": socket.gethostname(),
                "cpu_work": cpu_work,
                "payload_bytes": content_length,
                "waiting_s": wait_s,
                "payload_read_s": payload_read_s,
                "cpu_s": cpu_s,
                "service_s": service_s,
                "cgroup_cpu_s": max(0.0, cgroup_cpu_s),
                "cgroup_throttled_s": max(0.0, cgroup_throttled_s),
                "payload_sha256": payload_hash.hexdigest(),
                "proof_checksum": proof,
            },
        )


def serve() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = WorkerHTTPServer(("0.0.0.0", port), VMWorkerHandler)
    print(f"{VM_NAME} listening on 0.0.0.0:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    serve()
