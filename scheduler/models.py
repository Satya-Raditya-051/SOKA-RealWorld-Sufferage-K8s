from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil
from typing import Any


@dataclass(frozen=True)
class Task:
    id: int
    name: str
    source_mi: float
    cpu_work: int
    input_mbit: float = 0.0

    def __post_init__(self) -> None:
        if self.id < 0:
            raise ValueError(
                "[models.Task.__post_init__.INVALID_TASK_ID] "
                "ID tugas tidak boleh bernilai negatif"
            )
        if not self.name:
            raise ValueError(
                "[models.Task.__post_init__.EMPTY_TASK_NAME] Nama tugas tidak boleh kosong"
            )
        if self.source_mi <= 0:
            raise ValueError(
                "[models.Task.__post_init__.INVALID_SOURCE_MI] "
                "Nilai source_mi harus lebih besar dari nol"
            )
        if self.cpu_work < 0:
            raise ValueError(
                "[models.Task.__post_init__.INVALID_CPU_WORK] "
                "Nilai cpu_work tidak boleh negatif"
            )
        if self.input_mbit < 0:
            raise ValueError(
                "[models.Task.__post_init__.INVALID_INPUT_MBIT] "
                "Nilai input_mbit tidak boleh negatif"
            )

    @property
    def payload_bytes(self) -> int:
        return ceil(self.input_mbit * 1_000_000 / 8)


@dataclass(frozen=True)
class VMNode:
    id: int
    name: str
    host_id: str
    nominal_mips: float
    nominal_bandwidth_mbps: float
    cost_per_mi: float
    cpu_millicores: int
    endpoint_url: str

    def __post_init__(self) -> None:
        if self.id <= 0:
            raise ValueError(
                "[models.VMNode.__post_init__.INVALID_VM_ID] ID VM harus lebih besar dari nol"
            )
        if self.nominal_mips <= 0 or self.nominal_bandwidth_mbps <= 0:
            raise ValueError(
                "[models.VMNode.__post_init__.INVALID_NOMINAL_RATE] "
                "Laju nominal VM harus lebih besar dari nol"
            )
        if self.cost_per_mi < 0 or self.cpu_millicores <= 0:
            raise ValueError(
                "[models.VMNode.__post_init__.INVALID_VM_CAPACITY] "
                "Biaya atau batas CPU VM tidak valid"
            )


@dataclass(frozen=True)
class CalibrationProfile:
    vm_id: int
    cpu_work_per_s: float
    bandwidth_mbps: float
    cpu_samples: tuple[float, ...] = ()
    bandwidth_samples: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        if self.cpu_work_per_s <= 0 or self.bandwidth_mbps <= 0:
            raise ValueError(
                "[models.CalibrationProfile.__post_init__.INVALID_CALIBRATION_RATE] "
                "Laju kalibrasi harus lebih besar dari nol"
            )

    def estimate_seconds(self, task: Task) -> float:
        cpu_seconds = task.cpu_work / self.cpu_work_per_s
        transfer_seconds = task.input_mbit / self.bandwidth_mbps
        return cpu_seconds + transfer_seconds

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskAllocation:
    task_id: int
    task_name: str
    source_mi: float
    cpu_work: int
    input_mbit: float
    payload_bytes: int
    vm_id: int
    vm_name: str
    host_id: str
    predicted_start_s: float
    predicted_service_s: float
    predicted_finish_s: float
    modeled_cost: float
    actual_dispatch_start_s: float | None = None
    actual_finish_s: float | None = None
    client_elapsed_s: float | None = None
    worker_waiting_s: float | None = None
    worker_service_s: float | None = None
    worker_payload_read_s: float | None = None
    worker_cpu_s: float | None = None
    cgroup_cpu_s: float | None = None
    cgroup_throttled_s: float | None = None
    proof_checksum: str = ""
    payload_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkResult:
    algorithm: str
    scenario: str
    trial: int
    planning_time_s: float
    metrics: dict[str, float]
    allocations: list[TaskAllocation]
    calibration: dict[int, CalibrationProfile]
    algorithm_order: list[str] = field(default_factory=lambda: list[str]())

    def to_dict(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "scenario": self.scenario,
            "trial": self.trial,
            "planning_time_s": self.planning_time_s,
            "metrics": self.metrics,
            "allocations": [item.to_dict() for item in self.allocations],
            "calibration": {
                str(vm_id): profile.to_dict()
                for vm_id, profile in sorted(self.calibration.items())
            },
            "algorithm_order": self.algorithm_order,
        }
