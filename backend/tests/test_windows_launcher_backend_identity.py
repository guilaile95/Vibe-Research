"""Backend identity at launcher reuse and readiness, without starting services."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = REPO_ROOT / "start-vibe.ps1"


def test_backend_reuse_and_readiness_require_existing_service_marker() -> None:
    source = LAUNCHER.read_text(encoding="utf-8")
    calls = [line.strip() for line in source.splitlines()
             if 'Test-HttpEndpoint -Uri "$BackendUrl/api/health"' in line]
    assert len(calls) == 2, "Both reuse and newly started backend readiness must be checked"
    assert all('-ExpectedText "vibe-research-api"' in call for call in calls)


@pytest.mark.skipif(os.name != "nt", reason="Real PowerShell function is tested on Windows CI")
def test_backend_identity_real_powershell_with_mock_http(tmp_path: Path) -> None:
    # Parse only the function and its backend calls. Never dot-source the launcher:
    # its top-level body installs dependencies and starts services.
    fixture = tmp_path / "backend-identity.ps1"
    fixture.write_text(r'''
param([string]$Launcher)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Launcher, [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) { throw "Launcher parse failed" }
$function = $ast.Find({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq "Test-HttpEndpoint"
}, $true)
if ($null -eq $function) { throw "HTTP probe function missing" }
. ([scriptblock]::Create($function.Extent.Text))
$backendCalls = @($ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.CommandAst] -and
    $node.GetCommandName() -eq "Test-HttpEndpoint" -and
    $node.Extent.Text.Contains('$BackendUrl/api/health')
}, $true))
if ($backendCalls.Count -ne 2) { throw "Expected reuse and readiness calls" }
$BackendUrl = "http://fixture.invalid:8900"
$script:fixtureStatus = 200
$script:fixtureContent = '{"ok":true,"service":"unrelated-service"}'
$script:fixtureThrows = $false
function Invoke-WebRequest {
    param($Uri, $Method, $TimeoutSec, [switch]$SkipHttpErrorCheck)
    if ($Uri -ne "$BackendUrl/api/health") { throw "Unexpected URI" }
    if ($script:fixtureThrows) { throw "Synthetic endpoint failure" }
    return [pscustomobject]@{ StatusCode = $script:fixtureStatus; Content = $script:fixtureContent }
}
# Reproduce the old call contract: HTTP success alone accepted an unrelated body.
if (-not (Test-HttpEndpoint -Uri "$BackendUrl/api/health")) { throw "Old behavior reproduction failed" }
foreach ($call in $backendCalls) {
    $probe = [scriptblock]::Create($call.Extent.Text)
    $script:fixtureContent = '{"ok":true,"service":"unrelated-service"}'
    if (& $probe) { throw "Unrelated HTTP 200 accepted by backend caller" }
    $script:fixtureContent = '{"ok":true,"service":"vibe-research-api","version":"fixture"}'
    if (-not (& $probe)) { throw "Real service payload rejected" }
    $script:fixtureStatus = 503
    if (& $probe) { throw "Failed HTTP status accepted" }
    $script:fixtureStatus = 200
    $script:fixtureThrows = $true
    if (& $probe) { throw "Endpoint exception accepted" }
    $script:fixtureThrows = $false
}
Write-Output "Backend identity mock HTTP: PASS"
''', encoding="utf-8")
    result = subprocess.run(
        ["pwsh.exe", "-NoLogo", "-NoProfile", "-File", str(fixture), "-Launcher", str(LAUNCHER)],
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "Backend identity mock HTTP: PASS" in result.stdout
