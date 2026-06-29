"""
alta_digi_maestro.py
Agrega/actualiza DIGI Spain Telecom en la pestana MAESTRO_PROVEEDORES.
Ejecutar desde PowerShell en la raiz del proyecto:
    python scripts\alta_digi_maestro.py

L-064: proveedor fiscal valido, NIF A84919760.
"""
import json
import pickle
import sys
from pathlib import Path

# Localizar skill_dir (raiz del proyecto)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

CONFIG_PATH = PROJECT_ROOT / "config.json"
TOKEN_PATH  = PROJECT_ROOT / "token.pickle"
CREDS_PATH  = PROJECT_ROOT / "credentials.json"

if not CONFIG_PATH.exists():
    print("[ERROR] No se encuentra config.json en {}".format(PROJECT_ROOT))
    sys.exit(1)

with open(CONFIG_PATH, encoding="utf-8") as f:
    config = json.load(f)

SHEET_ID   = config["SHEET_FACTURAS_ID"]
TAB_NOMBRE = "MAESTRO_PROVEEDORES"

# Datos DIGI a escribir
DIGI_DATOS = {
    "Proveedor detectado":           "DIGI Spain Telecom, S.A.U.",
    "Proveedor norm":                "DIGI Spain Telecom, S.A.U.",
    "Email / dominio":               "digimobil.no-reply@bulkmail.digimobil.es",
    "Categoria":                     "Telecomunicaciones",
    "Tipo fiscal":                   "Nacional con IVA",
    "Estado por defecto":            "Registrada",
    "Proveedor seguro":              "Si",
    "Accion automatica":             "Registrar con confianza",
    "Estado validacion proveedor":   "validado",
    "Validado por":                  "Juan",
    "Fecha validacion":              "2026-06-29",
    "Criterio validado":             "Proveedor real telecomunicaciones. Parser DIGI validado. Facturas DGFC con IVA 21%. L-064.",
    "Primera deteccion":             "2026-01-01",
    "Ultima deteccion":              "2026-06-29",
    "Notas":                         "Validado L-064. Remitente digimobil/bulkmail.digimobil.es. NIF A84919760.",
}


def autenticar():
    try:
        import gspread
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        print("[ERROR] Dependencia faltante: {}".format(e))
        print("Instalar: pip install gspread google-auth google-auth-oauthlib")
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
        print("[AUTH] Token existente cargado")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("[AUTH] Token renovado")
        else:
            if not CREDS_PATH.exists():
                print("[ERROR] Falta credentials.json en {}".format(PROJECT_ROOT))
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
            print("[AUTH] OAuth completado")
        with open(TOKEN_PATH, "wb") as fh:
            pickle.dump(creds, fh)

    import gspread
    return gspread.authorize(creds)


def main():
    print()
    print("=" * 60)
    print("  ALTA DIGI EN MAESTRO_PROVEEDORES")
    print("=" * 60)

    gc = autenticar()

    print("[INFO] Abriendo Sheet ID: {}".format(SHEET_ID))
    ss = gc.open_by_key(SHEET_ID)

    # Obtener o crear la pestana
    try:
        ws = ss.worksheet(TAB_NOMBRE)
        print("[INFO] Pestana '{}' encontrada".format(TAB_NOMBRE))
    except Exception:
        print("[WARN] Pestana '{}' no existe. Creando...".format(TAB_NOMBRE))
        ws = ss.add_worksheet(title=TAB_NOMBRE, rows=100, cols=20)
        print("[INFO] Pestana creada")

    # Leer todas las filas
    todas = ws.get_all_values()

    if not todas:
        # Hoja vacia: escribir cabeceras + fila DIGI
        headers = list(DIGI_DATOS.keys())
        ws.append_row(headers)
        ws.append_row([DIGI_DATOS.get(h, "") for h in headers])
        print("[OK] Cabeceras + fila DIGI escritas (hoja estaba vacia)")
        _confirmar(ws)
        return

    headers = todas[0]
    print("[INFO] Cabeceras detectadas: {}".format(headers[:5]))
    filas_data = todas[1:]

    # Buscar columna "Proveedor detectado"
    col_prov = None
    for idx, h in enumerate(headers):
        if "proveedor detectado" in h.lower() or h.lower().strip() == "proveedor":
            col_prov = idx
            break
    if col_prov is None:
        col_prov = 0
        print("[WARN] Columna 'Proveedor detectado' no encontrada. Usando columna 0.")

    # Buscar si DIGI ya existe
    fila_digi_idx = None
    for i, fila in enumerate(filas_data):
        valor = fila[col_prov] if col_prov < len(fila) else ""
        if "digi" in valor.lower() or "digimobil" in valor.lower():
            fila_digi_idx = i
            print("[INFO] DIGI ya existe en fila {}: {!r}".format(i + 2, valor))
            break

    # Construir la fila segun las cabeceras existentes
    nueva_fila = []
    for h in headers:
        h_norm = h.lower().strip()
        val = ""
        for k, v in DIGI_DATOS.items():
            if k.lower().strip() == h_norm:
                val = v
                break
        nueva_fila.append(val)

    if fila_digi_idx is not None:
        row_num = fila_digi_idx + 2  # +1 header, +1 base-1
        ws.update("A{}".format(row_num), [nueva_fila])
        print("[OK] Fila DIGI actualizada en fila {}".format(row_num))
    else:
        ws.append_row(nueva_fila)
        print("[OK] Fila DIGI aniadida al final de MAESTRO_PROVEEDORES")

    _confirmar(ws)


def _confirmar(ws):
    todas = ws.get_all_values()
    print()
    print("-" * 60)
    print("[VERIFICACION] Filas en {}: {}".format(TAB_NOMBRE, len(todas)))
    for fila in todas:
        if any("digi" in str(c).lower() for c in fila):
            print("  DIGI encontrado: {}".format(fila[:4]))
    print("-" * 60)
    print()
    print("[SIGUIENTE PASO] Refresca el dashboard en el navegador.")
    print("La alerta amarilla de DIGI debe desaparecer.")
    print()


if __name__ == "__main__":
    main()
