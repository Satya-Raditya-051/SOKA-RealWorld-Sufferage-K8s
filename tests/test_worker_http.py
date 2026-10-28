import http.client
import threading
import unittest

from scheduler.k8s_broker import WorkerClient
from scheduler.models import VMNode
from vm_worker.worker_server import VMWorkerHandler, WorkerHTTPServer


class WorkerHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = WorkerHTTPServer(("127.0.0.1", 0), VMWorkerHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        port = cls.server.server_address[1]
        cls.vm = VMNode(1, "VM1", "host-1", 1, 1, 0.1, 1000, f"http://127.0.0.1:{port}")
        cls.client = WorkerClient(cls.vm, timeout_s=10)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def test_health_execute_full_payload_and_reset(self) -> None:
        health = self.client.health()
        self.assertEqual(health["status"], "ready")
        result = self.client.execute(99, "integration", 10_000, 2_500_123)
        self.assertEqual(result["payload_bytes"], 2_500_123)
        self.assertEqual(result["cpu_work"], 10_000)
        self.assertEqual(len(result["proof_checksum"]), 64)
        self.assertGreater(result["service_s"], 0)
        self.client.reset()
        self.assertEqual(self.client.health()["stats"]["tasks_completed"], 0)

    def test_invalid_request_is_rejected(self) -> None:
        port = self.server.server_address[1]
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("POST", "/execute", body=b"")
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()
