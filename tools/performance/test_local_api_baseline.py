"""Small deterministic checks for measurement math and offline guard behavior."""
import socket
import unittest
from unittest.mock import patch

import local_api_baseline as benchmark


class BaselineHarnessTests(unittest.TestCase):
    def test_quantiles_use_all_samples_and_nearest_rank_p95(self):
        values = list(reversed(range(1, 41)))
        result = benchmark.distribution(values)
        self.assertEqual(result["n"], 40)
        self.assertEqual(result["p50"], 20.5)
        self.assertEqual(result["p95"], 38)
        self.assertEqual(result["min"], 1)
        self.assertEqual(result["max"], 40)
        self.assertEqual(result["samples"], values)

    def test_single_sample_is_not_invented_distribution(self):
        self.assertEqual(benchmark.distribution([3])["p95"], 3)
        self.assertEqual(benchmark.distribution([3])["n"], 1)

    def test_guard_rejects_tcp_dns_without_contacting_network(self):
        with patch.object(socket.socket, "connect"), patch.object(socket.socket, "connect_ex"), patch.object(socket, "getaddrinfo"):
            attempts = benchmark.install_network_denial()
            with socket.socket(socket.AF_INET) as sock:
                for method in (sock.connect, sock.connect_ex):
                    with self.assertRaisesRegex(RuntimeError, "denied network"):
                        method(("127.0.0.1", 9))
            with self.assertRaisesRegex(RuntimeError, "denied DNS"):
                socket.getaddrinfo("example.invalid", 443)
            self.assertEqual(attempts, ["connect", "connect_ex", "getaddrinfo"])


if __name__ == "__main__":
    unittest.main()
