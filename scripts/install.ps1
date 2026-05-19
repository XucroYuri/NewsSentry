# =============================================================================
# News Sentry — Windows 安装脚本 (PowerShell)
# =============================================================================
# 创建目录结构、Python 虚拟环境，并注册为启动项（计划任务触发）。
#
# 用法（以普通用户身份运行，无需管理员）:
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -NonInteractive
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1 -Uninstall
# =============================================================================

param(
    [switch]$NonInteractive = $false,
    [switch]$Uninstall = $false,
    [switch]$Help = $false
)

if ($Help) {
    Write-Host @"
News Sentry — Windows 服务安装脚本

用法:
  powershell -ExecutionPolicy Bypass -File install.ps1                  # 交互式安装
  powershell -ExecutionPolicy Bypass -File install.ps1 -NonInteractive  # 非交互式
  powershell -ExecutionPolicy Bypass -File install.ps1 -Uninstall       # 移除服务

前置条件:
  - Windows 10+ / Windows Server 2019+
  - Python >= 3.11 (需加入 PATH，或脚本会自动检测)
  - 无需管理员权限
"@
    exit 0
}

$ErrorActionPreference = "Stop"

$BASE = "$env:USERPROFILE\.news-sentry"
$VENV = "$BASE\venv"
$DATA_DIR = "$BASE\data"
$LOGS_DIR = "$BASE\logs"
$SCRIPTS_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$TASK_NAME = "NewsSentry"

# ── 颜色辅助 ─────────────────────────────────────────────────────────────────

function Write-Green  { param($s) Write-Host $s -ForegroundColor Green }
function Write-Yellow { param($s) Write-Host $s -ForegroundColor Yellow }
function Write-Cyan   { param($s) Write-Host $s -ForegroundColor Cyan }
function Write-Red    { param($s) Write-Host $s -ForegroundColor Red }

# ── 卸载模式 ─────────────────────────────────────────────────────────────────

if ($Uninstall) {
    Write-Yellow "正在卸载 News Sentry 服务..."

    # 移除计划任务
    $task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
    if ($task) {
        Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
        Write-Green "已移除计划任务 '$TASK_NAME'。"
    } else {
        Write-Host "未找到计划任务 '$TASK_NAME'。"
    }

    # 移除启动快捷方式（旧版安装方式）
    $shortcut = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\NewsSentry.lnk"
    if (Test-Path $shortcut) {
        Remove-Item $shortcut -Force
        Write-Green "已移除启动快捷方式。"
    }

    Write-Host ""
    Write-Yellow "注意: $BASE 目录未被删除（包含数据与日志）。"
    Write-Host "如要完全移除，请手动执行: Remove-Item -Recurse -Force '$BASE'"
    exit 0
}

# ── 安装模式 ─────────────────────────────────────────────────────────────────

Write-Cyan "========================================================"
Write-Cyan "  News Sentry — 服务安装脚本 (Windows)"
Write-Cyan "========================================================"
Write-Host ""

# 1. 创建目录结构
Write-Cyan "[1/5] 创建目录结构..."
New-Item -ItemType Directory -Force -Path $DATA_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $LOGS_DIR | Out-Null
Write-Green "  + $DATA_DIR"
Write-Green "  + $LOGS_DIR"

# 2. 检测 Python
Write-Cyan "[2/5] 检测 Python 环境..."
$pythonCmd = $null
$pythonVersion = $null

# 按优先级尝试各 Python 命令
$candidates = @("python3", "python", "py")
foreach ($cmd in $candidates) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver) {
            $major, $minor = $ver -split '\.' | ForEach-Object { [int]$_ }
            if ($major -ge 3 -and $minor -ge 11) {
                $pythonCmd = $cmd
                $pythonVersion = $ver
                break
            }
        }
    } catch {
        # 继续尝试下一个
    }
}

# 也尝试从 Windows Store 或自定义路径查找
if (-not $pythonCmd) {
    $possiblePaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Python313\python.exe",
        "C:\Python312\python.exe",
        "C:\Python311\python.exe"
    )
    foreach ($p in $possiblePaths) {
        if (Test-Path $p) {
            $pythonCmd = $p
            $pythonVersion = & $p -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            break
        }
    }
}

if (-not $pythonCmd) {
    Write-Red "  未找到 Python >= 3.11"
    Write-Host ""
    Write-Host "请先安装 Python 3.11+ 并加入 PATH:"
    Write-Host "  https://www.python.org/downloads/"
    Write-Host "  安装时勾选 'Add Python to PATH'"
    exit 1
}
Write-Green "  找到: $pythonCmd ($pythonVersion)"

# 3. 创建虚拟环境
Write-Cyan "[3/5] 准备虚拟环境..."

if (Test-Path $VENV) {
    Write-Host "  虚拟环境已存在: $VENV"
    if ($NonInteractive) {
        Write-Host "  (non-interactive: 使用现有虚拟环境)"
    } else {
        $response = Read-Host "  重建虚拟环境? [y/N]"
        if ($response -eq 'y' -or $response -eq 'Y') {
            Remove-Item -Recurse -Force $VENV
            Write-Host "  已删除旧虚拟环境"
        } else {
            Write-Host "  保留现有虚拟环境"
        }
    }
}

if (-not (Test-Path $VENV)) {
    Write-Host "  创建虚拟环境..."
    & $pythonCmd -m venv $VENV
    Write-Green "  虚拟环境已创建"
}

$venvPython = "$VENV\Scripts\python.exe"

# 4. 安装/升级 news-sentry
Write-Cyan "[4/5] 安装 News Sentry..."
& $venvPython -m pip install --upgrade pip -q

try {
    & $venvPython -c "import news_sentry" 2>$null
    Write-Host "  news_sentry 已安装，升级到最新版本..."
    & $venvPython -m pip install --upgrade news-sentry -q 2>$null
    # 如果 PyPI 不可用，尝试从本地项目安装
    $pyproject = Join-Path $SCRIPTS_DIR "..\pyproject.toml"
    if (Test-Path $pyproject) {
        & $venvPython -m pip install -e (Resolve-Path (Join-Path $SCRIPTS_DIR "..")) -q 2>$null
    }
} catch {
    Write-Host "  安装 news_sentry..."
    try {
        & $venvPython -m pip install news-sentry -q 2>$null
    } catch {
        $pyproject = Join-Path $SCRIPTS_DIR "..\pyproject.toml"
        if (Test-Path $pyproject) {
            Write-Yellow "  PyPI 不可用，从本地项目安装"
            & $venvPython -m pip install -e (Resolve-Path (Join-Path $SCRIPTS_DIR "..")) -q
        } else {
            Write-Red "无法安装 news_sentry：PyPI 不可用且未找到本地项目"
            exit 1
        }
    }
}

# 验证安装
try {
    & $venvPython -c "import news_sentry" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "导入失败" }
} catch {
    Write-Red "  安装验证失败: 无法导入 news_sentry"
    exit 1
}
Write-Green "  News Sentry 安装/升级完成"

# 5. 注册为计划任务（登录时触发，持续运行）
Write-Cyan "[5/5] 注册为系统服务..."

# 创建启动脚本（供计划任务调用）
$launcherScript = "$BASE\launcher.ps1"
@"
# News Sentry launcher — 由计划任务在登录时触发
Set-Location '$BASE'
& '$venvPython' -m news_sentry.cli serve --foreground *>> '$LOGS_DIR\serve.log'
"@ | Out-File -FilePath $launcherScript -Encoding UTF8

# 移除旧计划任务（如存在）
$oldTask = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if ($oldTask) {
    Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false
}

# 创建新的计划任务：登录时触发，后台持续运行
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcherScript`""

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

# 允许在电池供电时运行，不因空闲停止
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)

# 使用当前用户凭据
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

Register-ScheduledTask -TaskName $TASK_NAME `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "News Sentry — News Intelligence Monitor" `
    -Force | Out-Null

Write-Green "  + 已创建计划任务 '$TASK_NAME'（登录时启动，失败自动重启）"

# 立即启动服务
Start-ScheduledTask -TaskName $TASK_NAME
Write-Green "  + 服务已启动"

# ── 完成 ─────────────────────────────────────────────────────────────────────

Write-Host ""
Write-Green "========================================================"
Write-Green "  安装完成！"
Write-Green "========================================================"
Write-Host ""
Write-Host "数据目录: $DATA_DIR"
Write-Host "日志目录: $LOGS_DIR"
Write-Host "日志文件: $LOGS_DIR\serve.log"
Write-Host ""
Write-Host "常用命令:"
Write-Host "  Get-ScheduledTask -TaskName '$TASK_NAME'      # 查看任务状态"
Write-Host "  Start-ScheduledTask -TaskName '$TASK_NAME'    # 手动启动"
Write-Host "  Stop-ScheduledTask -TaskName '$TASK_NAME'     # 手动停止"
Write-Host "  Get-Content '$LOGS_DIR\serve.log' -Tail 50    # 查看最近日志"
Write-Host ""
Write-Host "Web Dashboard: http://localhost:8080 (默认端口)"
Write-Host ""
Write-Host "提示: 服务随 Windows 登录自动启动，关闭终端窗口不影响运行。"
