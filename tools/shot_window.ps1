# Capture a single window by title (avoids capturing the rest of the desktop).
# Usage: powershell -File tools/shot_window.ps1 -Title "..." -Out "C:\path\shot.png"
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI
# unless a BOM is present, which corrupts non-ASCII comments and breaks parsing.
param(
    [string]$Title = "CampusNet",
    [string]$Out = "window.png",
    [int]$ProcessId = 0
)

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern IntPtr FindWindow(string cls, string name);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

if ($ProcessId -gt 0) {
    # By PID: avoids passing non-ASCII window titles through the command line,
    # which gets mangled by the console code page.
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) { Write-Error "process not found: $ProcessId"; exit 1 }
    $h = $proc.MainWindowHandle
} else {
    $h = [Win32]::FindWindow($null, $Title)
}
if ($h -eq [IntPtr]::Zero) { Write-Error "window not found"; exit 1 }
[void][Win32]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 500

$rect = New-Object Win32+RECT
[void][Win32]::GetWindowRect($h, [ref]$rect)
$w = $rect.Right - $rect.Left
$hgt = $rect.Bottom - $rect.Top
if ($w -le 0 -or $hgt -le 0) { Write-Error "bad window rect"; exit 1 }

$bmp = New-Object System.Drawing.Bitmap $w, $hgt
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $hgt))
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out ($w x $hgt)"
