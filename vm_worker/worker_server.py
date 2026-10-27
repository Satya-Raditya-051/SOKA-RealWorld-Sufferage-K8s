#!/usr/bin/env python3
"""HTTP worker that performs real CPU and payload work inside a VM Pod."""

import hashlib
import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VM_ID = int(os.environ.get("VM_ID", "1"))
VM_NAME = os.environ.get("VM_NAME", "VM1_Small")
HOST_ID = os.environ.get("HOST_ID", "host-1")
MIPS = float(os.environ.get("MIPS", "50.0"))
BW_MBPS = float(os.environ.get("BW_MBPS", "100.0"))
COST_PER_MI = float(os.environ.get("COST_PER_MI", "0.03"))
CPU_LIMIT_MILLICORES = int(os.environ.get("CPU_LIMIT_MILLICORES", "250"))
HASH_ITERATIONS_PER_MI = int(os.environ.get("HASH_ITERATIONS_PER_MI", "35000"))

EXECUTION_LOCK = threading.Lock()
STATS_LOCK = threading.Lock()
VM_STATS = {"tasks_completed": 0, "queue_length": 0, "total_busy_time_s": 0.0}


def run_real_cpu_and_io_workload(length_mi: float, file_size_mb: float) -> str:
    iterations = max(1000, int(length_mi * HASH_ITERATIONS_PER_MI))
    digest = b"soka-kelompok4-realworld-seed"
    for i in range(iterations):
        digest = hashlib.sha256(digest + i.to_bytes(4, "little")).digest()

    payload_bytes = min(8 * 1024 * 1024, max(4096, int(file_size_mb * 16384)))
    buf = bytearray(payload_bytes)
    buf[0] = digest[0]
    buf[-1] = digest[-1]
    time.sleep((file_size_mb / max(1.0, BW_MBPS)) * 0.10)
    return digest.hex()[:16]


class VMWorkerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, status_code: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            self._send_json(404, {"error": "Not found"})
            return
        with STATS_LOCK:
            stats_copy = dict(VM_STATS)
        self._send_json(200, {
            "status": "Ready",
            "vm_id": VM_ID,
            "vm_name": VM_NAME,
            "host_id": HOST_ID,
            "pod_hostname": socket.gethostname(),
            "mips": MIPS,
            "bandwidth_mbps": BW_MBPS,
            "cost_per_mi": COST_PER_MI,
            "cpu_limit_millicores": CPU_LIMIT_MILLICORES,
            "stats": stats_copy,
        })

    def do_POST(self):
        if self.path == "/reset":
            with STATS_LOCK:
                VM_STATS.update(tasks_completed=0, queue_length=0, total_busy_time_s=0.0)
            self._send_json(200, {"reset": True, "vm_id": VM_ID})
            return
        if self.path != "/execute":
            self._send_json(404, {"error": "Endpoint not found"})
            return

        content_len = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_len) if content_len > 0 else b"{}"
        try:
            req = json.loads(raw.decode("utf-8"))
            task_id = int(req.get("task_id", 0))
            task_name = str(req.get("task_name", f"T{task_id}"))
            length_mi = float(req.get("length_mi", 50.0))
            file_size_mb = float(req.get("file_size_mb", 20.0))
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._send_json(400, {"error": f"Invalid request: {exc}"})
            return

        arrival_wall_time = time.time()
        with STATS_LOCK:
            VM_STATS["queue_length"] += 1
        with EXECUTION_LOCK:
            start_wall_time = time.time()
            waiting_time_s = max(0.0, start_wall_time - arrival_wall_time)
            checksum = run_real_cpu_and_io_workload(length_mi, file_size_mb)
            finish_wall_time = time.time()
            exec_time_s = max(0.0001, finish_wall_time - start_wall_time)
        with STATS_LOCK:
            VM_STATS["queue_length"] -= 1
            VM_STATS["tasks_completed"] += 1
            VM_STATS["total_busy_time_s"] += exec_time_s

        self._send_json(200, {
            "task_id": task_id,
            "task_name": task_name,
            "vm_id": VM_ID,
            "vm_name": VM_NAME,
            "host_id": HOST_ID,
            "pod_hostname": socket.gethostname(),
            "arrival_wall_time": arrival_wall_time,
            "start_wall_time": start_wall_time,
            "finish_wall_time": finish_wall_time,
            "waiting_time_s": round(waiting_time_s, 4),
            "real_execution_time_s": round(exec_time_s, 4),
            "cost": round(length_mi * COST_PER_MI, 4),
            "proof_checksum": checksum,
        })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), VMWorkerHandler)
    print(f"[{VM_NAME}] Listening on 0.0.0.0:{port}")
    server.serve_forever()
