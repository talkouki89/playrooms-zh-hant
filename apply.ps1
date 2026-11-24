# Playrooms 繁體中文漢化 — 一鍵套用 / 還原
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File apply.ps1
#   powershell -ExecutionPolicy Bypass -File apply.ps1 -GameDir "D:\SteamLibrary\steamapps\common\Playrooms"
#   powershell -ExecutionPolicy Bypass -File apply.ps1 -Restore          # 還原英文原版
#
# 需求：Windows 10/11、Python 3.10+（缺少 UnityPy 時會自動安裝）

param(
    [string]$GameDir = "",
    [switch]$Restore,
    [switch]$NoPause
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $MyInvocation.MyCommand.Path
$patch = Join-Path $repo "tools\patchlib.py"

function Write-Step($text) { Write-Host "==> $text" -ForegroundColor Cyan }
function Stop-Here($code) {
    if (-not $NoPause) { Read-Host "按 Enter 結束" }
    exit $code
}

function Find-Python {
    foreach ($cmd in @("py", "python", "python3")) {
        try {
            $ver = & $cmd --version 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3") { return $cmd }
        } catch { }
    }
    return $null
}

function Find-GameDir {
    $candidates = @()
    if ($env:ProgramFiles) { $candidates += Join-Path $env:ProgramFiles "Steam\steamapps\common\Playrooms" }
    if (${env:ProgramFiles(x86)}) { $candidates += Join-Path ${env:ProgramFiles(x86)} "Steam\steamapps\common\Playrooms" }
    foreach ($drive in "C", "D", "E", "F", "G", "H") {
        $candidates += "${drive}:\SteamLibrary\steamapps\common\Playrooms"
        $candidates += "${drive}:\Steam\steamapps\common\Playrooms"
        $candidates += "${drive}:\Games\Steam\steamapps\common\Playrooms"
    }
    foreach ($path in $candidates) {
        if (Test-Path (Join-Path $path "Playrooms.exe")) { return $path }
    }
    return $null
}

Write-Host "Playrooms 繁體中文漢化" -ForegroundColor White
Write-Host "-------------------------------"

if (-not $GameDir) { $GameDir = Find-GameDir }
if ((-not $GameDir -or -not (Test-Path (Join-Path $GameDir "Playrooms.exe"))) -and -not $NoPause) {
    $GameDir = (Read-Host "請輸入 Playrooms 安裝資料夾（含 Playrooms.exe）").Trim('"')
}
if (-not $GameDir -or -not (Test-Path (Join-Path $GameDir "Playrooms.exe"))) {
    Write-Host "找不到 Playrooms.exe，中止。" -ForegroundColor Red
    Stop-Here 1
}
Write-Step "遊戲資料夾：$GameDir"

$proc = Get-Process Playrooms -ErrorAction SilentlyContinue
if ($proc) {
    Write-Step "偵測到遊戲正在執行，先關閉遊戲"
    $proc | Stop-Process -Force
    Start-Sleep -Seconds 3
}

$python = Find-Python
if (-not $python) {
    Write-Host "找不到 Python 3，請先安裝：https://www.python.org/downloads/" -ForegroundColor Red
    Stop-Here 1
}
Write-Step "Python：$python"

& $python -c "import UnityPy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Step "安裝相依套件 UnityPy（需要網路）"
    & $python -m pip install --disable-pip-version-check UnityPy
    if ($LASTEXITCODE -ne 0) {
        Write-Host "UnityPy 安裝失敗，請手動執行：$python -m pip install UnityPy" -ForegroundColor Red
        Stop-Here 1
    }
}

if ($Restore) {
    Write-Step "還原英文原版"
    & $python $patch --repo $repo --game-dir $GameDir --restore
} else {
    Write-Step "套用繁體中文"
    & $python $patch --repo $repo --game-dir $GameDir
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "執行失敗，請把上方訊息貼到 GitHub Issues。" -ForegroundColor Red
    Stop-Here 1
}

Write-Host ""
Write-Host "完成！從 Steam 啟動遊戲即可看到繁體中文。" -ForegroundColor Green
Write-Host "原始檔案備份於 $repo\.backup（要還原請加 -Restore）"
if (-not $NoPause) { Read-Host "按 Enter 結束" }
