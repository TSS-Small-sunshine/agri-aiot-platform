<#
==============================================================================
 智慧农业 AIoT 平台 —— 裸机开发一键启动（Windows / PowerShell 5.1+）

 用法：
   powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1            # 完整流程
   powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1 -Seed      # 额外灌历史数据
   powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1 -NoSim     # 只起后端
   powershell -ExecutionPolicy Bypass -File scripts/dev_up.ps1 -Stop      # 停掉后端与模拟器

 幂等：重复执行安全。已存在的 venv / node_modules 不会重建，只做增量安装。
 日志：logs\backend.log、logs\simulator.log；PID：logs\backend.pid、logs\simulator.pid
==============================================================================
#>
[CmdletBinding()]
param(
    [switch]$Seed,
    [switch]$NoSim,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'

# 让中文在任意代码页的终端里都能正常显示
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

# ---- 定位仓库根目录（脚本在 scripts\ 下，根目录是它的上一级）----
$RootDir = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $RootDir

$LogDir    = Join-Path $RootDir 'logs'
$VenvDir   = Join-Path $RootDir '.venv'
$StaticDir = Join-Path $RootDir 'backend\app\static'
$DistDir   = Join-Path $RootDir 'frontend\dist'

function Write-Log  { param([string]$m) Write-Host "[dev_up] $m" -ForegroundColor Cyan }
function Write-Warn2 { param([string]$m) Write-Host "[警告] $m" -ForegroundColor Yellow }
function Write-Die  { param([string]$m) Write-Host "[失败] $m" -ForegroundColor Red; exit 1 }

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Test-Cmd {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        Write-Die "找不到命令 $Name。请先安装它（$Hint），然后重新运行本脚本。"
    }
}

function Stop-One {
    param([string]$Name)
    $pidFile = Join-Path $LogDir "$Name.pid"
    if (Test-Path $pidFile) {
        $procId = (Get-Content $pidFile -Raw).Trim()
        $proc = $null
        if ($procId) { $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue }
        if ($proc) {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Write-Log "已停止 $Name（PID $procId）"
        } else {
            Write-Log "$Name 未在运行（PID 文件已过期）"
        }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    } else {
        Write-Log "$Name 未在运行（无 PID 文件）"
    }
}

# ---- -Stop：先处理停止请求，不做任何安装 ----
if ($Stop) {
    Stop-One 'backend'
    Stop-One 'simulator'
    Write-Log '完成。'
    exit 0
}

# ---- 1. 环境检查 ----
Test-Cmd 'python' 'https://www.python.org/downloads/ 安装时勾选 Add to PATH'
Test-Cmd 'node'   'https://nodejs.org 安装 LTS 版本'
Test-Cmd 'npm'    '随 Node.js 一起安装'

$pyVer = (& python --version 2>&1) -join ' '
$nodeVer = (& node --version 2>&1) -join ' '
Write-Log "Python $pyVer / Node $nodeVer / npm $((& npm --version 2>&1) -join '')"

# ---- 2. 载入 .env（没有就从 .env.example 复制）----
$envFile = Join-Path $RootDir '.env'
$envExample = Join-Path $RootDir '.env.example'
if (-not (Test-Path $envFile)) {
    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile
        Write-Log '未发现 .env，已从 .env.example 复制一份'
    } else {
        Write-Die '缺少 .env 与 .env.example，请先执行 Copy-Item .env.example .env 并填写配置。'
    }
}

# 解析 .env 到进程环境变量（供后续 uvicorn / 模拟器子进程继承）
foreach ($line in Get-Content -Encoding UTF8 $envFile) {
    $t = $line.Trim().TrimStart([char]0xFEFF)
    if (-not $t -or $t.StartsWith('#')) { continue }
    $idx = $t.IndexOf('=')
    if ($idx -lt 1) { continue }
    $k = $t.Substring(0, $idx).Trim()
    $v = $t.Substring($idx + 1).Trim().Trim('"')
    [Environment]::SetEnvironmentVariable($k, $v, 'Process')
}

# 裸机开发没有容器里的 /data 卷，把数据落到仓库本地 data\，避免写 /data 权限报错
$dataDir = Join-Path $RootDir 'data'
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$env:DB_PATH  = (Join-Path $dataDir 'agri.db') -replace '\\', '/'
$env:DATA_DIR = $dataDir
# 裸机开发时 broker 跑在本机，而不是 compose 服务名
if (-not $env:MQTT_HOST -or $env:MQTT_HOST -eq 'mosquitto') { $env:MQTT_HOST = '127.0.0.1' }
if (-not $env:APP_PORT) { $env:APP_PORT = '8000' }
$appPort = $env:APP_PORT

# ---- 3. Python 虚拟环境 + 依赖 ----
if (-not (Test-Path $VenvDir)) {
    Write-Log '创建虚拟环境 .venv'
    & python -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Write-Die '创建 venv 失败。请确认 Python 安装完整（含 venv 模块）。' }
}
$venvPython = Join-Path $VenvDir 'Scripts\python.exe'
if (-not (Test-Path $venvPython)) { Write-Die "激活虚拟环境失败：找不到 $venvPython" }
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'

$reqFile = Join-Path $RootDir 'backend\requirements.txt'
if (Test-Path $reqFile) {
    Write-Log '安装后端依赖（backend\requirements.txt）'
    & $venvPython -m pip install -q --upgrade pip
    & $venvPython -m pip install -q -r $reqFile
    if ($LASTEXITCODE -ne 0) {
        Write-Die '安装后端依赖失败。检查网络，或换国内源：.venv\Scripts\python -m pip install -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple'
    }
} else {
    Write-Warn2 '未找到 backend\requirements.txt，跳过后端依赖安装（后端负责人尚未提交？）'
}

$simScript = Join-Path $RootDir 'simulator\mock_sensor.py'
if (-not $NoSim -and -not (Test-Path $simScript)) {
    Write-Warn2 '未找到 simulator\mock_sensor.py，模拟器可能无法启动（模拟器负责人尚未提交？）'
}

# ---- 4. 前端依赖 + 构建 ----
$pkgJson = Join-Path $RootDir 'frontend\package.json'
if (Test-Path $pkgJson) {
    Write-Log '安装前端依赖并构建（frontend\）'
    Push-Location (Join-Path $RootDir 'frontend')
    try {
        if (-not (Test-Path (Join-Path (Get-Location) 'node_modules'))) { & npm install; if ($LASTEXITCODE -ne 0) { throw 'npm install 失败' } }
        & npm run build
        if ($LASTEXITCODE -ne 0) { throw 'npm run build 失败' }
    } catch {
        Pop-Location
        Write-Die "前端安装/构建失败：$_  可尝试：cd frontend; Remove-Item -Recurse -Force node_modules; npm install; npm run build"
    }
    Pop-Location
} else {
    Write-Warn2 '未找到 frontend\package.json，跳过前端构建（前端负责人尚未提交？）'
}

# ---- 5. 把 frontend\dist 拷到 backend\app\static（契约第 7 节）----
if (Test-Path $DistDir) {
    Write-Log '拷贝前端产物 frontend\dist -> backend\app\static'
    if (Test-Path $StaticDir) { Remove-Item $StaticDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $StaticDir | Out-Null
    Copy-Item (Join-Path $DistDir '*') $StaticDir -Recurse -Force
    $n = (Get-ChildItem $StaticDir -Recurse -File | Measure-Object).Count
    Write-Log "静态资源就绪：$n 个文件"
} else {
    Write-Warn2 'frontend\dist 不存在，后端将以「无前端」模式启动（访问 / 会返回一行 JSON 提示）。'
}

# ---- 6. 可选：灌历史数据 ----
if ($Seed) {
    $seedScript = Join-Path $RootDir 'scripts\seed_history.py'
    if (Test-Path $seedScript) {
        Write-Log '灌入历史数据（scripts\seed_history.py）'
        & $venvPython $seedScript
        if ($LASTEXITCODE -ne 0) { Write-Die '历史数据灌入失败，请检查 scripts\seed_history.py 的报错。' }
    } else {
        Write-Warn2 '未找到 scripts\seed_history.py，跳过历史数据灌入。'
    }
}

# ---- 7. 启动后端与模拟器（后台 + 日志）----
$mainPy = Join-Path $RootDir 'backend\app\main.py'
if (-not (Test-Path $mainPy)) {
    Write-Die '找不到 backend\app\main.py，后端无法启动（后端负责人尚未提交？）。'
}

Write-Log "启动后端 uvicorn（端口 $appPort），日志 -> logs\backend.log"
$backendLog = Join-Path $LogDir 'backend.log'
$backendProc = Start-Process -FilePath $venvPython -PassThru -WindowStyle Hidden `
    -WorkingDirectory (Join-Path $RootDir 'backend') `
    -RedirectStandardOutput $backendLog `
    -RedirectStandardError (Join-Path $LogDir 'backend.err.log') `
    -ArgumentList '-m', 'uvicorn', 'app.main:app', '--host', '0.0.0.0', '--port', $appPort
$backendProc.Id | Out-File -FilePath (Join-Path $LogDir 'backend.pid') -Encoding ascii

# 等后端起来（最多 30 秒）
$backendOk = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$appPort/api/health" -TimeoutSec 2 -UseBasicParsing
        if ($resp.StatusCode -eq 200) { $backendOk = $true; break }
    } catch { }
}
if ($backendOk) {
    Write-Log "后端已就绪：http://127.0.0.1:$appPort/api/health"
} else {
    Write-Warn2 '30 秒内未等到 /api/health 返回 200，请查看 logs\backend.log 排查。'
}

if (-not $NoSim -and (Test-Path $simScript)) {
    Write-Log '启动模拟器 mock_sensor，日志 -> logs\simulator.log'
    $simProc = Start-Process -FilePath $venvPython -PassThru -WindowStyle Hidden `
        -WorkingDirectory (Join-Path $RootDir 'simulator') `
        -RedirectStandardOutput (Join-Path $LogDir 'simulator.log') `
        -RedirectStandardError (Join-Path $LogDir 'simulator.err.log') `
        -ArgumentList 'mock_sensor.py'
    $simProc.Id | Out-File -FilePath (Join-Path $LogDir 'simulator.pid') -Encoding ascii
}

Write-Host ''
Write-Host '==================================================================' -ForegroundColor Green
Write-Host ' 启动完成'
Write-Host "   大屏地址   http://127.0.0.1:$appPort/"
Write-Host "   健康检查   http://127.0.0.1:$appPort/api/health"
Write-Host "   接口文档   http://127.0.0.1:$appPort/docs"
Write-Host '   后端日志   Get-Content logs\backend.log -Wait'
Write-Host '   模拟器日志 Get-Content logs\simulator.log -Wait'
Write-Host '   停止服务   powershell -ExecutionPolicy Bypass -File scripts\dev_up.ps1 -Stop'
Write-Host '==================================================================' -ForegroundColor Green
