"""
resumen.py -- Bordagran Fiscal v3.0
Genera resumenes de facturas procesadas desde Google Sheets.

Uso:
    python scripts/resumen.py --periodo diario --skill-dir .
    python scripts/resumen.py --periodo semanal --skill-dir .
    python scripts/resumen.py --periodo trimestral --skill-dir .
    python scripts/resumen.py --desde 2026-01-01 --hasta 2026-03-31 --skill-dir .
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
    "No fiscal / Albaran", "No fiscal / Aviso bancario", "No fiscal / Cliente",
    "No fiscal / Presupuesto", "No fiscal / Pedido", "No fiscal / Desconocido",
}

# SOLO estos estados suman en importe_total, iva_total, base_total (L-012)
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
    s = str(s).strip().replace("EUR", "").replace("e", "").replace(" ", "").replace("\xa0", "")
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


def calcular_trimestre_desde(dt: datetime) -> tuple:
    """Devuelve (desde, hasta) del trimestre que contiene dt."""
    q = (dt.month - 1) // 3
    from_month = q * 3 + 1
    desde = datetime(dt.year, from_month, 1)
    # fin de trimestre: primer dia del siguiente - 1 segundo
    if from_month + 3 > 12:
        hasta = datetime(dt.year + 1, 1, 1) - timedelta(seconds=1)
    else:
        hasta = datetime(dt.year, from_month + 3, 1) - timedelta(seconds=1)
    return desde, hasta


def parsear_fecha_fila(fila):
    """Intenta parsear la fecha de factura (col A, indice 0) o fecha proceso (col N, indice 13)."""
    # Intentar col A (FECHA_FAC) primero, luego col N (FECHA_PROCESO)
    for idx in [0, 13]:
        fecha_str = (fila[idx] if len(fila) > idx else "").strip()
        if not fecha_str:
            continue
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(fecha_str[:16], fmt[:len(fmt)])
            except ValueError:
                continue
        # Intentar sin hora
        for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(fecha_str[:10], fmt)
            except ValueError:
                continue
    return None


def filtrar_por_fecha(filas, desde, hasta):
    resultado = []
    for fila in filas:
        fp = parsear_fecha_fila(fila)
        if fp and desde <= fp <= hasta:
            resultado.append(fila)
    return resultado


def _detectar_columnas(headers):
    """Mapea nombres de columna del Sheet real a índices 0-based.
    Usa alias para robustez ante variaciones de nombre.
    Devuelve dict {clave: indice} con fallback a índices COL dict si no se encuentra."""
    ALIAS = {
        "proveedor":    ["proveedor", "provider", "nombre proveedor"],
        "num_factura":  ["num_factura", "numero factura", "num. factura", "factura"],
        "base":         ["base imponible", "base", "base eur", "base_eur"],
        "iva_pct":      ["iva%", "iva pct", "iva porcentaje", "iva_pct", "iva %"],
        "iva_eur":      ["iva eur", "iva_eur", "iva euros", "iva", "iva €",
                         "cuota iva", "importe iva", "vat", "vat amount"],
        "total":        ["importe total", "total", "total eur", "total_eur"],
        "estado":       ["estado", "status"],
        "notas":        ["notas", "notes", "observaciones"],
    }
    # Fallback 0-based del COL dict original (por si no hay headers reconocibles)
    FALLBACK = {
        "proveedor": 2, "num_factura": 4, "base": 6,
        "iva_pct": 7, "iva_eur": 8, "total": 9, "estado": 11, "notas": 12,
    }
    h_lower = [h.strip().lower() for h in headers]
    result = {}
    for clave, aliases in ALIAS.items():
        found = None
        for alias in aliases:
            if alias in h_lower:
                found = h_lower.index(alias)
                break
        result[clave] = found if found is not None else FALLBACK.get(clave, -1)
    return result


def _get_col(fila, idx, default=""):
    """Acceso seguro a fila por índice."""
    if idx < 0 or idx >= len(fila):
        return default
    return fila[idx]


def generar_resumen(filas, periodo, headers=None):
    """
    headers: lista de strings con la fila 1 del Sheet (nombres de columna).
    Si se pasa, los índices se detectan dinámicamente.
    Si no, se usan fallbacks hardcodeados del COL dict.
    """
    cols = _detectar_columnas(headers or [])

    resumen = {
        "periodo": periodo,
        "total_facturas": len(filas),
        "base_total": 0.0,
        "importe_total": 0.0,
        "iva_total": 0.0,
        "por_proveedor": {},
        "por_estado": {e: 0 for e in ESTADOS_VALIDOS},
        "facturas_revisar": [],
        "facturas_error": [],
        "_cols_usadas": cols,  # para debug
    }
    for fila in filas:
        proveedor = _get_col(fila, cols["proveedor"]) or "Desconocido"
        num_factura = _get_col(fila, cols["num_factura"])
        base = parse_importe(_get_col(fila, cols["base"]))
        iva_pct_raw = _get_col(fila, cols["iva_pct"])
        iva = parse_importe(_get_col(fila, cols["iva_eur"]))
        total = parse_importe(_get_col(fila, cols["total"]))
        estado = _get_col(fila, cols["estado"])
        notas = _get_col(fila, cols["notas"])

        # Guardia: si base > total en esta fila es señal de columna mal leída
        # (p.ej. leyendo IVA% como base imponible)
        if base > total > 0:
            base = 0.0
        # Derivacion: base vacia + IVA presente -> base = total - iva
        # No aplica si iva == 0 (Canva/Anthropic sin IVA no generan base derivada)
        if base == 0.0 and iva > 0.0 and total > iva:
            base = round(total - iva, 2)

        # Solo sumar importes de documentos fiscales confirmados (L-012)
        if estado in ESTADOS_SUMAR:
            resumen["base_total"] += base
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

    resumen["base_total"] = round(resumen["base_total"], 2)
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


def formatear_resumen_texto(resumen, ultimo, desde=None, hasta=None):
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    iconos = {
        "Registrada": "📄",
        "Revisar": "⚠️ ",
        "Duplicada": "🔁",
        "Error lectura": "❌",
        "Validada Carlos": "✅",
        "No fiscal / Albaran": "📦",
        "No fiscal / Aviso bancario": "🏦",
        "No fiscal / Cliente": "🚫",
        "No fiscal / Presupuesto": "📝",
        "No fiscal / Pedido": "🛒",
        "No fiscal / Desconocido": "❓",
    }

    periodo_str = resumen["periodo"].upper()
    if desde and hasta:
        periodo_str += " ({} -> {})".format(
            desde.strftime("%Y-%m-%d"), hasta.strftime("%Y-%m-%d")
        )

    lineas = [
        "📊 RESUMEN {} BORDAGRAN -- {}".format(periodo_str, ahora),
        "=" * 60,
        "Documentos en periodo   : {}".format(resumen["total_facturas"]),
        "Base imponible total    : {:.2f} EUR (solo Registrada + Validada)".format(resumen["base_total"]),
        "IVA fiscal total        : {:.2f} EUR".format(resumen["iva_total"]),
        "Importe fiscal total    : {:.2f} EUR".format(resumen["importe_total"]),
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
        lineas.append("Por proveedor (importe total):")
        ordenados = sorted(
            resumen["por_proveedor"].items(),
            key=lambda x: x[1]["importe"],
            reverse=True,
        )
        for prov, datos in ordenados:
            lineas.append(
                "  • {}: {} factura(s) -- {:.2f} EUR".format(
                    prov, datos["facturas"], datos["importe"]
                )
            )

    if resumen["facturas_revisar"]:
        lineas.append("")
        lineas.append("⚠️  Requieren revision manual:")
        for item in resumen["facturas_revisar"]:
            nota = " [{}]".format(item["notas"][:50]) if item.get("notas") else ""
            lineas.append(
                "  - {} | No {} | {:.2f} EUR{}".format(
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
    parser = argparse.ArgumentParser(description="Resumen fiscal Bordagran")
    parser.add_argument("--periodo", choices=["diario", "semanal", "trimestral"],
                        default="diario",
                        help="Periodo predefinido (alternativa a --desde/--hasta)")
    parser.add_argument("--desde", default=None, metavar="YYYY-MM-DD",
                        help="Inicio del rango (inclusive)")
    parser.add_argument("--hasta", default=None, metavar="YYYY-MM-DD",
                        help="Fin del rango (inclusive)")
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

    # Calcular rango de fechas
    if args.desde and args.hasta:
        desde = datetime.strptime(args.desde, "%Y-%m-%d")
        hasta = datetime.strptime(args.hasta, "%Y-%m-%d").replace(hour=23, minute=59, second=59)
        periodo_label = "personalizado"
    elif args.periodo == "trimestral":
        desde, hasta = calcular_trimestre_desde(ahora)
        periodo_label = "trimestral"
    elif args.periodo == "semanal":
        desde = ahora - timedelta(days=7)
        hasta = ahora
        periodo_label = "semanal"
    else:
        desde = ahora.replace(hour=0, minute=0, second=0, microsecond=0)
        hasta = ahora
        periodo_label = "diario"

    todas = sheet.get_all_values()
    headers = todas[0] if todas else []
    filas = todas[1:]  # saltar header
    filas_periodo = filtrar_por_fecha(filas, desde, hasta)
    ultimo = leer_ultimo_resultado(skill_dir)

    resumen = generar_resumen(filas_periodo, periodo_label, headers=headers)

    # Validacion de coherencia fiscal
    if resumen["importe_total"] > 0 and resumen["base_total"] > resumen["importe_total"]:
        print("WARN: base_total ({:.2f}) > importe_total ({:.2f}) -- columna mal mapeada".format(
            resumen["base_total"], resumen["importe_total"]))
        print("      Columnas detectadas: BASE={} IVA_EUR={} TOTAL={}".format(
            resumen["_cols_usadas"].get("base"), resumen["_cols_usadas"].get("iva_eur"),
            resumen["_cols_usadas"].get("total")))

    texto = formatear_resumen_texto(resumen, ultimo, desde=desde, hasta=hasta)
    print(texto)


if __name__ == "__main__":
    main()
