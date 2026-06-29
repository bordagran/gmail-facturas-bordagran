#Requires -Version 5.1
<#
.SYNOPSIS
    Lanzador principal de facturas Bordagran Gmail -> Sheets.

.DESCRIPTION
    Gestiona: verificacion git, lock, dry-run / proceso real, log y resumen.
    Por defecto siempre es DRY-RUN. Pasar -Real para escribir en Sheets.

.PARAMETER Desde
    Fecha inicio YYYY-MM-DD. Ejemplo: 2026-06-01

.PARAMETER Hasta
    Fecha fin YYYY-MM-DD. Ejemplo: 2026-06-30

.PARAMETER Real
    Ejecuta el proceso real (escribe en Drive y Sheets).
    Sin este flag siempre es dry-run.

.PARAMETER Proveedor
    Filtrar por proveedor (ej: DIGI, Radiokable, Velilla).
    Solo procesa emails del proveedor indicado; el resto se omite (pass --proveedor a Python).

.PARAMETER Forzar
    Pasar --forzar a procesar_facturas.py para ignorar el lock file.
    Usar solo si no hay proceso Python activo.

.PARAMETER SinConfirmacion
    Omitir confirmacion interactiva antes del modo real. Para automatizacion.

.EXAMPLE
    .\scripts\run_facturas_bordagran.ps1 -Desde 2026-06-01 -Hasta 2026-06-30
    .\scripts\run_facturas_bordagran.ps1 -Desde 2026-06-01 -Hasta 2026-06-30 -Proveedor DIGI
    .\scripts\run_facturas_bordagran.ps1 -Desde 2026-06-01 -Hasta 2026-06-30 -Proveedor DIGI -Forzar
    .\scripts\run_facturas_bordagran.ps1 -Desde 2026-06-01 -Hasta 2026-06-30 -Real
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$Desde,

    [Parameter(Mandatory=$true)]
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')]
    [string]$Hasta,

    [switch]$Real,

    [string]$Proveedor = "",

    [switch]$Forzar,

    [switch]$SinConfirmacion
)

$ErrorActionPreference = "Stop"

# --- Rutas ---
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$LogDir      = Join-Path $ProjectRoot "runtime\logs"
$PyScript    = Join-Path $ProjectRoot "scripts\procesar_facturas.py"
$LockFile    = Join-Path $ProjectRoot "runtime\procesar_facturas.lock"
$TagEstable  = "v3.4.4-main-estable"

$Timestamp   = Get-Date -Format "yyyyMMdd_HHmmss"
$Modo        = if ($Real) { "REAL" } else { "DRY-RUN" }
$LogFile     = Join-Path $LogDir "facturas_${Timestamp}_${Modo}.log"

# --- Funciones ---
function Write-Sep  {
    param([string]$Color = "Cyan")
    Write-Host ("=" * 60) -ForegroundColor $Color
}
function Write-OK   { param([string]$T) Write-Host "[OK]    $T" -ForegroundColor Green }
function Write-Warn { param([string]$T) Write-Host "[WARN]  $T" -ForegroundColor Yellow }
function Write-Fail { param([string]$T) Write-Host "[ERROR] $T" -ForegroundColor Red }
function Write-Info { param([string]$T) Write-Host "[INFO]  $T" -ForegroundColor Cyan }
function Write-Step { param([string]$T) Write-Host "" ; Write-Host "[PASO]  $T" -ForegroundColor Yellow }

function Count-Lines {
    param($Lines)
    return @($Lines).Count
}

# --- Banner ---
$ColorModo = if ($Real) { "Red" } else { "Cyan" }
Write-Sep $ColorModo
Write-Host "  BORDAGRAN FISCAL - $Modo - $(Get-Date -Format 'yyyy-MM-dd HH:mm')" -ForegroundColor $ColorModo
Write-Sep $ColorModo
Write-Host "  Periodo  : $Desde -> $Hasta"
Write-Host "  Modo     : $Modo" -ForegroundColor $ColorModo
if ($Proveedor) { Write-Host "  Filtro   : $Proveedor" -ForegroundColor Magenta }
if ($Forzar)    { Write-Host "  Forzar   : SI (ignora lock)" -ForegroundColor Yellow }
Write-Host "  Log      : $LogFile" -ForegroundColor DarkGray

# --- Crear carpeta de logs ---
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    Write-OK "Carpeta runtime\logs creada"
}

# Cabecera log
@"
=== BORDAGRAN FISCAL LOG ===
Fecha   : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Periodo : $Desde - $Hasta
Modo    : $Modo
Filtro  : $Proveedor
Forzar  : $Forzar

"@ | Out-File -FilePath $LogFile -Encoding UTF8

# --- PASO 1: Directorio ---
Write-Step "Verificando directorio"
Set-Location $ProjectRoot
Write-OK "Directorio: $ProjectRoot"

# --- PASO 2: Rama main ---
Write-Step "Verificando rama Git"
try {
    $Branch = & git rev-parse --abbrev-ref HEAD 2>&1
    if ($Branch -ne "main") {
        Write-Warn "Rama: $Branch - cambiando a main"
        & git switch main 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Fail "No se puede cambiar a main"; exit 1 }
    }
    Write-OK "Rama: main"
} catch {
    Write-Warn "No se pudo verificar rama git: $_"
}

# --- PASO 3: git pull ---
Write-Step "Actualizando desde origin/main"
try {
    & git pull origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "Repositorio actualizado"
    } else {
        Write-Warn "git pull fallo - usando version local"
    }
} catch {
    Write-Warn "git pull no disponible"
}

# --- PASO 4: HEAD ---
try {
    $GitHead = & git log --oneline --decorate -1 2>&1
    Write-OK "HEAD: $GitHead"
    "HEAD: $GitHead" | Out-File -FilePath $LogFile -Append -Encoding UTF8
} catch {}

# --- PASO 5: git status ---
Write-Step "Estado del repositorio"
try {
    $GitStatus = @(& git status --short 2>&1)
    $ModFuera = @($GitStatus | Where-Object { $_ -match "^\s*(M|AM)" -and $_ -notmatch "runtime/" -and $_ -notmatch "scripts/run_" })
    if (@($ModFuera).Count -gt 0) {
        Write-Warn "Archivos modificados fuera de runtime:"
        $ModFuera | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkYellow }
    } else {
        Write-OK "Repositorio limpio"
    }
} catch {
    Write-Warn "No se pudo leer git status"
}

# --- PASO 6: py_compile ---
Write-Step "Validando sintaxis de procesar_facturas.py"
if (-not (Test-Path $PyScript)) {
    Write-Fail "No existe: $PyScript"
    exit 1
}
python -m py_compile $PyScript 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Fail "SyntaxError en procesar_facturas.py"
    Write-Host "  Restaurando desde $TagEstable ..." -ForegroundColor Yellow
    & git checkout $TagEstable -- scripts\procesar_facturas.py 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "No se pudo restaurar. Abortando."; exit 1 }
    python -m py_compile $PyScript 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Fail "El tag tiene errores. Contactar soporte."; exit 1 }
    Write-OK "Restaurado desde $TagEstable"
} else {
    Write-OK "Sintaxis OK"
}

# --- PASO 7: Parser DIGI ---
$HasDigi = $false
try {
    $HasDigi = [bool](Select-String -Path $PyScript -Pattern "_extraer_datos_digi" -Quiet)
} catch {}
if ($HasDigi) {
    Write-OK "Parser DIGI presente en el script"
} else {
    Write-Warn "Parser DIGI NO encontrado - DIGI puede no ser reconocido"
}

# --- PASO 8: Verificar y limpiar lock file ---
Write-Step "Verificando lock file"
if (Test-Path $LockFile) {
    $LockContent = ""
    try { $LockContent = Get-Content $LockFile -ErrorAction SilentlyContinue } catch {}

    $ProcPython = @(Get-Process python -ErrorAction SilentlyContinue)
    if (@($ProcPython).Count -gt 0) {
        Write-Warn "Lock existe ($LockContent) y hay proceso Python activo"
        Write-Host "  PID(s): $($ProcPython.Id -join ', ')" -ForegroundColor Yellow
        if (-not $Forzar) {
            Write-Fail "Abortando. Usa -Forzar para ignorar el lock si el proceso esta colgado."
            exit 1
        } else {
            Write-Warn "-Forzar activado: ignorando lock (Python activo puede quedar en estado incompleto)"
        }
    } else {
        Write-Warn "Lock encontrado ($LockContent) pero sin proceso Python activo"
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
        Write-OK "Lock obsoleto eliminado"
    }
} else {
    Write-OK "Sin lock activo"
}

# --- PASO 9: Confirmacion modo real ---
if ($Real -and -not $SinConfirmacion) {
    Write-Host ""
    Write-Sep "Red"
    Write-Host "  [REAL] Se escribira en Google Sheets y Google Drive" -ForegroundColor Red
    Write-Host "  Periodo: $Desde -> $Hasta" -ForegroundColor Red
    Write-Sep "Red"
    Write-Host "  Presiona ENTER para continuar o CTRL+C para cancelar..." -ForegroundColor Yellow
    Read-Host | Out-Null
}

# --- PASO 10: Construir argumentos Python ---
Write-Step "Preparando argumentos"
$PythonArgs = [System.Collections.Generic.List[string]]@(
    $PyScript,
    "--modo", "backfill",
    "--desde", $Desde,
    "--hasta", $Hasta,
    "--skill-dir", $ProjectRoot
)
if (-not $Real) {
    $PythonArgs.Add("--dry-run")
    Write-OK "DRY-RUN activado (sin escritura en Sheets ni Drive)"
} else {
    Write-OK "Modo REAL activado"
}
if ($Forzar) {
    $PythonArgs.Add("--forzar")
    Write-OK "--forzar pasado a Python"
}
if ($Proveedor -ne "") {
    $PythonArgs.Add("--proveedor")
    $PythonArgs.Add($Proveedor)
    Write-OK "--proveedor $Proveedor pasado a Python (solo procesara ese proveedor)"
}

# --- PASO 11: Ejecutar ---
Write-Sep "White"
Write-Host "  EJECUTANDO - $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor White
Write-Sep "White"
Write-Host ""

$ExitCode = 0
$RawOutput = [System.Collections.Generic.List[string]]@()

try {
    python @PythonArgs 2>&1 | ForEach-Object {
        $Line = "$_"
        Write-Host $Line
        $RawOutput.Add($Line)
        $Line | Out-File -FilePath $LogFile -Append -Encoding UTF8
    }
    $ExitCode = $LASTEXITCODE
} catch {
    Write-Fail "Error al ejecutar Python: $_"
    $ExitCode = 1
}

# --- PASO 12: Resumen ---
Write-Host ""
Write-Sep "Cyan"
Write-Host "  RESUMEN - $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Cyan
Write-Sep "Cyan"
Write-Host ""
Write-Info "ExitCode : $ExitCode"
Write-Info "Log      : $LogFile"
Write-Info "Lineas   : $(@($RawOutput).Count)"
Write-Host ""

# Leer log para contadores (siempre desde array, nunca .Count directo sobre Select-String)
$LogLines = @()
if (Test-Path $LogFile) {
    try {
        $LogLines = @(Get-Content $LogFile -Encoding UTF8 -ErrorAction SilentlyContinue)
    } catch {
        $LogLines = @()
    }
}

# Contadores robustos con @()
if ($Real) {
    $cProcesados = @($LogLines | Select-String "Registrado\s*\|").Count
} else {
    $cProcesados = @($LogLines | Select-String "\[DRY-RUN\].*Habria insertado").Count
}
$cDuplicados = @($LogLines | Select-String "DUPLICADO").Count
$cPendientes = @($LogLines | Select-String "PENDIENTE").Count
$cRevisiones = @($LogLines | Select-String "\bRevisar\b").Count
$cErrores    = @($LogLines | Select-String "ERROR|Exception|Traceback").Count

Write-Host ("  {0,-30} {1}" -f "Facturas procesadas:", $cProcesados) `
    -ForegroundColor $(if ($cProcesados -gt 0) { "Green" } else { "White" })
Write-Host ("  {0,-30} {1}" -f "Duplicados:", $cDuplicados) `
    -ForegroundColor $(if ($cDuplicados -gt 0) { "Yellow" } else { "White" })
Write-Host ("  {0,-30} {1}" -f "Pendientes de revision:", $cPendientes) `
    -ForegroundColor $(if ($cPendientes -gt 0) { "Yellow" } else { "White" })
Write-Host ("  {0,-30} {1}" -f "Estado Revisar:", $cRevisiones) `
    -ForegroundColor $(if ($cRevisiones -gt 0) { "Yellow" } else { "White" })
Write-Host ("  {0,-30} {1}" -f "Errores:", $cErrores) `
    -ForegroundColor $(if ($cErrores -gt 0) { "Red" } else { "White" })

# --- Detalle DIGI ---
$DigiLines = @($LogLines | Select-String "DIGI|DGFC|digimobil" |
    Select-Object -ExpandProperty Line)

if (@($DigiLines).Count -gt 0) {
    Write-Host ""
    Write-Host "  [DIGI] Spain Telecom / digimobil.es" -ForegroundColor Magenta
    $DigiLines | Select-Object -Unique | ForEach-Object {
        Write-Host "    $_" -ForegroundColor Magenta
    }

    $NumFact = $null
    foreach ($ln in $DigiLines) {
        $m = [regex]::Match($ln, "DGFC\d{7,}")
        if ($m.Success) { $NumFact = $m.Value; break }
    }

    $InsercionLines = @($DigiLines | Where-Object { $_ -match "Habria insertado|Registrado" })
    Write-Host ""
    if ($NumFact) {
        Write-Host "    Numero factura : $NumFact" -ForegroundColor Green
    }
    if (@($InsercionLines).Count -gt 0) {
        if ($Real) {
            Write-Host "    [OK] INSERTADO en Google Sheets" -ForegroundColor Green
        } else {
            Write-Host "    [OK] Seria insertado - dry-run correcto -> listo para -Real" -ForegroundColor Green
        }
    } else {
        Write-Host "    [WARN] DIGI detectado en log pero sin insercion confirmada" -ForegroundColor Yellow
        Write-Host "    Revisar log completo: $LogFile" -ForegroundColor DarkGray
    }
} else {
    Write-Host ""
    if ($Proveedor -ieq "DIGI") {
        Write-Warn "No se encontraron lineas DIGI en el periodo $Desde - $Hasta"
        Write-Host "    Causas posibles:" -ForegroundColor DarkYellow
        Write-Host "      1. No hay emails de digimobil.es en ese periodo (revisar Gmail)" -ForegroundColor DarkYellow
        Write-Host "      2. El email vino de otro remitente" -ForegroundColor DarkYellow
        Write-Host "      3. El PDF no esta adjunto (viene como enlace)" -ForegroundColor DarkYellow
        Write-Host "      4. Ya existe en Sheet (duplicado prevenido)" -ForegroundColor DarkYellow
    }
}

# --- Filtro proveedor generico ---
if ($Proveedor -and $Proveedor -notmatch "^DIGI$") {
    Write-Host ""
    Write-Host "  [FILTRO] $Proveedor" -ForegroundColor Magenta
    $FiltLines = @($LogLines | Select-String $Proveedor | Select-Object -ExpandProperty Line)
    if (@($FiltLines).Count -gt 0) {
        $FiltLines | Select-Object -Unique | ForEach-Object {
            Write-Host "    $_" -ForegroundColor Magenta
        }
    } else {
        Write-Warn "Sin lineas que contengan '$Proveedor' en el log"
    }
}

# --- Pie final ---
Write-Host ""
Write-Host "  Log completo: $LogFile" -ForegroundColor DarkGray
Write-Host ""

if ($ExitCode -eq 0) {
    if (-not $Real) {
        # Si hay filtro de proveedor, verificar que ese proveedor tuvo insercion
        $DigiOK = $true
        if ($Proveedor -ieq "DIGI") {
            $cDigiInsert = @($LogLines | Select-String "Habria insertado.*DIGI|DGFC").Count
            if ($cDigiInsert -eq 0) {
                $DigiOK = $false
            }
        }

        Write-Sep "Cyan"
        if (-not $DigiOK) {
            Write-Host "  [WARN] DRY-RUN completado pero DIGI NO fue insertable." -ForegroundColor Yellow
            Write-Host "  Revisar el log antes de ejecutar -Real:" -ForegroundColor Yellow
            Write-Host "  $LogFile" -ForegroundColor DarkGray
        } else {
            Write-Host "  [DRY-RUN] OK. Si el resultado es correcto, ejecutar:" -ForegroundColor Cyan
            $RealCmd = ".\scripts\run_facturas_bordagran.ps1 -Desde $Desde -Hasta $Hasta"
            if ($Proveedor) { $RealCmd += " -Proveedor $Proveedor" }
            if ($Forzar)    { $RealCmd += " -Forzar" }
            $RealCmd += " -Real"
            Write-Host "  $RealCmd" -ForegroundColor White
        }
        Write-Sep "Cyan"
    } else {
        Write-Sep "Green"
        Write-Host "  [OK] PROCESO REAL completado." -ForegroundColor Green
        Write-Host "  Verificar en Sheets: pestana FACTURA PROVEEDORES" -ForegroundColor Green
        Write-Sep "Green"
    }
} else {
    Write-Sep "Red"
    Write-Fail "El proceso termino con errores (exit code $ExitCode)"
    Write-Host "  Revisar log: $LogFile" -ForegroundColor Red
    Write-Sep "Red"
    exit $ExitCode
}
