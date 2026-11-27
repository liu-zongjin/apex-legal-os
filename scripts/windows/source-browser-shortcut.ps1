function Get-SourceBrowserTarget {
    return (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe')
}

function Get-SourceBrowserArguments([string]$root) {
    $entry = Join-Path $root 'scripts\windows\source-install.ps1'
    return ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Action browser' -f $entry)
}

function Set-SourceBrowserShortcut($shell, [string]$path, [string]$root) {
    $shortcut = $shell.CreateShortcut($path)
    $target = Get-SourceBrowserTarget
    $arguments = Get-SourceBrowserArguments $root
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.IconLocation = (Join-Path $root 'windows-installer\src-tauri\icons\icon.ico') + ',0'
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = 'Stella 源码工作空间（浏览器）'
    $shortcut.Save()
}
