# Assemble release artifacts into release-out/ with versioned file names.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools/package_release.ps1
#   powershell -ExecutionPolicy Bypass -File tools/package_release.ps1 -Version 1.1.0
#
# Produces:
#   release-out\CampusNet-<ver>-win64.zip        GUI + CLI executables
#   release-out\CampusNet-Android-<ver>.apk      signed release build
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI,
# which corrupts non-ASCII text and breaks parsing.

param([string]$Version = "")

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Version) {
    $init = Get-Content "src\campusnet\__init__.py" -Raw
    if ($init -match '__version__\s*=\s*"([^"]+)"') {
        $Version = $Matches[1]
    }
}
if (-not $Version) {
    throw "cannot determine version; pass -Version explicitly"
}
Write-Output ("version: " + $Version)

$out = Join-Path $root "release-out"
New-Item -ItemType Directory -Force -Path $out | Out-Null

# --- desktop ----------------------------------------------------------------
$exes = @("dist\CampusNet.exe", "dist\CampusNet-CLI.exe")
foreach ($e in $exes) {
    if (-not (Test-Path $e)) {
        throw ("missing " + $e + "; run tools/build.ps1 first")
    }
}

$zip = Join-Path $out ("CampusNet-" + $Version + "-win64.zip")
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $exes -DestinationPath $zip -CompressionLevel Optimal
Write-Output ("zip: " + $zip)

# --- android ----------------------------------------------------------------
$apkSrc = "android\app\build\outputs\apk\release\app-release.apk"
if (Test-Path $apkSrc) {
    $apk = Join-Path $out ("CampusNet-Android-" + $Version + ".apk")
    Copy-Item $apkSrc $apk -Force
    Write-Output ("apk: " + $apk)
} else {
    Write-Warning "release apk not found; run: cd android && gradlew assembleRelease"
}

Write-Output ""
Get-ChildItem $out | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
