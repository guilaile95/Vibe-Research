#requires -Version 7.0
# Offline, dependency-free contract tests. No provider calls or user data.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$tokens = $null
$parseErrors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $RepoRoot 'start-vibe.ps1'), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
# Load production functions without executing the script entry point.
foreach ($definition in $ast.FindAll({ param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false)) {
    . ([scriptblock]::Create($definition.Extent.Text))
}
function Assert-Equal($Actual, $Expected, [string]$Label) {
    if ("$Actual" -cne "$Expected") { throw "$Label`: expected '$Expected', got '$Actual'" }
}
function Assert-Rejected([scriptblock]$Action, [string]$Label) {
    $rejected = $false
    try { & $Action | Out-Null } catch { $rejected = $true }
    if (-not $rejected) { throw "$Label was accepted" }
}

$cases = @(
    @{ Url = ''; Port = ''; Expected = 8911 },
    @{ Url = ''; Port = '18302'; Expected = 18302 },
    @{ Url = 'http://127.0.0.1:18302'; Port = ''; Expected = 18302 },
    @{ Url = 'http://localhost:18302/'; Port = '18302'; Expected = 18302 },
    @{ Url = 'http://[::1]:18302'; Port = ''; Expected = 18302 },
    @{ Url = ' http://localhost:18302/ '; Port = ' 18302 '; Expected = 18302 },
    @{ Url = ''; Port = '1024'; Expected = 1024 },
    @{ Url = ''; Port = '65535'; Expected = 65535 }
)
foreach ($case in $cases) {
    $endpoint = Resolve-AgentRuntimeEndpoint -Url $case.Url -Port $case.Port
    Assert-Equal $endpoint.Port $case.Expected 'resolved port'
    Assert-Equal $endpoint.Url "http://127.0.0.1:$($case.Expected)" 'canonical IPv4 URL'
}
foreach ($port in '0', '1023', '65536', '8900', '5899', '-1', '+18302', '1.2', 'abc', '１８３０２', '9999999999999999999999') {
    Assert-Rejected { Resolve-AgentRuntimeEndpoint -Url '' -Port $port } "port $port"
}
foreach ($url in 'https://127.0.0.1:18302', 'http://external.test:18302', 'http://0.0.0.0:18302',
    'http://127.0.0.2:18302', 'http://127.0.0.1', 'http://localhost:', 'http://u:p@127.0.0.1:18302',
    'http://127.0.0.1:18302/path', 'http://127.0.0.1:18302?', 'http://127.0.0.1:18302#',
    'http://127.0.0.1:18302\', 'http://127.0.0.1:183 02', 'http://127.0.0.1:65536',
    'http://127.0.0.1:8900', 'http://127.0.0.1:5899', 'http://localhost:9999999999999999') {
    Assert-Rejected { Resolve-AgentRuntimeEndpoint -Url $url -Port '' } "URL $url"
}
Assert-Rejected { Resolve-AgentRuntimeEndpoint -Url 'http://localhost:18302' -Port '18303' } 'conflicting pair'

# Keep the real wait function to exercise timeout and exited-child checks below.
$realWait = ${function:Wait-ForService}
$realStop = ${function:Stop-OwnedProcessTree}
$BackendDir = 'unused-backend'
$FrontendDir = 'unused-frontend'
$AgentRuntimeDir = 'unused-runtime'
$BackendPython = 'unused-python'
$BackendUrl = 'http://127.0.0.1:8900'
$FrontendUrl = 'http://127.0.0.1:5899'
$RuntimeDir = Join-Path ([IO.Path]::GetTempPath()) ('vibe-launcher-test-' + [guid]::NewGuid().ToString('N'))
$ValidateOnly = $false
$SmokeTest = $true
$NoBrowser = $true

function Assert-ProjectLayout {}
function Ensure-BackendEnvironment { $script:dependencyCalls++ }
function Resolve-NodeToolchain { return [pscustomobject]@{ Node = 'unused-node'; Npm = 'unused-npm' } }
function Ensure-FrontendEnvironment { param($Toolchain) }
function Ensure-AgentRuntimeEnvironment { param($Toolchain) }
function Test-HttpEndpoint {
    param($Uri, $ExpectedText)
    $script:probes += $Uri
    return ($script:reuseRuntime -and $ExpectedText -eq 'vibe-agent-runtime')
}
function Test-TcpPort {
    param($Port)
    $script:ports += $Port
    return $Port -eq $script:occupiedPort
}
function Start-OwnedProcess {
    param($Name, $FilePath, $ArgumentList, $WorkingDirectory)
    if ($Name -eq $script:startFailure) { throw 'synthetic start failure' }
    $entry = [pscustomobject]@{
        Name = $Name; Process = $null
        Url = $env:VR_AGENT_RUNTIME_URL; Port = $env:VR_AGENT_RUNTIME_PORT
    }
    $script:started += $entry
    return $entry
}
function Wait-ForService {
    param($Name, $Probe, $Process)
    & $Probe | Out-Null
    if ($script:started.Count -eq $script:waitFailureAfter) { throw 'synthetic readiness failure' }
}
function Show-LogTail { param($Entry) }
function Stop-OwnedProcessTree {
    param($Entry)
    $script:stopped += $Entry.Name
    if ($Entry.Name -eq $script:stopFailure) { throw 'synthetic cleanup failure' }
}
function Reset-Scenario {
    $script:started = @(); $script:stopped = @(); $script:probes = @(); $script:ports = @()
    $script:dependencyCalls = 0; $script:occupiedPort = 0; $script:reuseRuntime = $false
    $script:startFailure = ''; $script:waitFailureAfter = -1; $script:stopFailure = ''
}
$originalUrl = $env:VR_AGENT_RUNTIME_URL
$originalPort = $env:VR_AGENT_RUNTIME_PORT
try {
    foreach ($case in $cases) {
        Reset-Scenario
        $env:VR_AGENT_RUNTIME_URL = $case.Url
        $env:VR_AGENT_RUNTIME_PORT = $case.Port
        Assert-Equal (Invoke-VibeLauncher) 0 'smoke exit'
        Assert-Equal $started.Count 3 'started services'
        foreach ($entry in $started) {
            Assert-Equal $entry.Url "http://127.0.0.1:$($case.Expected)" 'child URL'
            Assert-Equal $entry.Port $case.Expected 'child port'
        }
        Assert-Equal ($ports -join ',') "$($case.Expected),8900,5899" 'collision ports'
        Assert-Equal ($probes[0]) "http://127.0.0.1:$($case.Expected)/health" 'health probe'
        Assert-Equal ($stopped -join ',') 'frontend,backend,agent-runtime' 'reverse owned cleanup'
        Assert-Equal $env:VR_AGENT_RUNTIME_URL $case.Url 'restored URL'
        Assert-Equal $env:VR_AGENT_RUNTIME_PORT $case.Port 'restored port'
    }
    Reset-Scenario
    $env:VR_AGENT_RUNTIME_URL = 'http://localhost:18302'
    $env:VR_AGENT_RUNTIME_PORT = '18303'
    Assert-Equal (Invoke-VibeLauncher) 1 'invalid configuration exit'
    Assert-Equal $dependencyCalls 0 'invalid configuration fails before dependencies'
    Assert-Equal $started.Count 0 'invalid configuration starts no process'
    Assert-Equal $env:VR_AGENT_RUNTIME_PORT '18303' 'failed configuration preserves env'

    $env:VR_AGENT_RUNTIME_URL = ''
    $env:VR_AGENT_RUNTIME_PORT = '18302'
    Reset-Scenario
    $occupiedPort = 18302
    Assert-Equal (Invoke-VibeLauncher) 1 'runtime collision exit'
    Assert-Equal $started.Count 0 'runtime collision starts no process'
    Assert-Equal $stopped.Count 0 'runtime collision kills no process'

    Reset-Scenario
    $occupiedPort = 8900
    Assert-Equal (Invoke-VibeLauncher) 1 'backend collision exit'
    Assert-Equal ($stopped -join ',') 'agent-runtime' 'backend collision cleans owned runtime only'

    Reset-Scenario
    $reuseRuntime = $true
    $startFailure = 'backend'
    Assert-Equal (Invoke-VibeLauncher) 1 'reused runtime then startup failure exit'
    Assert-Equal $stopped.Count 0 'reused runtime is never stopped'

    Reset-Scenario
    $startFailure = 'backend'
    Assert-Equal (Invoke-VibeLauncher) 1 'partial spawn failure exit'
    Assert-Equal ($stopped -join ',') 'agent-runtime' 'partial spawn cleanup'

    Reset-Scenario
    $waitFailureAfter = 2
    Assert-Equal (Invoke-VibeLauncher) 1 'readiness failure exit'
    Assert-Equal ($stopped -join ',') 'backend,agent-runtime' 'readiness failure cleanup'

    Reset-Scenario
    $stopFailure = 'frontend'
    Assert-Equal (Invoke-VibeLauncher) 1 'cleanup failure exit'
    Assert-Equal ($stopped -join ',') 'frontend,backend,agent-runtime' 'cleanup continues after a failure'
    Assert-Equal $env:VR_AGENT_RUNTIME_URL '' 'cleanup failure restores URL'
    Assert-Equal $env:VR_AGENT_RUNTIME_PORT '18302' 'cleanup failure restores port'

    Assert-Rejected { & $realWait -Name 'offline timeout' -Probe { $false } -TimeoutSeconds 0 } 'readiness timeout'
    # Real owned child only: never target arbitrary system or pre-existing PIDs.
    $pwsh = (Get-Process -Id $PID).Path
    $child = Start-Process -FilePath $pwsh -ArgumentList @('-NoProfile', '-Command', 'exit 7') -PassThru
    $child.WaitForExit()
    Assert-Rejected { & $realWait -Name 'exited child' -Probe { $true } -Process $child } 'exited child'
    & $realStop -Entry ([pscustomobject]@{ Name = 'already exited test child'; Process = $child })
    $child.Dispose()
    if ($IsWindows) {
        $child = Start-Process -FilePath $pwsh -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 60') -PassThru
        $entry = [pscustomobject]@{ Name = 'owned sleeping test child'; Process = $child }
        try {
            & $realStop -Entry $entry
            $child.Refresh()
            Assert-Equal $child.HasExited $true 'real owned process cleanup'
        }
        finally {
            & $realStop -Entry $entry
            $child.Dispose()
        }
    }
    Write-Host 'Windows launcher offline contracts: PASS'
}
finally {
    $env:VR_AGENT_RUNTIME_URL = $originalUrl
    $env:VR_AGENT_RUNTIME_PORT = $originalPort
    # Remove only the synthetic directory created by this test.
    if (Test-Path -LiteralPath $RuntimeDir) { Remove-Item -LiteralPath $RuntimeDir -Recurse -Force }
}
