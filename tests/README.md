# Tests — Gmail Facturas Bordagran

## Ejecución

```bash
python scripts/verificar_entorno.py --skill-dir /ruta/skill
python scripts/test_extraccion_pdf.py --skill-dir /ruta/skill
```

## Tests disponibles

| Script | Qué verifica |
|--------|-------------|
| verificar_entorno.py | credentials.json, config.json, dependencias, conexión Gmail/Sheets |
| test_extraccion_pdf.py | extracción de datos PDF con pdfplumber sobre PDFs de prueba |
