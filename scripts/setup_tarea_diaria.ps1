#Requires -Version 5.1
<#
.SYNOPSIS
    Registra la tarea programada "Bordagran Facturas Gmail Diario".
    Ejecutar UNA VEZ como administrador o como el usuario que tiene token.pickle.
#>

$ErrorActionPreference = "Stop"

$TaskName   = "Bordagran Facturas Gmail Diario"
$ProjectDir = "C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran"
$Script     = Join-Path $ProjectDir "scripts\run_facturas_diario.ps1"
$PsExe      = "powershell.exe"
$PsArgs     = "-NoProfile -ExecutionPolicy Bypass -File `"$Script`""

Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "  SETUP TAREA: $TaskName" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host ""

# Verificar que el script existe
if (-not (Test-Path $Script)) {
    Write-Host "[ERROR] No se encuentra: $Script" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Script encontrado: $Script" -ForegroundColor Green

# Accion
$Action = New-ScheduledTaskAction `
    -Execute  $PsExe `
    -Argument $PsArgs `
    -WorkingDirectory $ProjectDir

# Triggers: 09:00 y 20:00 diarios
$Trigger09 = New-ScheduledTaskTrigger -Daily -At "09:00"
$Trigger20 = New-ScheduledTaskTrigger -Daily -At "20:00"

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
    -RunOnlyIfNetworkAvailable:$false

# Registrar (o actualizar si ya existe)
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($ExistingTask) {
    Write-Host "[INFO] Tarea ya existe. Eliminando para recrear limpia..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "[OK] Tarea anterior eliminada" -ForegroundColor Green
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  @($Trigger09, $Trigger20) `
    -Settings $Settings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "[OK] Tarea creada: $TaskName" -ForegroundColor Green

# Verificar
$Task = Get-ScheduledTask -TaskName $TaskName
$Info = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host ""
Write-Host "  Estado    : $($Task.State)" -ForegroundColor White
Write-Host "  Triggers  : $($Task.Triggers.Count)" -ForegroundColor White
foreach ($t in $Task.Triggers) {
    Write-Host "    - $($t.CimClass.CimClassName): $($t.StartBoundary)" -ForegroundColor Gray
}
Write-Host "  Ultimo run: $($Info.LastRunTime)" -ForegroundColor White
Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Green
Write-Host "  TAREA REGISTRADA OK" -ForegroundColor Green
Write-Host ("=" * 60) -ForegroundColor Green
Write-Host ""
Write-Host "  Ejecutar ahora para probar:" -ForegroundColor Yellow
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'" -ForegroundColor White
Write-Host ""
