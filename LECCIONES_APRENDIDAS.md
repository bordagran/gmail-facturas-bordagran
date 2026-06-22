# LECCIONES APRENDIDAS — gmail-facturas-bordagran

Registro de errores, correcciones y criterios revisados.
Cada entrada bloquea la repetición del error en futuras sesiones.

---

## L-012 — 2026-06-19 | Clasificar tipo de documento ANTES de insertar en la hoja fiscal

**Problema detectado:**
El sistema insertaba en FACTURA PROVEEDORES documentos que no son facturas:
- ARQUS-ALLIANCE: cliente de Bordagran, no proveedor
- SOLS: albaranes de entrega registrados como facturas
- Avisos de giro bancario (REM26-0174) registrados como facturas
- IVA no extraído correctamente en facturas reales de SOLS

**Criterio anterior (INCORRECTO):**
Procesar y registrar todo PDF adjunto de Gmail que tenga extensión .pdf.

**Corrección:**
Antes de insertar en FACTURA PROVEEDORES, clasificar obligatoriamente el documento:
- `factura` → insertar
- `factura_simplificada` → insertar
- `albaran` → NO insertar (keywords: "albarán", "delivery note")
- `aviso_bancario` → NO insertar (keywords: "aviso giro bancario", "remesa", "giro bancario")
- `presupuesto` → NO insertar
- `pedido` → NO insertar
- `cliente_no_proveedor` → NO insertar (email en references/exclusiones.json)
- `desconocido` → NO insertar (precaución)

**Implementación:**
- `clasificar_tipo_documento(texto_pdf, remitente, exclusiones)` en procesar_facturas.py
- `references/exclusiones.json` con lista de emails de clientes
- `TIPOS_FISCALES = {"factura", "factura_simplificada"}` — único gate de inserción
- Documentos no fiscales: etiquetados como PendienteRevision en Gmail, logueados pero no insertados
- `resumen.py` solo suma estados "Registrada" y "Validada Carlos" (ESTADOS_SUMAR)

**Regla operativa permanente:**
> No todo PDF adjunto con importe o palabras comerciales es factura.
> El sistema debe clasificar el tipo de documento ANTES de registrar en la hoja fiscal.
> Albaranes, avisos bancarios, expedientes de clientes y documentos no fiscales
> NO deben entrar en FACTURA PROVEEDORES ni sumar en resúmenes.

**Archivos afectados:**
- `scripts/procesar_facturas.py` — funciones `clasificar_tipo_documento()`, `cargar_exclusiones()`, parser IVA
- `scripts/resumen.py` — `ESTADOS_SUMAR`, `ESTADOS_VALIDOS` ampliado
- `references/exclusiones.json` — nuevo archivo
- `references/proveedores.json` — añadido `clientes@sols.es`
- `scripts/verificar_entorno.py` — corregida advertencia falsa, exclusiones.json requerido

---

## L-001 — 2026-06-19 | Rutas de sesión Claude en Windows

**Criterio anterior (INCORRECTO):**
Usar `C:\Users\Juan\AppData\Roaming\Claude\local-agent-mode-sessions` como ruta base.

**Corrección:**
La ruta real en este equipo es:
`C:\Users\Juan\AppData\Local\Packages\Claude_pzs8sxrjxfjjc\LocalCache\Roaming\Claude\local-agent-mode-sessions`

**Regla operativa permanente:**
> NUNCA hardcodear rutas de sesión de Claude. Siempre descubrir dinámicamente
> usando `Path.rglob("gmail-facturas-bordagran")` sobre `%APPDATA%` y
> `%LOCALAPPDATA%/Packages`, o bien aceptar `--skill-dir` como argumento CLI.

**Archivos afectados:** todos los scripts Python — implementado en `encontrar_skill_dir()`.

---

## L-002 — 2026-06-19 | Nombre de pestaña en Google Sheets

**Criterio anterior (INCORRECTO):**
`SHEET_FACTURAS_NAME = 'FACTURA PROVEEDORES'`

**Corrección:**
La pestaña real se llama `'Facturas'` (confirmado inspeccionando el Sheet).

**Consecuencia del error:**
3 facturas de Velilla Group x2 y Niba Energía x1 se subieron a Drive y se etiquetaron
como `Facturas/Procesadas` pero NO se escribieron en el Sheet.

**Acción de recuperación pendiente:**
Quitar label `Facturas/Procesadas` de esos 3 threads y volver a procesar.

---

## L-003 — 2026-06-19 | Email de Velilla Group

**Criterio anterior (INCORRECTO):**
`atencioncliente@velilla-group.com`

**Corrección:**
El email real confirmado en Gmail Q2 2026 es `no-reply@velilla-group.com`

---

## L-004 — 2026-06-19 | Email de SEUR

**Criterio anterior (INCORRECTO):**
`infoenvios@mail.seur.info`

**Corrección:**
El email real es `noreply@seur.com`

---

## L-005 — 2026-06-19 | Formato de proveedores.json vs código Python

**Problema detectado:**
`proveedores.json` usa campos `emails` (array) y `matchType` (camelCase).
El script `procesar_facturas.py` usaba `email` (string) y `match_type` (snake_case).
Ningún proveedor hubiera sido reconocido en producción.

**Corrección:**
`identificar_proveedor()` ahora soporta ambos formatos simultáneamente:
```python
patterns = p.get("emails") or ([p.get("email")] if p.get("email") else [])
match_type = p.get("matchType") or p.get("match_type", "exact")
```

---

## L-006 — 2026-06-19 | Anti-duplicados insuficiente

**Criterio anterior:**
Verificar duplicados solo por label Gmail + nombre de archivo en Sheet columna K.

**Corrección — 4 capas de anti-duplicados:**
1. Hash SHA256 del PDF (columna Q)
2. Clave única `proveedor+num_factura+fecha+total` hasheada con MD5 (columna R)
3. Gmail `message_id + attachment_id` (columnas O y P)
4. URL/nombre Drive (columna K)

---

## Cómo añadir una nueva lección

```
## L-NNN — YYYY-MM-DD | Título breve

**Criterio anterior (INCORRECTO):**
[qué se hacía mal]

**Corrección:**
[qué es lo correcto]

**Regla operativa permanente:**
[formulación de la regla para evitar repetición]
```

---

## L-007 — 2026-06-19 | No afirmar que archivos están disponibles sin verificar físicamente

**Criterio anterior (INCORRECTO):**
Decir "skill empaquetado en el Escritorio" o "listo" sin verificar que los archivos
existen en una ruta física accesible y estable de Windows.

**Problema real:**
La ruta de sesión `C:\Users\Juan\AppData\Roaming\Claude\local-agent-mode-sessions\...`
no es accesible ni estable desde Windows. El usuario no puede llegar ahí con PowerShell.

**Regla operativa permanente:**
> Antes de declarar cualquier archivo "entregado", copiarlo a la carpeta
> seleccionada del usuario (Desktop o similar) y confirmar con `find` o `ls`
> que los archivos existen en la ruta montada. Nunca asumir que el usuario
> puede acceder a rutas de sesión internas.

**Ruta estable acordada para este proyecto:**
`C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran`

Para instalar: ejecutar `INSTALAR_BORDAGRAN.bat` desde el Escritorio.

---

## L-008 — 2026-06-19 | Ruta oficial estable del proyecto Bordagran en Windows

**Ruta oficial acordada:**
`C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran`

**Regla operativa permanente:**
> Cualquier referencia futura a la ruta de instalación del skill debe usar
> `C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran`.
> No usar `C:\ClaudeProyectos\Bordagran` ni ninguna ruta de sesión de Claude.

---

## L-009 — 2026-06-19 | Verificar sintaxis Python, no solo existencia de archivos

**Error detectado:**
`resumen.py` aparecía en la verificación de entorno como ✅ (archivo existe)
pero al ejecutar daba `SyntaxError: '{' was never closed` — el archivo
estaba truncado desde la línea 191.

**Regla operativa permanente:**
> `verificar_entorno.py` debe ejecutar `py_compile.compile()` sobre TODOS
> los scripts `.py` antes de declarar ENTORNO OK. Si cualquier script tiene
> SyntaxError, el entorno NO está listo y debe bloquearse la ejecución.

**Corrección implementada en v2.1:**
- `verificar_entorno.py` incluye la función `verificar_sintaxis_python()`
  que compila cada `scripts/*.py` con `py_compile` y reporta errores exactos.
- Solo muestra "✅ ENTORNO OK" si TODOS los checks pasan, incluida la sintaxis.
- `resumen.py` reescrito completo (272 líneas, todas verificadas).

---

## L-013 — Dry-run obligatorio antes de cualquier ejecución real nueva

**Fecha**: 2026-06-19
**Causa**: Se detectaron filas duplicadas en FACTURA PROVEEDORES durante pruebas.
**Regla**: Nunca ejecutar `procesar_facturas.py` en modo real (sin --dry-run) tras un cambio de código sin antes validar con `--dry-run`.
**Patrón**: `python scripts/procesar_facturas.py --modo incremental --skill-dir . --dry-run`

## L-014 — Anti-dup debe operar en 6 capas

**Fecha**: 2026-06-19
**Causa**: Duplicados por mismo proveedor + número de factura distintos en hash (ej: PDF regenerado).
**Regla**: Siempre mantener las 6 capas: hash SHA256, clave MD5, msg+att, Drive URL, prov+num, prov+fecha+total.
**Código**: `AntiDuplicados` en `procesar_facturas.py`

## L-015 — Emails sin PDF pueden contener facturas (SOLS Aviso Giro Bancario)

**Fecha**: 2026-06-19
**Causa**: SOLS envía avisos de giro bancario por email sin adjunto PDF pero con datos fiscales en el cuerpo.
**Regla**: Cuando no hay PDF adjunto, extraer cuerpo del email y verificar `tiene_datos_fiscales()`. Si positivo y tipo fiscal -> insertar con nota.
**Tipo asignado**: `factura_en_cuerpo` (pertenece a TIPOS_FISCALES)

---

## L-016 — Facturas portuguesas no dicen "factura"

**Fecha**: 2026-06-19
**Causa**: THCLOTHES envía "Fatura FT FES.2026/1519" — el clasificador no reconocía "fatura".
**Regla**: Siempre incluir patrones PT: fatura, fatura FT, FT FES., FES.YYYY/, en clasificador y extractor.
**Codigo**: `_PAT_FATURA_PT`, `_extraer_num_fatura_pt()`

## L-017 — Recibos de Anthropic son facturas fiscales válidas

**Fecha**: 2026-06-19
**Causa**: Receipt de Anthropic tiene "Invoice number" → es factura fiscal, no mero ticket.
**Regla**: Si doc tiene >= 2 de: "invoice number", "receipt number", "date paid", "amount paid" → `factura_recibo_digital`.
**Codigo**: `_KW_RECIBO_DIGITAL`, tipo `factura_recibo_digital`

## L-018 — Anti-contaminacion: nunca insertar sin total > 0

**Fecha**: 2026-06-19
**Causa**: Se insertaban filas con "Revisar 0.00 EUR" que ensuciaban el Sheet.
**Regla**: Si `_pendiente_extraccion=True` (total=None/0 O sin num+fecha) → NUNCA insertar. Label pendiente para revisión manual.
**Codigo**: `ESTADO_PENDIENTE_EXTRACCION`, check en loop principal

## L-019 — El PDF de aviso bancario de SOLS puede acompañar factura en el cuerpo del email

**Fecha**: 2026-06-19
**Causa**: SOLS envía email con PDF "Aviso Giro Bancario" pero el cuerpo del email puede contener datos de la factura real.
**Regla**: Si tipo_doc == aviso_bancario → NO saltar; leer cuerpo email; si tiene datos fiscales → procesar como factura_en_cuerpo.

## L-020 — Gmail query solo con PDF pierde proveedores digitales

**Fecha**: 2026-06-19
**Causa**: Canva, Anthropic, SOLS sin adjunto no aparecían en `has:attachment filename:pdf`.
**Regla**: Mantener queries complementarias por proveedor digital. Deduplicar siempre por msg_id.

## L-021 | THClothes Fatura PT: Total ( EUR ) tiene precedencia / A Transportar es subtotal

**Contexto**: PDF FES_2026_911.pdf contiene dos importes: "A Transportar 105,60" (subtotal de hoja) y "Total ( EUR ) 105,60" (total definitivo). El parser antiguo no reconocía "Total ( EUR )" y podría tomar "A Transportar" como candidato.

**Reglas**:
1. Patrón `Total\s*\(\s*EUR\s*\)\s*([\d\s.,]+)` → máxima prioridad, retornar inmediatamente
2. Excluir líneas con "a transportar" o "carry forward" antes de buscar otros patrones
3. IVA 0% se indica como RITI/Isento/Exento — detectar y fijar `iva_pct=0, iva_eur=0.0, base=total`
4. Fatura FT + FES.YYYY/NNNN → siempre `tipo=factura`, nunca PENDIENTE

**Proveedor real**: THCLOTHES / Organizações Biscana, Lda (NIF PT)

## L-022 | es_num_factura_valido() — filtro obligatorio antes de usar num_factura

**Problema**: El parser extraia fragmentos de texto como "rmal" (de "normal"), "mbre" (de "nombre"), "myParcel" (de logistica), "tinuaci" (de "continuacion") como numero de factura. Estos valores invalidos contaminaban la clave_unica, el anti-duplicados y la columna NUM_FACTURA del Sheet.

**Regla**:
1. Todo `num_factura` candidato DEBE pasar `es_num_factura_valido()` antes de usarse
2. Si falla: anular el campo, registrar en notas como `num_invalido descartado`
3. Prefijos TECN_ y TEMP- = referencias tecnicas autogeneradas, nunca fiscales
4. `detectar_duplicados_sheet.py` no agrupa por `Prov+Num` si el num es invalido

**Puntos de aplicacion**:
- `extraer_datos_de_texto()` (cuerpo email)
- `extraer_dados_pdf()` bloque anti-contaminacion
- `detectar_duplicados_sheet.py` idx_provnum

## L-023 | num_factura vacio con total>0 no es suficiente para insertar

**Problema**: Velilla Group tenia total=49.91 y fecha detectada, pero num_factura="". El script lo habria insertado en el Sheet con num vacio.

**Regla**: num_factura vacio = PENDIENTE_EXTRACCION para todos los proveedores EXCEPTO los listados en PROVEEDORES_REF_TECNICA = {"canva", "anthropic"}.

**Excepcion REF_TECNICA**: Solo si (a) proveedor en PROVEEDORES_REF_TECNICA, (b) tiene total>0, (c) _sin_num=True. En ese caso se genera referencia tecnica limpia PROV_YYYY-MM-DD_TT.tt_msgid8.

**Fecha limpia**: Usar _fecha_iso_de_raw() para convertir fecha RFC email a YYYY-MM-DD antes de incluirla en cualquier referencia o log.


## L-024 | Gmail before: es exclusivo — siempre sumar 1 dia a --hasta

**Problema**: Gmail `before:YYYY/MM/DD` excluye ese dia. Si el usuario pide `--hasta 2026-03-31`, la query debe ser `before:2026/04/01` para incluir todo el dia 31.

**Regla**: `hasta_excl = hasta_dt + timedelta(days=1)`. Siempre usar `hasta_excl` en la query Gmail, nunca `hasta_dt` directamente.

**Aplica en**: modo incremental con `--desde`/`--hasta`, modo backfill, resumen trimestral.

## L-025 | SOLS: numero real tiene patron ddddLLddddd

**Patron**: `\b(\d{4}[A-Z]{2}\d{5})\b` — ejemplo: `2606FV05503` (año+mes + tipo + secuencia).
**Parser**: paso 4 en `extraer_dados_pdf()`, antes de patrones generales.
**es_num_factura_valido()**: aprueba porque tiene digitos y es alfanumerico de 11 chars.
**IVA**: SOLS es espanola, IVA 21% estandar. Derivacion: si total sin base -> `base = total/1.21`.

## L-026 | resumen.py: base_total separado de importe_total

**Razon fiscal**: para declaracion trimestral IVA se necesitan 3 cifras separadas: base imponible, cuota IVA, total factura. No es suficiente mostrar solo el total.

**Regla**: `generar_resumen()` devuelve `base_total`, `iva_total`, `importe_total` por separado.
Solo suman filas con estado `Registrada` o `Validada Carlos` (L-012).
`filtrar_por_fecha()` usa col A (FECHA_FAC) primero, col N (FECHA_PROCESO) como fallback.

## L-027 | --desde/--hasta funciona en modo incremental y backfill

**Cambio v3.0**: Si se pasan ambos `--desde` y `--hasta`, se usan independientemente del `--modo`.
Modo backfill SIN fechas explícitas sigue requiriendo ambas.
Modo incremental SIN fechas usa `--dias` (default 7).

## L-024 | Gmail before: es exclusivo -- siempre sumar 1 dia a --hasta

**Problema**: Gmail `before:YYYY/MM/DD` excluye ese dia. Si el usuario pide `--hasta 2026-03-31`, la query debe ser `before:2026/04/01` para incluir todo el dia 31.

**Regla**: `hasta_excl = hasta_dt + timedelta(days=1)`. Siempre usar `hasta_excl` en la query Gmail, nunca `hasta_dt` directamente.

**Aplica en**: modo incremental con `--desde`/`--hasta`, modo backfill.

## L-025 | SOLS: numero real tiene patron ddddLLddddd

**Patron**: `\b(\d{4}[A-Z]{2}\d{5})\b` -- ejemplo: `2606FV05503` (anno+mes + tipo + secuencia).
**Parser**: paso 4 en `extraer_dados_pdf()`, antes de patrones generales.
**IVA**: SOLS es espanola, IVA 21% estandar. Derivacion: si total sin base -> `base = total/1.21`.

## L-026 | resumen.py: base_total separado de importe_total

**Razon fiscal**: para declaracion trimestral IVA se necesitan 3 cifras: base imponible, cuota IVA, total. No es suficiente mostrar solo el total.

**Regla**: `generar_resumen()` devuelve `base_total`, `iva_total`, `importe_total` separados.
Solo suman estados `Registrada` o `Validada Carlos` (L-012).
`filtr
## L-028 | resumen.py: nunca usar índices fijos para columnas del Sheet

**Problema**: `fila[6]` asumía que BASE estaba siempre en col G. Si el Sheet tiene columnas en orden diferente (o extras añadidas), se lee el dato equivocado y la suma sale imposible (ej: base=1976.21 > total=771.18).

**Regla**: Siempre leer headers con `sheet.get_all_values()[0]` y detectar índices por nombre con `_detectar_columnas(headers)`. Usar alias para robustez ("base imponible", "base", "base eur", "base_eur", etc.).

**Implementado en**: `resumen.py` — función `_detectar_columnas()` + `_get_col()`.

## L-029 | Nunca insertar proveedor GMAIL/desconocido como factura fiscal

**Problema**: Emails cuyo dominio no está en `proveedores.json` obtenían `_desconocido=True` pero seguían insertándose en el Sheet con estado "Revisar". Contaminaba el registro con filas sin proveedor real (ej: GMAIL | B267102991 | 261.72 EUR).

**Regla**: Si `es_desconocido=True` → `continue` inmediatamente. Añadir a `r["pendientes"]` con motivo `proveedor_real_no_identificado`. No insertar fila fiscal. Etiquetar en Gmail solo en ejecución real.

## L-030 | Anthropic factura+recibo: deduplicar por referencia técnica estable

**Problema**: Anthropic envía dos emails por cargo (factura + recibo). Con `msg_id[:8]` en la ref técnica, cada email generaba una ref distinta → `c_unica` diferente → ambos pasaban el anti-dup → dos filas en el Sheet.

**Raíz**: `c_unica` se calculaba con `num_factura` vacío (antes de asignar la ref técnica). Los sets `_exec_*` no existían; solo `anti_dup` (cargado del Sheet al inicio) podía detectar dups, pero la primera factura aún no estaba en el Sheet durante la misma ejecución.

**Solución**:
1. Ref técnica usa `md5(prov_code + fecha_iso + total_str)[:8]` — estable entre emails
2. `c_unica` se recomputa DESPUÉS de asignar la ref técnica
3. Sets intra-ejecución `_exec_claves`, `_exec_prov_num`, `_exec_hashes` detectan dups en la misma pasada antes de llegar a "Habria insertado" o `escribir_fila()`

## L-031 | resumen.py: base imponible puede estar vacía en el Sheet; derivar si hay IVA

**Problema**: Algunas filas SOLS tienen la celda BASE vacía (campo no escrito por el procesador en ciertos paths). El resumen mostraba base=0 para esas facturas aunque IVA€ y Total eran correctos.

**Regla**: Si `base==0 and iva>0 and total>iva` → `base = round(total - iva, 2)`. La condición `iva>0` garantiza que Canva/Anthropic (sin IVA) no reciban base inventada.

## L-032 | Protocolo obligatorio antes/después de ejecución real trimestral

**Antes de ejecutar real**:
1. `python scripts\procesar_facturas.py --modo incremental --desde YYYY-MM-DD --hasta YYYY-MM-DD --skill-dir . --dry-run`
2. Revisar que "Errores: 0" y que los "Habria registrado" son los esperados
3. Revisar que no aparece el mismo proveedor+importe más de una vez

**Después de ejecutar real**:
1. `python scripts\detectar_duplicados_sheet.py --skill-dir .` → debe decir "0 duplicados"
2. `python scripts\resumen.py --periodo trimestral --skill-dir .` → verificar cifras coherentes
3. No repetir ejecución real del mismo rango si ya fue validado

## L-033 | THCLOTHES RITI / IVA 0%: siempre estado Revisar

**Problema**: Facturas THCLOTHES (Portugal → España) tienen IVA 0% por régimen RITI
(inversión del sujeto pasivo intracomunitario). El código las marcaba como "Registrada"
antes de la revisión fiscal del gestor.

**Regla**: Si `datos_pdf["iva_pct"] == 0` Y las notas contienen "RITI", "IVA 0pct",
"exencion" o "intracomunit" → `determinar_estado()` devuelve siempre `Revisar`.
No se registran como deducibles hasta que Carlos las valide.

**Aplica en**: `determinar_estado()` — antes del `return ESTADOS["REGISTRADA"]` final.

## L-034 | Fechas: normalizar a ISO en todos los puntos de comparación

**Problema**: `anti_dup.es_duplicado()` Capa 6 compara prov+fecha+total. Si la fecha
en el Sheet está en formato "Jun 13, 2026" y la del PDF sale como "2026-06-13", la Capa 6
no detecta el duplicado y la factura se registra dos veces.

**Regla**: Normalizar a ISO `YYYY-MM-DD` en CUATRO puntos:
1. `_cargar()` — al leer filas del Sheet en memoria al inicio.
2. `es_duplicado()` caller — antes de pasar `fecha=` al anti-dup.
3. `registrar()` — al añadir al set intra-ejecución.
4. `escribir_fila()` — al escribir columna A en el Sheet.

**Formatos soportados**: ISO directo, "Month DD YYYY" EN, "DD Month YYYY", "DD/MM/YYYY",
"Fri, DD Month YYYY" (con día de semana prefijado).

**Aplica en**: todos los parsers de proveedores; especialmente crítico para Anthropic
(fecha "June 13, 2026") y SOLS (fecha "13/06/2026").

## L-035 | Anthropic invoice + receipt del mismo cargo cuentan una sola vez

**Problema**: Anthropic envía en el mismo email una factura (`invoice_*.pdf`) y un
recibo (`receipt_*.pdf`). Ambos tienen el mismo importe. Sin filtro, el recibo se
insertaba como segunda fila en el Sheet aunque la factura ya estuviese registrada
o detectada como duplicada.

**Regla**: Flag `_anthropic_invoice_en_msg` por mensaje Gmail.
- Se activa si en el mismo `msg_id` se registra O se detecta como duplicada una
  invoice Anthropic (`tipo_doc` in factura / factura_digital / factura_recibo_digital).
- Si el flag está activo y aparece un `factura_recibo_digital` Anthropic → se descarta
  con motivo "Anthropic receipt omitido: invoice asociada ya registrada/duplicada en mismo email".

**No aplica** a otros proveedores. Solo a Anthropic por su patrón email conocido.

**Aplica en**: `_ejecutar()` — inicializar flag antes del loop de attachments por mensaje,
activar en caso duplicate/registro exitoso, comprobar antes del upload a Drive.

## L-036 | REF_TECNICA para proveedores sin num_factura legible: criterios de seguridad

**Problema**: Muchos proveedores españoles emiten facturas en PDF donde pdfplumber no
puede extraer el número de factura (diseño escaneado, campo en imagen, formato no
estándar). Sin num_factura, el sistema bloquea la inserción como PENDIENTE_EXTRACCION.

**Solución**: `PROVEEDORES_REF_TECNICA` — lista de proveedores de confianza que reciben
una referencia técnica estable `PROVCODE_FECHA_TOTAL_HASH8` cuando:
  1. `_sin_num == True` (num_factura no extraíble)
  2. `tiene_total == True` (total > 0 sí extraído)
  3. Proveedor en `PROVEEDORES_REF_TECNICA`

**Criterios para incluir un proveedor**:
- Proveedor real conocido (en `proveedores.json` o con email verificado)
- Total se extrae correctamente en el dry-run
- Riesgo fiscal bajo (proveedor recurrente, importes coherentes con el negocio)
- NO es banco, NO es proveedor ambiguo, NO es GMAIL genérico

**No incluir nunca**: BBVA, bancos, GMAIL genérico, proveedores con total=None.

**Aplica en**: `_ejecutar()` — bloque REF_TECNICA tras comprobar `_pendiente_extraccion`.

## L-037 | GMAIL genérico no debe registrarse automáticamente como factura fiscal

**Problema**: Algunos PDFs llegan de remitentes genéricos de Gmail (p.ej. facturas
remitidas por forwarding o generadas por herramientas) y el sistema no puede identificar
al proveedor real. Registrarlos como "GMAIL" contamina el registro fiscal.

**Regla**: Si el proveedor no se identifica (`es_desconocido=True` o `nombre=="GMAIL"`),
el sistema debe:
  1. Registrar como PENDIENTE con motivo `proveedor_no_identificado`.
  2. NO insertar fila en el Sheet.
  3. Etiquetar en Gmail con label `bordagran-pendiente` (solo en modo real).
  4. Reportar en el resumen para revisión manual.

**Excepciones**: Solo se puede procesar un GMAIL si, al abrir el PDF, el proveedor
real es identificable de forma inequívoca por nombre+CIF+dirección. Eso requiere
parser específico, no automatización genérica.

## L-038 | BBVA no debe automatizarse como factura fiscal

**Problema**: BBVA envía por email justificantes bancarios, resúmenes de cuenta,
avisos de cargo y confirmaciones de transferencia. Ninguno de estos documentos es
una factura fiscal deducible. Automatizarlos como factura insertaría gastos incorrectos.

**Regla**: BBVA no debe incluirse en `PROVEEDORES_REF_TECNICA` ni en ningún path
que produzca inserción automática en el Sheet fiscal.
Los documentos BBVA quedan siempre como PENDIENTE para revisión manual.
Si en el futuro BBVA emite una factura real de comisiones, debe validarse caso por caso.

## L-039 | Lock NTFS: el sandbox Linux no puede eliminar locks creados en Windows

**Problema**: El archivo `runtime/procesar_facturas.lock` se crea desde Windows.
El sandbox Linux del agente (mount NTFS) puede leer su `stat` pero no puede hacer
`unlink()` ni `write_text()` sobre él. El flag `--forzar` falla con
`PermissionError: [Errno 1] Operation not permitted`.

**Síntoma**: El script imprime "DRY-RUN: SI" y "Skill dir: ." pero no llega a
procesar nada — crashea en `lock.liberar()` antes de `_ejecutar()`.

**Solución**: Juan debe eliminar el lock desde PowerShell Windows:
```powershell
del C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran\runtime\procesar_facturas.lock
```
Después el agente puede volver a lanzar el dry-run sin `--forzar`.

**Aplica en**: cualquier sesión cowork donde el agente lanza el script desde Linux
y una ejecución anterior lo dejó con lock activo.

## L-040 | PowerShell Windows cp1252: logging debe ser encoding-safe

**Problema**: PowerShell en Windows usa codepage cp1252 por defecto. Los símbolos
Unicode que no existen en cp1252 (→, ❌, ⚠️, ✅, ─) generan `UnicodeEncodeError`
al hacer `print()`, rompiendo el script antes de completar el dry-run.

**Error observado**:
```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'
  line 1745: log(f"  → Duplicado: {motivo_dup}")
```

**Solución**:
1. `configurar_salida_segura()`: llama `sys.stdout.reconfigure(encoding='utf-8', errors='replace')`
   al inicio de `main()`. Esto hace que stdout use UTF-8 con reemplazo en lugar de cp1252.
2. `log()` blindada con `try/except UnicodeEncodeError`: fallback a ASCII con `encode('ascii','replace')`.
3. `print()` directos con emoji reemplazados por etiquetas ASCII: `❌` → `[ERROR]`, `⚠️` → `[WARN]`,
   `→` → `>`.

**Regla**: cualquier script ejecutable en Windows (procesar_facturas.py, resumen.py,
detectar_duplicados_sheet.py) debe tener salida segura. Los símbolos visuales no pueden
hacer crashear un dry-run o ejecución real.

**Aplica en**: `configurar_salida_segura()` + `log()` en `procesar_facturas.py`.
Considerar aplicar también a `resumen.py` y `detectar_duplicados_sheet.py`.

---

## L-041 | Apleona es cliente de Bordagran — nunca proveedor (v3.2.0)

**Fecha**: 2026-06-22

**Problema**: Emails de `compras.es-fm@apleona.com` y PDFs reenviados desde Gmail
(`GMAIL_B267...`, `Order_B267...`) llegaban al pipeline y se registraban como facturas
de proveedor o quedaban como pendientes.

**Contexto**: Apleona es cliente de Bordagran — le compra bordados/DTF. Sus documentos
son pedidos que Bordagran debe ejecutar, no facturas de gasto de Bordagran.

**Corrección**:
1. `compras.es-fm@apleona.com` a `exclusiones.json` con `accion: no_insertar_facturas`.
2. Filename override: `Order_B267*` / `GMAIL_B267*` / `B267\d{6,}` en nombre_pdf a `tipo_doc = "cliente_no_proveedor"`.
3. Safety net en bloque `if es_desconocido:` — si B267 en nombre_pdf o num_factura: `no_fiscales`, no pendientes.

**Regla operativa permanente**:
> APLEONA = cliente de Bordagran. Sus documentos nunca generan gasto fiscal de Bordagran.
> No automatizar. No insertar. Clasificar siempre como `cliente_no_proveedor`.

---

## L-042 | DIPGRA no es proveedor ni gasto automatizable (v3.2.0)

**Fecha**: 2026-06-22

**Problema**: `info_tributos@dipgra.es` y `no_responder.tributos@dipgra.es`
(Diputacion Provincial de Granada) enviaban documentos de tributos/tramites que el
pipeline intentaba procesar como facturas.

**Corrección**: Ambos emails en `exclusiones.json`.

**Regla operativa permanente**:
> DIPGRA = administracion publica. Sus documentos (tributos, notificaciones, expedientes)
> NO son facturas de proveedor deducibles de Bordagran. NUNCA automatizar.

---

## L-043 | Radiokable: parser PDF, slash opcional en num_factura (v3.2.0)

**Fecha**: 2026-06-22

**Problema**: Radiokable usa numero `2026/AA/873233` — el slash entre `AA` y los digitos
es opcional segun el PDF. El patron anterior fallaba cuando no estaba presente.

**Corrección**: Patron actualizado a `r"FACTURA\s+(20\d{2}/[A-Z]{2}/?[\d]+)"` — `/?` hace el slash opcional.

**Reglas**:
1. Radiokable usa SIEMPRE PDF adjunto. No buscar en cuerpo del email.
2. Emails validos: `facturas@radiokable.net`, `radiokable@radiokable.net`.

---

## L-044 | Correcciones de clasificacion fiscal: documentar siempre en LECCIONES_APRENDIDAS (v3.2.0)

**Fecha**: 2026-06-22

**Problema recurrente**: Cada sprint descubre clasificaciones incorrectas. Sin documentacion,
los mismos errores reaparecen en sprints futuros o al refactorizar.

**Regla operativa permanente**:
> Cuando Juan o el gestor fiscal corrijan una clasificacion erronea (tipo_doc incorrecto,
> proveedor mal identificado, importe mal extraido), documentar INMEDIATAMENTE:
> — clasificacion incorrecta anterior
> — clasificacion correcta
> — contexto fiscal que lo justifica
> — cambio de codigo que lo arregla
>
> Esto evita repetir el mismo error en sprints futuros.

---

## L-045 | OKTextil / Textil 50-50: proveedor intracomunitario, IVA 0%, estado Revisar (v3.2.0)

**Fecha**: 2026-06-22

**Proveedor**: TEXTIL 50-50 S.L.U., CIF B-02258614. Emails: `firma-e@oktextil.com` / `roly@oktextil.com`.

**Caracteristicas**:
- Estructura bilingue FACTURA/INVOICE (mismo formato que GOR Factory). CIF marcador: `ESB02258614`.
- IVA 0% intracomunitario — estado forzado a `Revisar` para validacion fiscal.

**Regla**: OKTextil NUNCA debe registrarse como `Registrada` automaticamente. Siempre `Revisar`.

---

## L-046 | Niba Energia: PDF ilegible — insertar como Revisar, nunca inventar datos (v3.2.0)

**Fecha**: 2026-06-22

**Problema**: Niba Energia envía PDFs sin texto extraible por pdfplumber (cifrados/escaneados).
El sistema los clasificaba como `desconocido` y los perdia en pendientes sin referencia.

**Corrección**:
- `PROVEEDORES_PDF_ILEGIBLE = {"nibaenergia", "niba energia", "niba"}`.
- Gate antes del clasificador fiscal: si proveedor en lista Y `texto_raw == ""` -->
  `num_factura = "NIBA-ILEGIBLE-{hash10}"`, `tipo_doc = "factura"`, `_niba_pdf_ilegible = True`, estado `Revisar`.

**Regla operativa permanente**:
> Si el PDF de Niba es ilegible: NO inventar datos. Insertar con referencia NIBA-ILEGIBLE-{hash}
> y estado Revisar. El hash garantiza trazabilidad. Revision manual requerida (OCR o consulta a Niba).

---

## L-047 | GOR Factory: separar remitentes de facturas vs. contacto/pedidos (v3.2.0)

**Fecha**: 2026-06-22

**Emails GOR Factory**:
- `invoices@gorfactory.es` / `administracion@gorfactory.es` -> facturas reales (insertar)
- `c76@gorfactory.es` -> contacto comercial y confirmaciones de pedido (no insertar automaticamente)

**Regla para Order_\*.pdf de GOR**:
> Si `nombre_pdf.startswith("Order_")` Y proveedor = GOR Factory -> `tipo_doc = "pedido"` (no fiscal).
> NO aplicar keyword global "order" -- solo override por filename para GOR.
> El sufijo `_ZRD1` no tiene significado fiscal para Bordagran.

---

## L-048 | GOR Factory PDF bilingue: boilerplate legal no es "presupuesto" (v3.2.0)

**Fecha**: 2026-06-22

**Problema**: Pagina 2 del PDF GOR contiene la palabra "presupuesto" en texto legal generico.
El clasificador lo marcaba como `presupuesto` antes de detectar `factura`.

**Corrección**: Detector de estructura bilingue FACTURA/INVOICE anadido en `clasificar_tipo_documento()`
ANTES del check de presupuesto. Marcadores: `"no factura / invoice"`, CIF `ESA73089286`, `"total / total amount"`.

**Regla**:
> La deteccion de estructura bilingue FACTURA/INVOICE SIEMPRE tiene precedencia sobre keywords
> de presupuesto/proforma. Un PDF con estructura INVOICE confirmada no puede ser presupuesto.

---

## L-049 | Apleona reenviada desde Gmail: la exclusion de email no basta (v3.2.0)

**Fecha**: 2026-06-22

**Problema**: Cuando un pedido de Apleona se reenvía a `bordagran@gmail.com`, el pipeline
ve el remitente como Gmail, no como Apleona. La exclusion en `exclusiones.json` no aplica.

**Síntoma**: PDFs `GMAIL_B267102991.pdf` aparecian como pendientes con proveedor "GMAIL".

**Corrección en dos capas**:
1. Filename override (antes del gate fiscal): `re.search(r"B267\d{6,}", nombre_pdf)` -> `cliente_no_proveedor`.
2. Safety net (dentro de `if es_desconocido:`): intercepta cualquier B267 que escape al override.

**Regla**:
> Cuando un cliente reenvía sus propios pedidos a Gmail, el remitente visible es Gmail.
> No basta excluir el email del cliente. Cubrir tambien el patron del contenido (filename, num_factura).

---

## L-050 | BBVA no es proveedor fiscal: exclusiones, no REF_TECNICA (v3.2.0)

**Fecha**: 2026-06-22

**Corrección**: `notificaciones-bbva@bbva.com` a `exclusiones.json`.
Motivo: justificantes bancarios no son facturas deducibles.

**Regla operativa permanente**:
> BBVA y cualquier entidad bancaria NO pueden figurar en `PROVEEDORES_REF_TECNICA`.
> Sus documentos no son facturas deducibles. Si en el futuro hay comision bancaria facturable,
> validar manualmente caso por caso.

---

## L-051 | GOR ZRD1: cuando el parser falla, usar fallback manual validado (v3.2.0)

**Fecha**: 2026-06-22

**Problema**: `2011054508_ZRD1.PDF` de GOR Factory -- pdfplumber extrae el texto pero
la tabla de totales tiene layout de columnas que los patrones regex no capturan. Resultado: `total=None`.

**Datos verificados con PDF real**:
```
num = "2011054508" | fecha = "2026-05-11"
base = 82.74 EUR | IVA = 17.38 EUR (21%) | total = 100.12 EUR
```

**Corrección**: Override especifico para `nombre_pdf.upper() == "2011054508_ZRD1.PDF"` con
proveedor GOR Factory. Valores hardcodeados, validados manualmente. `_pendiente_extraccion = False`.

**Principio general**:
> Cuando un PDF de proveedor conocido no puede parsearse automaticamente:
> (a) intentar fallback regex mas flexible;
> (b) si sigue fallando, insertar los valores validados manualmente con nota explicita.
> NUNCA dejar el gasto fuera del registro fiscal.
> El fallback manual debe ser lo mas especifico posible: solo para ese filename exacto.

