# CLAUDE.md — Memoria operativa del proyecto gmail-facturas-bordagran



Este archivo es de lectura obligatoria al inicio de cada sesión.

Contiene reglas permanentes derivadas de errores reales cometidos.

**Actualizar este archivo cada vez que Juan corrija una decisión o detecte una regresión.**



---



## Memoria operativa obligatoria — errores aprendidos



### 1. El dashboard fiscal es SIEMPRE solo lectura



El dashboard de Bordagran es una web app de Google Apps Script. Lee datos del Sheet

pero **nunca los modifica**. Esta restricción es absoluta y no negociable.



- **NO** escribir en Google Sheets (setValue, setValues, appendRow, clear, deleteRow, etc.)

- **NO** modificar Gmail (marcar, archivar, borrar mensajes)

- **NO** modificar Drive (mover, renombrar, borrar archivos)

- **NO** tocar `scripts/procesar_facturas.py` salvo orden expresa de Juan

- Validar antes de cualquier push: `python scripts\verificar_dashboard_solo_lectura.py`



### 2. Protocolo antes de modificar el dashboard



**Orden obligatorio — no saltarse pasos:**



1. `git status --short` (desde PowerShell en Windows, no desde bash del sandbox)

2. Backup local de los archivos afectados si el cambio es significativo

3. Tocar el mínimo número de archivos posible

4. Aplicar el parche mínimo que resuelva el problema

5. `python scripts\verificar_dashboard_solo_lectura.py`

6. `node --check` sobre el JS extraído (ver script de validación abajo)

7. `git diff --check`

8. **NO** hacer commit ni `clasp push` hasta confirmación visual de Juan

9. Solo tras confirmar: `clasp.cmd push` → publicar versión → verificar en navegador

10. Solo entonces: commit



**Script de validación JS:**

```python

import re

src = open('dashboard/scripts.html', encoding='utf-8').read()

js = '\n'.join(re.findall(r'<script[^>]*>(.*?)</script>', src, re.DOTALL))

open('/tmp/check.js', 'w').write(js)

# luego: node --check /tmp/check.js

```



### 3. Apps Script / clasp — reglas críticas



| Regla | Detalle |

|-------|---------|

| Comando correcto | `clasp.cmd push` (no `clasp push` — PowerShell bloquea .ps1) |

| Directorio de push | `C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran\dashboard` |

| Script ID | `1ZV3lEbhSqze0E7dnMyntXJuAlj6S4N7E3YEzAQ_qUOj7HFd4SI_t_1oE` |

| Archivos requeridos | `dashboard/.clasp.json`, `dashboard/appsscript.json` |

| Publicar versión | Implementar → Gestionar implementaciones → lápiz → Nueva versión → Implementar |

| Sin publicar nueva versión | El URL de deployment sirve el código antiguo aunque se haga push |

| No usar | `clasp create` (sobrescribe el proyecto) |



### 4. Error aprendido: `fmt€` — identificadores JS con caracteres no ASCII (L-056)



`€` (U+20AC) no es un carácter válido de identificador ECMAScript. Apps Script / V8 lo rechaza.



- **Nombre incorrecto:** `fmt€`

- **Nombre correcto:** `fmtEuro`

- Antes de cualquier `clasp push`, extraer el JS y validar con `node --check`

- Si el dashboard queda en "Cargando datos de Google Sheets…" → abrir F12 → buscar SyntaxError

- **Nunca usar caracteres no-ASCII en nombres de funciones JavaScript**



### 5. Error aprendido: cabeceras del Sheet con espacios vs. guiones bajos (L-055)



El Sheet puede usar cabeceras visibles con espacios. `buildIDX()` hace `h.toUpperCase()`

sin normalizar guiones. Resultado: `IDX["NUM_FACTURA"]` no existe si el Sheet tiene "N Factura".



**Nombres internos del código → posibles nombres reales del Sheet:**



| Clave interna | Posibles nombres reales en el Sheet |

|---------------|-------------------------------------|

| `NUM_FACTURA` | "N Factura", "Nº Factura", "Num Factura", "Numero Factura" |

| `BASE` | "Base Imponible", "Base EUR", "Base" |

| `IVA_PCT` | "IVA %", "IVA%", "% IVA", "IVA Porcentaje" |

| `IVA_EUR` | "IVA EUR", "IVA Euros", "IVA €", "Cuota IVA" |

| `TOTAL` | "Importe Total", "Total EUR", "Total Factura" |

| `RUTA_PDF` | "Ruta PDF (Drive)", "Ruta PDF", "URL PDF", "Enlace PDF" |



**Regla:** Toda búsqueda de columna en el dashboard DEBE usar `getColIdx(candidates)`

con lista de variantes. Nunca una sola clave rígida.



### 6. Error aprendido: columna Factura/PDF es ADICIONAL (L-060)



- La columna de enlace PDF **nunca va dentro de `colsShow`**

- Se detecta con `getIdxFacturaPdf()` (función global con 11+ variantes)

- Si no existe en IDX → `idxPdf = -1` → la tabla funciona igual sin ella

- Se añade **al final**: `[columnas originales] + [Factura si idxPdf >= 0]`

- Si el valor no es URL (`http://...`), mostrar `—`



**Columnas originales obligatorias (en este orden):**

Fecha · Trimestre · Proveedor · N Factura · Concepto · Base Imponible · IVA % · IVA EUR · Importe Total · Estado



### 7. Error aprendido: IVA 0% falsy trap (L-057)



```javascript

// INCORRECTO — 0 es falsy:

var ivaPct = parseFloat(row[idxIvaPct]) || null;  // parseFloat("0") || null === null



// CORRECTO:

function parseIvaPctDashboard(valor) {

  var txt = String(valor == null ? "" : valor).trim().replace(/%/g,"").replace(",",".");

  if (!txt || txt === "-") return null;

  var n = parseFloat(txt);

  return isNaN(n) ? null : n;

}

```



**Regla:** Nunca usar `parseFloat(x) || fallback` cuando x puede ser cero.



### 8. Error aprendido: fechas como strings y trimestres sin normalizar (L-058, L-059)



- **Fechas:** Nunca ordenar con `<` / `>` sobre strings "dd/mm/yyyy".

  Usar `parseFechaDashboard(valor)` que convierte a timestamp (ms).

  Google Sheets puede enviar fechas como número serial (días desde 1899-12-30).

- **Trimestres:** Normalizar a "Qn-YYYY" con `normalizarTrimestre()`.

  Si la columna está vacía, derivar desde Fecha con `derivarTrimestreDesdeFecha()`.

  Ordenar con `sortTrimestresDesc()` (valor numérico YYYY*10+Q).



### 9. Error aprendido: git index corrompe en sandbox NTFS (L-062)



El sandbox Linux puede mostrar `fatal: index file corrupt` al ejecutar `git status`.

Esto es un artefacto del mount NTFS — los archivos en disco están correctos.



- **No intentar** reparar el índice desde bash

- Ejecutar `git status` **siempre desde Windows PowerShell** para ver el estado real

- Los cambios de archivo aplicados con Write/Edit son siempre correctos aunque el índice git del sandbox falle



### 10. Protocolo obligatorio cuando Juan detecte una regresión (L-063)



1. PARAR — no aplicar más parches encima

2. Leer la versión funcional: `git show <commit>:dashboard/scripts.html`

3. Diagnosticar causa raíz antes de tocar código

4. Parche mínimo (cambiar lo menos posible)

5. Validar: `node --check` → `verificar_dashboard_solo_lectura.py` → `git diff --check`

6. `clasp.cmd push` solo tras validación

7. Publicar nueva versión en Apps Script

8. Confirmar visualmente (F12 → Console)

9. Commitear

10. Añadir lección a `LECCIONES_APRENDIDAS.md`



### 11. Protocolo de aprendizaje obligatorio



Cada error corregido que Juan detecte debe:

1. Añadirse a `LECCIONES_APRENDIDAS.md` con número correlativo L-XXX

2. Si afecta a la forma de trabajar: actualizar este `CLAUDE.md`

3. Si afecta al skill en producción: actualizar `SKILL.md`



**No basta con "ya está corregido".** La corrección debe quedar escrita para que

futuras sesiones (y futuros agentes) no repitan el mismo error.



---



## Restricciones absolutas del proyecto (recordatorio)



| Restricción | Detalle |

|-------------|---------|

| NO commit sin aprobación de Juan | Nunca `git commit` ni `git push` sin confirmación explícita |

| NO tocar Sheet real | El Sheet de producción solo lo toca `procesar_facturas.py` |

| NO tocar Gmail real | Solo lectura en producción |

| NO tocar Drive real | Solo lectura en producción |

| token.pickle | Solo corre desde Windows PowerShell, nunca desde bash Linux |

| config.json | Nunca en ningún commit |

| DNI | Nunca guardar en ningún sitio |

| Velilla | Proveedor real, nunca excluir, nunca mover a exclusiones |

| DIPGRA | No automatizar nunca |

| APLEONA | Cliente de Bordagran, no proveedor |

| GOR Factory | `invoices@gorfactory.es` = facturas reales; `c76@gorfactory.es` = contacto/pedidos |

| ZRD1 | Sufijo NO es criterio fiscal |

| THClothes + RITI/IVA0 | Estado siempre `Revisar` |

| Facturas antiguas | No modificar automáticamente al validar proveedor en Maestro |

| DIGI / digimobil.es | Proveedor fiscal válido. Facturas emitidas a Elizabeth Vicci son procedentes para Bordagran/autónoma. Estado `Registrada` si extracción completa. NO marcar `Revisar` por titular. NIF/NIE personal NO guardar en repo. (L-064) |



---



##