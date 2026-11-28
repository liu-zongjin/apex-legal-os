param(
    [Parameter(Mandatory=$true)][string]$CurrentRoot,
    [Parameter(Mandatory=$true)][string]$ExpectedRevision,
    [switch]$BrowserMode
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path -LiteralPath $CurrentRoot).Path
$runtime = Join-Path $env:LOCALAPPDATA 'StellaSource'
$versions = Join-Path $env:LOCALAPPDATA 'StellaSourceVersions'
$desktop = [Environment]::GetFolderPath('DesktopDirectory')
$link = Join-Path $desktop 'Stella Source.lnk'
$shell = New-Object -ComObject WScript.Shell
$currentExe = Join-Path $root 'windows-installer\src-tauri\target\release\Stella.exe'
$currentArgs = '--source-root "' + $root + '"'
$installOptions = @()
$currentPython = Join-Path $root '.venv\Scripts\python.exe'
$browserShortcut = Join-Path $PSScriptRoot 'source_browser_shortcut.py'
if ($BrowserMode) {
    $link = Join-Path $desktop 'Stella Source (Browser).lnk'
    $installOptions += '-BrowserMode'
}
if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { throw '缺少 Git，请先安装官方 Git for Windows。' }
if ($ExpectedRevision -notmatch '^[0-9a-f]{40}$') { throw '目标源码版本无效。' }
if (-not (Test-Path -LiteralPath $link)) { throw '未找到源码版桌面快捷方式，请先检查现有安装。' }
if ($BrowserMode) {
    & $currentPython $browserShortcut verify $link --root $root
    if ($LASTEXITCODE -ne 0) { throw '未能验证当前浏览器快捷方式，未作修改。' }
    $stopLink = Join-Path $desktop '退出 Stella.lnk'
    if (Test-Path -LiteralPath $stopLink) {
        & $currentPython $browserShortcut verify $stopLink --root $root --stop
        if ($LASTEXITCODE -ne 0) { throw '退出快捷方式属于其他安装，未作修改。' }
    }
} else {
    $oldShortcut = $shell.CreateShortcut($link)
    if ($oldShortcut.TargetPath -ne $currentExe -or $oldShortcut.Arguments -ne $currentArgs) {
        throw '桌面快捷方式不属于当前源码安装，未作修改。'
    }
}
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
New-Item -ItemType Directory -Path $versions -Force | Out-Null
$lock = [System.IO.File]::Open((Join-Path $runtime 'source.lock'), [System.IO.FileMode]::OpenOrCreate,
    [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::ReadWrite)
try {
    try { $lock.Lock(0, 1) } catch { throw '请先关闭 Stella，等待后台完成保存后再更新。' }
    $folder = Join-Path $versions ('candidate-' + [guid]::NewGuid().ToString('N'))
    Write-Host '正在下载官方主分支源码到独立目录；旧版本和用户资料会保留。'
    & git.exe clone --depth 1 --branch main --single-branch https://github.com/liu-zongjin/apex-legal-os.git $folder
    if ($LASTEXITCODE -ne 0) { throw "下载失败；旧版本未变。候选目录：$folder" }
    $downloadedRevision = (& git.exe -C $folder rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $downloadedRevision -ne $ExpectedRevision) { throw '下载期间源码版本发生变化，请重新检查更新。旧版本未变。' }
    $installer = Join-Path $folder 'scripts\windows\source-install.ps1'
    if (-not (Test-Path $installer)) { throw '新源码不包含兼容的源码安装脚本，旧版本未变。' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -Action install @installOptions
    if ($LASTEXITCODE -ne 0) { throw '新版本依赖准备失败，旧版本未变。' }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -Action diagnose
    if ($LASTEXITCODE -ne 0) { throw '新版本依赖检查失败，旧版本未变。' }
    $newExe = Join-Path $folder 'windows-installer\src-tauri\target\release\Stella.exe'
    if (-not $BrowserMode) {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer -Action client -BuildOnly
        if ($LASTEXITCODE -ne 0) { throw '新版本编译失败，旧版本未变。' }
        if (-not (Test-Path $newExe)) { throw '新客户端不存在，旧版本未变。' }
    }
    & $currentPython (Join-Path $PSScriptRoot 'source-update-smoke.py') $folder
    if ($LASTEXITCODE -ne 0) { throw '新版本启动检查失败，旧版本未变。' }
    $storage = Join-Path $PSScriptRoot 'source_storage.py'
    try {
        & (Join-Path $root '.venv\Scripts\python.exe') $storage record --versions $versions --runtime $runtime --current (Split-Path -Leaf $folder)
        if ($LASTEXITCODE -ne 0) { Write-Warning '无法记录新环境，后续将保留该环境。' }
    } catch { Write-Warning '无法记录新环境，后续将保留该环境。' }
    $backup = Join-Path $runtime ('shortcut-before-update-' + [guid]::NewGuid().ToString('N') + '.lnk')
    Copy-Item -LiteralPath $link -Destination $backup
    $tempLink = Join-Path $desktop ('.Stella-update-' + [guid]::NewGuid().ToString('N') + '.lnk')
    if ($BrowserMode) {
        & $currentPython (Join-Path $folder 'scripts\windows\source_browser_shortcut.py') create $tempLink --root $folder
        if ($LASTEXITCODE -ne 0) { throw '未能创建候选浏览器快捷方式，旧版本未变。' }
        $tempStopLink = Join-Path $desktop ('.Stella-stop-' + [guid]::NewGuid().ToString('N') + '.lnk')
        & $currentPython (Join-Path $folder 'scripts\windows\source_browser_shortcut.py') create $tempStopLink --root $folder --stop
        if ($LASTEXITCODE -ne 0) { throw '未能创建退出快捷方式，旧版本未变。' }
    } else {
        $next = $shell.CreateShortcut($tempLink)
        $next.TargetPath = $newExe
        $next.IconLocation = $newExe + ',0'
        $next.Arguments = '--source-root "' + $folder + '"'
        $next.WorkingDirectory = $folder
        $next.Description = 'Stella 源码工作空间'
        $next.Save()
    }
    Move-Item -LiteralPath $tempLink -Destination $link -Force
    if ($BrowserMode) { Move-Item -LiteralPath $tempStopLink -Destination $stopLink -Force }
    try {
        & (Join-Path $root '.venv\Scripts\python.exe') $storage prune --versions $versions --runtime $runtime --current (Split-Path -Leaf $folder) --previous (Split-Path -Leaf $root)
        if ($LASTEXITCODE -ne 0) { Write-Warning '旧环境检查未完成，已保留剩余文件。' }
    } catch { Write-Warning '旧环境检查未完成，已保留剩余文件。' }
    Write-Host "更新已准备完成。请打开桌面快捷方式：$link。旧入口备份：$backup"
    Write-Host '首次启动会在迁移前备份数据库；若启动失败，请保留资料并查看诊断日志。'
} finally {
    try { $lock.Unlock(0, 1) } catch {}
    $lock.Dispose()
}
