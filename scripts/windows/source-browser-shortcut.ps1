function Get-SourceBrowserArguments([string]$root, [string]$runtime) {
    $entry = Join-Path $root 'scripts\windows\source_server.py'
    return ('"{0}" --runtime "{1}" --open-browser' -f $entry, $runtime)
}

function Set-SourceBrowserShortcut($shell, [string]$path, [string]$root, [string]$runtime) {
    $shortcut = $shell.CreateShortcut($path)
    $shortcut.TargetPath = Join-Path $root '.venv\Scripts\python.exe'
    $shortcut.Arguments = Get-SourceBrowserArguments $root $runtime
    $shortcut.IconLocation = (Join-Path $root 'windows-installer\src-tauri\icons\icon.ico') + ',0'
    $shortcut.WorkingDirectory = $root
    $shortcut.Description = 'Stella 源码工作空间（浏览器）'
    $shortcut.Save()
}
