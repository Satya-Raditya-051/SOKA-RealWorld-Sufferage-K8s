#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from scheduler.algorithms import (
    CCTSAScheduler,
    RoundRobinScheduler,
    StandardSufferageScheduler,
)
from scheduler.datasets import (
    GOCJ_WORK_PER_MI,
    PAPER_WORK_PER_MI,
    get_kubernetes_vms,
    get_scenario,
)
from scheduler.k8s_broker import (
    HealthResponse,
    calculate_metrics,
    calibrate_workers,
    check_workers,
    execute_allocations,
    make_clients,
    reset_workers,
)
from scheduler.models import BenchmarkResult, Task, TaskAllocation, VMNode

SCHEDULERS = {
    "cctsa": CCTSAScheduler,
    "sufferage": StandardSufferageScheduler,
    "round-robin": RoundRobinScheduler,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run real Sufferage, CCTSA, and Round Robin jobs on Kubernetes workers."
    )
    parser.add_argument("--scenario", choices=("paper", "gocj", "all"), default="all")
    parser.add_argument(
        "--algorithms",
        nargs="+",
        choices=tuple(SCHEDULERS),
        default=list(SCHEDULERS),
    )
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--calibration-repeats", type=int, default=5)
    parser.add_argument("--calibration-cpu-work", type=int, default=4_000_000)
    parser.add_argument("--calibration-payload-mbit", type=float, default=128.0)
    parser.add_argument("--base-host", default="http://127.0.0.1")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("results/realworld_summary.json"),
    )
    args = parser.parse_args()
    if args.trials <= 0:
        parser.error(
            "[run_benchmark.parse_args.INVALID_TRIALS] "
            "Nilai --trials harus lebih besar dari nol"
        )
    if args.calibration_repeats < 2:
        parser.error(
            "[run_benchmark.parse_args.INVALID_CALIBRATION_REPEATS] "
            "Nilai --calibration-repeats minimal 2"
        )
    return args


def validate_plan(
    tasks: list[Task],
    vms: list[VMNode],
    allocations: list[TaskAllocation],
) -> None:
    task_ids = [task.id for task in tasks]
    allocated_ids = [allocation.task_id for allocation in allocations]
    if sorted(allocated_ids) != sorted(task_ids) or len(set(allocated_ids)) != len(
        task_ids
    ):
        raise RuntimeError(
            "[run_benchmark.validate_plan.INCOMPLETE_ALLOCATION] "
            "Penjadwal harus mengalokasikan setiap tugas tepat satu kali"
        )
    valid_vms = {vm.id for vm in vms}
    if any(allocation.vm_id not in valid_vms for allocation in allocations):
        raise RuntimeError(
            "[run_benchmark.validate_plan.UNKNOWN_VM] Penjadwal memilih VM yang tidak dikenal"
        )
    for vm in vms:
        queue = [allocation for allocation in allocations if allocation.vm_id == vm.id]
        for previous, current in pairwise(queue):
            if abs(previous.predicted_finish_s - current.predicted_start_s) > 1e-9:
                raise RuntimeError(
                    "[run_benchmark.validate_plan.NON_SERIAL_QUEUE] "
                    f"Antrean prediksi untuk {vm.name} tidak berjalan secara serial"
                )


def collect_environment(health: dict[int, HealthResponse]) -> dict[str, object]:
    git = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    git_status = subprocess.run(
        ["git", "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
    )
    source_files = [
        Path("run_benchmark.py"),
        Path("scheduler/models.py"),
        Path("scheduler/datasets.py"),
        Path("scheduler/algorithms.py"),
        Path("scheduler/k8s_broker.py"),
        Path("vm_worker/worker_server.py"),
        Path("vm_worker/Dockerfile"),
        Path("k8s/kind-cluster.yaml"),
        Path("k8s/vm-pods.yaml"),
        Path("data/GoCJ_Dataset_100.txt"),
    ]
    source_hash = hashlib.sha256()
    for path in source_files:
        source_hash.update(str(path).encode())
        source_hash.update(path.read_bytes())
    return {
        "created_at": datetime.now(UTC).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "git_commit": git.stdout.strip() if git.returncode == 0 else "unknown",
        "git_worktree_dirty": bool(git_status.stdout.strip())
        if git_status.returncode == 0
        else None,
        "source_sha256": source_hash.hexdigest(),
        "workers": {str(vm_id): data for vm_id, data in sorted(health.items())},
        "topology_note": (
            "kind nodes are logical container nodes on one physical host; "
            "worker Pods are not hardware virtual machines"
        ),
    }


def summarize(
    results: list[BenchmarkResult],
) -> dict[str, dict[str, dict[str, object]]]:
    groups: dict[tuple[str, str], list[BenchmarkResult]] = {}
    for result in results:
        groups.setdefault((result.scenario, result.algorithm), []).append(result)

    summary: dict[str, dict[str, dict[str, object]]] = {}
    for (scenario, algorithm), group in sorted(groups.items()):
        metric_names = group[0].metrics.keys()
        metrics = {}
        for metric in metric_names:
            values = [item.metrics[metric] for item in group]
            metrics[metric] = {
                "median": statistics.median(values),
                "min": min(values),
                "max": max(values),
            }
        scenario_summary = summary.setdefault(scenario, {})
        scenario_summary[algorithm] = {
            "trials": len(group),
            "planning_time_s": {
                "median": statistics.median(item.planning_time_s for item in group),
                "min": min(item.planning_time_s for item in group),
                "max": max(item.planning_time_s for item in group),
            },
            "metrics": metrics,
        }
    return summary


def print_result(result: BenchmarkResult) -> None:
    metrics = result.metrics
    print(
        f"{result.scenario:16} trial={result.trial:<2} {result.algorithm:20} "
        f"makespan={metrics['real_makespan_s']:.4f}s "
        f"throughput={metrics['task_throughput_per_s']:.3f} task/s "
        f"cost={metrics['modeled_cost']:.2f} "
        f"DI={metrics['real_imbalance_di']:.3f}"
    )


def main() -> int:
    args = parse_args()
    vms = get_kubernetes_vms(args.base_host)
    clients = make_clients(vms, args.timeout)

    print("Checking four Kubernetes workers...")
    health = check_workers(clients)
    print("Calibrating real CPU and payload rates...")
    profiles = calibrate_workers(
        clients,
        repeats=args.calibration_repeats,
        cpu_work=args.calibration_cpu_work,
        payload_mbit=args.calibration_payload_mbit,
    )
    for vm in vms:
        profile = profiles[vm.id]
        print(
            f"{vm.name}: cpu={profile.cpu_work_per_s:.0f} work/s, "
            f"payload={profile.bandwidth_mbps:.2f} Mbit/s"
        )

    scenario_keys = ["paper", "gocj"] if args.scenario == "all" else [args.scenario]
    selected = [(key, SCHEDULERS[key]()) for key in args.algorithms]
    results: list[BenchmarkResult] = []

    for scenario_key in scenario_keys:
        scenario_name, tasks = get_scenario(scenario_key)
        for trial in range(1, args.trials + 1):
            offset = (trial - 1) % len(selected)
            rotated = selected[offset:] + selected[:offset]
            order_names = [scheduler.name for _, scheduler in rotated]
            for _, scheduler in rotated:
                reset_workers(clients)
                planning_start = time.perf_counter_ns()
                allocations = scheduler.plan(tasks, vms, profiles)
                planning_s = (time.perf_counter_ns() - planning_start) / 1_000_000_000
                validate_plan(tasks, vms, allocations)
                real_makespan = execute_allocations(allocations, vms, clients)
                metrics = calculate_metrics(allocations, vms, real_makespan)
                result = BenchmarkResult(
                    algorithm=scheduler.name,
                    scenario=scenario_name,
                    trial=trial,
                    planning_time_s=planning_s,
                    metrics=metrics,
                    allocations=allocations,
                    calibration=profiles,
                    algorithm_order=order_names,
                )
                results.append(result)
                print_result(result)

    document = {
        "schema_version": 1,
        "environment": collect_environment(health),
        "method": {
            "trials": args.trials,
            "algorithm_order": "cyclic rotation per trial",
            "calibration_repeats": args.calibration_repeats,
            "calibration_cpu_work": args.calibration_cpu_work,
            "calibration_payload_mbit": args.calibration_payload_mbit,
            "paper_cpu_work_per_source_mi": PAPER_WORK_PER_MI,
            "gocj_cpu_work_per_source_mi": GOCJ_WORK_PER_MI,
            "cost_definition": "source_mi multiplied by configured paper cost rate",
            "cost_is_real_spend": False,
            "cctsa_limitation": (
                "The paper's reported cost is not reproducible from its stated formula. "
                "This implementation follows its task predicate and minimum-completion-time assignment; "
                "completion cost breaks exact time ties."
            ),
        },
        "summary": summarize(results),
        "trials": [result.to_dict() for result in results],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
