"""
detectar_duplicados_sheet.py -- Bordagran Fiscal v2.4
Lee FACTURA PROVEEDORES y detecta posibles filas duplicadas.
NO borra nada. Solo genera reporte en runtime/duplicados_detectados.csv

Criterios de duplicacion:
  1. Clave unica factura (col R) identica
  2. Hash PDF (col Q) identico
  3. Gmail message_id + attachment_id (cols O+P) identicos
  4. Proveedor norm + num_factura norm (cols C+E, si num no vacio)
  5. Proveedor norm + fecha + total (cols C+A+J)

Uso:
    python scripts/detectar_duplicados_sheet.py --skill-dir .
    python scripts/detectar_duplicados_sheet.py --skill-dir . --salida runtime/dups.csv
"""

import argparse
import csv
import hashlib
import json
import os
import pickle
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def es_num_factura_valido(num: str) -> bool:
    """No agrupar por num de factura invalido (rmal, myParcel, etc.)"""
    if not num or len(num.strip()) < 3:
        return False
    s = num.strip()
    if not any(ch.isdigit() for ch in s):
        return False
    import re as _re
    if _re.match(r"^[A-Z]{2,10}_\d{4}-\d{2}-\d{2}_[\d.]+_[0-9a-f]{6,}$", s):
        return True
    _INVALIDOS = {
        "rmal", "por", "mbre", "myparcel", "parcel", "tracking",
        "tinuaci", "continuacion", "normal", "email", "pedido",
        "payment", "paid", "total", "date", "invoice", "receipt",
        "account", "factura", "fatura", "document", "attachment",
        "accoun", "revision",
    }
    sl = s.lower()
    if sl in _INVALIDOS:
        return False
    for inv in _INVALIDOS:
        if sl == inv or sl.startswith(inv + "_") or sl.endswith("_" + inv):
            return False
    if len([ch for ch in s if ch.isalnum()]) < 3:
        return False
    # TEMP- prefix: solo agrupar si coincide prov+fecha+total, no por num
    if sl.startswith("temp-") or sl.startswith("tecn_"):
        return False
    return True


def encontrar_skill_dir():
    for base in [
        Path(os.environ.get("APPDATA", "")) / "Claude",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Packages",
    ]:
        if not base.exists():
            continue
        for p in base.rglob("gmail-facturas-bordagran"):
            if p.is_dir() and (p / "SKILL.md").exists():
                return p
    return None


def normalizar(texto):
    if not texto:
        return ""
    return re.sub(r'\s+', '', str(texto)).upper().strip()


def autenticar(skill_dir):
    token_path = skill_dir / "token.pickle"
    if not token_path.exists():
        print("ERROR: No hay token.pickle. Ejecuta primero procesar_facturas.py")
        sys.exit(1)
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
    return creds


def main():
    parser = argparse.ArgumentParser(
        description="Detecta duplicados en FACTURA PROVEEDORES (sin borrar nada)"
    )
    parser.add_argument("--skill-dir", default=None)
    parser.add_argument("--salida", default=None,
                        help="Ruta CSV de salida (default: runtime/duplicados_detectados.csv)")
    args = parser.parse_args()

    print("\n================================================")
    print("  BORDAGRAN -- Detector de duplicados en Sheet")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("================================================\n")

    if args.skill_dir:
        skill_dir = Path(args.skill_dir).resolve()
    else:
        skill_dir = encontrar_skill_dir()
        if not skill_dir:
            print("ERROR: No se encontro skill_dir. Usa --skill-dir .")
            sys.exit(1)

    config_path = skill_dir / "config.json"
    with open(config_path, encoding="utf-8") as f:
        config = json.load(f)

    print(f"  Skill-dir : {skill_dir}")
    print(f"  Sheet     : {config['SHEET_FACTURAS_NAME']}\n")

    creds = autenticar(skill_dir)

    import gspread
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(config["SHEET_FACTURAS_ID"])
    sheet = ss.worksheet(config["SHEET_FACTURAS_NAME"])

    print("Leyendo filas del Sheet...")
    filas = sheet.get_all_values()
    header = filas[0] if filas else []
    datos = filas[1:]
    print(f"  {len(datos)} filas (sin cabecera)\n")

    # Indices para detectar duplicados
    idx_clave   = defaultdict(list)  # clave unica R -> [row_nums]
    idx_hash    = defaultdict(list)  # hash Q        -> [row_nums]
    idx_msgatt  = defaultdict(list)  # msg::att      -> [row_nums]
    idx_provnum = defaultdict(list)  # prov::num     -> [row_nums]
    idx_provfectot = defaultdict(list)  # prov::fecha::total -> [row_nums]

    for row_num, fila in enumerate(datos, start=2):  # fila 2 = primera de datos
        fecha    = (fila[0]  if len(fila) > 0  else "").strip()
        prov     = (fila[2]  if len(fila) > 2  else "").strip()
        num      = (fila[4]  if len(fila) > 4  else "").strip()
        total    = (fila[9]  if len(fila) > 9  else "").strip()
        msg_id   = (fila[14] if len(fila) > 14 else "").strip()
        att_id   = (fila[15] if len(fila) > 15 else "").strip()
        pdf_hash = (fila[16] if len(fila) > 16 else "").strip()
        clave    = (fila[17] if len(fila) > 17 else "").strip()

        if clave:
            idx_clave[clave].append(row_num)
        if pdf_hash and pdf_hash != "":
            idx_hash[pdf_hash].append(row_num)
        if msg_id and att_id:
            idx_msgatt[f"{msg_id}::{att_id}"].append(row_num)
        prov_n = normalizar(prov)
        num_n  = normalizar(num)
        # Solo agrupar por Prov+Num si el num es fiscalmente valido
        if prov_n and num_n and es_num_factura_valido(num):
            idx_provnum[f"{prov_n}::{num_n}"].append(row_num)
        fecha_n = fecha[:10]
        total_n = normalizar(total)
        if prov_n and fecha_n and total_n:
            idx_provfectot[f"{prov_n}::{fecha_n}::{total_n}"].append(row_num)

    # Recopilar grupos de duplicados
    grupos = []  # list of (motivo, [row_nums])

    def agregar(idx, motivo_prefix):
        for key, rows in idx.items():
            if len(rows) > 1:
                grupos.append((f"{motivo_prefix}: {key[:60]}", rows))

    agregar(idx_clave,      "Clave unica")
    agregar(idx_hash,       "Hash PDF")
    agregar(idx_msgatt,     "Gmail msg+att")
    agregar(idx_provnum,    "Prov+NumFactura")
    agregar(idx_provfectot, "Prov+Fecha+Total")

    # Eliminar duplicados de grupos (misma combinacion de filas)
    seen = set()
    grupos_unicos = []
    for motivo, rows in grupos:
        key = frozenset(rows)
        if key not in seen:
            seen.add(key)
            grupos_unicos.append((motivo, sorted(rows)))

    print(f"Grupos de posibles duplicados encontrados: {len(grupos_unicos)}\n")

    # Preparar CSV
    salida_path = Path(args.salida) if args.salida else skill_dir / "runtime" / "duplicados_detectados.csv"
    salida_path.parent.mkdir(parents=True, exist_ok=True)

    with open(salida_path, "w", newline="", encoding="utf-8-sig") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            "Motivo", "Filas_Sheet", "Proveedor", "Num_Factura",
            "Fecha", "Total", "Estado", "Hash_PDF", "Clave_Unica"
        ])
        for motivo, rows in grupos_unicos:
            for row_num in rows:
                fila = datos[row_num - 2]
                prov    = fila[2]  if len(fila) > 2  else ""
                num     = fila[4]  if len(fila) > 4  else ""
                fecha   = fila[0]  if len(fila) > 0  else ""
                total   = fila[9]  if len(fila) > 9  else ""
                estado  = fila[11] if len(fila) > 11 else ""
                ph      = fila[16] if len(fila) > 16 else ""
                clave   = fila[17] if len(fila) > 17 else ""
                writer.writerow([motivo, row_num, prov, num, fecha, total, estado, ph[:20], clave[:20]])
            writer.writerow([])  # linea en blanco entre grupos

    # Mostrar resumen en pantalla
    if grupos_unicos:
        print("POSIBLES DUPLICADOS:")
        print("-" * 60)
        for motivo, rows in grupos_unicos:
            print(f"\n  [{motivo}]  filas {rows}")
            for row_num in rows:
                fila = datos[row_num - 2]
                prov   = fila[2]  if len(fila) > 2  else "?"
                num    = fila[4]  if len(fila) > 4  else "?"
                fecha  = fila[0]  if len(fila) > 0  else "?"
                total  = fila[9]  if len(fila) > 9  else "?"
                estado = fila[11] if len(fila) > 11 else "?"
                print(f"    Fila {row_num:3d}: {prov} | Nro:{num} | {fecha} | {total}EUR | {estado}")
    else:
        print("No se detectaron duplicados. El Sheet esta limpio.")

    print("\n" + "=" * 60)
    print(f"Reporte guardado en: {salida_path}")
    print("IMPORTANTE: Este script NO borra nada.")
    print("Revisa el CSV y borra manualmente las filas duplicadas si procede.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
