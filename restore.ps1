# 還原 Playrooms 英文原版（等於 apply.ps1 -Restore 的捷徑）
# 用法：powershell -ExecutionPolicy Bypass -File restore.ps1

param([string]$GameDir = "")

$apply = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "apply.ps1"
& $apply -GameDir $GameDir -Restore
