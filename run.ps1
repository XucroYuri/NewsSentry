# News Sentry — CLI 入口包装脚本 (Windows PowerShell)
# 用法: .\run.ps1 [doctor|collect|filter|judge|output|all|serve] [--target <id>] [--profile <id>]
#
# 示例:
#   .\run.ps1 doctor --target italy
#   .\run.ps1 collect --target italy --profile local-workstation
#   .\run.ps1 serve --target italy

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ── 0. Python 版本检查 ──
$PythonMin = "3.11"
$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "Python not found at $VenvPython"
    Write-Error "Please create a virtualenv: python -m venv .venv"
    exit 1
}

$versionStr = & $VenvPython -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
$parts = $versionStr -split '\.'
$major = [int]$parts[0]
$minor = [int]$parts[1]
$minParts = $PythonMin -split '\.'
$minMajor = [int]$minParts[0]
$minMinor = [int]$minParts[1]

if (($major -lt $minMajor) -or (($major -eq $minMajor) -and ($minor -lt $minMinor))) {
    Write-Error "Python $PythonMin+ required, found $versionStr"
    exit 1
}

# ── 1. 激活虚拟环境 ──
$env:VIRTUAL_ENV = Join-Path $ScriptDir ".venv"
$env:PATH = "$($env:VIRTUAL_ENV)\Scripts;$($env:PATH)"

# ── 2. 设置 PYTHONPATH ──
$srcPath = Join-Path $ScriptDir "src"
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$srcPath;$($env:PYTHONPATH)"
} else {
    $env:PYTHONPATH = $srcPath
}

# ── 3. 检查依赖 ──
$null = & python -c "import news_sentry" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "news_sentry package not importable. Install with: pip install -e ."
    exit 1
}

# ── 4. 转发参数 ──
& python -m news_sentry.cli @RemainingArgs
exit $LASTEXITCODE
