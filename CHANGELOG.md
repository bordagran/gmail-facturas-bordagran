# CHANGELOG — gmail-facturas-bordagran
## [2.5.0] - 2026-06-19

### Clasificacion multilingue
- `clasificar_tipo_documento()` ampliado: reconoce documentos en ES/PT/EN/FR/IT
- Keywords positivos: fatura, fatura FT, invoice, receipt, tax invoice, facture, fattura, etc.
- `_KW_RECIBO_DIGITAL`: detecta recibos fiscales digitales (Anthropic, Stripe) por >= 2 keywords
- `_PAT_FATURA_PT`: patrones portugueses FT FES., FES.2026/, FES_2026_, etc.
- Albaran: solo bloquea si keyword aparece en las PRIMERAS 5 lineas (evita falsos positivos)

### Nuevos proveedores
- THCLOTHES (Portugal): Fatura FT FES.YYYY/NNNN, IVA intracomunitario 0%
- Canva (Australia): sin PDF, busca factura en cuerpo del email
- Anthropic: emails billing/invoice actualizados, tipo `factura_recibo_digital`

### Parser PDF mejorado (`extraer_datos_pdf`)
- `_extraer_num_fatura_pt()`: extrae y normaliza numero de fatura PT → FES.YYYY/NNNN
- `_extraer_total_zona_resumen()`: busca ultima ocurrencia de total (evita confundir linea de articulo con total)
- Anthropic: extrae Invoice number, Receipt number, Date paid, Amount paid
- Base imponible PT: Incidencia, Valor Tributavel, Subtotal
- Fecha: soporta "Date paid: June 19, 2026" (formato largo EN)
- Anti-contaminacion: si total=None/0 o sin num+fecha → `_pendiente_extraccion=True`

### Anti-contaminacion (NUNCA insertar si datos criticos faltan)
- `ESTADO_PENDIENTE_EXTRACCION = "PENDIENTE_EXTRACCION_SIN_REGISTRAR"`
- En el loop: si `_pendiente_extraccion=True` → log + label_pendiente + continue (NO Sheet)
- Evita insertar filas con NoneEUR o 0.00EUR

### Aviso bancario → cuerpo email
- Cuando PDF es `aviso_bancario`, el sistema ahora lee el cuerpo del email
- Si el cuerpo contiene datos fiscales → procesa como `factura_en_cuerpo`
- Solo ignora como aviso bancario si el cuerpo tampoco tiene datos fiscales

### Gmail multi-query
- Ademas de `has:attachment filename:pdf`, añade queries por proveedor digital:
  - Anthropic: from:invoice+statements@mail.anthropic.com
  - Canva: from:canva.com (invoice OR receipt OR paid)
  - THCLOTHES: from:thclothes.com (fatura OR FES)
  - SOLS: from:sols.es (factura OR aviso OR REM26)
- Deduplicacion por msg_id: ningun email se procesa dos veces

### Nuevo tipo fiscal
- `factura_recibo_digital` añadido a TIPOS_FISCALES (se inserta en Sheet)


## [2.4.0] - 2026-06-19

### Agregado
- **`--dry-run`**: modo seguro que simula el procesamiento sin escribir en Sheet/Drive/Gmail
- **Anti-duplicados 6 capas**: añadidas capas 5 (prov+num_factura) y 6 (prov+fecha+total) a `AntiDuplicados`
- **Email body parsing**: cuando no hay PDF, se extrae el cuerpo del email y se buscan datos fiscales
  - `extraer_texto_email()`: extrae texto plano (multipart, text/plain, text/html)
  - `tiene_datos_fiscales()`: heurística importe + referencia fiscal
  - `extraer_datos_de_texto()`: extrae num, fecha, base, IVA, total desde texto libre
  - Si datos fiscales encontrados y tipo en TIPOS_FISCALES → inserta con nota "Factura en cuerpo email, sin PDF adjunto"
- **`scripts/detectar_duplicados_sheet.py`**: lee FACTURA PROVEEDORES, detecta dups por 5 claves, genera `runtime/duplicados_detectados.csv` (NO borra nada)
- **Resumen mejorado**: muestra dry-run indicator, conteo `factura_en_cuerpo`, detalle de dups y no fiscales
- **Gating de escrituras**: Drive upload, Sheet append_row y Gmail label gateados con `if not dry_run:`

### Seguridad
- Anti-dup se registra SIEMPRE (incluso en dry-run) para detectar dups intra-sesión




## v2.3.0 — 2026-06-19

### Clasificación fiscal obligatoria antes de insertar en FACTURA PROVEEDORES (L-012)

**ADD** `references/exclusiones.json` — nueva lista de emails de clientes/no proveedores
  que no deben generar filas en FACTURA PROVEEDORES.
  Incluye: `admin-cyberactioning@arqus-alliance.eu` (ARQUS-ALLIANCE, cliente).

**ADD** `scripts/procesar_facturas.py` — función `clasificar_tipo_documento()`:
  Clasifica cada PDF antes de insertar: `factura`, `factura_simplificada`, `albaran`,
  `aviso_bancario`, `presupuesto`, `pedido`, `cliente_no_proveedor`, `desconocido`.
  Solo `factura` y `factura_simplificada` se insertan en la hoja fiscal.
  Detecta: albaranes ("albarán", "delivery note"), avisos bancarios ("aviso giro bancario",
  "remesa", "giro bancario"), presupuestos, pedidos.

**ADD** `scripts/procesar_facturas.py` — función `cargar_exclusiones()`:
  Lee `references/exclusiones.json`. Comprobación de email antes de clasificar.

**FIX** `scripts/procesar_facturas.py` — parser IVA mejorado para SOLS y similares:
  Si PDF tiene base e importe total pero no IVA explícito, calcula IVA por diferencia
  (IVA€ = total - base). IVA% se redondea a 21%, 10%, 4% o 0% con tolerancia ±1.5%.
  Si no encaja con ningún tipo legal, marca "IVA calculado — verificar tipo" en notas.

**UPDATE** `references/proveedores.json` — SOLS añadido `clientes@sols.es` como email
  adicional (junto a `no-reply@sols.es`).

**FIX** `scripts/resumen.py` — importe_total e iva_total solo suman estados "Registrada"
  y "Validada Carlos" (ESTADOS_SUMAR). Albaranes, avisos bancarios, documentos de
  clientes y no fiscales NO suman en el resumen fiscal.

**UPDATE** `scripts/resumen.py` — ESTADOS_VALIDOS ampliado con estados no fiscales:
  "No fiscal / Albarán", "No fiscal / Aviso bancario", "No fiscal / Cliente", etc.

**FIX** `scripts/verificar_entorno.py` — corregida advertencia falsa sobre nombre de
  pestaña: ahora verifica que `SHEET_FACTURAS_NAME = "FACTURA PROVEEDORES"` (correcto)
  en lugar de emitir falso warning por no ser "Facturas".

**ADD** `scripts/verificar_entorno.py` — `references/exclusiones.json` añadido a
  lista de archivos requeridos.

**ADD** `scripts/procesar_facturas.py` — banner de inicio con flush=True (L-010),
  flag `--forzar`, autenticación OAuth con mensajes detallados (traídos desde Desktop).

**RULE (L-012):** No todo PDF adjunto con importe o palabras comerciales es factura.
  El sistema debe clasificar el tipo de documento ANTES de registrar en la hoja fiscal.


## v2.1.0 — 2026-06-19

**FIX** `scripts/resumen.py` — archivo truncado en línea 191 (SyntaxError: dict no cerrado).
  Reescrito completo (272 líneas). Eliminados f-strings con emojis que causaban
  problemas en algunos terminales Windows; sustituidos por `.format()`.

**ADD** `scripts/verificar_entorno.py` — nueva función `verificar_sintaxis_python()`:
  compila todos los scripts/*.py con `py_compile` antes de declarar ENTORNO OK.
  Si hay SyntaxError, bloquea la ejecución y muestra el error exacto.

**RULE (L-009):** verificar_entorno.py nunca dirá ENTORNO OK si algún script
  tiene SyntaxError.


Formato: [TIPO] Descripción — archivo(s)

Tipos: ADD (nuevo), FIX (corrección), UPDATE (mejora), BREAK (cambio incompatible), SEC (seguridad)

---

**Ruta oficial de instalación:** `C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran`

## v2.0.0 — 2026-06-19

### Reescritura completa

**ADD** `scripts/procesar_facturas.py` v2.0
- Argumento `--modo [incremental|backfill]`
- Argumento `--desde / --hasta YYYY-MM-DD` para backfill
- Argumento `--dias N` para incremental (default: 7)
- Argumento `--skill-dir` para ruta explícita
- Lock de ejecución `runtime/procesar_facturas.lock` (timeout 60 min)
- Anti-duplicados 4 capas: hash SHA256, clave única MD5, msg_id+att_id, URL Drive
- Subida a Drive bajo `Facturas 2026/Q{1-4}-{año}/`
- Nombre de archivo normalizado: `YYYY-MM-DD_PROVEEDOR_FACTURA_IMPORTE.pdf`
- Procesamiento por adjunto individual (no por thread)
- Estados: `Registrada`, `Revisar`, `Duplicada`, `Error lectura`, `Validada Carlos`
- Columnas nuevas en Sheet: O (Gmail Message ID), P (Gmail Attachment ID), Q (Hash PDF), R (Clave Única)
- Resultado JSON guardado en `runtime/ultimo_resultado.json`

**ADD** `scripts/resumen.py` v2.0
- Lectura dinámica de `runtime/ultimo_resultado.json` del último proceso
- Todos los estados del v2 incluidos en conteo
- Lookup dinámico de skill_dir (sin hardcode)
- IVA total en resumen

**ADD** `scripts/verificar_entorno.py`
- Verificación completa: archivos, config, dependencias, .gitignore, token OAuth

**ADD** `scripts/setup_labels.py`
- Crea labels Gmail `Facturas/Procesadas` y `Facturas/PendienteRevision` si no existen

**ADD** `scripts/test_extraccion_pdf.py`
- Test manual de extracción de datos desde PDF individual
- Modos `--verbose` (texto crudo) y `--json` (output estructurado)

**ADD** `.gitignore` — excluye credentials.json, token.pickle, PDFs, logs, runtime

**ADD** `requirements.txt` — dependencias Python fijadas con versión mínima

**ADD** `config.json` — IDs confirmados de Sheet, Drive, labels

**ADD** `runtime/.gitkeep` — mantiene carpeta runtime en git sin archivos sensibles

**ADD** `tests/README.md`

**FIX** `references/proveedores.json` — emails correctos Velilla Group y SEUR

**FIX** `identificar_proveedor()` — ahora soporta campos `emails` (array) y `matchType` (camelCase)

**SEC** Credenciales nunca mostradas en logs ni en pantalla

---

## v1.0.0 — 2026-06 (sesión anterior)

- Estructura inicial del skill
- Config.gs con 15 proveedores reales verificados en Gmail Q2 2026
- Scripts GAS: GmailProcessor, DriveManager, OCRProcessor, SheetsManager, etc.
- SKILL.md inicial
- Tareas programadas: diario 20:00 + semanal lunes 8:00

## [2.6.0] - 2026-06-19

### SOLS: diagnóstico aviso bancario
- `_diag_sols()`: cuando PDF es aviso bancario y se revisa el cuerpo, registra en dry-run:
  - longitud del cuerpo, keywords encontradas, resultado clasificador
  - guarda `runtime/diagnostico_sols_{msg_id}.txt` con primeras 80 líneas
- `tiene_datos_fiscales()` ampliado: reconoce rem26, cl0XXXX, cobro, domiciliacion, vencimiento, abono, cargo, paid, amount, total a

### THCLOTHES: total portugués
- `_extraer_total_zona_resumen()` reescrita: trabaja sobre las últimas 60 líneas del texto
- Patrones PT: Total Documento, Total Neto, Valor a pagar, Total com IVA, Mercadoria
- Estrategia: elige el importe más alto de los candidatos del pie (total > subtotales de línea)

### Canva: num_factura limpio
- `extraer_datos_de_texto()`: filtro `_PALABRAS_EXCLUIR_NUM` evita "tinuaci", "continuacion", "payment", etc.
- Fallback autogenerado si num vacío: `CANVA_2026-06-19_12` con nota "Ref. técnica autogenerada"

### Resumen separado: PENDIENTE vs No fiscal
- Nueva clave `r["pendientes"]`: solo documentos con `_pendiente_extraccion=True`
- THClothes sin total → `PEN Pendientes sin registrar` (no mezclado con albaranes/ARQUS)
- Resumen muestra sección separada `PENDIENTES_EXTRACCION (revisar manualmente)`
