# Capture a single window by title (avoids capturing the rest of the desktop).
# Usage: powershell -File tools/shot_window.ps1 -Title "..." -Out "C:\path\shot.png"
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 reads .ps1 as ANSI
# unless a BOM is present, which corrupts non-ASCII comments and breaks parsing.
param(
    [string]$Title = "CampusNet",
    [string]$Out = "window.png",
    [int]$ProcessId = 0,
    [int]$Index = -1,
    [switch]$List
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
    [DllImport("user32.dll")]
    public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern IntPtr FindWindowEx(IntPtr parent, IntPtr after, string cls, string title);
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder text, int max);
    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@

if ($ProcessId -gt 0 -and $Index -ge 0) {
    # 枚举该进程的所有可见顶层窗口，按 Z 序取第 Index 个（用于截取对话框）
    $wins = @()
    $cur = [IntPtr]::Zero
    $nullStr = [NullString]::Value      # 必须是真正的 NULL，传 $null 会被转成空串
    while ($true) {
        $cur = [Win32]::FindWindowEx([IntPtr]::Zero, $cur, $nullStr, $nullStr)
        if ($cur -eq [IntPtr]::Zero) { break }
        $wpid = 0
        [void][Win32]::GetWindowThreadProcessId($cur, [ref]$wpid)
        if ($wpid -eq $ProcessId -and [Win32]::IsWindowVisible($cur)) {
            $wins += , $cur
        }
    }
    if ($List) {
        for ($i = 0; $i -lt $wins.Count; $i++) {
            $sb = New-Object System.Text.StringBuilder 256
            [void][Win32]::GetWindowText($wins[$i], $sb, 256)
            Write-Output ("[{0}] handle={1} titleLen={2}" -f $i, $wins[$i], $sb.Length)
        }
    }
    if ($Index -ge $wins.Count) { Write-Error "index out of range ($($wins.Count) windows)"; exit 1 }
    $h = $wins[$Index]
} elseif ($ProcessId -gt 0) {
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

# PrintWindow 直接把窗口画进内存，不受其它窗口遮挡影响；
# 失败时退回屏幕截取（可能被遮住）。
[IntPtr]$hdc = [IntPtr]::Zero
$ok = $false
try {
    $hdc = $g.GetHdc()
    if ($hdc -ne [IntPtr]::Zero) {
        $ok = [Win32]::PrintWindow($h, $hdc, 2)   # 2 = PW_RENDERFULLCONTENT
    }
} finally {
    if ($hdc -ne [IntPtr]::Zero) { $g.ReleaseHdc($hdc) }
}
if (-not $ok) {
    Write-Output "PrintWindow unavailable, falling back to screen capture"
    $g.CopyFromScreen($rect.Left, $rect.Top, 0, 0, (New-Object System.Drawing.Size $w, $hgt))
}
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
Write-Output "saved $Out ($w x $hgt)"
