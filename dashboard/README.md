# Dashboard Fiscal Bordagran — Solo Lectura

**Versión**: v3.3.0
**Fecha**: 2026-06-23

---

## ¿Qué es este dashboard?

Una aplicación web de solo lectura que muestra el estado fiscal del trimestre actual
leyendo directamente desde Google Sheets (pestaña `FACTURA PROVEEDORES` y `MAESTRO_PROVEEDORES`).

**No modifica ningún dato.** Solo lee y visualiza.

---

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `Code.gs` | Servidor Apps Script — solo lee Sheets |
| `Index.html` | HTML principal del dashboard |
| `styles.html` | CSS (incluido con `<?!= include('styles') ?>`) |
| `scripts.html` | JavaScript del cliente |

---

## Cómo desplegar

1. Abrir el Google Sheets de Bordagran.
2. Menú Extensiones → Apps Script.
3. Crear nuevo proyecto.
4. Pegar el contenido de `Code.gs` en el archivo `Code.gs` del proyecto.
5. Crear nuevos archivos HTML: `Index`, `styles`, `scripts`.
6. Pegar el contenido correspondiente en cada archivo.
7. Guardar todo.
8. Menú Implementar → Nueva implementación.
9. Tipo: Aplicación web.
10. Ejecutar como: Yo (bordagran@gmail.com).
11. Acceso: Solo yo.
12. Implementar.
13. Copiar la URL de la aplicación web.

---

## Cómo actualizar el dashboard

El dashboard se actualiza automáticamente cada vez que se abre o se pulsa Refrescar.
No hay que hacer nada especial — lee los datos actuales de la hoja en cada carga.

---

## Garantía de solo lectura

El script `scripts/verificar_dashboard_solo_lectura.py` valida que el dashboard
no contiene ninguna función de escritura a Google Sheets.

```powershell
python scripts/verificar_dashboard_solo_lectura.py
```

Resultado esperado: `OK — dashboard limpio de funciones de escritura`.

---

## Funciones prohibidas

El dashboard **nunca** contiene:

```
setValue  setValues  appendRow  clear  deleteRow  insertRow
update  remove  move  copyTo  sort  protect
setNumberFormat  setBackground  setFont  setFormula
```

---

## Seguridad

- Acceso solo al propietario (bordagran@gmail.com).
- No compartir la URL del dashboard.
- No añadir permisos de escritura al proyecto de Apps Script.
