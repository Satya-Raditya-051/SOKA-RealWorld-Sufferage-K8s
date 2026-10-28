from __future__ import annotations

import hashlib
import http.client
import json
import math
import statistics
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Protocol, TypedDict, cast
from urllib.parse import urlparse

from scheduler.models import CalibrationProfile, TaskAllocation, VMNode


class WorkerStats(TypedDict):
    tasks_completed: int
    queue_length: int
    total_service_s: float
    total_cpu_work: int
    total_payload_bytes: int


class HealthResponse(TypedDict):
    status: str
    vm_id: int
    vm_name: str
    host_id: str
    pod_hostname: str
    nominal_mips: float
    nominal_bandwidth_mbps: float
    cost_per_mi: float
    cpu_limit_millicores: int
    cpu_workers: int
    stats: WorkerStats


class ExecutionMeasurements(TypedDict):
    client_elapsed_s: float
    waiting_s: float
    payload_read_s: float
    cpu_s: float
    service_s: float
    cgroup_cpu_s: float
    cgroup_throttled_s: float
    payload_sha256: str
    proof_checksum: str


class ExecutionResult(ExecutionMeasurements):
    task_id: int
    task_name: str
    vm_id: int
    vm_name: str
    host_id: str
    pod_hostname: str
    cpu_work: int
    payload_bytes: int


class AllocationClient(Protocol):
    def execute(
        self,
        task_id: int,
        task_name: str,
        cpu_work: int,
        payload_bytes: int,
    ) -> ExecutionMeasurements: ...


class WorkerClient:
    def __init__(self, vm: VMNode, timeout_s: float = 120.0):
        self.vm = vm
        self.timeout_s = timeout_s
        parsed = urlparse(vm.endpoint_url)
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.path not in ("", "/")
        ):
            raise ValueError(
                "[k8s_broker.WorkerClient.__init__.INVALID_ENDPOINT] "
                f"Endpoint worker tidak valid: {vm.endpoint_url}"
            )
        self.host = parsed.hostname
        self.port = parsed.port or 80

    def _json_request(self, method: str, path: str) -> dict[str, object]:
        connection = http.client.HTTPConnection(
            self.host, self.port, timeout=self.timeout_s
        )
        try:
            connection.request(method, path, body=b"" if method == "POST" else None)
            response = connection.getresponse()
            body = response.read()
        finally:
            connection.close()
        payload = _decode_json(body, self.vm.name)
        if response.status != 200:
            raise RuntimeError(
                "[k8s_broker.WorkerClient._json_request.HTTP_ERROR] "
                f"Worker {self.vm.name} pada {path} mengembalikan HTTP "
                f"{response.status}: {payload}"
            )
        return payload

    def health(self) -> HealthResponse:
        payload = self._json_request("GET", "/health")
        if payload.get("status") != "ready" or payload.get("vm_id") != self.vm.id:
            raise RuntimeError(
                "[k8s_broker.WorkerClient.health.INVALID_HEALTH_RESPONSE] "
                f"Respons kesehatan dari {self.vm.name} tidak sesuai: {payload}"
            )
        stats_value = payload.get("stats")
        if not isinstance(stats_value, dict):
            raise TypeError(
                "[k8s_broker.WorkerClient.health.INVALID_STATS_RESPONSE] "
                f"Respons statistik dari {self.vm.name} tidak valid: {payload}"
            )
        stats = cast(dict[str, object], stats_value)
        return {
            "status": _required_str(payload, "status", self.vm.name),
            "vm_id": _required_int(payload, "vm_id", self.vm.name),
            "vm_name": _required_str(payload, "vm_name", self.vm.name),
            "host_id": _required_str(payload, "host_id", self.vm.name),
            "pod_hostname": _required_str(payload, "pod_hostname", self.vm.name),
            "nominal_mips": _required_float(payload, "nominal_mips", self.vm.name),
            "nominal_bandwidth_mbps": _required_float(
                payload, "nominal_bandwidth_mbps", self.vm.name
            ),
            "cost_per_mi": _required_float(payload, "cost_per_mi", self.vm.name),
            "cpu_limit_millicores": _required_int(
                payload, "cpu_limit_millicores", self.vm.name
            ),
            "cpu_workers": _required_int(payload, "cpu_workers", self.vm.name),
            "stats": {
                "tasks_completed": _required_int(
                    stats, "tasks_completed", self.vm.name
                ),
                "queue_length": _required_int(stats, "queue_length", self.vm.name),
                "total_service_s": _required_float(
                    stats, "total_service_s", self.vm.name
                ),
                "total_cpu_work": _required_int(stats, "total_cpu_work", self.vm.name),
                "total_payload_bytes": _required_int(
                    stats, "total_payload_bytes", self.vm.name
                ),
            },
        }

    def reset(self) -> None:
        payload = self._json_request("POST", "/reset")
        if payload.get("reset") is not True:
            raise RuntimeError(
                "[k8s_broker.WorkerClient.reset.RESET_FAILED] "
                f"Gagal mengatur ulang {self.vm.name}: {payload}"
            )

    def execute(
        self,
        task_id: int,
        task_name: str,
        cpu_work: int,
        payload_bytes: int,
        calibration: bool = False,
    ) -> ExecutionResult:
        if cpu_work < 0 or payload_bytes < 0:
            raise ValueError(
                "[k8s_broker.WorkerClient.execute.NEGATIVE_WORKLOAD] "
                "Beban CPU dan ukuran payload tidak boleh negatif"
            )
        connection = http.client.HTTPConnection(
            self.host, self.port, timeout=self.timeout_s
        )
        payload_seed = hashlib.sha256(f"soka-payload:{task_id}".encode()).digest()
        payload_chunk = payload_seed * (1024 * 1024 // len(payload_seed))
        sent_hash = hashlib.sha256()
        start_ns = time.perf_counter_ns()
        try:
            connection.putrequest("POST", "/execute", skip_accept_encoding=True)
            connection.putheader("Content-Length", str(payload_bytes))
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("X-Soka-Task-Id", str(task_id))
            connection.putheader("X-Soka-Task-Name", task_name)
            connection.putheader("X-Soka-CPU-Work", str(cpu_work))
            connection.putheader("X-Soka-Calibration", "1" if calibration else "0")
            connection.endheaders()
            remaining = payload_bytes
            while remaining:
                chunk = payload_chunk[: min(len(payload_chunk), remaining)]
                connection.send(chunk)
                sent_hash.update(chunk)
                remaining -= len(chunk)
            response = connection.getresponse()
            body = response.read()
        finally:
            connection.close()
        finish_ns = time.perf_counter_ns()
        payload = _decode_json(body, self.vm.name)
        if response.status != 200:
            raise RuntimeError(
                "[k8s_broker.WorkerClient.execute.HTTP_ERROR] "
                f"Eksekusi pada {self.vm.name} mengembalikan HTTP "
                f"{response.status}: {payload}"
            )
        result: ExecutionResult = {
            "task_id": _required_int(payload, "task_id", self.vm.name),
            "task_name": _required_str(payload, "task_name", self.vm.name),
            "vm_id": _required_int(payload, "vm_id", self.vm.name),
            "vm_name": _required_str(payload, "vm_name", self.vm.name),
            "host_id": _required_str(payload, "host_id", self.vm.name),
            "pod_hostname": _required_str(payload, "pod_hostname", self.vm.name),
            "cpu_work": _required_int(payload, "cpu_work", self.vm.name),
            "payload_bytes": _required_int(payload, "payload_bytes", self.vm.name),
            "waiting_s": _required_float(payload, "waiting_s", self.vm.name),
            "payload_read_s": _required_float(payload, "payload_read_s", self.vm.name),
            "cpu_s": _required_float(payload, "cpu_s", self.vm.name),
            "service_s": _required_float(payload, "service_s", self.vm.name),
            "cgroup_cpu_s": _required_float(payload, "cgroup_cpu_s", self.vm.name),
            "cgroup_throttled_s": _required_float(
                payload, "cgroup_throttled_s", self.vm.name
            ),
            "payload_sha256": _required_str(payload, "payload_sha256", self.vm.name),
            "proof_checksum": _required_str(payload, "proof_checksum", self.vm.name),
            "client_elapsed_s": (finish_ns - start_ns) / 1_000_000_000,
        }
        if result["vm_id"] != self.vm.id or result["task_id"] != task_id:
            raise RuntimeError(
                "[k8s_broker.WorkerClient.execute.RESPONSE_MISMATCH] "
                f"Respons eksekusi dari {self.vm.name} tidak cocok: {result}"
            )
        if result["payload_bytes"] != payload_bytes or result["cpu_work"] != cpu_work:
            raise RuntimeError(
                "[k8s_broker.WorkerClient.execute.INCOMPLETE_EXECUTION] "
                f"Eksekusi yang dilaporkan {self.vm.name} tidak lengkap: {result}"
            )
        if result["payload_sha256"] != sent_hash.hexdigest():
            raise RuntimeError(
                "[k8s_broker.WorkerClient.execute.CHECKSUM_MISMATCH] "
                f"Checksum payload dari {self.vm.name} tidak cocok"
            )
        return result


def _decode_json(body: bytes, worker_name: str) -> dict[str, object]:
    try:
        decoded: object = json.loads(body.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "[k8s_broker._decode_json.INVALID_JSON] "
            f"Respons JSON dari {worker_name} tidak valid"
        ) from exc
    if not isinstance(decoded, dict):
        raise TypeError(
            "[k8s_broker._decode_json.INVALID_JSON_OBJECT] "
            f"Respons JSON dari {worker_name} harus berupa objek"
        )
    return cast(dict[str, object], decoded)


def _required_int(payload: Mapping[str, object], key: str, worker_name: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(
            "[k8s_broker._required_int.INVALID_INTEGER] "
            f"Nilai {key!r} dalam respons dari {worker_name} harus berupa bilangan bulat"
        )
    return value


def _required_float(payload: Mapping[str, object], key: str, worker_name: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(
            "[k8s_broker._required_float.INVALID_NUMBER] "
            f"Nilai {key!r} dalam respons dari {worker_name} harus berupa angka"
        )
    number = float(value)
    if not math.isfinite(number):
        raise RuntimeError(
            "[k8s_broker._required_float.NON_FINITE_NUMBER] "
            f"Nilai {key!r} dalam respons dari {worker_name} harus berupa angka terbatas"
        )
    return number


def _required_str(payload: Mapping[str, object], key: str, worker_name: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise TypeError(
            "[k8s_broker._required_str.INVALID_STRING] "
            f"Nilai {key!r} dalam respons dari {worker_name} harus berupa teks"
        )
    return value


def make_clients(
    vms: list[VMNode], timeout_s: float = 120.0
) -> dict[int, WorkerClient]:
    return {vm.id: WorkerClient(vm, timeout_s) for vm in vms}


def check_workers(clients: dict[int, WorkerClient]) -> dict[int, HealthResponse]:
    results: dict[int, HealthResponse] = {}
    with ThreadPoolExecutor(max_workers=len(clients)) as executor:
        futures = {
            executor.submit(client.health): vm_id for vm_id, client in clients.items()
        }
        for future in as_completed(futures):
            vm_id = futures[future]
            results[vm_id] = future.result()
    return results


def reset_workers(clients: dict[int, WorkerClient]) -> None:
    with ThreadPoolExecutor(max_workers=len(clients)) as executor:
        futures = [executor.submit(client.reset) for client in clients.values()]
        for future in futures:
            future.result()


def calibrate_workers(
    clients: dict[int, WorkerClient],
    repeats: int = 5,
    cpu_work: int = 4_000_000,
    payload_mbit: float = 128.0,
) -> dict[int, CalibrationProfile]:
    if repeats < 2 or cpu_work <= 0 or payload_mbit <= 0:
        raise ValueError(
            "[k8s_broker.calibrate_workers.INVALID_CALIBRATION] "
            "Kalibrasi memerlukan minimal dua sampel dengan nilai positif"
        )

    def run_stage(
        name: str,
        sample: int,
        stage_cpu_work: int,
        stage_payload_bytes: int,
    ) -> dict[int, ExecutionResult]:
        results: dict[int, ExecutionResult] = {}
        with ThreadPoolExecutor(max_workers=len(clients)) as executor:
            futures = {
                executor.submit(
                    client.execute,
                    -(vm_id * 100_000 + sample + 1),
                    name,
                    stage_cpu_work,
                    stage_payload_bytes,
                    True,
                ): vm_id
                for vm_id, client in clients.items()
            }
            for future in as_completed(futures):
                results[futures[future]] = future.result()
        return results

    run_stage("calibration_warmup", 0, cpu_work // 4, 125_000)
    cpu_samples: dict[int, list[float]] = {vm_id: [] for vm_id in clients}
    bandwidth_samples: dict[int, list[float]] = {vm_id: [] for vm_id in clients}

    for sample in range(repeats):
        for vm_id, result in run_stage(
            "calibration_cpu", sample + 100, cpu_work, 0
        ).items():
            cpu_samples[vm_id].append(cpu_work / float(result["client_elapsed_s"]))

    payload_bytes = math.ceil(payload_mbit * 1_000_000 / 8)
    actual_mbit = payload_bytes * 8 / 1_000_000
    for sample in range(repeats):
        results = run_stage("calibration_bandwidth", sample + 200, 0, payload_bytes)
        for vm_id, result in results.items():
            bandwidth_samples[vm_id].append(
                actual_mbit / float(result["client_elapsed_s"])
            )

    profiles = {
        vm_id: CalibrationProfile(
            vm_id=vm_id,
            cpu_work_per_s=statistics.median(cpu_samples[vm_id]),
            bandwidth_mbps=statistics.median(bandwidth_samples[vm_id]),
            cpu_samples=tuple(cpu_samples[vm_id]),
            bandwidth_samples=tuple(bandwidth_samples[vm_id]),
        )
        for vm_id in clients
    }
    reset_workers(clients)
    return profiles


def execute_allocations(
    allocations: list[TaskAllocation],
    vms: list[VMNode],
    clients: Mapping[int, AllocationClient],
) -> float:
    by_vm: dict[int, list[TaskAllocation]] = {vm.id: [] for vm in vms}
    for allocation in allocations:
        if allocation.vm_id not in by_vm or allocation.vm_id not in clients:
            raise ValueError(
                "[k8s_broker.execute_allocations.UNKNOWN_VM] "
                f"Alokasi merujuk ke VM yang tidak dikenal: {allocation.vm_id}"
            )
        by_vm[allocation.vm_id].append(allocation)

    run_start_ns = time.perf_counter_ns()

    def run_queue(vm_id: int, queue: list[TaskAllocation]) -> None:
        client = clients[vm_id]
        for allocation in queue:
            allocation.actual_dispatch_start_s = (
                time.perf_counter_ns() - run_start_ns
            ) / 1_000_000_000
            result = client.execute(
                allocation.task_id,
                allocation.task_name,
                allocation.cpu_work,
                allocation.payload_bytes,
            )
            allocation.actual_finish_s = (
                time.perf_counter_ns() - run_start_ns
            ) / 1_000_000_000
            allocation.client_elapsed_s = result["client_elapsed_s"]
            allocation.worker_waiting_s = result["waiting_s"]
            allocation.worker_service_s = result["service_s"]
            allocation.worker_payload_read_s = result["payload_read_s"]
            allocation.worker_cpu_s = result["cpu_s"]
            allocation.cgroup_cpu_s = result["cgroup_cpu_s"]
            allocation.cgroup_throttled_s = result["cgroup_throttled_s"]
            allocation.proof_checksum = result["proof_checksum"]
            allocation.payload_sha256 = result["payload_sha256"]

    active_queues = [(vm_id, queue) for vm_id, queue in by_vm.items() if queue]
    with ThreadPoolExecutor(max_workers=len(active_queues)) as executor:
        futures = [
            executor.submit(run_queue, vm_id, queue) for vm_id, queue in active_queues
        ]
        for future in futures:
            future.result()

    makespan_s = (time.perf_counter_ns() - run_start_ns) / 1_000_000_000
    if any(not allocation.proof_checksum for allocation in allocations):
        raise RuntimeError(
            "[k8s_broker.execute_allocations.MISSING_EXECUTION_PROOF] "
            "Benchmark selesai tanpa bukti eksekusi untuk setiap tugas"
        )
    return makespan_s


def calculate_metrics(
    allocations: list[TaskAllocation],
    vms: list[VMNode],
    measured_makespan_s: float,
) -> dict[str, float]:
    if not allocations or measured_makespan_s <= 0:
        raise ValueError(
            "[k8s_broker.calculate_metrics.INVALID_INPUT] "
            "Alokasi yang telah selesai dan makespan positif diperlukan"
        )
    measured_allocations: list[tuple[TaskAllocation, float]] = []
    for allocation in allocations:
        if allocation.client_elapsed_s is None:
            raise ValueError(
                "[k8s_broker.calculate_metrics.MISSING_MEASUREMENT] "
                "Setiap alokasi harus memiliki hasil pengukuran eksekusi nyata"
            )
        measured_allocations.append((allocation, allocation.client_elapsed_s))

    predicted_makespan = max(item.predicted_finish_s for item in allocations)
    predicted_busy = {
        vm.id: sum(
            item.predicted_service_s for item in allocations if item.vm_id == vm.id
        )
        for vm in vms
    }
    real_busy = {
        vm.id: sum(
            elapsed for item, elapsed in measured_allocations if item.vm_id == vm.id
        )
        for vm in vms
    }
    absolute_errors = [
        abs(elapsed - item.predicted_service_s)
        for item, elapsed in measured_allocations
    ]
    cgroup_cpu_s = sum(float(item.cgroup_cpu_s or 0.0) for item in allocations)
    cpu_capacity_s = measured_makespan_s * sum(vm.cpu_millicores for vm in vms) / 1000
    total_input_mbit = sum(item.input_mbit for item in allocations)
    total_cpu_work = sum(item.cpu_work for item in allocations)

    return {
        "tasks": float(len(allocations)),
        "predicted_makespan_s": predicted_makespan,
        "real_makespan_s": measured_makespan_s,
        "task_throughput_per_s": len(allocations) / measured_makespan_s,
        "cpu_work_throughput_per_s": total_cpu_work / measured_makespan_s,
        "payload_throughput_mbps": total_input_mbit / measured_makespan_s,
        "total_input_mbit": total_input_mbit,
        "modeled_cost": sum(item.modeled_cost for item in allocations),
        "predicted_mean_queue_wait_s": statistics.fmean(
            item.predicted_start_s for item in allocations
        ),
        "real_mean_queue_wait_s": statistics.fmean(
            float(item.actual_dispatch_start_s or 0.0) for item in allocations
        ),
        "worker_mean_wait_s": statistics.fmean(
            float(item.worker_waiting_s or 0.0) for item in allocations
        ),
        "predicted_logical_utilization_pct": (
            sum(predicted_busy.values()) / (len(vms) * predicted_makespan) * 100
            if predicted_makespan
            else 0.0
        ),
        "real_logical_utilization_pct": (
            sum(real_busy.values()) / (len(vms) * measured_makespan_s) * 100
        ),
        "actual_cpu_capacity_utilization_pct": (
            cgroup_cpu_s / cpu_capacity_s * 100 if cpu_capacity_s else 0.0
        ),
        "total_cgroup_cpu_s": cgroup_cpu_s,
        "total_cgroup_throttled_s": sum(
            float(item.cgroup_throttled_s or 0.0) for item in allocations
        ),
        "predicted_imbalance_di": _degree_of_imbalance(list(predicted_busy.values())),
        "real_imbalance_di": _degree_of_imbalance(list(real_busy.values())),
        "prediction_mae_s": statistics.fmean(absolute_errors),
        "prediction_rmse_s": math.sqrt(
            statistics.fmean(error**2 for error in absolute_errors)
        ),
    }


def _degree_of_imbalance(values: list[float]) -> float:
    mean = statistics.fmean(values)
    return (max(values) - min(values)) / mean if mean else 0.0
