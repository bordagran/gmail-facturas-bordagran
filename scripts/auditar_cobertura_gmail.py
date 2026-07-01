"""
auditar_cobertura_gmail.py  v1.0  (L-065 / 2026-07)
=====================================================
Auditoria de cobertura: PDFs locales de 2Q 2026 vs Gmail.
100%% SOLO LECTURA -- no escribe en Sheets, Drive ni Gmail.

Uso desde PowerShell:
    python scripts\\auditar_cobertura_gmail.py --carpeta-local "C:\\Users\\Juan\\Downloads\\2Q 2026"

Opciones:
    --carpeta-local PATH   Carpeta con PDFs de control (obligatorio)
    --desde YYYY-MM-DD     Rango busqueda Gmail (default: 2026-04-01)
    --hasta YYYY-MM-DD     Rango busqueda Gmail (default: 2026-09-30)
    --en-spam              Incluir spam y papelera (in:anywhere) [lento]
    --skill-dir PATH       Raiz del proyecto (default: directorio padre del script)
    --salida-dir PATH      Donde guardar los reportes (default: runtime/)

Salida:
    runtime/auditoria_cobertura_gmail_2Q_2026.csv
    runtime/auditoria_cobertura_gmail_2Q_2026.json
"""

import argparse
import csv
import hashlib
import json
import os
import pickle
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# -- Rutas --
SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_PATH  = PROJECT_ROOT / "config.json"
TOKEN_PATH   = PROJECT_ROOT / "token.pickle"
CREDS_PATH   = PROJECT_ROOT / "credentials.json"

# -- Categorias de clasificacion --
CAT_YA_REGISTRADO       = "YA_REGISTRADO"
CAT_QUERY_NO_CAPTURA    = "EMAIL_ENCONTRADO_QUERY_NO_CAPTURA"
CAT_SIN_PDF             = "EMAIL_ENCONTRADO_SIN_PDF_ADJUNTO"
CAT_ENLACE              = "EMAIL_ENCONTRADO_ENLACE_NO_ADJUNTO"
CAT_FUERA_RANGO         = "EMAIL_FUERA_RANGO_FECHA_CORREO"
CAT_SPAM_TRASH          = "EMAIL_EN_SPAM_PAPELERA"
CAT_EXCLUIDO            = "PROVEEDOR_EXCLUIDO"
CAT_PENDIENTE           = "PROVEEDOR_PENDIENTE"
CAT_NO_ENCONTRADO       = "NO_ENCONTRADO_EN_GMAIL"

CATEGORIAS_ORDEN = [
    CAT_YA_REGISTRADO, CAT_QUERY_NO_CAPTURA, CAT_SIN_PDF, CAT_ENLACE,
    CAT_FUERA_RANGO, CAT_SPAM_TRASH, CAT_EXCLUIDO, CAT_PENDIENTE, CAT_NO_ENCONTRADO,
]

# -- Autenticacion --
def autenticar():
    try:
        import gspread
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError as e:
        print("[ERROR] Dependencia faltante: {}".format(e))
        sys.exit(1)

    SCOPES = [
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/spreadsheets.readonly",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as fh:
            creds = pickle.load(fh)
        print("[AUTH] Token cargado (solo lectura)")
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("[AUTH] Token renovado")
        else:
            print("[ERROR] Token invalido. Ejecutar primero procesar_facturas.py para renovarlo.")
            sys.exit(1)

    gmail  = build("gmail", "v1", credentials=creds)
    sheets = build("sheets", "v4", credentials=creds)
    return gmail, sheets, creds


# -- Extraer datos de PDF --
def extraer_datos_pdf_local(ruta_pdf: Path) -> dict:
    """Extrae texto, fecha, importe, num_factura del PDF local con pdfplumber."""
    resultado = {
        "ruta": str(ruta_pdf),
        "nombre": ruta_pdf.name,
        "texto_breve": "",
        "num_factura": "",
        "fecha": "",
        "total": None,
        "proveedor_hint": "",
        "hash": "",
    }
    try:
        with open(ruta_pdf, "rb") as f:
            resultado["hash"] = hashlib.sha256(f.read()).hexdigest()[:16]
    except Exception:
        pass

    try:
        import pdfplumber
        with pdfplumber.open(str(ruta_pdf)) as pdf:
            textos = []
            for page in pdf.pages[:3]:
                t = page.extract_text() or ""
                textos.append(t)
            texto = "\n".join(textos)
            resultado["texto_breve"] = texto[:800]

            # Palabras genericas que NO son num_factura (L-066)
            BLACKLIST_NUM = {
                'fecha', 'numero', 'factura', 'invoice', 'fatura',
                'elizabet', 'elizabeth', 'cliente', 'nombre', 'total',
                'date', 'importe', 'subtotal', 'base', 'cantidad', 'concepto',
            }
            # Numero de factura (varios formatos) -- especificos primero
            for pat in [
                r"(DGFC\d{7,})",
                r"(\d{4}FV\d{5,})",
                r"(REM26\d+)",
                r"(?:N[o\xba\xb0]?\.?\s*(?:Factura|Invoice|Fatura)[:\s]+)([\w/\-]{4,20})",
                r"FACTURA[:\s]+([\w/\-]{4,20})",
                r"INVOICE[:\s#]+([\w/\-]{4,20})",
                r"(F\d{9,})",
            ]:
                m = re.search(pat, texto, re.IGNORECASE)
                if m:
                    candidato = m.group(1).strip()
                    if candidato.lower() not in BLACKLIST_NUM and len(candidato) >= 4:
                        resultado["num_factura"] = candidato
                        break
            # Fallback: extraer num_factura desde nombre del archivo (L-066)
            if not resultado["num_factura"]:
                stem = ruta_pdf.stem
                for pat_fn in [
                    r"(DGFC\d{7,})",
                    r"(FV\d{10,})",
                    r"(\d{4}FV\d{5,})",
                    r"(REM26\d+)",
                    r"([A-Z]{2,3}\d{6,})",
                    r"(\d{5,})",
                ]:
                    m_fn = re.search(pat_fn, stem)
                    if m_fn:
                        resultado["num_factura"] = m_fn.group(1)
                        break

            # Fecha
            m_f = re.search(
                r"(?:Fecha|Date|Fatura)[:\s]+(\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
                texto, re.IGNORECASE
            )
            if m_f:
                resultado["fecha"] = m_f.group(1).strip()

            # Total
            for pat_t in [
                r"TOTAL[:\s]+([\d.,]+)\s*EUR",
                r"Total[:\s]+([\d.,]+)\s*EUR",
                r"IMPORTE\s+TOTAL[:\s]+([\d.,]+)",
            ]:
                m_t = re.search(pat_t, texto, re.IGNORECASE)
                if m_t:
                    try:
                        v = m_t.group(1).replace(".", "").replace(",", ".")
                        resultado["total"] = float(v)
                    except Exception:
                        pass
                    break

            # Proveedor hint desde texto
            prov_hints = {
                "gor factory": "GOR Factory",
                "velilla": "Velilla Group",
                "niba": "Niba Energia",
                "sols": "SOLS",
                "workteam": "Workteam",
                "radiokable": "Radiokable",
                "oktextil": "OKTextil",
                "inkplanet": "Inkplanet",
                "anthropic": "Anthropic",
                "canva": "Canva",
                "shopify": "Shopify",
                "jhk": "JHK T-Shirt",
                "thclothes": "THClothes",
                "lucushost": "LucusHost",
                "octopus": "Octopus Energy",
                "digi spain": "DIGI Spain",
                "digimobil": "DIGI Spain",
                "vivadtf": "VIVADTF",
                "seur": "SEUR",
                "guijarro": "GUIJARRO (EXCLUIDO)",
                "arkiplot": "Arkiplot",
                "webpositer": "WEBPOSITER",
                "openai": "OpenAI",
                "tiendanimal": "Tiendanimal",
            }
            texto_l = texto.lower()
            for kw, prov in prov_hints.items():
                if kw in texto_l:
                    resultado["proveedor_hint"] = prov
                    break

            # Hint adicional desde nombre del archivo
            if not resultado["proveedor_hint"]:
                nombre_l = ruta_pdf.stem.lower()
                for kw, prov in prov_hints.items():
                    if kw.replace(" ", "") in nombre_l or kw.split()[0] in nombre_l:
                        resultado["proveedor_hint"] = prov
                        break

    except Exception as e:
        resultado["error_pdf"] = str(e)

    return resultado


# -- Buscar en Gmail --
def buscar_gmail(gmail, query: str, max_results: int = 100) -> list:
    mensajes = []
    try:
        req = gmail.users().messages().list(userId="me", q=query, maxResults=max_results)
        while req:
            res = req.execute()
            mensajes.extend(res.get("messages", []))
            if len(mensajes) >= max_results:
                break
            req = gmail.users().messages().list_next(req, res)
    except Exception as e:
        print(f"  [WARN] query fallo: {e}")
    return mensajes


def obtener_labels(gmail, msg_id: str) -> list:
    """Obtiene label IDs de un mensaje para detectar spam/trash."""
    try:
        msg = gmail.users().messages().get(userId="me", id=msg_id, format="minimal").execute()
        return msg.get("labelIds", [])
    except Exception:
        return []


def tiene_pdf_adjunto(gmail, msg_id: str) -> bool:
    """Comprueba si el mensaje tiene al menos un adjunto PDF."""
    try:
        msg = gmail.users().messages().get(userId="me", id=msg_id, format="full").execute()
        payload = msg.get("payload", {})
        parts = payload.get("parts", [payload])
        for part in _flatten_parts(parts):
            fn = part.get("filename", "")
            if fn.lower().endswith(".pdf") or "pdf" in part.get("mimeType", "").lower():
                return True
    except Exception:
        pass
    return False


def _flatten_parts(parts):
    result = []
    for p in parts:
        result.append(p)
        sub = p.get("parts", [])
        if sub:
            result.extend(_flatten_parts(sub))
    return result


# -- Comprobar Sheet existente --
def cargar_sheet_registrados(sheets, sheet_id: str, tab: str = "FACTURA PROVEEDORES") -> set:
    """Devuelve set de num_factura ya registrados (lower, normalizado)."""
    registrados = set()
    try:
        result = sheets.spreadsheets().values().get(
            spreadsheetId=sheet_id, range=f"'{tab}'!A:R"
        ).execute()
        filas = result.get("values", [])
        if not filas:
            return registrados
        headers = [h.lower().strip() for h in filas[0]]
        # Buscar columna num_factura
        idx = -1
        for i, h in enumerate(headers):
            if "factura" in h or "invoice" in h or "num" in h:
                idx = i
                break
        if idx < 0:
            idx = 4  # columna E por defecto
        for fila in filas[1:]:
            if idx < len(fila) and fila[idx]:
                registrados.add(fila[idx].strip().lower())
    except Exception as e:
        print(f"  [WARN] No se pudo leer el Sheet: {e}")
    return registrados


# -- Clasificar un PDF --
def clasificar_pdf(
    datos_pdf: dict,
    gmail,
    registrados: set,
    exclusiones: list,
    desde_str: str,
    hasta_str: str,
    incluir_spam: bool,
) -> dict:
    """Clasifica un PDF local y devuelve el resultado de la auditoria."""

    resultado = {
        "archivo": datos_pdf["nombre"],
        "proveedor_hint": datos_pdf.get("proveedor_hint", ""),
        "num_factura": datos_pdf.get("num_factura", ""),
        "fecha_pdf": datos_pdf.get("fecha", ""),
        "total_pdf": datos_pdf.get("total", ""),
        "hash": datos_pdf.get("hash", ""),
        "categoria": CAT_NO_ENCONTRADO,
        "motivo": "",
        "msg_id": "",
        "query_exitosa": "",
        "labels": "",
    }

    prov_hint = datos_pdf.get("proveedor_hint", "").lower()

    # 1. Comprobar si es proveedor excluido
    for excl in exclusiones:
        kws = excl.get("palabras_clave", [])
        em  = excl.get("email", "")
        for kw in kws:
            if kw.lower() in prov_hint:
                resultado["categoria"] = CAT_EXCLUIDO
                resultado["motivo"] = excl.get("motivo", "excluido")
                return resultado
        if em and em.lower() in prov_hint:
            resultado["categoria"] = CAT_EXCLUIDO
            resultado["motivo"] = excl.get("motivo", "excluido")
            return resultado

    # 2. Comprobar si ya esta registrado en el Sheet
    num_f = datos_pdf.get("num_factura", "").strip().lower()
    if num_f and num_f in registrados:
        resultado["categoria"] = CAT_YA_REGISTRADO
        resultado["motivo"] = f"num_factura {num_f!r} ya en Sheet"
        return resultado

    # 3. Buscar en Gmail con varias estrategias
    desde_dt = datetime.strptime(desde_str, "%Y-%m-%d")
    hasta_dt = datetime.strptime(hasta_str, "%Y-%m-%d")
    hasta_excl = hasta_dt + timedelta(days=1)
    rango_q2   = (f"after:{desde_dt.strftime('%Y/%m/%d')} "
                  f"before:{hasta_excl.strftime('%Y/%m/%d')}")
    # Ventana ampliada +90 dias (facturas tardias)
    hasta_amp  = hasta_dt + timedelta(days=90)
    rango_amp  = (f"after:{desde_dt.strftime('%Y/%m/%d')} "
                  f"before:{hasta_amp.strftime('%Y/%m/%d')}")

    nombre_stem = Path(datos_pdf["nombre"]).stem
    num_f_raw   = datos_pdf.get("num_factura", "")
    total_str   = str(int(datos_pdf["total"])) if datos_pdf.get("total") else ""

    queries_por_estrategia = []

    # Estrategia A: por numero de factura en asunto/cuerpo
    if num_f_raw:
        queries_por_estrategia.append((
            f"{num_f_raw} {rango_amp}", "num_factura_rango_ampliado"
        ))
        if incluir_spam:
            queries_por_estrategia.append((
                f"in:anywhere {num_f_raw}", "num_factura_in_anywhere"
            ))

    # Estrategia B: nombre del archivo (parcial)
    partes_nombre = re.sub(r"[_\-]", " ", nombre_stem).strip()
    if len(partes_nombre) >= 6:
        queries_por_estrategia.append((
            f"{partes_nombre[:30]} {rango_amp}", "filename_rango_ampliado"
        ))

    # Estrategia C: importe en asunto
    if total_str:
        queries_por_estrategia.append((
            f"{total_str} EUR {rango_amp} (factura OR invoice)", "importe_rango_ampliado"
        ))

    # Estrategia D: por proveedor hint + rango ampliado
    if datos_pdf.get("proveedor_hint"):
        prov_term = datos_pdf["proveedor_hint"].split("(")[0].strip().replace("  ", " ")
        queries_por_estrategia.append((
            f"{prov_term} {rango_amp} (factura OR invoice OR pdf)", "proveedor_rango_ampliado"
        ))
        # Fuera del rango
        queries_por_estrategia.append((
            f"{prov_term} has:attachment filename:pdf", "proveedor_sin_rango"
        ))

    # Estrategia E: query original del sistema (para detectar si habria entrado)
    query_sistema = f"has:attachment filename:pdf {rango_q2}"
    # No buscar con esto porque buscaria TODOS los emails -- solo anotar

    msg_encontrado = None
    estrategia_ok  = ""

    for query, etiq in queries_por_estrategia:
        time.sleep(0.2)
        msgs = buscar_gmail(gmail, query, max_results=10)
        if msgs:
            msg_encontrado = msgs[0]
            estrategia_ok  = etiq
            break

    if not msg_encontrado:
        resultado["categoria"] = CAT_NO_ENCONTRADO
        resultado["motivo"]    = "No encontrado con ninguna estrategia de busqueda"
        return resultado

    # Email encontrado -- analizar por que no lo capturo el sistema
    msg_id = msg_encontrado["id"]
    resultado["msg_id"]       = msg_id
    resultado["query_exitosa"] = estrategia_ok

    # Obtener labels
    labels = obtener_labels(gmail, msg_id)
    resultado["labels"] = ",".join(labels)

    # Esta en spam o trash?
    if "SPAM" in labels or "TRASH" in labels:
        resultado["categoria"] = CAT_SPAM_TRASH
        resultado["motivo"] = f"Email en {'SPAM' if 'SPAM' in labels else 'TRASH'}"
        return resultado

    # Tiene PDF adjunto?
    time.sleep(0.3)
    if not tiene_pdf_adjunto(gmail, msg_id):
        resultado["categoria"] = CAT_ENLACE
        resultado["motivo"] = "Email encontrado pero sin PDF adjunto (factura por enlace)"
        return resultado

    # La query original del sistema (rango Q2) lo habria encontrado?
    # L-066: usar proveedor_hint (no num_f_raw) porque el num de factura
    # suele estar en el PDF, NO en el cuerpo del email. Aniadirlo al query
    # causa falsos QUERY_NO_CAPTURA (Octopus, etc.).
    time.sleep(0.2)
    prov_q2_term = datos_pdf.get("proveedor_hint", "").split("(")[0].strip()
    query_sistema_prov = (f"{query_sistema} {prov_q2_term}"
                          if prov_q2_term else query_sistema)
    msgs_q2 = buscar_gmail(gmail, query_sistema_prov, max_results=200)
    ids_q2 = {m["id"] for m in msgs_q2}

    if msg_id in ids_q2:
        # Estaba en la query -> motivo es otro (ya registrado, filtrado, etc.)
        if num_f_raw and num_f_raw.lower() in registrados:
            resultado["categoria"] = CAT_YA_REGISTRADO
            resultado["motivo"] = "Estaba en query sistema y ya registrado en Sheet"
        else:
            resultado["categoria"] = CAT_PENDIENTE
            resultado["motivo"] = "En query sistema pero no registrado -- posible pendiente"
    else:
        # No estaba en la query original
        # Es porque el email llego fuera del rango?
        resultado["categoria"] = CAT_QUERY_NO_CAPTURA
        resultado["motivo"] = (
            f"Email encontrado ({estrategia_ok}) pero NO en query original "
            f"'has:attachment filename:pdf {rango_q2}'. "
            "Probable causa: email recibido fuera del rango de fechas (tardio o avanzado)."
        )

    return resultado


# -- MAIN --
def main():
    parser = argparse.ArgumentParser(
        description="Auditoria cobertura Gmail vs PDFs locales 2Q 2026 (solo lectura)"
    )
    parser.add_argument("--carpeta-local", required=True,
                        help="Carpeta con PDFs de control (ej: C:\\Users\\Juan\\Downloads\\2Q 2026)")
    parser.add_argument("--desde", default="2026-04-01", metavar="YYYY-MM-DD",
                        help="Inicio rango Gmail (default: 2026-04-01)")
    parser.add_argument("--hasta", default="2026-09-30", metavar="YYYY-MM-DD",
                        help="Fin rango Gmail (default: 2026-09-30)")
    parser.add_argument("--en-spam", action="store_true",
                        help="Incluir busqueda en spam/papelera (in:anywhere, lento)")
    parser.add_argument("--skill-dir", default=str(PROJECT_ROOT),
                        help="Raiz del proyecto")
    parser.add_argument("--salida-dir", default=str(PROJECT_ROOT / "runtime"),
                        help="Directorio de salida para reportes")
    args = parser.parse_args()

    print()
    print("=" * 65)
    print("  AUDITORIA COBERTURA GMAIL vs PDFs LOCALES  (solo lectura)")
    print("=" * 65)
    print(f"  Carpeta local : {args.carpeta_local}")
    print(f"  Rango Gmail   : {args.desde} -> {args.hasta}")
    print(f"  in:anywhere   : {'Si' if args.en_spam else 'No'}")
    print()

    # Cargar config
    if not CONFIG_PATH.exists():
        print(f"[ERROR] config.json no encontrado en {PROJECT_ROOT}")
        sys.exit(1)
    with open(CONFIG_PATH, encoding="utf-8") as f:
        config = json.load(f)
    SHEET_ID = config["SHEET_FACTURAS_ID"]
    TAB_NAME = config.get("SHEET_TAB_FACTURAS", "FACTURA PROVEEDORES")

    # Autenticar
    gmail, sheets, _ = autenticar()

    # Cargar exclusiones
    excl_path = Path(args.skill_dir) / "references" / "exclusiones.json"
    exclusiones = []
    if excl_path.exists():
        with open(excl_path, encoding="utf-8") as f:
            exclusiones = json.load(f)
    print(f"[INFO] {len(exclusiones)} exclusiones cargadas")

    # Cargar registrados del Sheet
    print(f"[INFO] Leyendo Sheet '{TAB_NAME}'...")
    registrados = cargar_sheet_registrados(sheets, SHEET_ID, TAB_NAME)
    print(f"[INFO] {len(registrados)} num_factura ya registrados en Sheet")

    # Escanear PDFs locales
    carpeta = Path(args.carpeta_local)
    if not carpeta.exists():
        print(f"[ERROR] Carpeta no encontrada: {carpeta}")
        sys.exit(1)

    pdfs = sorted(carpeta.rglob("*.pdf")) + sorted(carpeta.rglob("*.PDF"))
    pdfs = list(dict.fromkeys(pdfs))  # deduplicar
    print(f"[INFO] {len(pdfs)} PDFs encontrados en {carpeta}")
    print()

    # Procesar cada PDF
    resultados = []
    for i, pdf_path in enumerate(pdfs):
        print(f"[{i+1}/{len(pdfs)}] {pdf_path.name}")
        try:
            datos = extraer_datos_pdf_local(pdf_path)
            print(f"  proveedor_hint={datos['proveedor_hint']!r}  "
                  f"num_factura={datos['num_factura']!r}  "
                  f"total={datos['total']}")
            res = clasificar_pdf(
                datos, gmail, registrados, exclusiones,
                args.desde, args.hasta, args.en_spam
            )
            print(f"  -> {res['categoria']}  {res['motivo'][:80]}")
        except Exception as e:
            res = {
                "archivo": pdf_path.name,
                "proveedor_hint": "",
                "num_factura": "",
                "fecha_pdf": "",
                "total_pdf": "",
                "hash": "",
                "categoria": "ERROR",
                "motivo": str(e),
                "msg_id": "",
                "query_exitosa": "",
                "labels": "",
            }
            print(f"  -> ERROR: {e}")
        resultados.append(res)
        print()

    # Resumen por categoria
    print("=" * 65)
    print("  RESUMEN POR CATEGORIA")
    print("=" * 65)
    conteo = {}
    for r in resultados:
        c = r["categoria"]
        conteo[c] = conteo.get(c, 0) + 1
    for cat in CATEGORIAS_ORDEN + ["ERROR"]:
        if cat in conteo:
            print(f"  {cat:45} : {conteo[cat]:3}")
    print()

    # Guardar CSV
    salida_dir = Path(args.salida_dir)
    salida_dir.mkdir(exist_ok=True)
    csv_path  = salida_dir / "auditoria_cobertura_gmail_2Q_2026.csv"
    json_path = salida_dir / "auditoria_cobertura_gmail_2Q_2026.json"

    campos_csv = [
        "archivo", "proveedor_hint", "num_factura", "fecha_pdf", "total_pdf",
        "hash", "categoria", "motivo", "msg_id", "query_exitosa", "labels"
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=campos_csv, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(resultados)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "generado": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "carpeta_local": args.carpeta_local,
            "rango_gmail": {"desde": args.desde, "hasta": args.hasta},
            "total_pdfs": len(pdfs),
            "resumen": conteo,
            "resultados": resultados,
        }, f, ensure_ascii=False, indent=2)

    print(f"[OK] Reporte CSV  : {csv_path}")
    print(f"[OK] Reporte JSON : {json_path}")
    print()
    print("[SIGUIENTE PASO]")
    print("  Compartir el reporte con Claude para analizar causas y proponer correcciones.")
    print("  NO ejecutar procesar_facturas.py -Real hasta revisar el reporte.")
    print()


if __name__ == "__main__":
    main()
