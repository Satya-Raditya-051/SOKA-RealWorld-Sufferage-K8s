import unittest

from scheduler.algorithms import (
    CCTSAScheduler,
    RoundRobinScheduler,
    StandardSufferageScheduler,
)
from scheduler.datasets import get_paper_tasks
from scheduler.models import Task, VMNode


def task(task_id: int) -> Task:
    return Task(task_id, f"T{task_id}", 1.0, 1)


def vm(vm_id: int) -> VMNode:
    return VMNode(
        vm_id, f"M{vm_id}", "host", 1, 1, vm_id / 10, 1000, f"http://m{vm_id}"
    )


class StandardSufferageTests(unittest.TestCase):
    def test_maheswaran_table_3(self) -> None:
        tasks = [task(index) for index in range(4)]
        vms = [vm(index + 1) for index in range(4)]
        etc = [
            [40, 48, 134, 50],
            [50, 82, 88, 89],
            [55, 68, 94, 93],
            [52, 60, 78, 108],
        ]

        allocations = StandardSufferageScheduler().plan_from_matrices(tasks, vms, etc)
        mapping = {item.task_id: item.vm_id - 1 for item in allocations}

        self.assertEqual(mapping, {1: 0, 2: 1, 3: 2, 0: 3})
        self.assertEqual(max(item.predicted_finish_s for item in allocations), 78)
        self.assertEqual(len(allocations), 4)

    def test_equal_sufferage_keeps_first_task(self) -> None:
        tasks = [task(1), task(2)]
        vms = [vm(1), vm(2)]
        allocations = StandardSufferageScheduler().plan_from_matrices(
            tasks, vms, [[1, 5], [1, 5]]
        )
        self.assertEqual(allocations[0].task_id, 1)

    def test_one_vm_schedules_every_task_once(self) -> None:
        tasks = [task(1), task(2), task(3)]
        allocations = StandardSufferageScheduler().plan_from_matrices(
            tasks, [vm(1)], [[1], [2], [3]]
        )
        self.assertEqual([item.task_id for item in allocations], [1, 2, 3])
        self.assertEqual(allocations[-1].predicted_finish_s, 6)


class CCTSATests(unittest.TestCase):
    def test_paper_reported_cost_is_below_formula_lower_bound(self) -> None:
        minimum_possible_cost = sum(item.source_mi for item in get_paper_tasks()) * 0.03
        self.assertAlmostEqual(minimum_possible_cost, 31.17)
        self.assertGreater(minimum_possible_cost, 21.30)

    def test_paper_fallback_uses_highest_remaining_index(self) -> None:
        tasks = [task(1), task(2), task(3)]
        allocations = CCTSAScheduler().plan_from_matrices(
            tasks,
            [vm(1), vm(2)],
            [[5, 6], [5, 6], [5, 6]],
            [[1, 2], [1, 2], [1, 2]],
        )
        self.assertEqual(allocations[0].task_id, 3)

    def test_paper_predicate_is_scanned_descending(self) -> None:
        tasks = [task(1), task(2)]
        allocations = CCTSAScheduler().plan_from_matrices(
            tasks,
            [vm(1), vm(2)],
            [[1, 3], [1, 4]],
            [[1, 2], [1, 2]],
        )
        self.assertEqual(allocations[0].task_id, 2)

    def test_cost_only_breaks_equal_completion_time(self) -> None:
        allocation = CCTSAScheduler().plan_from_matrices(
            [task(1)],
            [vm(1), vm(2)],
            [[1, 1]],
            [[5, 2]],
        )[0]
        self.assertEqual(allocation.vm_id, 2)
        self.assertEqual(allocation.modeled_cost, 2)


class RoundRobinTests(unittest.TestCase):
    def test_cyclic_mapping_and_serial_ready_times(self) -> None:
        tasks = [task(index) for index in range(1, 6)]
        vms = [vm(1), vm(2)]
        allocations = RoundRobinScheduler().plan_from_matrices(
            tasks, vms, [[1, 1] for _ in tasks]
        )
        self.assertEqual([item.vm_id for item in allocations], [1, 2, 1, 2, 1])
        self.assertEqual(
            [item.predicted_start_s for item in allocations], [0, 0, 1, 1, 2]
        )

    def test_rejects_duplicate_task_ids(self) -> None:
        with self.assertRaisesRegex(ValueError, "DUPLICATE_TASK_ID"):
            RoundRobinScheduler().plan_from_matrices(
                [task(1), task(1)], [vm(1)], [[1], [1]]
            )


if __name__ == "__main__":
    unittest.main()
