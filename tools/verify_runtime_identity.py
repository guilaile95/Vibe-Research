"""Read-only exact-source deployment comparison. Never starts/stops services.

Example: python tools/verify_runtime_identity.py --expected-sha <40 hex commit>
This is not a health probe, login test or proof of model/provider availability.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler


def local_origin(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid loopback endpoint") from exc
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None or parsed.password is not None
            or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
            or port is None or not 1024 <= port <= 65535):
        raise ValueError("only explicit loopback HTTP endpoints are supported")
    return value.rstrip("/")


def compare_identities(expected_sha: str, identities: dict) -> dict:
    if not re.fullmatch(r"[a-f0-9]{40}", expected_sha):
        raise ValueError("expected SHA must be the full lower-case Git commit")
    expected_services = {"backend": "vibe-research-api", "frontend": "vibe-research-frontend",
                         "agent_runtime": "vibe-agent-runtime"}
    results = {}
    for name, service in expected_services.items():
        value = identities.get(name)
        value = value.get("data", value) if isinstance(value, dict) else {}
        if not isinstance(value, dict):
            value = {}
        sha = value.get("git_sha")
        state = "UNVERIFIED"
        if value.get("service") == service and isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha):
            if sha != expected_sha or value.get("source_state") == "modified":
                state = "MISMATCH"
            elif value.get("source_state") == "clean":
                state = "SOURCE_MATCH"
        # Development HMR and arbitrary archives are not immutable build proof.
        if name == "frontend" and value.get("identity_scope") != "BUILD_SOURCE_SNAPSHOT" and state == "SOURCE_MATCH":
            state = "UNVERIFIED"
        results[name] = {"status": state, "git_sha": sha if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{40}", sha) else None,
                         "source_state": value.get("source_state") if value.get("source_state") in {"clean", "modified", "unknown"} else "unknown"}
    states = [value["status"] for value in results.values()]
    status = "MISMATCH" if "MISMATCH" in states else "SOURCE_MATCH" if all(x == "SOURCE_MATCH" for x in states) else "UNVERIFIED"
    return {"expected_sha": expected_sha, "status": status, "services": results,
            "scope": "READ_ONLY_SOURCE_IDENTITY_NOT_SERVICE_OR_MODEL_ACCEPTANCE"}


def fetch_identity(url: str, token: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    # No redirects: never forward a local API credential to another destination.
    from urllib.request import HTTPRedirectHandler
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(url, headers=headers), timeout=3) as response:
        data = response.read(65537)
        if len(data) > 65536:
            raise ValueError("identity response exceeded budget")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("invalid identity response")
        return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--backend", default="http://127.0.0.1:8900")
    parser.add_argument("--frontend", default="http://127.0.0.1:5899")
    parser.add_argument("--agent-runtime", default="http://127.0.0.1:8911")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.expected_sha):
        parser.error("expected SHA must be the full lower-case Git commit")
    endpoints = {"backend": (local_origin(args.backend), "/api/runtime-info"),
                 "frontend": (local_origin(args.frontend), "/vibe-build.json"),
                 "agent_runtime": (local_origin(args.agent_runtime), "/runtime-info")}
    identities = {}
    for name, (origin, route) in endpoints.items():
        try:
            identities[name] = fetch_identity(origin + route, os.environ.get("VR_API_KEY") if name == "backend" else None)
        except Exception:
            identities[name] = {}  # No network URLs, exceptions or credentials in output.
    report = compare_identities(args.expected_sha, identities)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "SOURCE_MATCH" else 1 if report["status"] == "MISMATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
