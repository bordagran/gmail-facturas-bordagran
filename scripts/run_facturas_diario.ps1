#Requires -Version 5.1
<#
.SYNOPSIS
    Ejecucion diaria automatizada de facturas Bordagran (Task Scheduler).

.DESCRIPTION
    Calcula fechas automaticamente (ultimos N dias -> hoy), ejecuta el
    proceso real y guarda log. Los duplicados son manejados por el script
    principal mediante hash/clave unica.

.PARAMETER Dias
    Dias hacia atras desde hoy. Default: 7.

.EXAMPLE
    .\scripts\run_facturas_diario.ps1
    .\scripts\run_facturas_diario.ps1 -Dias 14
#>

param(
    [int]$Dias = 7
)

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir      = Join-Path $ProjectRoot "runtime\logs"

if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

$Hasta = Get-Date -Format "yyyy-MM-dd"
$Desde = (Get-Date).AddDays(-$Dias).ToString("yyyy-MM-dd")

Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "  BORDAGRAN FACTURAS DIARIO - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "  Periodo : $Desde -> $Hasta ($Dias dias)"
Write-Host "  Modo    : REAL (automatico)"
Write-Host ""

& "$ScriptDir\run_facturas_bordagran.ps1" `
    -Desde $Desde `
    -Hasta $Hasta `
    -Real `
    -SinConfirmacion

$ExitCode = $LASTEXITCODE

Write-Host ""
Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "  FIN - $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host "  Exit: $ExitCode" -ForegroundColor $(if ($ExitCode -eq 0) { "Green" } else { "Red" })
Write-Host ("=" * 60) -ForegroundColor Cyan

exit $ExitCode
