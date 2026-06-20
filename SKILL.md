---
name: gmail-facturas-bordagran
description: >
  Automatiza la gestión fiscal de Bordagran: busca facturas de proveedores en Gmail,
  descarga los PDFs adjuntos, extrae datos con Python/pdfplumber, los sube a Drive
  y los registra en Google Sheets evitando duplicados. Úsalo cuando el usuario diga
  "procesar facturas", "revisar facturas pendientes", "resumen de facturas",
  "facturas del trimestre", "hay facturas nuevas", "actualizar el registro de gastos",
  "backfill Q2", o cualquier variante sobre gestión de facturas de Bordagran.
  También se ejecuta automáticamente cada lunes a las 8:00 (resumen semanal)
  y cada día a las 20:00 (resumen diario).
---

# Skill: gmail-facturas-bordagran v3.0.1

## Reglas de oro (no negociables)

1. **NUNCA subas a GitHub:** `credentials.json`, `token.pickle`, `.env`, PDFs, logs con datos.
2. **NUNCA hardcodees rutas de sesión** — descubrir dinámicamente con `encontrar_skill_dir()`.
3. **Si falta `credentials.json`**, detén la ejecución y muestra:
   > "Necesito el archivo credentials.json de tu proyecto Google Cloud.
   > Ve a console.cloud.google.com → proyecto bordagran-fiscal → APIs & Services →
   > Credentials → Download OAuth 2.0 Client ID → guárdalo como credentials.json
   > en la carpeta del skill."
4. **No muestres tokens, credenciales ni rutas sensibles completas** en pantalla.
5. Antes de cualquier commit, verifica que `.gitignore` excluye `credentials.json` y `token.pickle`.

---

## Descubrimiento dinámico del skill-dir

**REGLA CRÍTICA (L-001):** La ruta de sesión de Claude varía según el equipo y la instalación.
En el equipo de Juan María es:
`C:\Users\Juan\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\...`
NO `C:\Users\Juan\AppData\Roaming\Claude\...`

Siempre descubrir el skill-dir así (implementado en `encontrar_skill_dir()`):
```python
import os
from pathlib import Path

def encontrar_skill_dir() -> Path:
    bases = [
        Path(os.environ.get("APPDATA", "")) / "Claude",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Packages",
    ]
    for base in bases:
        if not base.exists():
            continue
        for p in base.rglob("gmail-facturas-bordagran"):
            if p.is_dir() and (p / "SKILL.md").exists():
                return p
    return None
```

O bien pasar `--skill-dir /ruta/exacta` como argumento CLI.

**Ruta oficial de instalación en este equipo:**
```
C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran
```
Para instalar: ejecutar `INSTALAR_BORDAGRAN.bat` desde el Escritorio.



---

## Regla de clasificación fiscal (L-012 — CRÍTICO)

**Antes de insertar en FACTURA PROVEEDORES**, el sistema clasifica el tipo de documento:

| tipo_documento | Acción | Detectado por |
|---|---|---|
| `factura` | ✅ Insertar | Keyword "factura", "invoice" |
| `factura_simplificada` | ✅ Insertar | Keyword "factura simplificada" |
| `albaran` | ⛔ No insertar | "albarán", "albaran", "delivery note" |
| `aviso_bancario` | ⛔ No insertar | "aviso giro bancario", "remesa", "giro bancario" |
| `presupuesto` | ⛔ No insertar | "presupuesto", "quotation", "estimate" |
| `pedido` | ⛔ No insertar | "orden de compra", "purchase order" |
| `cliente_no_proveedor` | ⛔ No insertar | Email en `references/exclusiones.json` |
| `desconocido` | ⛔ No insertar | Sin clasificación clara (precaución) |

**Archivos de referencia:**
- `references/exclusiones.json` — emails de clientes que nunca son proveedores
- `references/proveedores.json` — emails de proveedores reconocidos

**Resumen fiscal:** `resumen.py` solo suma importes con estado `Registrada` o `Validada Carlos`.
Albaranes, avisos bancarios y documentos no fiscales no suman.

---

## Qué hace este skill

1. **Busca** emails con PDF adjunto en Gmail para el rango de fechas indicado
2. **Descarga** PDFs con Gmail API (adjunto a adjunto, no por thread)
3. **Extrae** datos con `pdfplumber`: nº factura, fecha, base, IVA, total
4. **Clasifica** tipo de documento (factura, albarán, aviso bancario, etc.) — L-012
5. **Verifica** duplicados (4 capas) contra columnas O-R del Sheet
6. **Sube** PDF a Drive bajo `Facturas 2026/Q{n}-{año}/`
7. **Registra** fila nueva en Sheet pestaña "FACTURA PROVEEDORES" (columnas A-R) solo si fiscal
8. **Etiqueta** email como `Facturas/Procesadas` o `Facturas/PendienteRevision`
9. **Genera** resumen de lo procesado

---

## Cuándo ejecutar cada modo

| Invocación del usuario | Modo | Comando |
|------------------------|------|---------|
| "procesar Q2", "backfill", "todas las facturas" | backfill | `--modo backfill --desde 2026-04-01 --hasta 2026-06-30` |
| "procesar facturas", "hay facturas nuevas" | incremental | `--modo incremental` |
| Tarea programada lunes 8:00 | resumen semanal | `resumen.py --periodo semanal` |
| Tarea programada diaria 20:00 | resumen diario | `resumen.py --periodo diario` |

---

## Configuración inicial (solo la primera vez)

### Archivos necesarios en la carpeta del skill:

```
gmail-facturas-bordagran/
├── credentials.json    ← OAuth2 GCP (el usuario lo aporta)
├── config.json         ← Ya creado (IDs confirmados)
└── references/
    └── proveedores.json ← Ya creado (25 proveedores)
```

### config.json (valores confirmados):

```json
{
  "SHEET_FACTURAS_ID": "16kVW39cAV7NWnjKnhkXkeOMkcMV_3JiynRHhwJ27fUU",
  "SHEET_FACTURAS_NAME": "FACTURA PROVEEDORES",
  "LABEL_PROCESADAS": "Facturas/Procesadas",
  "LABEL_PENDIENTE": "Facturas/PendienteRevision",
  "OWNER_EMAIL": "bordagran@gmail.com",
  "DRIVE_ROOT_FOLDER_ID": "1oPj9aqn3wSYgrB5-aV_eKXqkHpUciN7Q"
}
```

**REGLA (L-002 actualizada):** La pestaña oficial del Sheet es `"FACTURA PROVEEDORES"`.
NO usar "Facturas". `verificar_entorno.py` confirma este valor como correcto.

---

## Flujo de ejecución completo

### Paso 1 — Instalar dependencias

```bash
pip install -r requirements.txt --break-system-packages --quiet
```

### Paso 2 — Verificar entorno (incluye comprobación de sintaxis)

```bash
python scripts/verificar_entorno.py --skill-dir "C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran"
```

### Paso 3 — Ejecutar procesamiento

Obtener la ruta del skill dinámicamente:
```bash
# Windows: el skill puede estar en rutas distintas según la instalación
# Usar --skill-dir para evitar ambigüedad:
python scripts/procesar_facturas.py --modo incremental --skill-dir "C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran"
```

O dejar que el script descubra la ruta automáticamente (sin --skill-dir).

### Paso 4 — Ver resumen

```bash
python scripts/resumen.py --periodo diario --skill-dir "C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran"
```

### Paso 5 — Presentar resultado al usuario

Mostrar siempre:
- Nº de facturas nuevas registradas
- Nº de duplicados ignorados (con motivo)
- Importes totales de
## Modo Dry-Run (seguro)

Antes de cualquier ejecucion real, valida siempre con --dry-run:

```bash
python scripts/procesar_facturas.py --modo incremental --skill-dir . --dry-run
```

El modo dry-run simula todo el procesamiento (clasifica, detecta dups, parsea) sin escribir nada en Sheet, Drive ni Gmail.

## Detectar duplicados en el Sheet

```bash
python scripts/detectar_duplicados_sheet.py --skill-dir .
```

Genera `runtime/duplicados_detectados.csv` con grupos de filas posiblemente duplicadas (NO borra nada).

---

## Reglas operativas v3.0 (añadidas 2026-06-20)

### CLI: rango de fechas
- `--desde YYYY-MM-DD --hasta YYYY-MM-DD` funciona en modo incremental Y backfill
- Gmail `before:` = `--hasta + 1 dia` (L-024, exclusivo por API)
- Sin fechas explícitas: usar `--dias` (default 7)

### Resumen trimestral
- `python scripts/resumen.py --periodo trimestral --skill-dir .`
- `python scripts/resumen.py --desde 2026-01-01 --hasta 2026-03-31 --skill-dir .`
- Dry-run trimestral OBLIGATORIO antes de ejecucion real de backfill Q

### Fiscalidad por proveedor
| Proveedor | Num. factura | IVA | Notas |
|-----------|-------------|-----|-------|
| SOLS | `\d{4}[A-Z]{2}\d{5}` ej: 2606FV05503 | 21% ES | Derivar base si solo total |
| THClothes | FES.YYYY/NNNN via PT | 0% RITI | Total ( EUR ) como prioridad |
| Canva | Ref tecnica CANVA_... | 0% intra | Sin breakdown fiscal |
| Anthropic | Invoice number del PDF | 0% intra | Amount paid en PDF |
| Velilla | num_factura real requerido | 21% ES | Sin num -> PENDIENTE |
| VIVADTF | num_factura real requerido | 21% ES | myParcel = invalido |
| DIPGRA | patrones generales ES | 21% ES | |


## Reglas operativas v3.0.1 (añadidas 2026-06-20)

### Deduplicación intra-ejección
- Los sets `_exec_claves`, `_exec_prov_num`, `_exec_hashes` detectan dups durante la misma pasada
- `c_unica` siempre se recomputa DESPUÉS de asignar ref técnica (antes fallaba con num vacío)
- Aplica tanto en dry-run como en ejecución real

### Proveedores desconocidos / GMAIL
- Si dominio no está en `proveedores.json`: `es_desconocido=True` -> `continue`, nunca `escribir_fila()`
- Va a `r["pendientes"]` con motivo `proveedor_real_no_identificado`
- NUNCA insertar fila con proveedor GMAIL, outlook.com, hotmail.com etc. como factura fiscal

### Referencias técnicas estables
- Ref técnica = `md5(prov_code + fecha_iso + total_str)[:8]`, no `msg_id[:8]`
- Mismo hash para Anthropic factura y recibo -> segunda detectada como `duplicado intra-ejecucion`

### resumen.py: columnas por nombre, no por índice
- `_detectar_columnas(headers)` mapea "Base Imponible", "IVA €", "Importe Total" por nombre real
- Si base=0 y IVA>0 y total>IVA: base = total - IVA (derivación defensiva)
- Condición IVA>0 evita inventar base para Canva/Anthropic

### Protocolo ejecución trimestral
```
# 1. Dry-run obligatorio
python scripts\procesar_facturas.py --modo incremental --desde YYYY-MM-DD --hasta YYYY-MM-DD --skill-dir . --dry-run
# 2. Ejecucion real (solo si dry-run OK)
python scripts\procesar_facturas.py --modo incremental --desde YYYY-MM-DD --hasta YYYY-MM-DD --skill-dir .
# 3. Verificacion post-ejecucion (ambos obligatorios)
python scripts\detectar_duplicados_sheet.py --skill-dir .
python scripts\resumen.py --periodo trimestral --skill-dir .
```

### Resultado Q2 2026 (referencia validada)
- Periodo: 2026-04-01 -> 2026-06-20
- Documentos fiscales: 9 | Base: 585.71 EUR | IVA: 123.00 EUR | Total: 771.18 EUR
- SOLS x4 (708.71) | Canva x3 (36.00) | Anthropic x2 (26.47)
- Tag: v3.0.1 | Commit: 11a132a
