# gmail-facturas-bordagran

Automatización fiscal para **Bordagran** — descarga facturas PDF de Gmail, las sube a Drive y las registra en Google Sheets sin duplicados.

---

## Requisitos

- Python 3.9+
- Proyecto Google Cloud `bordagran-fiscal` con APIs habilitadas: Gmail, Drive, Sheets
- Archivo `credentials.json` (OAuth2 Desktop) descargado desde GCP Console
- Archivo `config.json` con los IDs del Sheet y Drive

---

## Instalación

**Ruta oficial de instalación:** `C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran`

Para instalar desde el Escritorio: hacer doble clic en `INSTALAR_BORDAGRAN.bat`.

```bash
# 1. Instalar dependencias
pip install -r requirements.txt --break-system-packages

# 2. Colocar credentials.json en esta carpeta
#    Ve a console.cloud.google.com → APIs & Services → Credentials → Download

# 3. Verificar entorno
python scripts/verificar_entorno.py --skill-dir "C:\ClaudeProyectos\Bordagran\gmail-facturas-bordagran"

# 4. Crear labels Gmail (solo la primera vez)
python scripts/setup_labels.py --skill-dir .

# 5. Primera ejecución — backfill Q2 2026
python scripts/procesar_facturas.py --modo backfill --desde 2026-04-01 --hasta 2026-06-30 --skill-dir .
```

---

## Uso diario

```bash
# Procesar facturas de los últimos 7 días
python scripts/procesar_facturas.py --modo incremental --skill-dir .

# Procesar últimas 24h
python scripts/procesar_facturas.py --modo incremental --dias 1 --skill-dir .

# Ver resumen del día
python scripts/resumen.py --periodo diario --skill-dir .

# Ver resumen semanal
python scripts/resumen.py --periodo semanal --skill-dir .

# Testear extracción de un PDF concreto
python scripts/test_extraccion_pdf.py /ruta/factura.pdf --verbose
```

---

## Estructura del proyecto

```
gmail-facturas-bordagran/
├── SKILL.md                        ← Instrucciones para Claude
├── README.md                       ← Este archivo
├── CHANGELOG.md
├── LECCIONES_APRENDIDAS.md
├── config.json                     ← IDs Sheet/Drive/Labels
├── credentials.json                ← NO en git (OAuth2 GCP)
├── token.pickle                    ← NO en git (generado automático)
├── requirements.txt
├── .gitignore
├── scripts/
│   ├── procesar_facturas.py        ← Procesamiento principal
│   ├── resumen.py                  ← Generador de resúmenes
│   ├── verificar_entorno.py        ← Comprobación pre-ejecución
│   ├── setup_labels.py             ← Crea labels Gmail
│   └── test_extraccion_pdf.py      ← Test de extracción PDF
├── references/
│   └── proveedores.json            ← 25 proveedores reconocidos
├── runtime/                        ← Archivos temporales (no en git)
│   ├── .gitkeep
│   ├── procesar_facturas.lock      ← Lock de ejecución
│   ├── ultimo_resultado.json       ← Resultado del último proceso
│   └── resumen_*.json              ← Resúmenes guardados
└── tests/
    └── README.md
```

---

## Columnas del Google Sheet (pestaña "Facturas")

| Col | Campo | Descripción |
|-----|-------|-------------|
| A | Fecha factura | Extraída del PDF |
| B | Trimestre | Q1/Q2/Q3/Q4 calculado |
| C | Proveedor | Nombre del proveedor |
| D | Email proveedor | Remitente del email |
| E | Nº Factura | Número extraído del PDF |
| F | Concepto | Primera línea descriptiva |
| G | Base imponible | Float |
| H | IVA % | 21, 10, o 4 |
| I | IVA € | Float |
| J | Importe total | Float |
| K | Ruta PDF (Drive) | URL del PDF en Drive |
| L | Estado | Registrada / Revisar / Duplicada / Error lectura / Validada Carlos |
| M | Notas | Avisos del extractor |
| N | Fecha proceso | Timestamp de procesamiento |
| O | Gmail Message ID | ID del mensaje en Gmail |
| P | Gmail Attachment ID | ID del adjunto en Gmail |
| Q | Hash PDF | SHA256 del PDF (anti-dup) |
| R | Clave Única Factura | MD5(proveedor+num+fecha+total) |

---

## Anti-duplicados

El sistema usa 4 capas de protección:

1. **Hash SHA256** del PDF binario → columna Q
2. **Clave única** `proveedor+num_factura+fecha+importe` hasheada → columna R
3. **Gmail message_id + attachment_id** → columnas O+P
4. **URL en Drive** → columna K

Al arrancar, `AntiDuplicados` carga todas las columnas O-R del Sheet en memoria para comparación O(1).

---

## Estructura Drive

```
Drive/
└── Facturas 2026/
    ├── Q1-2026/
    │   └── 2026-01-15_VELILLA_GROUP_F2026-001_1234EUR.pdf
    ├── Q2-2026/
    ├── Q3-2026/
    └── Q4-2026/
```

---

## Seguridad

- `credentials.json` y `token.pickle` nunca se suben a git
- Sin esos archivos, el script para y muestra instrucciones claras
- Tokens y credenciales nunca aparecen en logs
- Ver `.gitignore` para lista completa de exclusiones

---

## Proveedores reconocidos

Ver `references/proveedores.json`. Actualmente: **25 proveedores**.

Si llega un email de un remitente no reconocido:
- Se procesa igualmente usando el dominio como nombre provisional
- Se marca con estado `Revisar`
- Se etiqueta con `Facturas/PendienteRevision` en Gmail

Para añadir un proveedor nuevo, editar `proveedores.json`:
```json
{
  "nombre": "Nombre Proveedor",
  "emails": ["factura@proveedor.es"],
  "matchType": "exact",
  "activo": true
}
```

---

## Tareas programadas (ya configuradas en Claude)

| Cron | Acción |
|------|--------|
| `0 20 * * *` | Resumen diario (20:00 todos los días) |
| `0 8 * * 1` | Resumen semanal (lunes 8:00) |
