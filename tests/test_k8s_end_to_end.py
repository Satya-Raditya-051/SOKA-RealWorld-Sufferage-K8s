import json
import os
import subprocess
import unittest

from scheduler.algorithms import (
    CCTSAScheduler,
    RoundRobinScheduler,
    StandardSufferageScheduler,
)
from scheduler.datasets import get_kubernetes_vms, get_paper_tasks
from scheduler.k8s_broker import (
    calculate_metrics,
    calibrate_workers,
    check_workers,
    execute_allocations,
    make_clients,
    reset_workers,
)

RUN_K8S = os.environ.get("SOKA_RUN_K8S_TESTS") == "1"


@unittest.skipUnless(RUN_K8S, "set SOKA_RUN_K8S_TESTS=1 to test a live cluster")
class KubernetesEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.vms = get_kubernetes_vms()
        cls.clients = make_clients(cls.vms, timeout_s=120)
        cls.health = check_workers(cls.clients)

    def kubectl_json(self, *args: str):
        completed = subprocess.run(
            ["kubectl", "--context", "kind-soka-datacenter", *args, "-o", "json"],
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(completed.stdout)

    def test_topology_placement_qos_and_services(self) -> None:
        nodes = self.kubectl_json("get", "nodes")["items"]
        self.assertEqual(len(nodes), 3)
        labels = [node["metadata"]["labels"] for node in nodes]
        self.assertEqual(
            sum(item.get("soka.its.ac.id/host-id") == "host-1" for item in labels), 1
        )
        self.assertEqual(
            sum(item.get("soka.its.ac.id/host-id") == "host-2" for item in labels), 1
        )

        pods = self.kubectl_json(
            "get", "pods", "-n", "soka-cloud", "-l", "app=soka-vm"
        )["items"]
        self.assertEqual(len(pods), 4)
        expected_nodes = {
            "vm-1-small": "soka-datacenter-worker",
            "vm-2-medium": "soka-datacenter-worker",
            "vm-3-large": "soka-datacenter-worker2",
            "vm-4-xlarge": "soka-datacenter-worker2",
        }
        for pod in pods:
            name = pod["metadata"]["name"]
            self.assertEqual(pod["spec"]["nodeName"], expected_nodes[name])
            self.assertEqual(pod["status"]["phase"], "Running")
            self.assertEqual(pod["status"]["qosClass"], "Guaranteed")
            ready = next(
                item for item in pod["status"]["conditions"] if item["type"] == "Ready"
            )
            self.assertEqual(ready["status"], "True")

        services = self.kubectl_json("get", "services", "-n", "soka-cloud")["items"]
        node_ports = sorted(
            port["nodePort"]
            for service in services
            for port in service["spec"].get("ports", [])
            if "nodePort" in port
        )
        self.assertEqual(node_ports, [30081, 30082, 30083, 30084])
        self.assertEqual(set(self.health), {1, 2, 3, 4})

    def test_all_algorithms_execute_real_paper_tasks_once(self) -> None:
        profiles = calibrate_workers(
            self.clients,
            repeats=2,
            cpu_work=500_000,
            payload_mbit=8,
        )
        tasks = get_paper_tasks()[:4]
        for scheduler in (
            CCTSAScheduler(),
            StandardSufferageScheduler(),
            RoundRobinScheduler(),
        ):
            with self.subTest(algorithm=scheduler.name):
                reset_workers(self.clients)
                allocations = scheduler.plan(tasks, self.vms, profiles)
                self.assertEqual(
                    sorted(item.task_id for item in allocations),
                    sorted(task.id for task in tasks),
                )
                makespan = execute_allocations(allocations, self.vms, self.clients)
                metrics = calculate_metrics(allocations, self.vms, makespan)
                self.assertGreater(metrics["real_makespan_s"], 0)
                self.assertGreater(metrics["actual_cpu_capacity_utilization_pct"], 0)
                self.assertTrue(all(item.proof_checksum for item in allocations))
                self.assertTrue(all(item.payload_sha256 for item in allocations))


if __name__ == "__main__":
    unittest.main()
