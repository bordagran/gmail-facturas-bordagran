"""
resumen.py — Bordagran Fiscal v2.1
Genera resumenes diarios y semanales de facturas procesadas.

Uso:
    python scripts/resumen.py --periodo diario --skill-dir .
    python scripts/resumen.py --periodo semanal --skill-dir .
"""

import argparse
import json
import pickle
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
import gspread

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

# Estados que cuentan en el resumen por_estado
ESTADOS_VALIDOS = {
    "Registrada", "Revisar", "Duplicada", "Error lectura", "Validada Carlos",
    "No fiscal / Albarán", "No fiscal / Aviso bancario", "No fiscal / Cliente",
    "No fiscal / Presupuesto", "No fiscal / Pedido", "No fiscal / Desconocido",
}

# SOLO estos estados suman en importe_total e iva_total (L-012)
ESTADOS_SUMAR = {"Registrada", "Validada Carlos"}


def encontrar_skill_dir():
    import os
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


def autenticar(skill_dir):
    token_path = skill_dir / "token.pickle"
    if not token_path.exists():
        print("ERROR: No hay sesion autenticada. Ejecuta primero procesar_facturas.py")
        sys.exit(1)
    with open(token_path, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def parse_importe(s):
    if not s:
        return 0.0
    s = str(s).strip().replace("EUR", "").replace("€", "").replace(" ", "").replace("\xa0", "")
    if re.search(r"\d\.\d{3},", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.search(r"\d,\d{2}$", s):
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def filtrar_por_fecha(filas, desde, hasta):
    resultado = []
    for fila in filas:
        if len(fila) < 14:
            continue
        fecha_str = (fila[13] or "").strip()
        if not fecha_str:
            continue
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
            try:
                fp = datetime.strptime(fecha_str, fmt)
                if desde <= fp <= hasta:
                    resultado.append(fila)
                break
            except ValueError:
                continue
    return resultado


def generar_resumen(filas, periodo):
    resumen = {
        "periodo": periodo,
        "total_facturas": len(filas),
        "importe_total": 0.0,
        "iva_total": 0.0,
        "por_proveedor": {},
        "por_estado": {e: 0 for e in ESTADOS_VALIDOS},
        "facturas_revisar": [],
        "facturas_error": [],
    }
    for fila in filas:
        proveedor = (fila[2] if len(fila) > 2 else "") or "Desconocido"
        num_factura = fila[4] if len(fila) > 4 else ""
        total = parse_importe(fila[9]) if len(fila) > 9 else 0.0
        iva = parse_importe(fila[8]) if len(fila) > 8 else 0.0
        estado = (fila[11] if len(fila) > 11 else "") or ""
        notas = (fila[12] if len(fila) > 12 else "") or ""

        # Solo sumar importes de documentos fiscales confirmados (L-012)
        if estado in ESTADOS_SUMAR:
            resumen["importe_total"] += total
            resumen["iva_total"] += iva

        if proveedor not in resumen["por_proveedor"]:
            resumen["por_proveedor"][proveedor] = {"facturas": 0, "importe": 0.0}
        resumen["por_proveedor"][proveedor]["facturas"] += 1
        resumen["por_proveedor"][proveedor]["importe"] += total

        if estado in resumen["por_estado"]:
            resumen["por_estado"][estado] += 1

        if estado == "Revisar":
            resumen["facturas_revisar"].append({
                "proveedor": proveedor,
                "num_factura": num_factura,
                "importe": total,
                "notas": notas,
            })
        elif estado == "Error lectura":
            resumen["facturas_error"].append({
                "proveedor": proveedor,
                "num_factura": num_factura,
                "notas": notas,
            })

    resumen["importe_total"] = round(resumen["importe_total"], 2)
    resumen["iva_total"] = round(resumen["iva_total"], 2)
    for p in resumen["por_proveedor"]:
        resumen["por_proveedor"][p]["importe"] = round(
            resumen["por_proveedor"][p]["importe"], 2
        )
    return resumen


def leer_ultimo_resultado(skill_dir):
    ruta = skill_dir / "runtime" / "ultimo_resultado.json"
    if ruta.exists():
        try:
            with open(ruta) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def formatear_resumen_texto(resumen, ultimo):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    iconos = {
        "Registrada": "📄",
        "Revisar": "⚠️ ",
        "Duplicada": "🔁",
        "Error lectura": "❌",
        "Validada Carlos": "✅",
        "No fiscal / Albarán": "📦",
        "No fiscal / Aviso bancario": "🏦",
        "No fiscal / Cliente": "🚫",
        "No fiscal / Presupuesto": "📝",
        "No fiscal / Pedido": "🛒",
        "No fiscal / Desconocido": "❓",
    }

    lineas = [
        "📊 RESUMEN {} BORDAGRAN — {}".format(resumen["periodo"].upper(), ahora),
        "=" * 55,
        "Documentos en período : {}".format(resumen["total_facturas"]),
        "Importe fiscal total  : {:.2f} € (solo Registrada + Validada)".format(resumen["importe_total"]),
        "IVA fiscal total      : {:.2f} €".format(resumen["iva_total"]),
    ]

    if ultimo:
        lineas.append("")
        lineas.append("📥 Última ejecución de procesamiento:")
        lineas.append("  ✅ Nuevas registradas : {}".format(len(ultimo.get("procesados", []))))
        lineas.append("  🔁 Duplicados         : {}".format(len(ultimo.get("duplicados", []))))
        lineas.append("  ❌ Errores            : {}".format(len(ultimo.get("errores", []))))

    lineas.append("")
    lineas.append("Por estado:")
    for estado, n in resumen["por_estado"].items():
        if n > 0:
            ico = iconos.get(estado, "•")
            lineas.append("  {} {}: {}".format(ico, estado, n))

    if resumen["por_proveedor"]:
        lineas.append("")
        lineas.append("Por proveedor:")
        ordenados = sorted(
            resumen["por_proveedor"].items(),
            key=lambda x: x[1]["importe"],
            reverse=True,
        )
        for prov, datos in ordenados:
            lineas.append(
                "  • {}: {} factura(s) — {:.2f} €".format(
                    prov, datos["facturas"], datos["importe"]
                )
            )

    if resumen["facturas_revisar"]:
        lineas.append("")
        lineas.append("⚠️  Requieren revisión manual:")
        for item in resumen["facturas_revisar"]:
            nota = " [{}]".format(item["notas"][:50]) if item.get("notas") else ""
            lineas.append(
                "  - {} | Nº {} | {:.2f} €{}".format(
                    item["proveedor"], item["num_factura"], item["importe"], nota
                )
            )

    if resumen["facturas_error"]:
        lineas.append("")
        lineas.append("❌ Con error de lectura:")
        for item in resumen["facturas_error"]:
            lineas.append("  - {} | {}".format(item["proveedor"], item["notas"][:60]))

    return "\n".join(lineas)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--periodo", choices=["diario", "semanal"], default="diario")
    parser.add_argument("--skill-dir", default=None)
    args = parser.parse_args()

    if args.skill_dir:
        skill_dir = Path(args.skill_dir)
    else:
        skill_dir = encontrar_skill_dir()
        if not skill_dir:
            skill_dir = Path(__file__).parent.parent

    config_path = skill_dir / "config.json"
    if not config_path.exists():
        print("ERROR: config.json no encontrado en {}".format(skill_dir))
        sys.exit(1)
    with open(config_path) as f:
        config = json.load(f)

    creds = autenticar(skill_dir)
    gc = gspread.authorize(creds)

    try:
        ss = gc.open_by_key(config["SHEET_FACTURAS_ID"])
        sheet = ss.worksheet(config["SHEET_FACTURAS_NAME"])
    except Exception as e:
        print("ERROR abriendo Sheet: {}".format(e))
        sys.exit(1)

    ahora = datetime.now()
    if args.periodo == "diario":
        desde = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        hasta = ahora
    else:
        desde = ahora - timedelta(days=7)
        hasta = ahora

    filas = sheet.get_all_values()[1:]
    filas_periodo = filtrar_por_fecha(filas, desde, hasta)
    ultimo = leer_ultimo_resultado(skill_dir)

    resumen = generar_resumen(filas_periodo, args.periodo)
    texto = formatear_resumen_texto(resumen, ultimo)
    print(texto)

    resultado_path = skill_dir / "runtime" / "resumen_{}.json".format(args.periodo)
    resultado_path.parent.mkdir(exist_ok=True)
    with open(resultado_path, "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)

    return resumen


if __name__ == "__main__":
    main()
