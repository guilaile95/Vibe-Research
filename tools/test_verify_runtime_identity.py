import unittest
from unittest.mock import patch
from urllib.request import HTTPRedirectHandler
from verify_runtime_identity import compare_identities, local_origin, fetch_identity


class RuntimeIdentityTests(unittest.TestCase):
    def fixtures(self):
        return {name: {"service": service, "git_sha": "a" * 40, "source_state": "clean",
                       "identity_scope": "BUILD_SOURCE_SNAPSHOT"}
                for name, service in [("backend", "vibe-research-api"), ("frontend", "vibe-research-frontend"),
                                      ("agent_runtime", "vibe-agent-runtime")]}

    def test_all_three_sources_must_match(self):
        self.assertEqual(compare_identities("a" * 40, self.fixtures())["status"], "SOURCE_MATCH")
        for key in self.fixtures():
            data = self.fixtures(); data[key]["git_sha"] = "b" * 40
            self.assertEqual(compare_identities("a" * 40, data)["status"], "MISMATCH")

    def test_unknown_dirty_wrong_service_and_hmr_cannot_pass(self):
        for key in self.fixtures():
            for field, value in [("git_sha", None), ("service", "other")]:
                data = self.fixtures(); data[key][field] = value
                self.assertEqual(compare_identities("a" * 40, data)["status"], "UNVERIFIED")
            data = self.fixtures(); data[key]["source_state"] = "modified"
            self.assertEqual(compare_identities("a" * 40, data)["status"], "MISMATCH")
        data = self.fixtures(); data["frontend"]["identity_scope"] = "DEV_SERVER_STARTUP_SNAPSHOT_NOT_IMMUTABLE_ASSETS"
        self.assertEqual(compare_identities("a" * 40, data)["status"], "UNVERIFIED")

    def test_malformed_source_state_is_unverified(self):
        for key in self.fixtures():
            for value in [[], {}, None, 1, True, "unexpected"]:
                with self.subTest(service=key, value=value):
                    data = self.fixtures(); data[key]["source_state"] = value
                    report = compare_identities("a" * 40, data)
                    self.assertEqual(report["status"], "UNVERIFIED")
                    self.assertEqual(report["services"][key]["source_state"], "unknown")

    def test_endpoint_safety(self):
        self.assertEqual(local_origin("http://[::1]:8911/"), "http://[::1]:8911")
        for value in ["https://evil.example:8911", "http://127.0.0.1:8911?x=1",
                      "http://user:pass@127.0.0.1:8911", "http://127.0.0.1:8911/path", "http://127.0.0.1"]:
            with self.assertRaises(ValueError): local_origin(value)

    def test_credentials_cannot_follow_redirects(self):
        captured = []
        def build(*handlers):
            captured.extend(handlers)
            raise OSError("synthetic unavailable")
        with patch("verify_runtime_identity.build_opener", side_effect=build):
            with self.assertRaises(OSError): fetch_identity("http://127.0.0.1:8900/api/runtime-info", "SYNTHETIC")
        redirects = [handler for handler in captured if isinstance(handler, HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        self.assertIsNone(redirects[0].redirect_request(None, None, 302, "", {}, "http://outside.invalid/"))


if __name__ == "__main__":
    unittest.main()
