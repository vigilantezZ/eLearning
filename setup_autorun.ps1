# ========================================================================
#   BMP CBT Tryout - Windows Task Scheduler Auto-Run Setup (PowerShell)
# ========================================================================

# 1. Check for Administrator privileges and elevate if needed
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "Meminta hak akses Administrator (UAC elevation)..." -ForegroundColor Yellow
    Start-Process powershell.exe -Verb RunAs -ArgumentList ("-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"")
    Exit
}

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "   MEMASANG AUTO-RUN STARTUP BMP CBT TRYOUT (TASK SCHEDULER)" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# 2. Locate BMPTryout.exe
$ExePath = $null
$WorkDir = $null

if (Test-Path "$ScriptDir\BMPTryout.exe") {
    $ExePath = "$ScriptDir\BMPTryout.exe"
    $WorkDir = "$ScriptDir"
} elseif (Test-Path "$ScriptDir\dist\BMPTryout.exe") {
    $ExePath = "$ScriptDir\dist\BMPTryout.exe"
    $WorkDir = "$ScriptDir\dist"
} elseif (Test-Path "C:\PROJECT\Production\eLearning\BMPTryout.exe") {
    $ExePath = "C:\PROJECT\Production\eLearning\BMPTryout.exe"
    $WorkDir = "C:\PROJECT\Production\eLearning"
} else {
    Write-Host "[ERROR] File BMPTryout.exe tidak ditemukan!" -ForegroundColor Red
    Write-Host "Pastikan file BMPTryout.exe berada di folder ini." -ForegroundColor Red
    Write-Host ""
    Read-Host "Tekan Enter untuk keluar..."
    Exit 1
}

Write-Host "[+] Executable Path : $ExePath" -ForegroundColor Green
Write-Host "[+] Working Directory: $WorkDir" -ForegroundColor Green
Write-Host ""

# 3. Create Scheduled Task components
$action = New-ScheduledTaskAction -Execute "$ExePath" -WorkingDirectory "$WorkDir"

# Trigger 1: At Startup (Boot) with 10s delay
$triggerBoot = New-ScheduledTaskTrigger -AtStartup
$triggerBoot.Delay = "PT10S"

# Trigger 2: At Logon
$triggerLogon = New-ScheduledTaskTrigger -AtLogOn

# Principal: SYSTEM with Highest Privileges
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest

# Settings: Allow on battery, auto-restart on fail, no time limit
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval ([TimeSpan]::FromMinutes(1)) -ExecutionTimeLimit ([TimeSpan]::Zero)

# 4. Unregister existing and Register new task
Unregister-ScheduledTask -TaskName "BMPTryout" -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName "BMPTryout" `
    -Action $action `
    -Trigger @($triggerBoot, $triggerLogon) `
    -Principal $principal `
    -Settings $settings `
    -Description "BMP CBT Tryout Standalone WSGI Production Server" `
    -Force | Out-Null

Write-Host "================================================================" -ForegroundColor Green
Write-Host " [BERHASIL] Task Scheduler 'BMPTryout' telah terpasang!" -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host " Aplikasi akan OTOMATIS BERJALAN saat Windows dinyalakan/reboot." -ForegroundColor White
Write-Host ""
Write-Host " Menjalankan service sekarang..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName "BMPTryout"
Start-Sleep -Seconds 2

Write-Host ""
Write-Host " [OK] Service sedang berjalan." -ForegroundColor Green
Write-Host " Akses di Browser: http://localhost:5000" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Tekan Enter untuk menutup jendela ini..."
