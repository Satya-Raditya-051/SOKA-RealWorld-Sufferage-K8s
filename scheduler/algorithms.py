from __future__ import annotations

from collections.abc import Sequence

from scheduler.models import CalibrationProfile, Task, TaskAllocation, VMNode

Matrix = Sequence[Sequence[float]]


def compute_matrices(
    tasks: Sequence[Task],
    vms: Sequence[VMNode],
    profiles: dict[int, CalibrationProfile],
) -> tuple[list[list[float]], list[list[float]]]:
    _validate_entities(tasks, vms)
    missing = [vm.id for vm in vms if vm.id not in profiles]
    if missing:
        raise ValueError(
            "[algorithms.compute_matrices.MISSING_CALIBRATION] "
            f"Kalibrasi tidak tersedia untuk ID VM: {missing}"
        )
    etc = [[profiles[vm.id].estimate_seconds(task) for vm in vms] for task in tasks]
    ecc = [[task.source_mi * vm.cost_per_mi for vm in vms] for task in tasks]
    return etc, ecc


def _validate_entities(tasks: Sequence[Task], vms: Sequence[VMNode]) -> None:
    if not tasks:
        raise ValueError(
            "[algorithms._validate_entities.EMPTY_TASKS] Minimal satu tugas diperlukan"
        )
    if not vms:
        raise ValueError(
            "[algorithms._validate_entities.EMPTY_VMS] Minimal satu VM diperlukan"
        )
    if len({task.id for task in tasks}) != len(tasks):
        raise ValueError(
            "[algorithms._validate_entities.DUPLICATE_TASK_ID] "
            "Setiap ID tugas harus unik"
        )
    if len({vm.id for vm in vms}) != len(vms):
        raise ValueError(
            "[algorithms._validate_entities.DUPLICATE_VM_ID] Setiap ID VM harus unik"
        )


def _validate_matrices(
    tasks: Sequence[Task],
    vms: Sequence[VMNode],
    etc: Matrix,
    ecc: Matrix,
) -> None:
    _validate_entities(tasks, vms)
    if len(etc) != len(tasks) or len(ecc) != len(tasks):
        raise ValueError(
            "[algorithms._validate_matrices.INVALID_ROW_COUNT] "
            "Jumlah baris matriks harus sama dengan jumlah tugas"
        )
    for matrix in (etc, ecc):
        if any(len(row) != len(vms) for row in matrix):
            raise ValueError(
                "[algorithms._validate_matrices.INVALID_COLUMN_COUNT] "
                "Jumlah kolom matriks harus sama dengan jumlah VM"
            )
        if any(value < 0 for row in matrix for value in row):
            raise ValueError(
                "[algorithms._validate_matrices.NEGATIVE_MATRIX_VALUE] "
                "Nilai matriks tidak boleh negatif"
            )


def _default_ecc(tasks: Sequence[Task], vms: Sequence[VMNode]) -> list[list[float]]:
    return [[task.source_mi * vm.cost_per_mi for vm in vms] for task in tasks]


def _allocation(
    task: Task,
    vm: VMNode,
    start_s: float,
    service_s: float,
    cost: float,
) -> TaskAllocation:
    return TaskAllocation(
        task_id=task.id,
        task_name=task.name,
        source_mi=task.source_mi,
        cpu_work=task.cpu_work,
        input_mbit=task.input_mbit,
        payload_bytes=task.payload_bytes,
        vm_id=vm.id,
        vm_name=vm.name,
        host_id=vm.host_id,
        predicted_start_s=start_s,
        predicted_service_s=service_s,
        predicted_finish_s=start_s + service_s,
        modeled_cost=cost,
    )


class StandardSufferageScheduler:
    name = "Standard Sufferage"

    def plan(
        self,
        tasks: Sequence[Task],
        vms: Sequence[VMNode],
        profiles: dict[int, CalibrationProfile],
    ) -> list[TaskAllocation]:
        etc, ecc = compute_matrices(tasks, vms, profiles)
        return self.plan_from_matrices(tasks, vms, etc, ecc)

    def plan_from_matrices(
        self,
        tasks: Sequence[Task],
        vms: Sequence[VMNode],
        etc: Matrix,
        ecc: Matrix | None = None,
    ) -> list[TaskAllocation]:
        costs = _default_ecc(tasks, vms) if ecc is None else ecc
        _validate_matrices(tasks, vms, etc, costs)

        ready = [0.0] * len(vms)
        remaining = list(range(len(tasks)))
        allocations: list[TaskAllocation] = []

        while remaining:
            winners: dict[int, tuple[int, float]] = {}
            for task_index in remaining:
                completion = [
                    ready[vm_index] + etc[task_index][vm_index]
                    for vm_index in range(len(vms))
                ]
                ranked_vms = sorted(
                    range(len(vms)),
                    key=lambda vm_index: (completion[vm_index], vms[vm_index].id),
                )
                best_vm = ranked_vms[0]
                second_completion = (
                    completion[ranked_vms[1]]
                    if len(ranked_vms) > 1
                    else completion[best_vm]
                )
                sufferage = second_completion - completion[best_vm]

                incumbent = winners.get(best_vm)
                if incumbent is None or sufferage > incumbent[1]:
                    winners[best_vm] = (task_index, sufferage)

            winner_tasks = {task_index for task_index, _ in winners.values()}
            for vm_index in sorted(winners):
                task_index = winners[vm_index][0]
                start = ready[vm_index]
                service = etc[task_index][vm_index]
                allocations.append(
                    _allocation(
                        tasks[task_index],
                        vms[vm_index],
                        start,
                        service,
                        costs[task_index][vm_index],
                    )
                )
                ready[vm_index] = start + service

            remaining = [index for index in remaining if index not in winner_tasks]

        return allocations


class CCTSAScheduler:
    name = "CCTSA"

    def plan(
        self,
        tasks: Sequence[Task],
        vms: Sequence[VMNode],
        profiles: dict[int, CalibrationProfile],
    ) -> list[TaskAllocation]:
        etc, ecc = compute_matrices(tasks, vms, profiles)
        return self.plan_from_matrices(tasks, vms, etc, ecc)

    def plan_from_matrices(
        self,
        tasks: Sequence[Task],
        vms: Sequence[VMNode],
        etc: Matrix,
        ecc: Matrix | None = None,
    ) -> list[TaskAllocation]:
        costs = _default_ecc(tasks, vms) if ecc is None else ecc
        _validate_matrices(tasks, vms, etc, costs)

        ready_time = [0.0] * len(vms)
        ready_cost = [0.0] * len(vms)
        remaining = list(range(len(tasks)))
        allocations: list[TaskAllocation] = []

        while remaining:
            completion_time: dict[int, list[float]] = {}
            completion_cost: dict[int, list[float]] = {}
            qualifies: dict[int, bool] = {}

            for task_index in remaining:
                ct = [
                    ready_time[vm_index] + etc[task_index][vm_index]
                    for vm_index in range(len(vms))
                ]
                cc = [
                    ready_cost[vm_index] + costs[task_index][vm_index]
                    for vm_index in range(len(vms))
                ]
                ordered_ct = sorted(ct)
                ordered_cc = sorted(cc, reverse=True)
                fmict = ordered_ct[0]
                smict = ordered_ct[1] if len(ordered_ct) > 1 else fmict
                fmxc = ordered_cc[0]
                smxc = ordered_cc[1] if len(ordered_cc) > 1 else fmxc
                svct = smict - fmict
                svc = fmxc - smxc

                completion_time[task_index] = ct
                completion_cost[task_index] = cc
                qualifies[task_index] = svct > fmict and svc < fmxc

            chosen_task = max(remaining)
            for task_index in sorted(remaining, reverse=True):
                if qualifies[task_index]:
                    chosen_task = task_index
                    break

            ct = completion_time[chosen_task]
            cc = completion_cost[chosen_task]
            vm_index = min(
                range(len(vms)),
                key=lambda index: (ct[index], cc[index], vms[index].id),
            )
            start = ready_time[vm_index]
            service = etc[chosen_task][vm_index]
            cost = costs[chosen_task][vm_index]
            allocations.append(
                _allocation(tasks[chosen_task], vms[vm_index], start, service, cost)
            )
            ready_time[vm_index] = start + service
            ready_cost[vm_index] += cost
            remaining.remove(chosen_task)

        return allocations


class RoundRobinScheduler:
    name = "Round Robin"

    def plan(
        self,
        tasks: Sequence[Task],
        vms: Sequence[VMNode],
        profiles: dict[int, CalibrationProfile],
    ) -> list[TaskAllocation]:
        etc, ecc = compute_matrices(tasks, vms, profiles)
        return self.plan_from_matrices(tasks, vms, etc, ecc)

    def plan_from_matrices(
        self,
        tasks: Sequence[Task],
        vms: Sequence[VMNode],
        etc: Matrix,
        ecc: Matrix | None = None,
    ) -> list[TaskAllocation]:
        costs = _default_ecc(tasks, vms) if ecc is None else ecc
        _validate_matrices(tasks, vms, etc, costs)
        ready = [0.0] * len(vms)
        allocations: list[TaskAllocation] = []

        for task_index, task in enumerate(tasks):
            vm_index = task_index % len(vms)
            start = ready[vm_index]
            service = etc[task_index][vm_index]
            allocations.append(
                _allocation(
                    task, vms[vm_index], start, service, costs[task_index][vm_index]
                )
            )
            ready[vm_index] = start + service

        return allocations
