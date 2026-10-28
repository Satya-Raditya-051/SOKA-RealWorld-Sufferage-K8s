import threading
import time
import unittest
from typing import ClassVar

from scheduler.algorithms import RoundRobinScheduler
from scheduler.k8s_broker import (
    ExecutionMeasurements,
    calculate_metrics,
    execute_allocations,
)
from scheduler.models import Task, VMNode


def vm(vm_id: int) -> VMNode:
    return VMNode(vm_id, f"VM{vm_id}", "host", 1, 1, 0.1, 1000, f"http://vm{vm_id}")


class FakeClient:
    lock: ClassVar[threading.Lock] = threading.Lock()
    active_by_vm: ClassVar[dict[int, int]] = {}
    active_total: ClassVar[int] = 0
    max_active_total: ClassVar[int] = 0

    def __init__(self, vm_id: int):
        self.vm_id = vm_id

    def execute(
        self,
        task_id: int,
        task_name: str,
        cpu_work: int,
        payload_bytes: int,
    ) -> ExecutionMeasurements:
        with self.lock:
            self.assert_serial()
            self.active_by_vm[self.vm_id] = 1
            type(self).active_total += 1
            type(self).max_active_total = max(
                type(self).max_active_total, type(self).active_total
            )
        time.sleep(0.02)
        with self.lock:
            self.active_by_vm[self.vm_id] = 0
            type(self).active_total -= 1
        return {
            "client_elapsed_s": 0.02,
            "waiting_s": 0.0,
            "service_s": 0.019,
            "payload_read_s": 0.001,
            "cpu_s": 0.018,
            "cgroup_cpu_s": 0.018,
            "cgroup_throttled_s": 0.0,
            "proof_checksum": f"proof-{task_id}",
            "payload_sha256": f"payload-{task_id}",
        }

    def assert_serial(self):
        if self.active_by_vm.get(self.vm_id, 0):
            raise AssertionError(
                "[test_broker.FakeClient.assert_serial.PARALLEL_EXECUTION] "
                "Dua tugas berjalan bersamaan pada satu VM"
            )


class BrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.active_by_vm = {}
        FakeClient.active_total = 0
        FakeClient.max_active_total = 0

    def test_dispatch_is_serial_per_vm_and_parallel_across_vms(self) -> None:
        vms = [vm(1), vm(2)]
        tasks = [Task(index, f"T{index}", 1, 1) for index in range(1, 5)]
        allocations = RoundRobinScheduler().plan_from_matrices(
            tasks, vms, [[0.02, 0.02] for _ in tasks]
        )
        elapsed = execute_allocations(
            allocations,
            vms,
            {1: FakeClient(1), 2: FakeClient(2)},
        )
        self.assertEqual(FakeClient.max_active_total, 2)
        self.assertLess(elapsed, 0.07)
        self.assertTrue(all(item.proof_checksum for item in allocations))

    def test_metrics_include_idle_vms_and_capacity(self) -> None:
        vms = [vm(1), vm(2)]
        tasks = [Task(1, "T1", 10, 100)]
        allocations = RoundRobinScheduler().plan_from_matrices(tasks, vms, [[1, 1]])
        item = allocations[0]
        item.actual_dispatch_start_s = 0.0
        item.actual_finish_s = 1.0
        item.client_elapsed_s = 1.0
        item.worker_waiting_s = 0.0
        item.worker_service_s = 0.9
        item.cgroup_cpu_s = 0.5
        metrics = calculate_metrics(allocations, vms, 1.0)
        self.assertEqual(metrics["real_logical_utilization_pct"], 50)
        self.assertEqual(metrics["real_imbalance_di"], 2)
        self.assertEqual(metrics["actual_cpu_capacity_utilization_pct"], 25)
        self.assertEqual(metrics["modeled_cost"], 1)


if __name__ == "__main__":
    unittest.main()
