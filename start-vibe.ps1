#requires -Version 7.0
[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$NoBrowser,
    [switch]$ValidateOnly,
    [switch]$SmokeTest
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$global:LASTEXITCODE = 0

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $RepoRoot "backend"
$FrontendDir = Join-Path $RepoRoot "frontend"
$RuntimeDir = Join-Path $RepoRoot ".vibe-runtime"
$BackendLock = Join-Path $BackendDir "requirements-dev-windows-py312.lock.txt"
$BackendVenv = Join-Path $BackendDir ".venv"
$BackendPython = Join-Path $BackendVenv "Scripts\python.exe"
$FrontendLock = Join-Path $FrontendDir "package-lock.json"
$FrontendModules = Join-Path $FrontendDir "node_modules"
$BackendMarker = Join-Path $RuntimeDir "backend-lock.sha256"
$FrontendMarker = Join-Path $RuntimeDir "frontend-lock.sha256"
$BackendUrl = "http://127.0.0.1:8900"
$FrontendUrl = "http://127.0.0.1:5899"

function Assert-ProjectLayout {
    $required = @(
        (Join-Path $BackendDir "app.py"),
        $BackendLock,
        (Join-Path $FrontendDir "package.json"),
        $FrontendLock,
        (Join-Path $RepoRoot "Start-Vibe.cmd")
    )
    foreach ($path in $required) {
        if (-not (Test-Path -LiteralPath $path)) {
            throw "项目文件缺失：$path"
        }
    }
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$ArgumentList,
        [Parameter(Mandatory)] [string]$WorkingDirectory,
        [Parameter(Mandatory)] [string]$Description
    )

    Push-Location $WorkingDirectory
    try {
        & $FilePath @ArgumentList | Out-Host
        $commandExitCode = $LASTEXITCODE
        if ($commandExitCode -ne 0) {
            throw "$Description 失败，退出码：$commandExitCode"
        }
    }
    finally {
        Pop-Location
    }
}

function Resolve-Python312Launcher {
    $py = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $py) {
        $version = (& $py.Source -3.12 -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $version -match '^3\.12\.') {
            return [pscustomobject]@{
                FilePath = $py.Source
                PrefixArguments = @("-3.12")
                Version = $version
            }
        }
    }

    $python = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $python) {
        $version = (& $python.Source -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null | Select-Object -First 1)
        if ($LASTEXITCODE -eq 0 -and $version -match '^3\.12\.') {
            return [pscustomobject]@{
                FilePath = $python.Source
                PrefixArguments = @()
                Version = $version
            }
        }
    }

    throw "未找到 Python 3.12。请先安装 Python 3.12，并确保 py.exe 或 python.exe 可用。"
}

function Get-ContentHash {
    param([Parameter(Mandatory)] [string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Ensure-BackendEnvironment {
    $created = $false
    if (-not (Test-Path -LiteralPath $BackendPython)) {
        $launcher = Resolve-Python312Launcher
        Write-Host "首次运行：创建 Python 3.12 环境……" -ForegroundColor Cyan
        $arguments = @($launcher.PrefixArguments) + @("-m", "venv", $BackendVenv)
        Invoke-CheckedCommand `
            -FilePath $launcher.FilePath `
            -ArgumentList $arguments `
            -WorkingDirectory $RepoRoot `
            -Description "创建 Python 环境"
        $created = $true
    }

    $venvVersion = (& $BackendPython -c "import sys; print('.'.join(map(str, sys.version_info[:3])))" 2>$null | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or $venvVersion -notmatch '^3\.12\.') {
        throw "backend\.venv 不是可用的 Python 3.12 环境。请先备份并移走该目录，再重新启动。"
    }

    $expected = Get-ContentHash $BackendLock
    $actual = if (Test-Path -LiteralPath $BackendMarker) {
        (Get-Content -LiteralPath $BackendMarker -Raw).Trim().ToLowerInvariant()
    }
    else {
        ""
    }

    if ($Setup -or $created -or $actual -ne $expected) {
        Write-Host "同步后端依赖……" -ForegroundColor Cyan
        Invoke-CheckedCommand `
            -FilePath $BackendPython `
            -ArgumentList @("-m", "pip", "install", "--disable-pip-version-check", "-r", $BackendLock) `
            -WorkingDirectory $BackendDir `
            -Description "安装后端依赖"
        Set-Content -LiteralPath $BackendMarker -Value $expected -NoNewline -Encoding utf8
    }
}

function Ensure-FrontendEnvironment {
    $node = Get-Command "node.exe" -ErrorAction SilentlyContinue
    $npm = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($null -eq $node -or $null -eq $npm) {
        throw "未找到 Node.js 22 / npm.cmd。请先安装 Node.js 22。"
    }

    $nodeVersion = (& $node.Source --version 2>$null | Select-Object -First 1)
    if ($LASTEXITCODE -ne 0 -or $nodeVersion -notmatch '^v22\.') {
        throw "当前 Node.js 版本为 $nodeVersion；Vibe-Research 需要 Node.js 22。"
    }

    $expected = Get-ContentHash $FrontendLock
    $actual = if (Test-Path -LiteralPath $FrontendMarker) {
        (Get-Content -LiteralPath $FrontendMarker -Raw).Trim().ToLowerInvariant()
    }
    else {
        ""
    }

    if ($Setup -or -not (Test-Path -LiteralPath $FrontendModules) -or $actual -ne $expected) {
        Write-Host "同步前端依赖……" -ForegroundColor Cyan
        Invoke-CheckedCommand `
            -FilePath $npm.Source `
            -ArgumentList @("ci") `
            -WorkingDirectory $FrontendDir `
            -Description "安装前端依赖"
        Set-Content -LiteralPath $FrontendMarker -Value $expected -NoNewline -Encoding utf8
    }

    return $npm.Source
}

function Test-HttpEndpoint {
    param(
        [Parameter(Mandatory)] [string]$Uri,
        [string]$ExpectedText = ""
    )

    try {
        $response = Invoke-WebRequest -Uri $Uri -Method Get -TimeoutSec 3 -SkipHttpErrorCheck
        if ($response.StatusCode -lt 200 -or $response.StatusCode -ge 400) {
            return $false
        }
        if ($ExpectedText -and $response.Content -notlike "*$ExpectedText*") {
            return $false
        }
        return $true
    }
    catch {
        return $false
    }
}

function Test-TcpPort {
    param([Parameter(Mandatory)] [int]$Port)

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $task = $client.ConnectAsync("127.0.0.1", $Port)
        if (-not $task.Wait(500)) {
            return $false
        }
        return $client.Connected
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Start-OwnedProcess {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [string]$FilePath,
        [Parameter(Mandatory)] [string[]]$ArgumentList,
        [Parameter(Mandatory)] [string]$WorkingDirectory
    )

    $token = "{0}-{1}" -f (Get-Date -Format "yyyyMMdd-HHmmss"), ([guid]::NewGuid().ToString("N").Substring(0, 8))
    $stdout = Join-Path $RuntimeDir "$Name-$token.out.log"
    $stderr = Join-Path $RuntimeDir "$Name-$token.err.log"
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr `
        -WindowStyle Hidden `
        -PassThru

    return [pscustomobject]@{
        Name = $Name
        Process = $process
        Stdout = $stdout
        Stderr = $stderr
    }
}

function Wait-ForService {
    param(
        [Parameter(Mandatory)] [string]$Name,
        [Parameter(Mandatory)] [scriptblock]$Probe,
        [int]$TimeoutSeconds = 90,
        [AllowNull()] [System.Diagnostics.Process]$Process = $null
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($null -ne $Process) {
            $Process.Refresh()
            if ($Process.HasExited) {
                throw "$Name 启动后立即退出，退出码：$($Process.ExitCode)"
            }
        }
        if (& $Probe) {
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "等待 $Name 就绪超时（$TimeoutSeconds 秒）。"
}

function Show-LogTail {
    param([Parameter(Mandatory)] [pscustomobject]$Entry)

    foreach ($path in @($Entry.Stderr, $Entry.Stdout)) {
        if (Test-Path -LiteralPath $path) {
            Write-Host "`n--- $path ---" -ForegroundColor DarkYellow
            Get-Content -LiteralPath $path -Tail 40
        }
    }
}

function Stop-OwnedProcessTree {
    param([Parameter(Mandatory)] [pscustomobject]$Entry)

    $Entry.Process.Refresh()
    if ($Entry.Process.HasExited) {
        return
    }
    Write-Host "停止 $($Entry.Name)……" -ForegroundColor DarkGray
    & taskkill.exe /PID $Entry.Process.Id /T /F *> $null
}

Assert-ProjectLayout
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

if ($ValidateOnly) {
    $cmdText = Get-Content -LiteralPath (Join-Path $RepoRoot "Start-Vibe.cmd") -Raw
    if ($cmdText -notmatch '(?i)\bpwsh\.exe\b') {
        throw "Start-Vibe.cmd 必须通过 pwsh.exe 启动。"
    }
    if ($cmdText -match '(?i)\bpowershell\.exe\b') {
        throw "Start-Vibe.cmd 不得调用旧版 powershell.exe。"
    }
    if ($cmdText -notmatch '%\*') {
        throw "Start-Vibe.cmd 必须把显式参数转交给 PowerShell 7 启动器。"
    }
    Write-Host "One-click launcher validation: PASS"
    exit 0
}

$ownedProcesses = @()
$exitCode = 0

try {
    Ensure-BackendEnvironment
    $npmPath = Ensure-FrontendEnvironment

    $backendEntry = $null
    if (Test-HttpEndpoint -Uri "$BackendUrl/api/health") {
        Write-Host "后端已在运行，直接复用。" -ForegroundColor Green
    }
    else {
        if (Test-TcpPort -Port 8900) {
            throw "端口 8900 已被其他程序占用，但不是可用的 Vibe 后端。"
        }
        Write-Host "启动后端……" -ForegroundColor Cyan
        $backendEntry = Start-OwnedProcess `
            -Name "backend" `
            -FilePath $BackendPython `
            -ArgumentList @("-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8900") `
            -WorkingDirectory $BackendDir
        $ownedProcesses += $backendEntry
        Wait-ForService `
            -Name "后端" `
            -Probe { Test-HttpEndpoint -Uri "$BackendUrl/api/health" } `
            -Process $backendEntry.Process
    }

    $frontendEntry = $null
    if (Test-HttpEndpoint -Uri $FrontendUrl -ExpectedText "Vibe-Research") {
        Write-Host "前端已在运行，直接复用。" -ForegroundColor Green
    }
    else {
        if (Test-TcpPort -Port 5899) {
            throw "端口 5899 已被其他程序占用，但不是可用的 Vibe 前端。"
        }
        Write-Host "启动前端……" -ForegroundColor Cyan
        $frontendEntry = Start-OwnedProcess `
            -Name "frontend" `
            -FilePath $npmPath `
            -ArgumentList @("run", "dev", "--", "--host", "127.0.0.1", "--port", "5899", "--strictPort") `
            -WorkingDirectory $FrontendDir
        $ownedProcesses += $frontendEntry
        Wait-ForService `
            -Name "前端" `
            -Probe { Test-HttpEndpoint -Uri $FrontendUrl -ExpectedText "Vibe-Research" } `
            -Process $frontendEntry.Process
    }

    if (-not $NoBrowser -and -not $SmokeTest) {
        Start-Process $FrontendUrl | Out-Null
    }

    Write-Host "`nVibe-Research 已就绪：$FrontendUrl" -ForegroundColor Green

    if ($SmokeTest) {
        Write-Host "One-click launcher smoke: PASS" -ForegroundColor Green
    }
    else {
        Write-Host "保持此窗口开启；按 Ctrl+C 会停止本次启动的服务。" -ForegroundColor DarkGray
        while ($true) {
            foreach ($entry in $ownedProcesses) {
                $entry.Process.Refresh()
                if ($entry.Process.HasExited) {
                    throw "$($entry.Name) 已意外退出，退出码：$($entry.Process.ExitCode)"
                }
            }
            Start-Sleep -Seconds 2
        }
    }
}
catch [System.Management.Automation.PipelineStoppedException] {
    Write-Host "`n正在停止 Vibe-Research……" -ForegroundColor DarkGray
    $exitCode = 0
}
catch {
    Write-Host "`n启动失败：$($_.Exception.Message)" -ForegroundColor Red
    foreach ($entry in $ownedProcesses) {
        Show-LogTail -Entry $entry
    }
    $exitCode = 1
}
finally {
    for ($index = $ownedProcesses.Count - 1; $index -ge 0; $index--) {
        Stop-OwnedProcessTree -Entry $ownedProcesses[$index]
    }
}

exit $exitCode
