# Dashboard Fiscal HTML — Solo Lectura

**Versión**: v3.3.0
**Fecha**: 2026-06-23
**Tipo**: Google Apps Script Web App (o HTML estático)

---

## Definición de "solo lectura"

El dashboard fiscal HTML es **exclusivamente de lectura**.

### Puede hacer
- Leer datos de `FACTURA PROVEEDORES` con `getValues()` o `get_all_records()`
- Leer datos de `MAESTRO_PROVEEDORES`
- Mostrar tarjetas, gráficos, tablas y alertas
- Calcular totales, agrupaciones y filtros **en memoria del navegador**
- Refrescar la visualización leyendo la hoja de nuevo
- Permitir filtrar, ordenar y agrupar visualmente
- Exportar una vista filtrada como CSV (solo lectura de pantalla)

### No puede hacer — PROHIBIDO
El dashboard **no contiene, no llama y no ejecuta** ninguna de estas funciones:

```
setValue        setValues       appendRow       clear
deleteRow       insertRow       update          remove
move            copyTo          sort            protect
setNumberFormat setBackground   setFont         setFormula
```

Cuando se diga "actualizar dashboard" significa:
```
Volver a leer los datos de la hoja y refrescar la visualización.
```
Nunca significa modificar la hoja.

---

## Validación de solo lectura

El script `scripts/verificar_dashboard_solo_lectura.py` valida automáticamente
que el código del dashboard no contiene ninguna función de escritura.

Ejecutar con:
```powershell
python scripts/verificar_dashboard_solo_lectura.py
```

Debe terminar con `OK — dashboard limpio de funciones de escritura`.
Si falla, muestra el archivo y línea donde se encontró la función prohibida.

---

## Arquitectura

```
dashboard/
├── README.md          ← Instrucciones de despliegue
├── Code.gs            ← Apps Script: servidor (solo lee Sheets)
├── Index.html         ← HTML principal del dashboard
├── styles.html        ← CSS incluido con <?!= include('styles') ?>
└── scripts.html       ← JS del cliente (filtros, gráficos, alertas)
```

El dashboard se despliega como Google Apps Script Web App con acceso restringido
al propietario. No es público.

---

## Tarjetas resumen (KPIs principales)

```
┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Total       │ │ Base        │ │ IVA         │ │ Total       │
│ facturas    │ │ imponible   │ │ soportado   │ │ importe     │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘

┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Registradas │ │ En Revisar  │ │ Pendientes  │ │ Proveedores │
│             │ │             │ │             │ │ nuevos      │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘

┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
│ Sin PDF     │ │ IVA         │ │ Fechas      │ │ Intracom.   │
│ real        │ │ anómalo     │ │ sospechosas │ │ / RITI      │
└─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

---

## Filtros disponibles

- Año
- Trimestre (Q1/Q2/Q3/Q4)
- Mes
- Proveedor
- Estado (`Registrada`, `Revisar`, `Validada Carlos`, etc.)
- Categoría
- Tipo fiscal
- Proveedor seguro (Sí/No)
- Acción automática

---

## Gráficos

| Gráfico | Tipo |
|---------|------|
| Gasto por mes | Barras |
| Gasto por trimestre | Barras agrupadas |
| Top proveedores por gasto | Barras horizontales |
| IVA soportado por trimestre | Línea |
| Facturas por estado | Tarta |
| Facturas por categoría | Tarta |
| Evolución mensual del gasto | Línea |

---

## Tablas

| Tabla | Descripción |
|-------|-------------|
| Facturas filtradas | Vista completa con todos los filtros aplicados |
| Facturas en Revisar | Solo las que necesitan revisión manual |
| Proveedores nuevos sin clasificar | Pendientes de configuración en Maestro |
| Alertas fiscales | Lista priorizada de anomalías |
| Ranking de proveedores | Por importe total |
| Resumen mensual | Totales por mes |
| Resumen trimestral | Totales por trimestre |
| Resumen anual | Totales del año |

---

## Alertas semáforo

### Verde — Correcto
- Factura completa con todos los campos
- IVA coherente con tipo fiscal
- Fecha dentro del rango
- Proveedor en Maestro y marcado como seguro

### Amarillo — Revisar
- THClothes (intracomunitario / RITI)
- Niba Energía (falta factura real)
- Factura con IVA 0% sin clasificación RITI explícita
- Proveedor nuevo sin clasificar en Maestro
- Fecha que parece correcta pero fuera del rango habitual

### Rojo — Posible error fiscal o dato incompleto
- Factura sin número
- Total = 0 o vacío
- IVA detectado incorrectamente (ej: VIVADTF fila 7)
- Fecha sospechosa (ver criterios abajo)
- Proveedor excluido que aparece en FACTURA PROVEEDORES

---

## Criterios de fecha sospechosa

Una fecha se marca como sospechosa si cumple alguna de estas condiciones:

1. **Fuera del rango ejecutado**: la fecha de la factura está fuera del rango `--desde / --hasta` que se usó en la última ejecución.
2. **Trimestre incoherente**: el trimestre calculado de la fecha no coincide con el que aparece en la columna B.
3. **Fecha futura**: la fecha es posterior a la fecha de proceso (columna N).
4. **Extraída desde número de factura**: la fecha parece haber sido tomada del número de factura en lugar del cuerpo del PDF (ej: GOR fila 16).
5. **Contradice periodo**: la fecha es de un año diferente al que se procesaba.

Alerta: `🔴 Fecha sospechosa` con tooltip explicando el motivo.

---

## Ejemplo de alertas en tabla

| Factura | Proveedor | Alerta | Motivo |
|---------|-----------|--------|--------|
| FES.2026/0042 | THClothes | 🟡 Amarillo | Intracomunitario / RITI — revisión fiscal obligatoria |
| NIBA-ENLACE-3f7a2c | Niba Energía | 🟡 Amarillo | Falta factura real — enlace con autenticación |
| VIVADTF-xxx | VIVADTF | 🔴 Rojo | IVA detectado incorrectamente |
| 2011054508 | GOR Factory | 🔴 Rojo | Fecha sospechosa — posible fecha del num factura |

---

## Notas de despliegue

1. Abrir Google Apps Script en el Sheets de Bordagran.
2. Crear nuevo proyecto de script.
3. Copiar `Code.gs`, `Index.html`, `styles.html`, `scripts.html`.
4. Desplegar como Web App: ejecutar como yo, acceso solo yo.
5. La URL del dashboard es privada — no compartir.
6. **No añadir permisos de escritura al script.**

---

## Notas de seguridad

- El script de Apps Script usa solo `SpreadsheetApp.openById().getSheetByName().getValues()`.
- No usa `SpreadsheetApp.getActiveSpreadsheet()` para evitar accidentalmente afectar la hoja activa.
- No tiene botones que modifiquen datos.
- No tiene formularios de entrada que escriban en Sheets.
- Toda interacción del usuario (filtros, orden) opera sobre una copia en memoria de los datos.
