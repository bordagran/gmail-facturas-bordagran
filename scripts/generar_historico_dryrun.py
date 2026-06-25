#!/usr/bin/env python3
"""
generar_historico_dryrun.py — Bordagran Fiscal v3.4.0
======================================================
Escaneo historico de Gmail por trimestres en modo DRY-RUN estricto.

GARANTIAS:
  - NO escribe en FACTURA PROVEEDORES (cero appendRow)
  - NO sube archivos a Google Drive
  - NO modifica etiquetas de Gmail
  - NO modifica MAESTRO_PROVEEDORES
  - Solo lectura: Gmail, Google Sheets (MAESTRO_PROVEEDORES)

Uso:
    python scripts/generar_historico_dryrun.py --skill-dir /ruta/skill
    python scripts/generar_historico_dryrun.py --skill-dir /ruta/skill --trimestres Q1-2025 Q2-2025
    python scripts/generar_historico_dryrun.py --skill-dir /ruta/skill --desde 2025-01-01 --hasta 2025-06-30

Salidas (en runtime/):
    historico_facturas_dryrun.json      Resultado completo estructurado
    proveedores_candidatos.csv          Proveedores no reconocidos
    tipos_documento_candidatos.csv      Clasificacion de todos los documentos
"""

import argparse
import csv
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────
# Bootstrap: importar funciones compartidas de procesar_facturas.py
# (safe: main() esta protegido por if __name__ == "__main__")
# ─────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from procesar_facturas import (
    configurar_salida_segura,
    log,
    ESTADOS,
    normalizar_texto,
    calcular_trimestre,
    autenticar,
    cargar_proveedores,
    cargar_exclusiones,
    identificar_proveedor,
    es_email_excluido,
    clasificar_tipo_documento,
    extraer_datos_pdf,
    determinar_estado,
    encontrar_skill_dir,
    buscar_mensajes,
    obtener_metadata,
    descargar_adjuntos_pdf,
    cargar_maestro_proveedores,
    buscar_en_maestro,
    criterio_maestro,
)
import gspread
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ─────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────

VERSION = "v3.4.0"

# Trimestres a escanear por defecto (desde — hasta inclusive)
TRIMESTRES_DEFAULT = [
    ("Q1-2025", "2025/01/01", "2025/04/01"),
    ("Q2-2025", "2025/04/01", "2025/07/01"),
    ("Q3-2025", "2025/07/01", "2025/10/01"),
    ("Q4-2025", "2025/10/01", "2026/01/01"),
    ("Q1-2026", "2026/01/01", "2026/04/01"),
    ("Q2-2026", "2026/04/01", "2026/07/01"),
]

TRIMESTRES_VALIDOS = {t[0] for t in TRIMESTRES_DEFAULT}

# Campos del CSV de documentos
CSV_DOCS_FIELDS = [
    "trimestre", "fecha_email", "fecha_pdf", "remitente",
    "proveedor", "tipo_documento", "estado_estimado",
    "num_factura", "total", "iva_pct", "base",
    "nombre_pdf", "msg_id", "notas",
]

# Campos del CSV de proveedores candidatos
CSV_CAND_FIELDS = [
    "trimestre", "fecha_email", "remitente",
    "nombre_detectado", "nombre_pdf", "msg_id", "motivo",
]

# ─────────────────────────────────────────────────────────
# UTILIDADES LOCALES
# ─────────────────────────────────────────────────────────

def cargar_config(skill_dir: Path) -> dict:
    config_path = skill_dir / "config.json"
    if not config_path.exists():
        log(f"config.json no encontrado en {skill_dir}", "ERROR")
        sys.exit(1)
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def query_trimestre(etiqueta: str, desde: str, hasta: str) -> str:
    """
    Construye query Gmail para el trimestre.
    Usa 'has:attachment filename:pdf' como filtro base.
    Las fechas son en formato YYYY/MM/DD (requerido por Gmail API).
    """
    return f"has:attachment filename:pdf after:{desde} before:{hasta}"


def estado_estimado(datos_pdf: dict, es_desconocido: bool, criterio) -> str:
    """Wrapper de determinar_estado sin side effects."""
    return determinar_estado(datos_pdf, es_desconocido, criterio=criterio)


def _fmt(v) -> str:
    """Formato seguro para CSV."""
    if v is None:
        return ""
    return str(v).replace("\n", " ").replace("\r", " ").strip()


def _es_excluido_por_nombre(nombre: str, exclusiones: list) -> dict | None:
    """
    Comprueba palabras_clave de exclusiones contra el nombre de proveedor.
    Complementa es_email_excluido() que actua sobre el email/remitente.
    Necesario para ESCUELAARTEGRANADA y similares detectados por nombre, no email.
    """
    norm = normalizar_texto(nombre)
    for excl in exclusiones:
        for kw in excl.get("palabras_clave", []):
            if normalizar_texto(kw) in norm:
                return excl
    return None


# ─────────────────────────────────────────────────────────
# PROCESAMIENTO POR TRIMESTRE
# ─────────────────────────────────────────────────────────

def procesar_trimestre(
    gmail,
    etiqueta: str, desde: str, hasta: str,
    proveedores: list, exclusiones: list,
    maestro_data: dict, sheet_maestro,
) -> dict:
    """
    Procesa un trimestre completo.
    Lee Gmail, descarga PDFs a tmp, extrae datos, clasifica.
    CERO escrituras a Sheets, Drive o Gmail.
    Devuelve dict con resultados del trimestre.
    """
    log(f"\n{'='*60}")
    log(f"TRIMESTRE: {etiqueta}  ({desde} → {hasta})")
    log(f"{'='*60}")

    query = query_trimestre(etiqueta, desde, hasta)
    log(f"Query Gmail: {query}")

    try:
        mensajes = buscar_mensajes(gmail, query)
    except Exception as e:
        log(f"Error buscando mensajes para {etiqueta}: {e}", "ERROR")
        return {"trimestre": etiqueta, "mensajes": 0, "error": str(e), "docs": []}

    log(f"Mensajes encontrados: {len(mensajes)}")

    docs = []
    candidatos = []
    stats = {
        "total_mensajes": len(mensajes),
        "total_pdfs": 0,
        "por_estado": {},
        "por_tipo": {},
        "por_proveedor": {},
        "excluidos": 0,
        "desconocidos": 0,
        "errores_pdf": 0,
    }

    for idx, msg in enumerate(mensajes, 1):
        msg_id = msg["id"]
        try:
            meta = obtener_metadata(gmail, msg_id)
        except Exception as e:
            log(f"  [{idx}/{len(mensajes)}] Error metadata {msg_id}: {e}", "WARN")
            continue

        remitente = meta.get("remitente", "")
        fecha_email = meta.get("fecha", "")
        asunto = meta.get("asunto", "")

        # Verificar exclusion de email
        excl = es_email_excluido(remitente, exclusiones)
        if excl:
            log(f"  [{idx}] EXCLUIDO ({excl.get('motivo','?')}): {remitente}")
            stats["excluidos"] += 1
            continue

        prov = identificar_proveedor(remitente, proveedores)
        es_desconocido = prov.get("_desconocido", False)
        nombre_prov = prov.get("nombre", remitente)

        log(f"  [{idx}/{len(mensajes)}] {remitente} -> {nombre_prov}")

        # Exclusión por nombre de proveedor (palabras_clave v3.4.0 — ESCUELAARTEGRANADA etc.)
        excl_nombre = _es_excluido_por_nombre(nombre_prov, exclusiones)
        if excl_nombre:
            log(f"    EXCLUIDO por nombre ({excl_nombre.get('motivo','?')}): {nombre_prov}")
            stats["excluidos"] += 1
            continue

        # Descargar adjuntos PDF a directorio temporal
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                adjuntos = descargar_adjuntos_pdf(gmail, msg_id, tmp_dir)
            except Exception as e:
                log(f"    Error descargando adjuntos: {e}", "WARN")
                stats["errores_pdf"] += 1
                continue

            if not adjuntos:
                log(f"    Sin adjuntos PDF")
                continue

            for adj in adjuntos:
                stats["total_pdfs"] += 1
                ruta_local = adj.get("ruta", "")
                nombre_pdf = adj.get("nombre", "")

                # Proveedor desconocido -> candidato
                if es_desconocido:
                    stats["desconocidos"] += 1
                    candidatos.append({
                        "trimestre": etiqueta,
                        "fecha_email": fecha_email,
                        "remitente": remitente,
                        "nombre_detectado": nombre_prov,
                        "nombre_pdf": nombre_pdf,
                        "msg_id": msg_id,
                        "motivo": "Proveedor no reconocido en proveedores.json",
                    })

                # Extraer datos del PDF
                try:
                    datos_pdf = extraer_datos_pdf(ruta_local) if ruta_local else {}
                except Exception as e:
                    log(f"    Error extrayendo {nombre_pdf}: {e}", "WARN")
                    datos_pdf = {"notas": f"Error extraccion PDF: {str(e)[:80]}"}
                    stats["errores_pdf"] += 1

                # Clasificar tipo de documento
                texto_pdf = datos_pdf.get("_texto_completo", "")
                tipo_doc, motivo_excl = clasificar_tipo_documento(
                    texto_pdf, remitente, exclusiones
                )

                # Obtener criterio del Maestro (solo lectura)
                entrada_maestro = buscar_en_maestro(maestro_data, nombre_prov)
                criterio = criterio_maestro(entrada_maestro)
                accion_criterio = (criterio or {}).get("accion", "")

                # Calcular estado estimado
                if es_desconocido:
                    est = ESTADOS["REVISAR"]
                elif accion_criterio == "excluir":
                    est = "Excluido (Maestro)"
                elif tipo_doc in ("no_fiscal", "no_factura", "marketing", "pedido_cliente"):
                    est = f"No fiscal ({tipo_doc})"
                else:
                    # Proveedor nuevo (en Maestro disponible pero sin registro)
                    es_nuevo_maestro = (
                        entrada_maestro is None
                        and sheet_maestro is not None
                    )
                    if es_nuevo_maestro:
                        est = ESTADOS["REVISAR"] + " [nuevo en Maestro]"
                    else:
                        est = estado_estimado(datos_pdf, es_desconocido, criterio)

                # Acumular estadisticas
                stats["por_estado"][est] = stats["por_estado"].get(est, 0) + 1
                stats["por_tipo"][tipo_doc] = stats["por_tipo"].get(tipo_doc, 0) + 1
                stats["por_proveedor"][nombre_prov] = (
                    stats["por_proveedor"].get(nombre_prov, 0) + 1
                )

                doc = {
                    "trimestre": etiqueta,
                    "fecha_email": fecha_email,
                    "fecha_pdf": datos_pdf.get("fecha", ""),
                    "remitente": remitente,
                    "proveedor": nombre_prov,
                    "tipo_documento": tipo_doc,
                    "estado_estimado": est,
                    "num_factura": datos_pdf.get("num_factura", ""),
                    "total": datos_pdf.get("total", ""),
                    "iva_pct": datos_pdf.get("iva_pct", ""),
                    "base": datos_pdf.get("base", ""),
                    "nombre_pdf": nombre_pdf,
                    "msg_id": msg_id,
                    "notas": datos_pdf.get("notas", ""),
                    "asunto": asunto,
                    "_es_desconocido": es_desconocido,
                }
                docs.append(doc)

                log(f"    {nombre_pdf}: {tipo_doc} → {est}")

    log(f"\n  Resumen {etiqueta}:")
    log(f"    PDFs procesados: {stats['total_pdfs']}")
    log(f"    Excluidos:       {stats['excluidos']}")
    log(f"    Desconocidos:    {stats['desconocidos']}")
    for est, n in sorted(stats["por_estado"].items()):
        log(f"    {est}: {n}")

    return {
        "trimestre": etiqueta,
        "desde": desde,
        "hasta": hasta,
        "stats": stats,
        "docs": docs,
        "candidatos": candidatos,
    }


# ─────────────────────────────────────────────────────────
# ESCRITURA DE SALIDAS
# ─────────────────────────────────────────────────────────

def escribir_salidas(resultados: list, runtime_dir: Path, ts: str):
    """
    Escribe los 3 archivos de salida en runtime/.
    NUNCA escribe en Sheets, Drive o Gmail.
    """
    runtime_dir.mkdir(exist_ok=True)

    # 1. JSON completo
    json_path = runtime_dir / "historico_facturas_dryrun.json"
    payload = {
        "_meta": {
            "version": "v3.4.0",
            "generado": ts,
            "nota": "DRY-RUN — sin escritura en Sheets, Drive ni Gmail",
        },
        "trimestres": resultados,
        "resumen_global": _resumen_global(resultados),
    }
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    log(f"\nJSON escrito: {json_path}")

    # 2. CSV de documentos
    docs_path = runtime_dir / "tipos_documento_candidatos.csv"
    all_docs = [d for r in resultados for d in r.get("docs", [])]
    with open(docs_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_DOCS_FIELDS, extrasaction="ignore")
        w.writeheader()
        for d in all_docs:
            w.writerow({k: _fmt(d.get(k, "")) for k in CSV_DOCS_FIELDS})
    log(f"CSV docs escrito: {docs_path}  ({len(all_docs)} filas)")

    # 3. CSV de proveedores candidatos
    cand_path = runtime_dir / "proveedores_candidatos.csv"
    all_cands = [c for r in resultados for c in r.get("candidatos", [])]
    # Deduplicar por remitente
    seen = set()
    cands_uniq = []
    for c in all_cands:
        key = normalizar_texto(c["remitente"])
        if key not in seen:
            seen.add(key)
            cands_uniq.append(c)
    with open(cand_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_CAND_FIELDS, extrasaction="ignore")
        w.writeheader()
        for c in cands_uniq:
            w.writerow({k: _fmt(c.get(k, "")) for k in CSV_CAND_FIELDS})
    log(f"CSV candidatos escrito: {cand_path}  ({len(cands_uniq)} proveedores unicos)")

    return json_path, docs_path, cand_path


def _resumen_global(resultados: list) -> dict:
    total_msgs = sum(r.get("stats", {}).get("total_mensajes", 0) for r in resultados)
    total_pdfs = sum(r.get("stats", {}).get("total_pdfs", 0) for r in resultados)
    estados: dict = {}
    tipos: dict = {}
    proveedores: dict = {}
    for r in resultados:
        s = r.get("stats", {})
        for k, v in s.get("por_estado", {}).items():
            estados[k] = estados.get(k, 0) + v
        for k, v in s.get("por_tipo", {}).items():
            tipos[k] = tipos.get(k, 0) + v
        for k, v in s.get("por_proveedor", {}).items():
            proveedores[k] = proveedores.get(k, 0) + v
    return {
        "total_mensajes": total_msgs,
        "total_pdfs": total_pdfs,
        "por_estado": dict(sorted(estados.items(), key=lambda x: -x[1])),
        "por_tipo": dict(sorted(tipos.items(), key=lambda x: -x[1])),
        "por_proveedor": dict(sorted(proveedores.items(), key=lambda x: -x[1])),
    }


def imprimir_resumen_final(resultados: list):
    rg = _resumen_global(resultados)
    sep = "=" * 60
    log(f"\n{sep}")
    log(f"RESUMEN GLOBAL — Historico DRY-RUN {VERSION}")
    log(sep)
    log(f"Mensajes procesados: {rg['total_mensajes']}")
    log(f"PDFs analizados:     {rg['total_pdfs']}")
    log("")
    log("Por estado estimado:")
    for est, n in rg["por_estado"].items():
        log(f"  {n:4d}  {est}")
    log("")
    log("Por tipo de documento:")
    for tipo, n in rg["por_tipo"].items():
        log(f"  {n:4d}  {tipo}")
    log("")
    log("Por proveedor (top 15):")
    for prov, n in list(rg["por_proveedor"].items())[:15]:
        log(f"  {n:4d}  {prov}")
    log(sep)


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    configurar_salida_segura()

    parser = argparse.ArgumentParser(
        description=f"generar_historico_dryrun.py {VERSION} — escaneo historico Gmail DRY-RUN"
    )
    parser.add_argument("--skill-dir", help="Ruta al directorio del skill (con config.json y token.pickle)")
    parser.add_argument(
        "--trimestres", nargs="+", metavar="Q",
        choices=list(TRIMESTRES_VALIDOS) + ["todos"],
        default=["todos"],
        help="Trimestres a procesar. Default: todos. Ej: Q1-2025 Q2-2025"
    )
    parser.add_argument("--desde", help="Fecha inicio custom YYYY-MM-DD (ignora --trimestres)")
    parser.add_argument("--hasta", help="Fecha fin custom YYYY-MM-DD (ignora --trimestres)")
    args = parser.parse_args()

    # ── Skill dir ────────────────────────────────────────────
    if args.skill_dir:
        skill_dir = Path(args.skill_dir)
    else:
        skill_dir = encontrar_skill_dir()
    if not skill_dir or not skill_dir.exists():
        log("No se encontro skill-dir. Usa --skill-dir /ruta/al/skill", "ERROR")
        sys.exit(1)
    log(f"Skill dir: {skill_dir}")

    # ── Config ───────────────────────────────────────────────
    config = cargar_config(skill_dir)

    # ── Proveedores y exclusiones ─────────────────────────────
    proveedores = cargar_proveedores(skill_dir)
    log(f"{len(proveedores)} proveedores cargados")
    exclusiones = cargar_exclusiones(skill_dir)
    log(f"{len(exclusiones)} exclusiones cargadas")

    # ── Autenticacion (lee token.pickle, NO abre navegador si token valido) ──
    log("Autenticando...")
    creds = autenticar(skill_dir)

    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    gc    = gspread.authorize(creds)
    log("APIs conectadas")

    # ── MAESTRO_PROVEEDORES (solo lectura) ────────────────────
    ss = None
    try:
        ss = gc.open_by_key(config["SHEET_FACTURAS_ID"])
        maestro_data, sheet_maestro = cargar_maestro_proveedores(ss)
    except Exception as e:
        log(f"No se pudo cargar MAESTRO_PROVEEDORES: {e} — operando sin maestro", "WARN")
        maestro_data, sheet_maestro = {}, None

    # ── Seleccionar trimestres ────────────────────────────────
    if args.desde and args.hasta:
        # Rango custom: convertir formato de fecha para Gmail query
        desde_g = args.desde.replace("-", "/")
        hasta_g = args.hasta.replace("-", "/")
        trimestres = [("CUSTOM", desde_g, hasta_g)]
        log(f"Rango custom: {args.desde} → {args.hasta}")
    elif "todos" in args.trimestres:
        trimestres = TRIMESTRES_DEFAULT
    else:
        trimestres = [t for t in TRIMESTRES_DEFAULT if t[0] in args.trimestres]

    log(f"Trimestres a procesar: {[t[0] for t in trimestres]}")
    log("\n[!] Modo DRY-RUN estricto — sin escritura en Sheets, Drive ni Gmail\n")

    # ── Procesar ──────────────────────────────────────────────
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    resultados = []

    for etiqueta, desde, hasta in trimestres:
        resultado = procesar_trimestre(
            gmail=gmail,
            etiqueta=etiqueta,
            desde=desde,
            hasta=hasta,
            proveedores=proveedores,
            exclusiones=exclusiones,
            maestro_data=maestro_data,
            sheet_maestro=sheet_maestro,
        )
        resultados.append(resultado)

    # ── Salidas ───────────────────────────────────────────────
    runtime_dir = Path(__file__).parent.parent / "runtime"
    json_path, docs_path, cand_path = escribir_salidas(resultados, runtime_dir, ts)

    imprimir_resumen_final(resultados)

    log(f"\nArchivos generados:")
    log(f"  {json_path}")
    log(f"  {docs_path}")
    log(f"  {cand_path}")
    log("\n[!] Ningun dato fue modificado en Sheets, Drive ni Gmail.")


if __name__ == "__main__":
    main()
