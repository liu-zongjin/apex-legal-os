param(
    [ValidateSet('check', 'install', 'start', 'diagnose')][string]$Action = 'check',
    [int]$Port = 18865
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$runtime = Join-Path $env:LOCALAPPDATA 'StellaSource'
$venvPython = Join-Path $root '.venv\Scripts\python.exe'
Set-Location $root
try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw '仅支持 Intel/AMD 64 位 Windows。' }
    if ([Environment]::OSVersion.Version.Build -lt 17763) { throw '需要 Windows 10 1809 或更新版本。' }
    if ($Port -lt 1 -or $Port -gt 65535) { throw '端口必须在 1 到 65535 之间。' }
    Write-Host "源码目录: $root`n数据目录: $runtime`nWindows build: $([Environment]::OSVersion.Version.Build)"
    $python = $null
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $candidate = & py -3.12-64 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) { $python = $candidate }
    }
    if (-not $python -and (Get-Command python -ErrorAction SilentlyContinue)) {
        $candidate = & python -c 'import sys,struct; print(sys.executable if sys.version_info[:2] == (3,12) and sys.maxsize > 2**32 else str())' 2>$null
        if ($LASTEXITCODE -eq 0 -and $candidate) { $python = $candidate }
    }
    if ($python) { Write-Host "Python 3.12: $python" } else { Write-Host '未找到 64 位 Python 3.12。' }
    if (Test-Path $venvPython) { Write-Host '项目虚拟环境已存在。' }
    if ($Action -eq 'install') {
        if (-not $python) { throw '请从 python.org 安装 64 位 Python 3.12，或让 Agent 使用官方渠道安装后重试。' }
        if (-not (Test-Path $venvPython)) { & $python -m venv (Join-Path $root '.venv'); if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败。' } }
        & $venvPython -c 'import sys,struct; assert sys.version_info[:2] == (3,12) and sys.maxsize > 2**32'
        if ($LASTEXITCODE -ne 0) { throw '现有虚拟环境不是 64 位 Python 3.12；请保留数据并检查该环境。' }
        & $venvPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-runtime.txt')
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败；请检查上方 pip 输出和网络连接。' }
        & $venvPython -m pip check
        if ($LASTEXITCODE -ne 0) { throw '依赖检查失败。' }
        Write-Host '依赖安装完成。运行 start 启动并初始化。'
    }
    if ($Action -eq 'diagnose' -and (Test-Path $venvPython)) {
        & $venvPython -m pip check
        if ($LASTEXITCODE -ne 0) { throw '依赖检查失败。' }
        & $venvPython -c 'import fastapi,uvicorn,fitz,docx,openpyxl; print("核心依赖导入正常")'
        if ($LASTEXITCODE -ne 0) { throw '核心依赖导入失败。' }
    }
    if ($Action -eq 'start') {
        if (-not (Test-Path $venvPython)) { throw '尚未安装依赖，请先执行 install。' }
        Write-Host "正在启动；成功后访问 http://127.0.0.1:$Port/ 。关闭此窗口会停止服务。"
        & $venvPython (Join-Path $PSScriptRoot 'source_server.py') --runtime $runtime --port $Port
        if ($LASTEXITCODE -ne 0) { throw "服务退出，代码 $LASTEXITCODE；请检查上方错误。" }
    }
} catch {
    Write-Error "Stella 源码部署失败：$_"
    exit 1
}
