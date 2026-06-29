#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Raiz = "C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran"
Set-Location $Raiz

Write-Host ""
Write-Host ("=" * 65) -ForegroundColor Cyan
Write-Host "  BORDAGRAN AUTOMATIZACION COMPLETA" -ForegroundColor Cyan
Write-Host ("=" * 65) -ForegroundColor Cyan

# 1. Validaciones
Write-Host ""
Write-Host "[1/6] Validaciones..." -ForegroundColor Yellow
python -m py_compile scripts\procesar_facturas.py
Write-Host "  py_compile OK" -ForegroundColor Green

[void][System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts\run_facturas_bordagran.ps1'), [ref]$null)
Write-Host "  run_facturas_bordagran.ps1 OK" -ForegroundColor Green

[void][System.Management.Automation.PSParser]::Tokenize((Get-Content -Raw 'scripts\run_facturas_diario.ps1'), [ref]$null)
Write-Host "  run_facturas_diario.ps1 OK" -ForegroundColor Green

# 2. Git status
Write-Host ""
Write-Host "[2/6] Git status..." -ForegroundColor Yellow
git status --short

# 3. Crear tarea programada
Write-Host ""
Write-Host "[3/6] Registrando tarea programada..." -ForegroundColor Yellow

$TaskName   = "Bordagran Facturas Gmail Diario"
$Script     = Join-Path $Raiz "scripts\run_facturas_diario.ps1"
$Action     = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" -WorkingDirectory $Raiz
$Trigger09  = New-ScheduledTaskTrigger -Daily -At "09:00"
$Trigger20  = New-ScheduledTaskTrigger -Daily -At "20:00"
$Settings   = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "  Tarea anterior eliminada" -ForegroundColor Gray
}
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($Trigger09, $Trigger20) -Settings $Settings -RunLevel Highest -Force | Out-Null
Write-Host "  Tarea creada: $TaskName" -ForegroundColor Green

$Task = Get-ScheduledTask -TaskName $TaskName
Write-Host "  Triggers: $($Task.Triggers.Count)" -ForegroundColor White
$Task.Triggers | ForEach-Object { Write-Host "    - $($_.StartBoundary)" -ForegroundColor Gray }

# 4. Prueba manual (dry-run via run_facturas_bordagran.ps1)
Write-Host ""
Write-Host "[4/6] Prueba manual dry-run (5 dias recientes)..." -ForegroundColor Yellow
$Desde = (Get-Date).AddDays(-5).ToString("yyyy-MM-dd")
$Hasta = (Get-Date -Format "yyyy-MM-dd")
Write-Host "  Periodo: $Desde -> $Hasta" -ForegroundColor Gray

& ".\scripts\run_facturas_bordagran.ps1" -Desde $Desde -Hasta $Hasta -SinConfirmacion -Forzar
$ExitDry = $LASTEXITCODE
Write-Host "  Exit code dry-run: $ExitDry" -ForegroundColor $(if ($ExitDry -eq 0) {"Green"} else {"Red"})

# 5. Git commit
Write-Host ""
Write-Host "[5/6] Git commit..." -ForegroundColor Yellow

git add scripts\run_facturas_bordagran.ps1 scripts\run_facturas_diario.ps1 scripts\setup_tarea_diaria.ps1 scripts\procesar_facturas.py references\proveedores.json scripts\alta_digi_maestro.py CLAUDE.md LECCIONES_APRENDIDAS.md SKILL.md

git status --short
git commit -m "feat: automatizar procesamiento fiscal diario Windows + DIGI fix (L-064)"

git tag -a v3.4.5-automatizacion-diaria-estable -m "Automatizacion diaria fiscal Bordagran estable v3.4.5" --force

git log --oneline --decorate -3

# 6. Push
Write-Host ""
Write-Host "[6/6] Push..." -ForegroundColor Yellow
git push origin main
git push origin v3.4.5-automatizacion-diaria-estable

# Resumen final
Write-Host ""
Write-Host ("=" * 65) -ForegroundColor Green
Write-Host "  COMPLETADO" -ForegroundColor Green
Write-Host ("=" * 65) -ForegroundColor Green
Write-Host ""
Write-Host "  Tarea programada: $TaskName" -ForegroundColor White
Write-Host "  Horarios: 09:00 y 20:00 diarios" -ForegroundColor White
Write-Host ""
Write-Host "  Logs en: $Raiz\runtime\logs\" -ForegroundColor White
Write-Host ""
Get-ChildItem "$Raiz\runtime\logs" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 3 | ForEach-Object { Write-Host "  $($_.Name)" -ForegroundColor Gray }
Write-Host ""
