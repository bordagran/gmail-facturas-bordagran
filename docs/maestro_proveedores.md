# MAESTRO_PROVEEDORES — Diseño y Especificación

**Versión**: v3.3.0 rev2 (columnas de validación añadidas)
**Fecha**: 2026-06-23
**Pestaña en Google Sheets**: `MAESTRO_PROVEEDORES`

---

## Propósito

`MAESTRO_PROVEEDORES` es una pestaña auxiliar de Google Sheets que centraliza:

- La lista de proveedores detectados por el script.
- El nombre normalizado de cada proveedor.
- Los criterios fiscales (tipo IVA, estado por defecto, acción automática).
- El estado de validación manual por Juan/Carlos.
- El historial de primera y última detección.
- Notas operativas para revisión humana.

**No es la hoja operativa.** La hoja operativa sigue siendo `FACTURA PROVEEDORES`.
El Maestro se lee al inicio de cada ejecución para clasificar proveedores.
Solo escribe el script para añadir proveedores nuevos (modo real, nunca dry-run).

---

## Columnas — 15 en total (A–O)

| Col | Nombre | Tipo | Descripción |
|-----|--------|------|-------------|
| A | Proveedor detectado | Texto | Nombre tal como aparece en el email o PDF |
| B | Proveedor normalizado | Texto | Nombre canónico oficial |
| C | Email / dominio origen | Texto | Dominio o dirección de email del remitente |
| D | Categoría | Enum | Clasificación del tipo de proveedor |
| E | Tipo fiscal | Enum | Régimen fiscal aplicable |
| F | Estado por defecto | Enum | Estado base que el script asignará (puede ser elevado a Revisar por otras reglas) |
| G | Proveedor seguro | Enum | Si puede procesarse automáticamente (Sí/No) |
| H | Acción automática | Enum | Qué debe hacer el script con este proveedor |
| I | **Estado validación proveedor** | Enum | Estado del proceso de validación manual |
| J | **Validado por** | Texto | Quién validó el proveedor (Juan, Carlos, etc.) |
| K | **Fecha validación** | Fecha | Fecha en que se marcó como Validado |
| L | **Criterio validado** | Texto | Descripción breve del criterio de validación |
| M | Primera detección | Fecha | Primera vez que el script lo detectó |
| N | Última detección | Fecha | Última vez que apareció en procesamiento |
| O | Notas | Texto | Observaciones fiscales o de revisión |

---

## Valores permitidos por columna

### Categoría (col D)
```
Textil proveedor
Material DTF
Suministro energia
Transporte
Software / SaaS
Hosting / Web
Papeleria / Oficina
Pendiente
No proveedor fiscal
```

### Tipo fiscal (col E)
```
Nacional con IVA
Intracomunitario / RITI
Nacional sin IVA
Suministro
Pendiente
No fiscal
```

### Estado por defecto (col F)
```
Registrada
Revisar
Nuevo / Pendiente clasificar
Excluido
```

### Proveedor seguro (col G)
```
Si
No
```

### Acción automática (col H)
```
Registrar con control
Registrar siempre como Revisar
No registrar automatico
Excluir
```

### Estado validación proveedor (col I) — NUEVO
```
Pendiente
Validado
Revisar siempre
Excluido
```

---

## Reglas funcionales del campo Estado validación proveedor

### Pendiente
- El proveedor ha sido detectado pero aún no ha sido revisado por Juan o Carlos.
- Toda factura de este proveedor entra como `Revisar`.
- Nota en la factura: `Proveedor pendiente de validacion en MAESTRO_PROVEEDORES`.
- No puede entrar como `Registrada` bajo ninguna circunstancia.
- Siempre se asigna automáticamente cuando el script añade un proveedor nuevo.

### Validado
- Juan o Carlos han revisado el proveedor y confirmado que es un proveedor fiscal legítimo.
- Las futuras facturas de este proveedor pueden entrar como `Registrada`
  **siempre que** todos los controles fiscales sean correctos.
- Un proveedor Validado **no implica aprobar todas sus facturas sin control**.
  La factura sigue entrando como `Revisar` si hay:
  - IVA anómalo (ej: 0% sin clasificación RITI explícita)
  - Fecha sospechosa (trimestre no cuadra, fecha futura, etc.)
  - Falta de PDF real (cuerpo de email, enlace con autenticación)
  - Importe o número de factura incompleto
  - Operación intracomunitaria / RITI
  - Cualquier regla especial activa (THClothes L-053, Niba L-054, etc.)
  - Cualquier otra alerta fiscal detectada por el script

### Revisar siempre
- Todas las facturas de este proveedor entran como `Revisar`, sin excepción.
- No hay bypass posible aunque los datos sean completos y correctos.
- Se usa para proveedores con casuística fiscal compleja que requiere
  revisión humana en cada factura (THClothes, Niba Energía, etc.).

### Excluido
- El proveedor no debe registrarse como gasto fiscal de Bordagran.
- El script no inserta sus facturas en `FACTURA PROVEEDORES`.
- Se registra en `no_fiscales` con motivo explicativo.
- Se usa para: clientes de Bordagran, entidades no proveedoras, DIPGRA, bordagran@gmail.com.

---

## Regla para proveedores nuevos (alta automática)

Cuando el script detecta un proveedor que NO existe en `MAESTRO_PROVEEDORES`
y la pestaña está disponible:

| Campo | Valor automático |
|-------|-----------------|
| Proveedor detectado | Nombre detectado tal cual |
| Proveedor normalizado | (vacío — para rellenar manualmente) |
| Email / dominio origen | Remitente del email |
| Categoría | Pendiente |
| Tipo fiscal | Pendiente |
| Estado por defecto | Revisar |
| Proveedor seguro | No |
| Acción automática | No registrar automatico |
| Estado validación proveedor | **Pendiente** |
| Validado por | (vacío) |
| Fecha validación | (vacío) |
| Criterio validado | (vacío) |
| Primera detección | Fecha de ejecución actual |
| Última detección | Fecha de ejecución actual |
| Notas | Añadido automáticamente por el script v3.3.0 |

**Para la factura actual de ese proveedor:**
- Estado: `Revisar`
- Nota: `Proveedor nuevo pendiente de validacion en MAESTRO_PROVEEDORES`

**Para futuras ejecuciones hasta que Juan/Carlos lo valide:**
- El proveedor ya existe en el Maestro con `Estado validación proveedor = Pendiente`.
- Todas sus facturas siguen entrando como `Revisar`.

**El sistema puede aprender, pero no puede inventarse criterios fiscales.**

---

## Proceso de validación manual de un proveedor nuevo

1. Juan o Carlos abre la pestaña `MAESTRO_PROVEEDORES` en Google Sheets.
2. Busca el proveedor con `Estado validación proveedor = Pendiente`.
3. Revisa la ficha: nombre, email, categoría, tipo fiscal.
4. Toma una decisión:

   **Opción A — Validar como proveedor real:**
   - Cambia `Estado validación proveedor` → `Validado`
   - Completa `Categoría`, `Tipo fiscal`, `Acción automática`
   - Cambia `Proveedor seguro` → `Si`
   - Rellena `Validado por`, `Fecha validación`, `Criterio validado`
   - La próxima ejecución puede generar `Registrada` si los datos fiscales son correctos.

   **Opción B — Marcar como Revisar siempre:**
   - Cambia `Estado validación proveedor` → `Revisar siempre`
   - Se usa para proveedores reales pero con casuística fiscal compleja.
   - Todas sus futuras facturas entran como `Revisar`.

   **Opción C — Excluir:**
   - Cambia `Estado validación proveedor` → `Excluido`
   - Cambia `Acción automática` → `Excluir`
   - Las futuras facturas no se insertan en `FACTURA PROVEEDORES`.

5. No hay impacto en facturas ya registradas. La validación afecta solo a futuras ejecuciones.

---

## Prioridad de criterios en `determinar_estado()`

El estado de una factura se determina en este orden de prioridad (mayor a menor):

1. **Reglas fijas del script** (independientes del Maestro):
   - Error de lectura → `Error lectura`
   - Hash/clave duplicada → `Duplicada` (no inserta)
   - `es_desconocido = True` (dominio genérico sin proveedor identificado) → `Revisar`
   - PENDIENTE_EXTRACCION_SIN_REGISTRAR (sin total ni num) → no inserta
   - Gate bordagran@gmail.com (L-052) → `no_fiscal`, no inserta

2. **Estado validación proveedor del Maestro**:
   - `Excluido` → no inserta en FACTURA PROVEEDORES
   - `Pendiente` → `Revisar` forzado
   - `Revisar siempre` → `Revisar` forzado
   - `Validado` → continúa a los controles fiscales (punto 3)

3. **Controles fiscales del script** (aunque el proveedor esté Validado):
   - Abono / nota de crédito → `Revisar`
   - PDF ilegible de Niba (L-046) → `Revisar`
   - IVA 0% + RITI/intracomunitario (L-033) → `Revisar`
   - Sin total → `Revisar`
   - Sin número de factura → `Revisar`
   - Falta PDF real (cuerpo email, enlace) → puede quedar `Revisar`

4. **Solo si supera todos los controles**:
   - `Registrada`

**Un proveedor Validado puede generar facturas `Registrada` si y solo si pasa
todos los controles fiscales del punto 3.**

---

## Comportamiento cuando MAESTRO_PROVEEDORES no existe

Si la pestaña no existe en Google Sheets:
- `maestro_data = {}`, `sheet_maestro = None`
- Comportamiento v3.2.1 preservado al 100%
- Warning en el log: `[MAESTRO] Pestana no encontrada — operando sin maestro (v3.2.1)`
- No se pueden añadir proveedores nuevos al Maestro
- No se pueden aplicar criterios de validación

Para activar v3.3.0 completa, la pestaña debe existir con los encabezados correctos.

---

## Archivo semilla JSON

Ruta: `references/maestro_proveedores_seed.json`

Incluye los 15 proveedores conocidos pre-clasificados con todos los campos,
incluyendo `Estado validación proveedor` (ya marcados como `Validado` los
proveedores cuya clasificación está aprobada por Juan).

Ver: `references/maestro_proveedores_seed.json`

---

## Notas de implementación

- El script lee `MAESTRO_PROVEEDORES` al inicio con `get_all_values()`.
- Los encabezados se normalizan con `normalizar_encabezado()` (sin acentos, minúsculas).
- La clave de búsqueda es `normalizar_texto(proveedor_detectado)`.
- Los 15 proveedores de la semilla tienen `Estado validación proveedor = Validado`
  salvo DIPGRA, Apleona y bordagran@gmail.com que tienen `Excluido`.
- Un proveedor nuevo añadido automáticamente por el script tiene `Pendiente`.
- La escritura en `MAESTRO_PROVEEDORES` solo ocurre en modo real y solo para altas nuevas.
- `FACTURA PROVEEDORES` nunca se modifica por lógica del Maestro.
- **No implementar en v3.2.x. Solo en v3.3.0 con dry-run validado.**
