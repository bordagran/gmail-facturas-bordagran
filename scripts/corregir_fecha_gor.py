"""
corregir_fecha_gor.py
Corrige la fecha y trimestre de la factura GOR Factory que aparece en Q4-2026
pero corresponde a mayo 2026 (Q2-2026).

Bug L-065: el parser bilingue no capturo la fecha del PDF (pdfplumber con espacios
en los separadores de fecha). Se uso la fecha del correo (noviembre) como fallback.

Ejecutar desde PowerShell en la raiz del proyecto:
    python scripts\corregir_fecha_gor.py

El script:
1. Lee todas las filas de FACTURA PROVEEDORES
2. Encuentra las filas de GOR Factory con trimestre Q4-2026
3. Muestra los datos antes de cambiar
4. Pide confirmacion
5. Actualiza fecha a 2026-05-11 y trimestre a Q2-2026
6. Verifica el resultado
"""
import json
import pickle
import sys
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_PATH  = PROJECT_ROOT / "config.json"
TOKEN_PATH   = PROJECT_ROOT / "token.pickle"
CREDS_PATH   = PROJECT_ROOT / "credentials.json"

# Fecha correcta (mayo 2026)
FECHA_CORRECTA    = "2026-05-11"
TRIMESTRE_CORRECTO = "Q2-2026"

if not CONFIG_PATH.exists():
    print("[ERROR] No se encuentra config.json en {}".format(PROJECT_ROOT))
    sys.exit(1)

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

SHEET_ID   = config["SHEET_FACTURAS_ID"]
TAB_NOMBRE = config.get("SHEET_TAB_FACTURAS", "FACTURA PROVEEDORES")


def autenticar():
    try:
        import gspread
        from google.auth.transport.requests import Request
    except ImportError as e:
        print("[ERROR] Dependencia faltante: {}".format(e))
        sys.exit(1)

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
        "https://mail.google.com/",
    ]
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as fh:
            creds = pickle.load(fh)
        print("[AUTH] Token cargado")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("[AUTH] Token renovado")
        else:
            print("[ERROR] Token invalido y no hay modo interactivo disponible.")
            print("        Ejecutar primero procesar_facturas.py para renovar el token.")
            sys.exit(1)
    import gspread
    return gspread.authorize(creds)


def main():
    print()
    print("=" * 65)
    print("  CORRECCION FECHA GOR FACTORY  (L-065 fix)")
    print("=" * 65)
    print()

    gc = autenticar()
    ss = gc.open_by_key(SHEET_ID)

    try:
        ws = ss.worksheet(TAB_NOMBRE)
        print("[INFO] Pestana '{}' encontrada".format(TAB_NOMBRE))
    except Exception as e:
        print("[ERROR] Pestana '{}' no encontrada: {}".format(TAB_NOMBRE, e))
        sys.exit(1)

    todas = ws.get_all_values()
    if not todas:
        print("[ERROR] La hoja esta vacia.")
        sys.exit(1)

    headers = todas[0]
    filas   = todas[1:]

    print("[INFO] Total filas en {}: {}".format(TAB_NOMBRE, len(filas)))
    print("[INFO] Cabeceras (primeras 8): {}".format(headers[:8]))
    print()

    # Columnas relevantes (0-indexed en la lista de filas, 1-indexed en Sheets)
    def col_idx(candidatos):
        for c in candidatos:
            for i, h in enumerate(headers):
                if c.lower() in h.lower():
                    return i
        return -1

    idx_fecha     = col_idx(["fecha"])
    idx_trimestre = col_idx(["trimestre", "q1", "q2", "q3", "q4"])
    idx_proveedor = col_idx(["proveedor", "empresa"])
    idx_numfac    = col_idx(["n factura", "num factura", "factura", "invoice"])
    idx_total     = col_idx(["total", "importe"])

    print("[INFO] Columna fecha     -> {}  ({})".format(
        idx_fecha, headers[idx_fecha] if idx_fecha >= 0 else "NO ENCONTRADA"))
    print("[INFO] Columna trimestre -> {}  ({})".format(
        idx_trimestre, headers[idx_trimestre] if idx_trimestre >= 0 else "NO ENCONTRADA"))
    print("[INFO] Columna proveedor -> {}  ({})".format(
        idx_proveedor, headers[idx_proveedor] if idx_proveedor >= 0 else "NO ENCONTRADA"))
    print()

    if idx_fecha < 0 or idx_trimestre < 0:
        print("[ERROR] No se pudo encontrar columna Fecha o Trimestre.")
        sys.exit(1)

    # Buscar filas GOR Factory con Q4-2026
    candidatas = []
    for i, fila in enumerate(filas):
        prov_val = fila[idx_proveedor].lower() if idx_proveedor >= 0 and idx_proveedor < len(fila) else ""
        tri_val  = fila[idx_trimestre] if idx_trimestre < len(fila) else ""
        if "gor" in prov_val and "q4" in tri_val.lower():
            candidatas.append((i + 2, fila))  # +2: header en fila 1, data desde fila 2

    if not candidatas:
        print("[INFO] No se encontraron filas GOR Factory con Q4-2026.")
        print("       Puede que ya hayan sido corregidas o el nombre de proveedor sea diferente.")
        # Mostrar todas las filas GOR para debug
        gor_filas = []
        for i, fila in enumerate(filas):
            prov_val = fila[idx_proveedor].lower() if idx_proveedor >= 0 and idx_proveedor < len(fila) else ""
            if "gor" in prov_val:
                gor_filas.append((i + 2, fila))
        if gor_filas:
            print("\n[DEBUG] Filas GOR Factory encontradas ({} total):".format(len(gor_filas)))
            for row_num, fila in gor_filas[:5]:
                fecha_v = fila[idx_fecha] if idx_fecha < len(fila) else "?"
                tri_v   = fila[idx_trimestre] if idx_trimestre < len(fila) else "?"
                num_v   = fila[idx_numfac] if idx_numfac >= 0 and idx_numfac < len(fila) else "?"
                print("  Fila {}: fecha={!r:15} trimestre={!r:10} num_factura={!r}".format(
                    row_num, fecha_v, tri_v, num_v))
        sys.exit(0)

    print("[CANDIDATAS] {} fila(s) GOR Factory con Q4-2026:".format(len(candidatas)))
    print()
    for row_num, fila in candidatas:
        fecha_v = fila[idx_fecha]     if idx_fecha < len(fila)     else "?"
        tri_v   = fila[idx_trimestre] if idx_trimestre < len(fila) else "?"
        num_v   = fila[idx_numfac]    if idx_numfac >= 0 and idx_numfac < len(fila) else "?"
        tot_v   = fila[idx_total]     if idx_total >= 0 and idx_total < len(fila)    else "?"
        prov_v  = fila[idx_proveedor] if idx_proveedor >= 0 and idx_proveedor < len(fila) else "?"
        print("  Fila {} en Sheet:".format(row_num))
        print("    Proveedor   : {}".format(prov_v))
        print("    Fecha actual: {}  (INCORRECTO - debe ser mayo)".format(fecha_v))
        print("    Trimestre   : {}  (INCORRECTO - debe ser Q2-2026)".format(tri_v))
        print("    N Factura   : {}".format(num_v))
        print("    Total       : {}".format(tot_v))
        print()
        print("  Cambio propuesto:")
        print("    Fecha     : {} -> {}".format(fecha_v, FECHA_CORRECTA))
        print("    Trimestre : {} -> {}".format(tri_v, TRIMESTRE_CORRECTO))
        print()

    resp = input("Confirmar correccion? [s/N]: ").strip().lower()
    if resp != "s":
        print("[CANCELADO] No se hizo ninguna modificacion.")
        sys.exit(0)

    # Aplicar correcciones
    col_letra_fecha     = chr(ord('A') + idx_fecha)
    col_letra_trimestre = chr(ord('A') + idx_trimestre)

    for row_num, fila in candidatas:
        celda_fecha     = "{}{}".format(col_letra_fecha, row_num)
        celda_trimestre = "{}{}".format(col_letra_trimestre, row_num)
        ws.update(celda_fecha,     [[FECHA_CORRECTA]])
        ws.update(celda_trimestre, [[TRIMESTRE_CORRECTO]])
        print("[OK] Fila {} actualizada: fecha={} trimestre={}".format(
            row_num, FECHA_CORRECTA, TRIMESTRE_CORRECTO))

    # Verificacion
    print()
    print("[VERIFICACION] Releyendo filas actualizadas...")
    todas2 = ws.get_all_values()
    filas2 = todas2[1:]
    for row_num, _ in candidatas:
        fila2 = filas2[row_num - 2]
        fecha_v2 = fila2[idx_fecha]     if idx_fecha < len(fila2)     else "?"
        tri_v2   = fila2[idx_trimestre] if idx_trimestre < len(fila2) else "?"
        ok_f = fecha_v2 == FECHA_CORRECTA or "05" in fecha_v2 and "2026" in fecha_v2
        ok_t = TRIMESTRE_CORRECTO in tri_v2 or "q2" in tri_v2.lower()
        print("  Fila {}: fecha={!r:18} {} | trimestre={!r:12} {}".format(
            row_num,
            fecha_v2, "OK" if ok_f else "REVISAR",
            tri_v2,   "OK" if ok_t else "REVISAR"
        ))

    print()
    print("[SIGUIENTE PASO]")
    print("  1. Refresca el dashboard en el navegador")
    print("  2. La factura GOR Factory debe aparecer en Q2-2026")
    print()


if __name__ == "__main__":
    main()
