# Build the two executables (GUI + CLI) with PyInstaller.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/build.ps1
#   powershell -ExecutionPolicy Bypass -File tools/build.ps1 -Python "D:\Python\python.exe"
#
# Produces:
#   dist\CampusNet.exe       - GUI, no console window, double-click to run
#   dist\CampusNet-CLI.exe   - console build for scripts (status/login/logout/...)
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI,
# which corrupts non-ASCII text and breaks parsing.

param([string]$Python = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- find an interpreter that has PyInstaller installed -----------------------
# A plain "python" may resolve to a different install than the one you set up
# (``powershell -File`` does not load your profile), so probe a few candidates.
function Test-Python {
    param([string]$Exe, [string[]]$Pre)
    try {
        & $Exe @Pre -c "import PyInstaller" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$candidates = @()
if ($Python) { $candidates += , @($Python) }
if ($env:CAMPUSNET_PYTHON) { $candidates += , @($env:CAMPUSNET_PYTHON) }
$candidates += , @("python")
$candidates += , @("py", "-3.10")
$candidates += , @("py", "-3.11")
$candidates += , @("py", "-3.12")
$candidates += , @("py", "-3")

$found = $null
foreach ($cand in $candidates) {
    $exe = $cand[0]
    $rest = @()
    if ($cand.Count -gt 1) { $rest = $cand[1..($cand.Count - 1)] }
    $label = ($cand -join " ")
    if (Test-Python $exe $rest) {
        $found = $cand
        break
    }
    Write-Output ("  (skip) $label - no PyInstaller")
}
if (-not $found) {
    throw "no interpreter with PyInstaller found. Install it first: python -m pip install pyinstaller"
}

$pyExe = $found[0]
$pyPre = @()
if ($found.Count -gt 1) { $pyPre = $found[1..($found.Count - 1)] }
Write-Output ("using interpreter: " + $pyExe + " " + ($pyPre -join " "))

$icon = "assets\campusnet.ico"
$data = "src\campusnet\data\error_codes.json;campusnet\data"
$assets = "assets;assets"

Write-Output "== 1/3 generating icon =="
& $pyExe @pyPre tools\make_icon.py

Write-Output "== 2/3 building GUI (windowed) =="
& $pyExe @pyPre -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name CampusNet `
    --icon $icon `
    --paths src `
    --add-data $data `
    --add-data $assets `
    --exclude-module pytest `
    run_gui.pyw

Write-Output "== 3/3 building CLI (console) =="
& $pyExe @pyPre -m PyInstaller --noconfirm --onefile --console `
    --name CampusNet-CLI `
    --icon $icon `
    --paths src `
    --add-data $data `
    --add-data $assets `
    --exclude-module pytest `
    run_cli.py

Write-Output ""
Write-Output "== done =="
Get-ChildItem dist | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
