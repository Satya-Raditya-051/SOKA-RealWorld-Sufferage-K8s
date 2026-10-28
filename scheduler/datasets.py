from __future__ import annotations

from pathlib import Path

from scheduler.models import Task, VMNode

PAPER_WORK_PER_MI = 50_000
GOCJ_WORK_PER_MI = 50
GOCJ_DATA = Path(__file__).resolve().parent.parent / "data" / "GoCJ_Dataset_100.txt"


def get_kubernetes_vms(base_host: str = "http://127.0.0.1") -> list[VMNode]:
    specs = [
        (1, "VM1_Small", "host-1", 50.0, 100.0, 0.03, 250, 30081),
        (2, "VM2_Medium", "host-1", 100.0, 200.0, 0.12, 500, 30082),
        (3, "VM3_Large", "host-2", 200.0, 250.0, 0.24, 1000, 30083),
        (4, "VM4_XLarge", "host-2", 300.0, 300.0, 0.35, 1500, 30084),
    ]
    return [
        VMNode(
            id=vm_id,
            name=name,
            host_id=host_id,
            nominal_mips=mips,
            nominal_bandwidth_mbps=bandwidth,
            cost_per_mi=cost,
            cpu_millicores=millicores,
            endpoint_url=f"{base_host}:{port}",
        )
        for vm_id, name, host_id, mips, bandwidth, cost, millicores, port in specs
    ]


def get_paper_tasks() -> list[Task]:
    specs = [
        (1, 206.0, 44.0),
        (2, 50.0, 95.0),
        (3, 128.0, 64.0),
        (4, 69.0, 30.0),
        (5, 118.0, 59.0),
        (6, 112.0, 47.0),
        (7, 21.0, 39.0),
        (8, 200.0, 61.0),
        (9, 90.0, 23.0),
        (10, 45.0, 23.0),
    ]
    return [
        Task(
            id=task_id,
            name=f"T{task_id}",
            source_mi=source_mi,
            cpu_work=round(source_mi * PAPER_WORK_PER_MI),
            input_mbit=input_mbit,
        )
        for task_id, source_mi, input_mbit in specs
    ]


def load_gocj_values() -> list[float]:
    values = [
        float(line.strip())
        for line in GOCJ_DATA.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(values) != 100 or any(value <= 0 for value in values):
        raise ValueError(
            "[datasets.load_gocj_values.INVALID_DATASET] "
            f"Dataset GoCJ pada {GOCJ_DATA} tidak valid"
        )
    return values


def get_gocj_tasks(count: int = 24) -> list[Task]:
    values = load_gocj_values()
    if count <= 0 or count > len(values):
        raise ValueError(
            "[datasets.get_gocj_tasks.INVALID_TASK_COUNT] "
            f"Jumlah tugas GoCJ harus berada antara 1 dan {len(values)}"
        )
    return [
        Task(
            id=index,
            name=f"GoCJ_{index:03d}",
            source_mi=source_mi,
            cpu_work=round(source_mi * GOCJ_WORK_PER_MI),
            input_mbit=0.0,
        )
        for index, source_mi in enumerate(values[:count], start=1)
    ]


def get_scenario(name: str) -> tuple[str, list[Task]]:
    if name == "paper":
        return "paper_10", get_paper_tasks()
    if name == "gocj":
        return "gocj_first_24", get_gocj_tasks()
    raise ValueError(
        f"[datasets.get_scenario.UNKNOWN_SCENARIO] Skenario tidak dikenal: {name}"
    )
