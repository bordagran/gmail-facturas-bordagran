# CHANGELOG — gmail-facturas-bordagran
## [3.1.0] - 2026-06-20

### Fix: THCLOTHES — extracción de total sin capturar saltos de línea (FIX 1)
- Regex `Total\s*\(\s*EUR\s*\)\s*([\d\s.,]+)` capturaba la línea siguiente (fecha)
  y producía `total=None` al fallar la conversión numérica.
- Corregido a `([\d.,]+)` — solo dígitos, puntos y comas, sin espacios.
- Afectadas: `_extraer_total_zona_resumen()`, dos variantes del patrón.

### Fix: THCLOTHES — estado Revisar para facturas RITI / IVA 0% (FIX 2, L-033)
- Facturas intracomunitarias PT→ES tienen IVA 0% por exención RITI.
- `determinar_estado()` devuelve ahora `Revisar` cuando `iva_pct==0` y las notas
  contienen "RITI", "IVA 0pct", "exencion" o "intracomunit".
- Garantiza revisión fiscal manual antes de cualquier deducción.

### Fix: fechas — normalización ISO en todo el ciclo anti-dup (FIX 3-6, L-034)
- **FIX 3** (`_ejecutar`): normaliza `datos_pdf["fecha"]` a ISO antes de llamar
  a `anti_dup.es_duplicado()` (Capa 6: prov+fecha+total).
- **FIX 4+4b** (`_cargar`): normaliza fecha raw del Sheet al cargar en memoria,
  incluyendo el caso "Fri, 13 May 2026" (día de la semana prefijado).
- **FIX 5** (`escribir_fila`): escribe siempre ISO `YYYY-MM-DD` en columna A.
- **FIX 6** (`registrar`): normaliza fecha en los sets intra-ejecución para dedup
  correcto entre facturas del mismo trimestre procesadas en la misma pasada.

### Fix: Anthropic — receipt no duplica gasto si invoice del mismo email ya registrada (FIX 7, L-035)
- Flag `_anthropic_invoice_en_msg` por mensaje Gmail: se activa cuando la invoice
  Anthropic se registra O se detecta como duplicada en el mismo msg_id.
- Si el flag está activo y aparece un `factura_recibo_digital` Anthropic en el
  mismo mensaje → se descarta con motivo "Anthropic receipt omitido: invoice
  asociada ya registrada/duplicada en mismo email".
- Sin este fix: la recarga API de 8.47 EUR se insertaba dos veces (invoice + receipt).

### Fix: parsers — proveedores de bajo riesgo con num_factura no legible (FIX 8-9, L-036)
- Ampliado `PROVEEDORES_REF_TECNICA` con proveedores españoles que emiten facturas
  sin número legible por pdfplumber pero sí tienen total extraído:
  `workteam`, `mayton`, `tiendanimal`, `textilolius`, `textil olius`,
  `vivadtf`, `velilla` (solo cuando tiene total > 0).
- Ampliado `PROVEEDORES_IVA_DEFAULT` con IVA 21% para los mismos proveedores ES.
- Impacto estimado: 39 pendientes → ~28 (recuperación ~11 facturas por lote).
- Criterio de inclusión: proveedor conocido + total extraído + riesgo fiscal bajo.
- Excluidos intencionalmente: BBVA (justificante bancario, no factura fiscal),
  GMAIL genérico (proveedor no identificado), Radiokable/GOR (total=None).

### Fix: logging seguro Windows/cp1252 — UnicodeEncodeError (FIX 10, L-040)
- PowerShell Windows usa cp1252 por defecto; los símbolos → ❌ ⚠️ ✅ causaban crash
  antes de completar cualquier dry-run (falla en la primera línea de duplicado).
- `configurar_salida_segura()`: reconfigura stdout/stderr a UTF-8 con `errors='replace'`
  al inicio de `main()`.
- `log()` blindada con `try/except UnicodeEncodeError` → fallback ASCII.
- `print()` directos con emoji fuera de `log()` reemplazados por etiquetas ASCII seguras.
- Sin este fix ningún dry-run en Windows era fiable.

### Fix: proveedores faltantes en prov.json + REF_TECNICA + clasificador (FIX 11-14)
Dry-run lote 2 validado: 39→35→23 pendientes | 3→7→14 registradas | 0 errores.

**FIX 11 — 4 nuevos proveedores en `references/proveedores.json`:**
- `Textilolius` (textilolius@textilolius.com / textilolius.com) — distinto de Textil Olius/Patricia
- `Tiendanimal` (no-reply.store@tiendanimal.es / tiendanimal.es)
- `VIVADTF` (pedidos@vivadtf.com / vivadtf.com)
- `Vinilos y Serigrafia` (info@vinilosyserigrafia.com / vinilosyserigrafia.com)
- Causa raíz: estos proveedores caían en DESCONOCIDO porque su email remitente
  no estaba en prov.json, impidiendo que REF_TECNICA funcionara.

**FIX 12 — Ampliar `PROVEEDORES_REF_TECNICA`:**
- Añadidos: `arkiplot`, `octopus`, `vinilosyserigrafia`
- Arkiplot y Octopus ya estaban en prov.json pero sin REF_TECNICA → pendiente_extraccion.

**FIX 13 — Ampliar `PROVEEDORES_IVA_DEFAULT`:**
- Añadidos al 21%: `vinilosyserigrafia`, `arkiplot`, `octopus`

**FIX 14 — Bug clasificador: proformas pasaban como `factura` (L-041):**
- `PROFORMA-PRE-*.pdf` de WORKTEAM se clasificaban como `factura` porque el
  texto del PDF contiene "factura" en la referencia de pago pero no "presupuesto".
- Añadidos `"proforma"` y `"pro-forma"` a `_KW_PRESUPUESTO`.
- Resultado: 2 proformas WORKTEAM → `no_fiscales` (correcto).

**Impacto real dry-run lote 2 (2026-04-01 → 2026-06-20):**
- Nuevas registradas: +7 (Textilolius×2, Tiendanimal×2, VIVADTF×1, Arkiplot×1,
  Octopus×1, Vinilos y Serigrafia×1)
- Base imponible total simulada: 1917.39 EUR | IVA: 180.03 EUR | Total: 2097.42 EUR
- Pendientes restantes: 23 (GMAIL×9 forwarded, BBVA×2 no-fiscal, Radiokable×3
  total=None, Velilla×4 total=None o abono, GOR/DIPGRA×3 total=None, APLEONA×2 pendiente confirmación)

**Pendientes irresolubles en este sprint (manual):**
- GMAIL/bordagran@gmail.com: 9 forwarded — proveedor no identificable sin PDF parse
- BBVA: 2 justificantes bancarios — no son facturas fiscales
- Radiokable/Velilla/GOR/DIPGRA: total=None — parsers pendientes sprint siguiente

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

## [3.0.0] - 2026-06-20

### Rango de fechas flexible (--desde / --hasta)
- `--desde YYYY-MM-DD` + `--hasta YYYY-MM-DD` funcionan ahora en modo incremental Y backfill
- Gmail `before:` calculado como `hasta + 1 dia` (exclusivo por diseno de la API)
- `--dias` sigue funcionando como fallback cuando no se pasan fechas explicitas
- L-024: documentado el comportamiento exclusivo de `before:` en Gmail

### Resumen trimestral (resumen.py v3.0)
- Nuevo `--periodo trimestral`: calcula automaticamente el trimestre actual
- Nuevos `--desde` / `--hasta` en resumen.py para rango personalizado
- Output ahora muestra 3 cifras separadas: base imponible, IVA, total (L-026)
- `filtrar_por_fecha()` usa col A (FECHA_FAC) primero, col N como fallback
- `calcular_trimestre_desde()`: devuelve rango exacto Q1-Q4 del ano

### Extraccion fiscal completa
- SOLS: nuevo patron `\d{4}[A-Z]{2}\d{5}` extrae numero real (ej: `2606FV05503`) — L-025
- Derivacion fiscal si 2 de 3 datos conocidos: base+IVA%->total, total+IVA%->base, base+total->IVA%
- RITI/intracomunitario: IVA=0, base=total (ya implementado v2.7, confirmado)
- Acumulador `base_total` en dry-run: visible en resumen final junto a IVA y total

### Sheet headers: verificar_headers() mejorado
- Lee fila 1 real del Sheet antes de escribir
- Detecta si faltan columnas BASE, IVA_PCT, IVA_EUR, TOTAL y avisa
- Verifica que cols O-R (MSG_ID, ATT_ID, HASH, CLAVE_UNICA) existan
- No desplaza columnas e
## [3.0.1] - 2026-06-20

### Deduplicación intra-ejecución reforzada (procesar_facturas.py)
- Sets locales `_exec_claves`, `_exec_prov_num`, `_exec_hashes` inicializados al arranque
- `c_unica` recomputada DESPUÉS de asignar la referencia técnica (antes se calculaba con num_factura vacío)
- Resultado: Anthropic factura+recibo del mismo periodo ya no se registran doble
- Motivo de duplicado visible en log: `duplicado intra-ejecucion (clave|hash|prov+num)`

### Referencias técnicas estables (procesar_facturas.py)
- Ref técnica de proveedor digital ya no usa `msg_id[:8]` (cambiaba según email origen)
- Nuevo: `md5(prov_code + fecha_iso + total_str)[:8]` — mismo hash independientemente del email
- Aplica tanto al path PDF como al path de factura-en-cuerpo

### Bloqueo de proveedores desconocidos / GMAIL (procesar_facturas.py)
- Si `es_desconocido=True` (dominio no mapeado en proveedores.json): `continue` — no se inserta fila
- Se añade a `r["pendientes"]` con nota `proveedor_real_no_identificado`
- Etiquetado Gmail como pendiente solo en ejecución real (no en dry-run)

### resumen.py: detección dinámica de columnas por header
- Eliminados índices hardcodeados (`fila[6]`, `fila[8]`, `fila[9]`)
- Nueva función `_detectar_columnas(headers)`: busca por nombre real con lista de alias
- Alias de IVA €: "iva eur", "iva_eur", "iva euros", "iva", "iva €", "cuota iva", "importe iva"
- Fallback a COL dict si el Sheet no tiene headers reconocibles

### resumen.py: derivación defensiva de base imponible
- Si base=0 y IVA€>0 y total>IVA: `base = total - iva` (evita base 0 cuando el Sheet la tiene vacía)
- Condición IVA>0 impide inventar base para Canva/Anthropic (IVA=0 en esas facturas)
- Guardia: si base>total en una fila, se descarta esa base (señal de columna mal mapeada)
- Corrige resumen incoherente anterior: base 1976.21 EUR → correcta 585.71 EUR

### Resultado Q2 2026-04-01 → 2026-06-20 (validado)
- Documentos fiscales: 9
- Base imponible total: 585.71 EUR
- IVA fiscal total: 123.00 EUR
- Importe fiscal total: 771.18 EUR
- SOLS: 4 facturas (708.71 EUR) | Canva: 3 (36.00 EUR) | Anthropic: 2 (26.47 EUR)
- Duplicados detectados post-ejecución: 0
