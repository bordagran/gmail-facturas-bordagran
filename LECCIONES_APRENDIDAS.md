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

