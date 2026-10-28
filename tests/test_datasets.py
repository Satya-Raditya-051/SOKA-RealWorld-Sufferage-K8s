import unittest

from scheduler.datasets import (
    GOCJ_WORK_PER_MI,
    PAPER_WORK_PER_MI,
    get_gocj_tasks,
    get_kubernetes_vms,
    get_paper_tasks,
    load_gocj_values,
)


class DatasetTests(unittest.TestCase):
    def test_paper_table_ii_is_exact(self) -> None:
        tasks = get_paper_tasks()
        self.assertEqual(len(tasks), 10)
        self.assertEqual(
            [(item.source_mi, item.input_mbit) for item in tasks],
            [
                (206, 44),
                (50, 95),
                (128, 64),
                (69, 30),
                (118, 59),
                (112, 47),
                (21, 39),
                (200, 61),
                (90, 23),
                (45, 23),
            ],
        )
        self.assertEqual(tasks[0].cpu_work, 206 * PAPER_WORK_PER_MI)
        self.assertEqual(tasks[1].payload_bytes, 11_875_000)

    def test_gocj_uses_published_values_without_invented_io(self) -> None:
        values = load_gocj_values()
        tasks = get_gocj_tasks()
        self.assertEqual(len(values), 100)
        self.assertEqual(len(tasks), 24)
        self.assertEqual(
            [item.source_mi for item in tasks[:6]],
            [127000, 83000, 63000, 63000, 65000, 15000],
        )
        self.assertEqual(tasks[11].source_mi, 712500)
        self.assertTrue(all(item.input_mbit == 0 for item in tasks))
        self.assertEqual(tasks[0].cpu_work, 127000 * GOCJ_WORK_PER_MI)

    def test_gocj_count_is_validated(self) -> None:
        for invalid in (0, 101):
            with self.assertRaises(ValueError):
                get_gocj_tasks(invalid)

    def test_vm_contract(self) -> None:
        vms = get_kubernetes_vms()
        self.assertEqual([vm.id for vm in vms], [1, 2, 3, 4])
        self.assertEqual(
            [vm.host_id for vm in vms], ["host-1", "host-1", "host-2", "host-2"]
        )
        self.assertEqual([vm.cpu_millicores for vm in vms], [250, 500, 1000, 1500])
        self.assertEqual(
            [vm.endpoint_url for vm in vms],
            [
                "http://127.0.0.1:30081",
                "http://127.0.0.1:30082",
                "http://127.0.0.1:30083",
                "http://127.0.0.1:30084",
            ],
        )


if __name__ == "__main__":
    unittest.main()
