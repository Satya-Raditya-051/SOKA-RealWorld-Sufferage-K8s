import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class KubernetesContractTests(unittest.TestCase):
    def test_manifest_preserves_names_ports_and_hardening(self) -> None:
        manifest = (ROOT / "k8s" / "vm-pods.yaml").read_text()
        for name in ("vm-1-small", "vm-2-medium", "vm-3-large", "vm-4-xlarge"):
            self.assertIn(f"name: {name}", manifest)
        for port in range(30081, 30085):
            self.assertIn(f"nodePort: {port}", manifest)
        self.assertEqual(manifest.count("readOnlyRootFilesystem: true"), 4)
        self.assertEqual(manifest.count("automountServiceAccountToken: false"), 4)
        self.assertEqual(manifest.count("readinessProbe:"), 4)
        self.assertEqual(manifest.count("livenessProbe:"), 4)
        self.assertNotIn("image: soka-vm-worker:latest", manifest)

    def test_kind_ports_bind_only_to_loopback(self) -> None:
        config = (ROOT / "k8s" / "kind-cluster.yaml").read_text()
        self.assertEqual(config.count('listenAddress: "127.0.0.1"'), 4)

    def test_production_worker_has_no_fake_delay_or_payload_cap(self) -> None:
        worker = (ROOT / "vm_worker" / "worker_server.py").read_text()
        self.assertNotIn("time.sleep", worker)
        self.assertNotIn("8 * 1024 * 1024", worker)


if __name__ == "__main__":
    unittest.main()
