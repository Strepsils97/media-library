# Ярлик на робочому столі.
#
# Окремим кроком, а не частиною збірки: класти щось на робочий стіл при
# кожній перезбірці — нав'язливо.

$ErrorActionPreference = 'Stop'

$exe = (Resolve-Path (Join-Path $PSScriptRoot '..\dist\media-library\media-library.exe')).Path
$desktop = [Environment]::GetFolderPath('Desktop')
$link = Join-Path $desktop 'media-library.lnk'

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = Split-Path $exe
$shortcut.Description = 'Локальна бібліотека медіа з семантичним пошуком'
$shortcut.IconLocation = "$exe,0"
$shortcut.Save()

Write-Output ('Ярлик: ' + $link)
Write-Output ('Ціль:  ' + $shell.CreateShortcut($link).TargetPath)
