param()
$ErrorActionPreference = 'Stop'

function Refresh-ToolPath {
    $parts = @([Environment]::GetEnvironmentVariable('Path', 'Machine'),
        [Environment]::GetEnvironmentVariable('Path', 'User'),
        (Join-Path $env:USERPROFILE '.cargo\bin'), $env:PATH)
    $env:PATH = ($parts | Where-Object { $_ }) -join ';'
}
function Invoke-Winget([string]$id, [string[]]$extra = @()) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw '未找到 Windows 包管理器 winget；请让 AI 按部署说明从官方来源安装缺失组件。'
    }
    Write-Host "正在安装 $id；系统可能要求用户确认权限。"
    & winget.exe install --id $id --exact --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity @extra
    if ($LASTEXITCODE -ne 0) { throw "安装 $id 未完成（代码 $LASTEXITCODE），请根据上方提示处理后重试。" }
    Refresh-ToolPath
}
function Has-Python {
    $candidate = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($candidate) {
        & $candidate.Source -3.12-64 -c 'import sys' 2>$null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    $candidate = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($candidate) {
        & $candidate.Source -c 'import sys; assert sys.version_info[:2] == (3,12) and sys.maxsize > 2**32' 2>$null
        if ($LASTEXITCODE -eq 0) { return $true }
    }
    return $false
}
function Has-CppTools {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path $vswhere)) { return $false }
    $result = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    return [bool]$result
}
function Has-WebView2 {
    $key = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    foreach ($path in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$key", "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$key")) {
        $version = (Get-ItemProperty -Path $path -Name pv -ErrorAction SilentlyContinue).pv
        if ($version -and $version -ne '0.0.0.0') { return $true }
    }
    return $false
}

Refresh-ToolPath
if (-not (Has-Python)) { Invoke-Winget 'Python.Python.3.12' @('--silent') }
if (-not (Has-Python)) { throw '未检测到 Python 3.12；可能需要重启终端后重试。' }
if (-not (Has-CppTools)) {
    Invoke-Winget 'Microsoft.VisualStudio.2022.BuildTools' @('--override', '--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended')
}
if (-not (Has-CppTools)) { throw '未检测到 C++ 构建工具；请检查安装日志或重启后重试。' }
if (-not (Get-Command cargo.exe -ErrorAction SilentlyContinue)) { Invoke-Winget 'Rustlang.Rustup' @('--silent') }
if (-not (Get-Command cargo.exe -ErrorAction SilentlyContinue)) { throw '未检测到 Rust；请检查安装结果并重启终端。' }
if (-not (Has-WebView2)) { Invoke-Winget 'Microsoft.EdgeWebView2Runtime' @('--silent') }
if (-not (Has-WebView2)) { throw '未检测到 WebView2 Runtime；请检查安装结果后重试。' }
Write-Host '系统依赖检查通过。'
