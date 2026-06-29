#!/usr/bin/env python3
"""
generar_historico_dryrun.py — Bordagran Fiscal v3.4.2
======================================================
Escaneo historico de Gmail por trimestres en modo DRY-RUN estricto.
v3.4.2: clasificador local de documentos con score de confianza fiscal.

GARANTIAS:
  - NO escribe en FACTURA PROVEEDORES (cero appendRow)
  - NO sube archivos a Google Drive
  - NO modifica etiquetas de Gmail
  - NO modifica MAESTRO_PROVEEDORES
  - Solo lectura: Gmail, Google Sheets (MAESTRO_PROVEEDORES)

Uso:
    python scripts/generar_historico_dryrun.py --skill-dir . --trimestres Q1-2025
    python scripts/generar_historico_dryrun.py --skill-dir . --trimestres Q1-2025 Q2-2025
    python scripts/generar_historico_dryrun.py --skill-dir .   # todos los trimestres

Salidas (en runtime/):
    historico_facturas_probables.csv        Docs confianza ALTA o MEDIA
    historico_facturas_probables.json       Idem en JSON
    historico_documentos_no_fiscales.csv    Docs confianza BAJA
    historico_documentos_no_fiscales.json   Idem en JSON
    proveedores_candidatos.csv              Proveedores no reconocidos (deduplicados)
    tipos_documento_candidatos.csv          Todos los docs con clasificacion v2
"""

import argparse
import csv
import json
import sys
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────────────────
# Bootstrap: importar funciones compartidas de procesar_facturas.py
# main() alli esta protegido por if __name__ == "__main__"
# ─────────────────────────────────────────────────────────
_SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(_SCRIPTS_DIR))

from procesar_facturas import (
    configurar_salida_segura,
    log,
    ESTADOS,
    normalizar_texto,
    autenticar,
    cargar_proveedores,
    cargar_exclusiones,
    identificar_proveedor,
    es_email_excluido,
    extraer_datos_pdf,
    encontrar_skill_dir,
    buscar_mensajes,
    obtener_metadata,
    descargar_adjuntos_pdf,
    cargar_maestro_proveedores,
    buscar_en_maestro,
    criterio_maestro,
)
import gspread
from googleapiclient.discovery import build

# ─────────────────────────────────────────────────────────
# CONSTANTES GLOBALES
# ─────────────────────────────────────────────────────────

VERSION = "v3.4.2"

TRIMESTRES_DEFAULT = [
    ("Q1-2025", "2025/01/01", "2025/04/01"),
    ("Q2-2025", "2025/04/01", "2025/07/01"),
    ("Q3-2025", "2025/07/01", "2025/10/01"),
    ("Q4-2025", "2025/10/01", "2026/01/01"),
    ("Q1-2026", "2026/01/01", "2026/04/01"),
    ("Q2-2026", "2026/04/01", "2026/07/01"),
]
TRIMESTRES_VALIDOS = {t[0] for t in TRIMESTRES_DEFAULT}

# ── Tipos de documento v3.4.2 ──────────────────────────
TIPO_FACTURA         = "factura"
TIPO_RECIBO          = "recibo"
TIPO_PRESUPUESTO     = "presupuesto"
TIPO_TARIFA          = "tarifa"
TIPO_DISENO_ARTE     = "diseno_arte"
TIPO_MANDATO_SEPA    = "mandato_sepa"
TIPO_JUST_BANCARIO   = "justificante_bancario"
TIPO_INFORME_SEO     = "informe_seo"
TIPO_CV_PERSONAL     = "cv_documento_personal"
TIPO_PEDIDO_ALBARAN  = "pedido_albaran"
TIPO_DESCONOCIDO     = "desconocido"

CONFIANZA_ALTA  = "ALTA"
CONFIANZA_MEDIA = "MEDIA"
CONFIANZA_BAJA  = "BAJA"

TIPOS_FISCALES_H   = {TIPO_FACTURA, TIPO_RECIBO}
TIPOS_NO_FISCALES_H = {
    TIPO_PRESUPUESTO, TIPO_TARIFA, TIPO_DISENO_ARTE,
    TIPO_MANDATO_SEPA, TIPO_JUST_BANCARIO, TIPO_INFORME_SEO,
    TIPO_CV_PERSONAL, TIPO_PEDIDO_ALBARAN,
}

# ── CSV fields ──────────────────────────────────────────
CSV_PROBABLES_FIELDS = [
    "trimestre", "fecha_email", "fecha_pdf", "remitente",
    "proveedor", "tipo_doc_v2", "confianza", "senales",
    "num_factura", "total", "iva_pct", "base",
    "nombre_pdf", "msg_id", "notas",
]
CSV_NO_FISCALES_FIELDS = [
    "trimestre", "fecha_email", "remitente",
    "proveedor", "tipo_doc_v2", "confianza",
    "nombre_pdf", "asunto", "msg_id",
]
CSV_TODOS_FIELDS = [
    "trimestre", "fecha_email", "fecha_pdf", "remitente",
    "proveedor", "tipo_doc_v2", "confianza", "senales",
    "num_factura", "total", "iva_pct", "base",
    "nombre_pdf", "msg_id", "notas",
]
CSV_CAND_FIELDS = [
    "trimestre", "fecha_email", "remitente",
    "nombre_detectado", "nombre_pdf", "msg_id", "motivo",
]

# ─────────────────────────────────────────────────────────
# CLASIFICADOR LOCAL v3.4.2
# No depende de clasificar_tipo_documento() de procesar_facturas.py
# ─────────────────────────────────────────────────────────

# Keywords por tipo (se buscan en corpus normalizado sin acentos)
_KW = {
    TIPO_FACTURA: [
        "factura", "invoice", "tax invoice", "fatura", "fattura", "facture",
        "factura simplificada", "factura electronica", "ft fes", "fatura ft",
        "numero de factura", "num. factura", "no. factura", "n. factura",
        "invoice number", "invoice no", "receipt of payment",
        "factura recibo", "factura de venta",
    ],
    TIPO_RECIBO: [
        "recibo", "receipt", "payment receipt", "paid receipt",
        "payment confirmation", "comprobante de pago", "comprobante pago",
        "justificante de pago", "confirmacion de pago",
        "receipt number", "date paid", "amount paid", "recibo de pago",
        "pago recibido", "payment received",
    ],
    TIPO_PRESUPUESTO: [
        "presupuesto", "quotation", "quote no", "quote number",
        "oferta economica", "propuesta economica", "oferta de servicios",
        "proforma", "pro-forma", "estimate", "oferta comercial",
        "estimacion de costes", "propuesta de precio",
    ],
    TIPO_TARIFA: [
        "tarifa ", "tarifas ", "price list", "lista de precios",
        "tabla de precios", "tarifario", "rate card",
        "precio unitario", "coste por metro", "precio por unidad",
        "precios de servicios",
    ],
    TIPO_DISENO_ARTE: [
        "arte final", "artes finales", "mockup", "proof", "prueba de color",
        "diseno grafico", "diseno personalizado", "archivo de diseno",
        "arte para imprimir", "fichero de arte", "diseno bordado",
        "bordado digital", "arte dtf", "diseno dtf",
    ],
    TIPO_MANDATO_SEPA: [
        "mandato sepa", "sepa mandate", "sepa direct debit",
        "adeudo directo sepa", "domiciliacion sepa",
        "autorizacion de adeudo", "sepa core", "core dd",
    ],
    TIPO_JUST_BANCARIO: [
        "justificante de transferencia", "justificante transferencia",
        "aviso giro bancario", "aviso de giro", "giro bancario",
        "aviso de pago bancario", "payment advice",
        "movimiento bancario", "extracto bancario",
        "comprobante de transferencia", "giro de recibo",
        "remesa", "domiciliacion bancaria", "aviso bancario",
    ],
    TIPO_INFORME_SEO: [
        "informe seo", "seo report", "semrush", "ahrefs",
        "posicionamiento web", "keyword ranking",
        "organic traffic", "backlink report",
        "domain authority", "visibilidad organica",
        "reporte de posicionamiento", "analisis seo",
        "google search console", "google analytics report",
    ],
    TIPO_CV_PERSONAL: [
        "curriculum vitae", "curriculum ", "cv profesional",
        "experiencia profesional", "certificado de empadronamiento",
        "vida laboral", "informe vida laboral",
        "historial laboral", "datos de caracter personal",
        "datos personales", "informacion personal",
    ],
    TIPO_PEDIDO_ALBARAN: [
        "albaran de entrega", "albaran ", "delivery note",
        "packing list", "nota de entrega",
        "orden de compra", "purchase order", "po number",
        "pedido num", "pedido n.", "order confirmation",
        "confirmacion de pedido", "nota de pedido",
    ],
}

# Senales fiscales positivas (IVA, CIF, importes, numero factura)
_SENALES_FISCALES = [
    "cif", "nif", "vat number", "cif/nif",
    "iva", "igic", "irpf",
    "base imponible", "tipo impositivo", "cuota tributaria",
    "total factura", "importe total", "total a pagar", "total eur",
    "numero de factura", "factura num", "no. factura", "n. factura",
    "fecha de factura", "fecha emision", "fecha de emision",
    "razon social", "domicilio fiscal",
    "euros", "eur",
]

# Senales negativas: presencia baja confianza aunque aparezca "factura"
_SENALES_NEGATIVAS = [
    "arte final", "mockup", "diseno", "design proof",
    "curriculum", "sepa mandate", "mandato sepa",
    "seo report", "semrush", "ahrefs",
    "presupuesto", "quotation", "proforma",
    "albaran", "delivery note",
    "aviso giro", "giro bancario", "extracto bancario",
]

# Emails propios de Bordagran — nunca son proveedores fiscales externos
# No generan candidatos ni documentos fiscales
_BORDAGRAN_SELF_EMAILS = frozenset({
    "bordagran@gmail.com",
    "bordagran@bordagran.com",
})

def _es_email_propio(email: str) -> bool:
    """True si el remitente es una cuenta propia de Bordagran."""
    return email.lower().strip() in _BORDAGRAN_SELF_EMAILS


# Orden de prioridad: tipos NO fiscales especificos primero (evita falsos positivos)
_PRIORIDAD_TIPOS = [
    TIPO_MANDATO_SEPA,
    TIPO_INFORME_SEO,
    TIPO_CV_PERSONAL,
    TIPO_DISENO_ARTE,
    TIPO_JUST_BANCARIO,
    TIPO_TARIFA,
    TIPO_PRESUPUESTO,
    TIPO_PEDIDO_ALBARAN,
    TIPO_RECIBO,
    TIPO_FACTURA,
]


def _norm_cls(texto: str) -> str:
    """Normaliza para comparacion de keywords: sin acentos, minusculas."""
    if not texto:
        return ""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def clasificar_documento_historico(
    texto_pdf: str,
    nombre_pdf: str,
    remitente: str,
    asunto: str,
    datos_pdf: dict,
    nombre_prov: str,
    es_desconocido: bool,
) -> dict:
    """
    Clasificador local v3.4.2 para el historico dry-run.
    Devuelve: {tipo, confianza, senales, n_pos, n_neg}

    No toca procesar_facturas.py. Sin side-effects. Solo lectura.
    """
    # Corpus normalizado: texto PDF + nombre archivo + remitente + asunto
    corpus = _norm_cls(
        " ".join([texto_pdf or "", nombre_pdf or "", remitente or "", asunto or ""])
    )

    # ── 1. Score por tipo ──────────────────────────────
    scores = {
        tipo: sum(1 for kw in kws if kw in corpus)
        for tipo, kws in _KW.items()
    }

    # Tipo con mayor score segun prioridad (no-fiscales primero)
    tipo_detectado = TIPO_DESCONOCIDO
    for tipo in _PRIORIDAD_TIPOS:
        if scores.get(tipo, 0) > 0:
            tipo_detectado = tipo
            break

    # Override: si factura tiene score >= 3 y el tipo detectado no es fiscal,
    # puede ser que el PDF es una factura con menciones ocasionales de palabras no-fiscales
    if tipo_detectado not in TIPOS_FISCALES_H and scores.get(TIPO_FACTURA, 0) >= 3:
        tipo_detectado = TIPO_FACTURA

    # ── 2. Senales fiscales ───────────────────────────
    senales_pos = [s for s in _SENALES_FISCALES if s in corpus]
    senales_neg = [s for s in _SENALES_NEGATIVAS if s in corpus]
    n_pos = len(senales_pos)
    n_neg = len(senales_neg)

    # ── 3. Datos extraidos del PDF ────────────────────
    tiene_total       = bool(datos_pdf.get("total"))
    tiene_num_factura = bool(datos_pdf.get("num_factura"))
    tiene_iva         = datos_pdf.get("iva_pct") is not None

    # ── 4. Calcular confianza ─────────────────────────
    if tipo_detectado in TIPOS_NO_FISCALES_H:
        # Tipos no fiscales: siempre BAJA
        confianza = CONFIANZA_BAJA

    elif tipo_detectado in TIPOS_FISCALES_H:
        # ALTA: senales fiscales solidas + datos numericos + sin senales negativas
        cond_alta = (
            n_pos >= 3
            and (tiene_total or tiene_num_factura)
            and n_neg == 0
        ) or (
            n_pos >= 2
            and not es_desconocido
            and (tiene_total or tiene_num_factura)
            and n_neg <= 1
        )
        # MEDIA: senales parciales o proveedor conocido con algunos datos
        cond_media = (
            n_pos >= 1
            or (tiene_total and not es_desconocido)
            or tiene_num_factura
        )

        if cond_alta:
            confianza = CONFIANZA_ALTA
        elif cond_media:
            confianza = CONFIANZA_MEDIA
        else:
            confianza = CONFIANZA_BAJA

        # Override: senales negativas fuertes bajan ALTA -> MEDIA
        if confianza == CONFIANZA_ALTA and n_neg >= 2:
            confianza = CONFIANZA_MEDIA

    else:
        # TIPO_DESCONOCIDO: puede ser factura si tiene senales fiscales + datos
        if n_pos >= 2 and (tiene_total or tiene_num_factura):
            tipo_detectado = TIPO_FACTURA  # probable no clasificado
            confianza = CONFIANZA_MEDIA
        else:
            confianza = CONFIANZA_BAJA

    return {
        "tipo":      tipo_detectado,
        "confianza": confianza,
        "senales":   senales_pos[:5],   # top 5 para display
        "n_pos":     n_pos,
        "n_neg":     n_neg,
    }


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
    Query Gmail para el trimestre.
    La clasificacion posterior separa documentos fiscales de no fiscales.
    Mantenemos query amplia para no perder facturas reales.
    """
    return f"has:attachment filename:pdf after:{desde} before:{hasta}"


def _fmt(v) -> str:
    """Formato seguro para CSV."""
    if v is None:
        return ""
    if isinstance(v, list):
        return "|".join(str(x) for x in v)
    return str(v).replace("\n", " ").replace("\r", " ").strip()


def _es_excluido_por_nombre(nombre: str, exclusiones: list) -> dict | None:
    """Comprueba palabras_clave de exclusiones contra nombre de proveedor."""
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
    Procesa un trimestre. CERO escrituras a Sheets, Drive o Gmail.
    Devuelve dict con resultados clasificados.
    """
    log(f"\n{'='*60}")
    log(f"TRIMESTRE: {etiqueta}  ({desde} -> {hasta})")
    log(f"{'='*60}")

    query = query_trimestre(etiqueta, desde, hasta)
    log(f"Query Gmail: {query}")

    try:
        mensajes = buscar_mensajes(gmail, query)
    except Exception as e:
        log(f"Error buscando mensajes {etiqueta}: {e}", "ERROR")
        return {
            "trimestre": etiqueta, "desde": desde, "hasta": hasta,
            "stats": {}, "docs": [], "candidatos": [], "error": str(e),
        }

    log(f"Mensajes encontrados: {len(mensajes)}")

    docs       = []
    candidatos = []
    stats = {
        "total_mensajes":  len(mensajes),
        "total_pdfs":      0,
        "por_tipo_v2":     {},
        "por_confianza":   {CONFIANZA_ALTA: 0, CONFIANZA_MEDIA: 0, CONFIANZA_BAJA: 0},
        "por_proveedor":   {},
        "excluidos":       0,
        "desconocidos":    0,
        "errores_pdf":     0,
    }

    for i, msg in enumerate(mensajes, 1):
        msg_id = msg["id"]

        try:
            meta = obtener_metadata(gmail, msg_id)
        except Exception as e:
            log(f"  [{i}/{len(mensajes)}] Error metadata {msg_id}: {e}", "WARN")
            continue

        remitente   = meta.get("remitente", "")
        fecha_email = meta.get("fecha", "")
        asunto      = meta.get("asunto", "")

        # Email propio de Bordagran: no es proveedor externo, no genera candidato
        if _es_email_propio(remitente):
            log(f"  [{i}] PROPIO - omitiendo: {remitente}")
            stats["excluidos"] += 1
            continue

        # Exclusion por email exacto o palabras_clave
        excl = es_email_excluido(remitente, exclusiones)
        if excl:
            log(f"  [{i}] EXCLUIDO email ({excl.get('motivo','?')}): {remitente}")
            stats["excluidos"] += 1
            continue

        prov          = identificar_proveedor(remitente, proveedores)
        es_desconocido = prov.get("_desconocido", False)
        nombre_prov   = prov.get("nombre", remitente)

        # Exclusion por nombre de proveedor (keywords v3.4.0)
        excl_nombre = _es_excluido_por_nombre(nombre_prov, exclusiones)
        if excl_nombre:
            log(f"  [{i}] EXCLUIDO nombre ({excl_nombre.get('motivo','?')}): {nombre_prov}")
            stats["excluidos"] += 1
            continue

        log(f"  [{i}/{len(mensajes)}] {remitente} -> {nombre_prov}")

        # Descargar adjuntos PDF a directorio temporal (no se guardan en Drive)
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

                # Proveedor desconocido: registrar como candidato (deduplicado al escribir)
                if es_desconocido:
                    stats["desconocidos"] += 1
                    candidatos.append({
                        "trimestre":      etiqueta,
                        "fecha_email":    fecha_email,
                        "remitente":      remitente,
                        "nombre_detectado": nombre_prov,
                        "nombre_pdf":     nombre_pdf,
                        "msg_id":         msg_id,
                        "motivo":         "Proveedor no reconocido en proveedores.json",
                    })

                # Extraer datos numericos del PDF (pdfplumber)
                try:
                    datos_pdf = extraer_datos_pdf(ruta_local) if ruta_local else {}
                except Exception as e:
                    log(f"    Error extrayendo {nombre_pdf}: {e}", "WARN")
                    datos_pdf = {"notas": f"Error PDF: {str(e)[:80]}"}
                    stats["errores_pdf"] += 1

                texto_pdf = datos_pdf.get("_texto_completo", "")

                # ── Clasificacion local v3.4.2 ──────────────
                clas = clasificar_documento_historico(
                    texto_pdf=texto_pdf,
                    nombre_pdf=nombre_pdf,
                    remitente=remitente,
                    asunto=asunto,
                    datos_pdf=datos_pdf,
                    nombre_prov=nombre_prov,
                    es_desconocido=es_desconocido,
                )
                tipo_v2   = clas["tipo"]
                confianza = clas["confianza"]
                senales   = clas["senales"]

                # Proveedor excluido en Maestro
                entrada_maestro  = buscar_en_maestro(maestro_data, nombre_prov)
                criterio         = criterio_maestro(entrada_maestro)
                accion_criterio  = (criterio or {}).get("accion", "")
                if accion_criterio == "excluir":
                    log(f"    EXCLUIDO Maestro: {nombre_prov} -> {nombre_pdf}")
                    stats["excluidos"] += 1
                    continue

                # ── Boost de confianza: proveedor conocido + datos fiscales extraidos ──
                # Razon: n_pos=0 es frecuente cuando el texto PDF no contiene las palabras
                # clave exactas (PDF imagen, encoding raro, texto en cabecera email).
                # Si el proveedor ya esta validado en Maestro o es conocido en proveedores.json
                # y el parser extrajo num_factura + total, la confianza debe ser ALTA.
                if tipo_v2 in TIPOS_FISCALES_H:
                    _tiene_todo = (
                        bool(datos_pdf.get("num_factura")) and bool(datos_pdf.get("total"))
                    )
                    _tiene_algo = (
                        bool(datos_pdf.get("total")) or bool(datos_pdf.get("num_factura"))
                    )
                    # Comprobar si el Maestro lo tiene como validado / proveedor seguro
                    _es_validado = False
                    if entrada_maestro:
                        _ev = str(entrada_maestro.get("estado_validacion", "")).strip().lower()
                        _ps = str(entrada_maestro.get("proveedor_seguro", "")).strip().lower()
                        if _ev in ("validada carlos", "validada") or _ps == "si":
                            _es_validado = True
                    # Regla ALTA: (validado en Maestro O proveedor conocido) + num_factura + total
                    if (
                        (_es_validado or not es_desconocido)
                        and _tiene_todo
                        and confianza != CONFIANZA_ALTA
                        and clas.get("n_neg", 0) < 2
                    ):
                        confianza = CONFIANZA_ALTA
                    # Regla ALTA degradada: señal negativa fuerte -> no forzar ALTA, quedar en MEDIA
                    elif (
                        (_es_validado or not es_desconocido)
                        and _tiene_todo
                        and clas.get("n_neg", 0) >= 2
                        and confianza == CONFIANZA_BAJA
                    ):
                        confianza = CONFIANZA_MEDIA
                    # Regla MEDIA: proveedor conocido + algun dato fiscal pero no todo
                    elif not es_desconocido and _tiene_algo and confianza == CONFIANZA_BAJA:
                        confianza = CONFIANZA_MEDIA

                elif tipo_v2 == TIPO_DESCONOCIDO and not es_desconocido:
                    # Proveedor conocido con documento no clasificado:
                    # si el parser extrajo datos fiscales, es probablemente una factura
                    _tiene_algo = (
                        bool(datos_pdf.get("total")) or bool(datos_pdf.get("num_factura"))
                    )
                    if _tiene_algo:
                        tipo_v2   = TIPO_FACTURA
                        confianza = CONFIANZA_MEDIA

                # Acumular stats
                stats["por_tipo_v2"][tipo_v2] = stats["por_tipo_v2"].get(tipo_v2, 0) + 1
                stats["por_confianza"][confianza] = stats["por_confianza"].get(confianza, 0) + 1
                stats["por_proveedor"][nombre_prov] = stats["por_proveedor"].get(nombre_prov, 0) + 1

                doc = {
                    # Identificacion
                    "trimestre":    etiqueta,
                    "fecha_email":  fecha_email,
                    "fecha_pdf":    datos_pdf.get("fecha", ""),
                    "remitente":    remitente,
                    "proveedor":    nombre_prov,
                    "asunto":       asunto,
                    "nombre_pdf":   nombre_pdf,
                    "msg_id":       msg_id,
                    # Clasificacion v3.4.2
                    "tipo_doc_v2":  tipo_v2,
                    "confianza":    confianza,
                    "senales":      senales,
                    # Datos fiscales extraidos
                    "num_factura":  datos_pdf.get("num_factura", ""),
                    "total":        datos_pdf.get("total", ""),
                    "iva_pct":      datos_pdf.get("iva_pct", ""),
                    "base":         datos_pdf.get("base", ""),
                    "notas":        datos_pdf.get("notas", ""),
                    # Meta
                    "_es_desconocido": es_desconocido,
                }
                docs.append(doc)

                log(f"    {nombre_pdf}: {tipo_v2} [{confianza}] senales={clas['n_pos']} neg={clas['n_neg']}")

    log(f"\n  Resumen {etiqueta}:")
    log(f"    Mensajes:  {stats['total_mensajes']}")
    log(f"    PDFs:      {stats['total_pdfs']}")
    log(f"    ALTA:      {stats['por_confianza'].get(CONFIANZA_ALTA, 0)}")
    log(f"    MEDIA:     {stats['por_confianza'].get(CONFIANZA_MEDIA, 0)}")
    log(f"    BAJA:      {stats['por_confianza'].get(CONFIANZA_BAJA, 0)}")
    log(f"    Excluidos: {stats['excluidos']}")
    log(f"    Errores:   {stats['errores_pdf']}")

    return {
        "trimestre": etiqueta,
        "desde":     desde,
        "hasta":     hasta,
        "stats":     stats,
        "docs":      docs,
        "candidatos": candidatos,
    }


# ─────────────────────────────────────────────────────────
# ESCRITURA DE SALIDAS (5 archivos — NUNCA toca Sheets/Drive/Gmail)
# ─────────────────────────────────────────────────────────

def escribir_salidas(resultados: list, runtime_dir: Path, ts: str):
    runtime_dir.mkdir(exist_ok=True)

    all_docs  = [d for r in resultados for d in r.get("docs", [])]
    all_cands = [c for r in resultados for c in r.get("candidatos", [])]

    # Separar por confianza
    probables    = [d for d in all_docs if d["confianza"] in (CONFIANZA_ALTA, CONFIANZA_MEDIA)]
    no_fiscales  = [d for d in all_docs if d["confianza"] == CONFIANZA_BAJA]

    # Deduplicar candidatos por remitente
    seen_cands: set = set()
    cands_uniq = []
    for c in all_cands:
        key = normalizar_texto(c["remitente"])
        if key not in seen_cands:
            seen_cands.add(key)
            cands_uniq.append(c)

    # ── 1. historico_facturas_probables.csv ──────────
    p_csv = runtime_dir / "historico_facturas_probables.csv"
    with open(p_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_PROBABLES_FIELDS, extrasaction="ignore")
        w.writeheader()
        for d in probables:
            row = {k: _fmt(d.get(k, "")) for k in CSV_PROBABLES_FIELDS}
            w.writerow(row)
    log(f"CSV probables:     {p_csv}  ({len(probables)} docs)")

    # ── 2. historico_facturas_probables.json ─────────
    p_json = runtime_dir / "historico_facturas_probables.json"
    with open(p_json, "w", encoding="utf-8") as f:
        json.dump({
            "_meta": {"version": VERSION, "generado": ts,
                      "nota": "DRY-RUN - confianza ALTA o MEDIA"},
            "total": len(probables),
            "facturas": probables,
        }, f, ensure_ascii=False, indent=2)
    log(f"JSON probables:    {p_json}")

    # ── 3. historico_documentos_no_fiscales.csv ──────
    nf_csv = runtime_dir / "historico_documentos_no_fiscales.csv"
    with open(nf_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_NO_FISCALES_FIELDS, extrasaction="ignore")
        w.writeheader()
        for d in no_fiscales:
            row = {k: _fmt(d.get(k, "")) for k in CSV_NO_FISCALES_FIELDS}
            w.writerow(row)
    log(f"CSV no fiscales:   {nf_csv}  ({len(no_fiscales)} docs)")

    # ── 4. historico_documentos_no_fiscales.json ─────
    nf_json = runtime_dir / "historico_documentos_no_fiscales.json"
    with open(nf_json, "w", encoding="utf-8") as f:
        json.dump({
            "_meta": {"version": VERSION, "generado": ts,
                      "nota": "DRY-RUN - confianza BAJA, no son facturas fiscales probables"},
            "total": len(no_fiscales),
            "documentos": no_fiscales,
        }, f, ensure_ascii=False, indent=2)
    log(f"JSON no fiscales:  {nf_json}")

    # ── 5. tipos_documento_candidatos.csv (todos) ────
    todos_csv = runtime_dir / "tipos_documento_candidatos.csv"
    with open(todos_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_TODOS_FIELDS, extrasaction="ignore")
        w.writeheader()
        for d in all_docs:
            row = {k: _fmt(d.get(k, "")) for k in CSV_TODOS_FIELDS}
            w.writerow(row)
    log(f"CSV todos docs:    {todos_csv}  ({len(all_docs)} docs)")

    # ── 6. proveedores_candidatos.csv ────────────────
    cand_csv = runtime_dir / "proveedores_candidatos.csv"
    with open(cand_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_CAND_FIELDS, extrasaction="ignore")
        w.writeheader()
        for c in cands_uniq:
            w.writerow({k: _fmt(c.get(k, "")) for k in CSV_CAND_FIELDS})
    log(f"CSV candidatos:    {cand_csv}  ({len(cands_uniq)} unicos)")

    return p_csv, p_json, nf_csv, nf_json, todos_csv, cand_csv


# ─────────────────────────────────────────────────────────
# RESUMEN GLOBAL
# ─────────────────────────────────────────────────────────

def _resumen_global(resultados: list) -> dict:
    total_msgs = 0
    total_pdfs = 0
    por_tipo:       dict = {}
    por_confianza   = {CONFIANZA_ALTA: 0, CONFIANZA_MEDIA: 0, CONFIANZA_BAJA: 0}
    por_proveedor:  dict = {}
    total_excluidos = 0
    total_desconocidos = 0
    total_errores  = 0

    for r in resultados:
        s = r.get("stats", {})
        total_msgs += s.get("total_mensajes", 0)
        total_pdfs += s.get("total_pdfs", 0)
        total_excluidos    += s.get("excluidos", 0)
        total_desconocidos += s.get("desconocidos", 0)
        total_errores      += s.get("errores_pdf", 0)
        for k, v in s.get("por_tipo_v2", {}).items():
            por_tipo[k] = por_tipo.get(k, 0) + v
        for k, v in s.get("por_confianza", {}).items():
            por_confianza[k] = por_confianza.get(k, 0) + v
        # Ranking fiscal: solo documentos ALTA o MEDIA (excluye BAJA, excluidos, propios)
        for doc in r.get("docs", []):
            if doc.get("confianza") in (CONFIANZA_ALTA, CONFIANZA_MEDIA):
                prov = doc.get("proveedor", "")
                if prov:
                    por_proveedor[prov] = por_proveedor.get(prov, 0) + 1

    # Candidatos unicos globales
    all_cands = [c for r in resultados for c in r.get("candidatos", [])]
    seen: set = set()
    cands_uniq = []
    for c in all_cands:
        key = normalizar_texto(c["remitente"])
        if key not in seen:
            seen.add(key)
            cands_uniq.append(c)

    return {
        "total_mensajes":    total_msgs,
        "total_pdfs":        total_pdfs,
        "por_confianza":     por_confianza,
        "por_tipo_v2":       dict(sorted(por_tipo.items(), key=lambda x: -x[1])),
        "por_proveedor":     dict(sorted(por_proveedor.items(), key=lambda x: -x[1])),
        "excluidos":         total_excluidos,
        "candidatos_unicos": len(cands_uniq),
        "desconocidos_total": total_desconocidos,
        "errores":           total_errores,
    }


def imprimir_resumen_final(resultados: list):
    rg  = _resumen_global(resultados)
    sep = "=" * 60
    log(f"\n{sep}")
    log(f"RESUMEN GLOBAL - Historico DRY-RUN {VERSION}")
    log(sep)
    log(f"Mensajes procesados:         {rg['total_mensajes']:>6}")
    log(f"PDFs analizados:             {rg['total_pdfs']:>6}")
    log("")
    log(f"Facturas probables ALTA:     {rg['por_confianza'].get(CONFIANZA_ALTA, 0):>6}")
    log(f"Facturas probables MEDIA:    {rg['por_confianza'].get(CONFIANZA_MEDIA, 0):>6}")
    log(f"Documentos BAJA descartados: {rg['por_confianza'].get(CONFIANZA_BAJA, 0):>6}")
    log("")
    log("Documentos no fiscales por tipo:")
    tipos_no_f = [t for t in TIPOS_NO_FISCALES_H | {TIPO_DESCONOCIDO}]
    for tipo in sorted(tipos_no_f):
        n = rg["por_tipo_v2"].get(tipo, 0)
        if n:
            log(f"  {tipo:<28} {n:>4}")
    log("")
    log(f"Proveedores candidatos unicos:{rg['candidatos_unicos']:>5}")
    log(f"Desconocidos (instancias):   {rg['desconocidos_total']:>6}")
    log(f"Excluidos (email/nombre):    {rg['excluidos']:>6}")
    log(f"Errores PDF:                 {rg['errores']:>6}")
    log("")
    log("Proveedores fiscales ALTA+MEDIA (top 10):")
    for prov, n in list(rg["por_proveedor"].items())[:10]:
        log(f"  {n:4d}  {prov}")
    log("")
    log("[!] Ningun dato fue modificado en Sheets, Drive ni Gmail.")
    log(sep)


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    configurar_salida_segura()

    parser = argparse.ArgumentParser(
        description=f"generar_historico_dryrun.py {VERSION} — escaneo historico Gmail DRY-RUN"
    )
    parser.add_argument(
        "--skill-dir",
        help="Ruta al directorio del skill (con config.json y token.pickle)"
    )
    parser.add_argument(
        "--trimestres", nargs="+", metavar="Q",
        choices=list(TRIMESTRES_VALIDOS) + ["todos"],
        default=["todos"],
        help="Trimestres a procesar. Default: todos. Ej: Q1-2025 Q2-2025"
    )
    parser.add_argument(
        "--desde",
        help="Fecha inicio custom YYYY-MM-DD (ignora --trimestres)"
    )
    parser.add_argument(
        "--hasta",
        help="Fecha fin custom YYYY-MM-DD (ignora --trimestres)"
    )
    args = parser.parse_args()

    # ── Skill dir ──────────────────────────────────────
    if args.skill_dir:
        skill_dir = Path(args.skill_dir)
    else:
        skill_dir = encontrar_skill_dir()
    if not skill_dir or not skill_dir.exists():
        log("No se encontro skill-dir. Usa --skill-dir /ruta/al/skill", "ERROR")
        sys.exit(1)
    log(f"Skill dir: {skill_dir}")

    # ── Config ─────────────────────────────────────────
    config = cargar_config(skill_dir)

    # ── Proveedores y exclusiones ──────────────────────
    proveedores = cargar_proveedores(skill_dir)
    log(f"{len(proveedores)} proveedores cargados")
    exclusiones = cargar_exclusiones(skill_dir)
    log(f"{len(exclusiones)} exclusiones cargadas")

    # ── Autenticacion ──────────────────────────────────
    log("Autenticando...")
    creds = autenticar(skill_dir)
    gmail = build("gmail", "v1", credentials=creds, cache_discovery=False)
    gc    = gspread.authorize(creds)
    log("APIs conectadas (solo lectura)")

    # ── MAESTRO_PROVEEDORES (solo lectura) ─────────────
    ss = None
    try:
        ss = gc.open_by_key(config["SHEET_FACTURAS_ID"])
        maestro_data, sheet_maestro = cargar_maestro_proveedores(ss)
    except Exception as e:
        log(f"No se pudo cargar MAESTRO: {e} - operando sin maestro", "WARN")
        maestro_data, sheet_maestro = {}, None

    # ── Seleccionar trimestres ─────────────────────────
    if args.desde and args.hasta:
        desde_g  = args.desde.replace("-", "/")
        hasta_g  = args.hasta.replace("-", "/")
        trimestres = [("CUSTOM", desde_g, hasta_g)]
        log(f"Rango custom: {args.desde} -> {args.hasta}")
    elif "todos" in args.trimestres:
        trimestres = TRIMESTRES_DEFAULT
    else:
        trimestres = [t for t in TRIMESTRES_DEFAULT if t[0] in args.trimestres]

    log(f"Trimestres: {[t[0] for t in trimestres]}")
    log(f"\n[!] Modo DRY-RUN estricto {VERSION} - sin escritura en Sheets, Drive ni Gmail\n")

    # ── Procesar ───────────────────────────────────────
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

    # ── Salidas ────────────────────────────────────────
    runtime_dir = Path(__file__).parent.parent / "runtime"
    salidas = escribir_salidas(resultados, runtime_dir, ts)

    imprimir_resumen_final(resultados)

    log("\nArchivos generados:")
    for s in salidas:
        log(f"  {s}")
    log("\n[!] Ningun dato fue modificado en Sheets, Drive ni Gmail.")


if __name__ == "__main__":
    main()
