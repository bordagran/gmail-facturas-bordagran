"""
procesar_facturas.py — Bordagran Fiscal v2.0
Procesa facturas PDF de Gmail → Drive → Google Sheets con anti-duplicados robusto.

Uso:
    python scripts/procesar_facturas.py --modo incremental --skill-dir /ruta
    python scripts/procesar_facturas.py --modo incremental --dias 7 --skill-dir /ruta
    python scripts/procesar_facturas.py --modo backfill --desde 2026-04-01 --hasta 2026-06-30 --skill-dir /ruta

Modos:
    incremental  → últimos N días (default 7)
    backfill     → rango de fechas explícito (requiere --desde y --hasta)
"""

import argparse
import base64
import hashlib
import json
import os
import pickle
import re
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pdfplumber
from dateutil import parser as dateparser
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import gspread

# ─────────────────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────────────────

SCOPES = [
    "https://mail.google.com/",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

ESTADOS = {
    "REGISTRADA": "Registrada",
    "REVISAR":    "Revisar",
    "DUPLICADA":  "Duplicada",
    "ERROR":      "Error lectura",
    "VALIDADA":   "Validada Carlos",   # solo revisión humana
}

# Columnas del Sheet (base 1)
COL = {
    "FECHA": 1, "TRIMESTRE": 2, "PROVEEDOR": 3, "EMAIL": 4,
    "NUM_FACTURA": 5, "CONCEPTO": 6, "BASE": 7, "IVA_PCT": 8,
    "IVA_EUR": 9, "TOTAL": 10, "RUTA_PDF": 11, "ESTADO": 12,
    "NOTAS": 13, "FECHA_PROCESO": 14, "MSG_ID": 15,
    "ATT_ID": 16, "HASH_PDF": 17, "CLAVE_UNICA": 18,
}

LOCK_TIMEOUT_MIN = 60


# ─────────────────────────────────────────────────────────
# UTILIDADES
# ─────────────────────────────────────────────────────────

def log(msg: str, nivel: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] [{nivel}] {msg}")


def encontrar_skill_dir() -> Path:
    """Busca dinámicamente la carpeta gmail-facturas-bordagran en AppData."""
    import os
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    bases = [Path(appdata) / "Claude", Path(localappdata) / "Packages"]
    for base in bases:
        if not base.exists():
            continue
        for p in base.rglob("gmail-facturas-bordagran"):
            if p.is_dir() and (p / "SKILL.md").exists():
                return p
    return None


def normalizar_texto(texto: str) -> str:
    if not texto:
        return ""
    return re.sub(r'\s+', '', texto).upper().strip()


def calcular_trimestre(fecha: datetime) -> str:
    return f"Q{(fecha.month - 1) // 3 + 1}-{fecha.year}"


def hash_pdf(ruta: str) -> str:
    sha = hashlib.sha256()
    with open(ruta, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def clave_unica(proveedor: str, num_factura: str, fecha: str, total: float) -> str:
    prov_n = normalizar_texto(proveedor)
    num_n = normalizar_texto(num_factura)
    fecha_n = normalizar_texto(fecha)
    total_n = f"{total:.2f}" if total else "0"
    raw = f"{prov_n}_{num_n}_{fecha_n}_{total_n}"
    return hashlib.md5(raw.encode()).hexdigest()


def parse_importe(s: str) -> float:
    if not s:
        return None
    s = str(s).strip().replace("€", "").replace(" ", "").replace("\xa0", "")
    # Formato europeo: 1.234,56 → 1234.56
    if re.search(r"\d\.\d{3},", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.search(r"\d,\d{2}$", s):
        s = s.replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


# ─────────────────────────────────────────────────────────
# LOCK DE EJECUCIÓN
# ─────────────────────────────────────────────────────────

class Lock:
    def __init__(self, skill_dir: Path):
        self.path = skill_dir / "runtime" / "procesar_facturas.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def adquirir(self) -> bool:
        if self.path.exists():
            mtime = datetime.fromtimestamp(self.path.stat().st_mtime)
            edad_min = (datetime.now() - mtime).seconds / 60
            if edad_min < LOCK_TIMEOUT_MIN:
                log(f"⚠️  Lock activo (edad: {edad_min:.0f} min). Otra ejecución en curso.", "WARN")
                return False
            else:
                log(f"Lock antiguo detectado ({edad_min:.0f} min). Limpiando.", "WARN")
                self.liberar()
        self.path.write_text(datetime.now().isoformat())
        return True

    def liberar(self):
        if self.path.exists():
            self.path.unlink()


# ─────────────────────────────────────────────────────────
# AUTENTICACIÓN GOOGLE
# ─────────────────────────────────────────────────────────

def autenticar(skill_dir: Path):
    token_path = skill_dir / "token.pickle"
    creds_path = skill_dir / "credentials.json"

    if not creds_path.exists():
        print("\n" + "!" * 60)
        print("❌ CREDENCIALES NO ENCONTRADAS")
        print("!" * 60)
        print(f"\nFalta el archivo: {creds_path}")
        print("\nSolución:")
        print("  1. Ve a console.cloud.google.com")
        print("  2. Selecciona tu proyecto bordagran-fiscal")
        print("  3. APIs & Services → Credentials")
        print("  4. Descarga el OAuth 2.0 Client ID")
        print(f"  5. Guárdalo como credentials.json en:\n     {skill_dir}\n")
        sys.exit(1)

    creds = None
    if token_path.exists():
        try:
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
            log("Token existente cargado")
        except Exception as e:
            log(f"Token corrupto, ignorando: {e}", "WARN")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log("Token expirado — renovando automáticamente...")
            try:
                creds.refresh(Request())
                log("Token renovado OK")
            except Exception as e:
                log(f"No se pudo renovar el token: {e}", "WARN")
                creds = None

        if not creds or not creds.valid:
            log("No hay sesión válida. Iniciando autenticación OAuth...")
            print("\n" + "-" * 60)
            print("  AUTENTICACIÓN REQUERIDA")
            print("  Se abrirá el navegador para autorizar con bordagran@gmail.com")
            print("  Si el navegador no abre, usa la URL que aparece en pantalla.")
            print("-" * 60 + "\n")
            try:
                flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
                creds = flow.run_local_server(port=0, open_browser=True)
            except Exception as e:
                print(f"\n❌ ERROR EN AUTENTICACIÓN OAUTH: {e}")
                print("\nPosibles causas:")
                print("  - credentials.json no es de tipo 'Desktop app'")
                print("  - Las APIs de Gmail/Drive/Sheets no están habilitadas en GCP")
                print("  - El email bordagran@gmail.com no está como usuario de prueba en GCP")
                sys.exit(1)

        try:
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
            log(f"Token guardado en: {token_path}")
        except Exception as e:
            log(f"Advertencia: no se pudo guardar token: {e}", "WARN")

    return creds


# ─────────────────────────────────────────────────────────
# PROVEEDORES
# ─────────────────────────────────────────────────────────

def cargar_proveedores(skill_dir: Path) -> list:
    prov_path = skill_dir / "references" / "proveedores.json"
    if prov_path.exists():
        with open(prov_path) as f:
            return json.load(f)
    return []


def identificar_proveedor(email: str, proveedores: list) -> dict:
    """
    Soporta proveedores.json con 'emails' (array) + 'matchType' (camelCase)
    y el formato legacy 'email' (string) + 'match_type' (snake_case).
    """
    lower = email.lower()
    for p in proveedores:
        if not p.get("activo", True):
            continue
        patterns = p.get("emails") or ([p.get("email")] if p.get("email") else [])
        match_type = p.get("matchType") or p.get("match_type", "exact")
        for pattern in patterns:
            if not pattern:
                continue
            if match_type == "exact" and lower == pattern.lower():
                return p
            if match_type == "contains" and pattern.lower() in lower:
                return p
    # Fallback: coincidencia por dominio (ej: account.canva.com -> canva.com)
    if "@" in email:
        email_dominio = email.lower().split("@")[1]  # e.g. account.canva.com
        for p in proveedores:
            if not p.get("activo", True):
                continue
            # Checar si el dominio del email termina en un dominio conocido del proveedor
            dom_prov = p.get("dominio", "").lower()
            if dom_prov and (email_dominio == dom_prov or email_dominio.endswith("." + dom_prov)):
                return p
            # Checar dominios_extra
            for dom_ext in p.get("dominios_extra", []):
                if email_dominio == dom_ext.lower() or email_dominio.endswith("." + dom_ext.lower()):
                    return p
    # Desconocido
    dominio = email.split("@")[1].split(".")[0].upper() if "@" in email else "DESCONOCIDO"
    return {"nombre": dominio, "_desconocido": True, "email": email}


# ─────────────────────────────────────────────────────────
# EXCLUSIONES (clientes / no proveedores)
# ─────────────────────────────────────────────────────────

def cargar_exclusiones(skill_dir: Path) -> list:
    excl_path = skill_dir / "references" / "exclusiones.json"
    if excl_path.exists():
        with open(excl_path) as f:
            return json.load(f)
    return []


def es_email_excluido(email: str, exclusiones: list) -> dict | None:
    """Devuelve el registro de exclusión si el email está excluido, None en caso contrario."""
    lower = email.lower()
    for excl in exclusiones:
        if excl.get("email", "").lower() == lower:
            return excl
    return None


# ─────────────────────────────────────────────────────────
# CLASIFICACIÓN DE TIPO DE DOCUMENTO
# ─────────────────────────────────────────────────────────

# Tipos fiscales que SE INSERTAN en FACTURA PROVEEDORES
TIPOS_FISCALES = {"factura", "factura_simplificada", "factura_en_cuerpo", "factura_recibo_digital"}

# Proveedores que pueden insertar con referencia tecnica autogenerada (sin num fiscal real)
PROVEEDORES_REF_TECNICA = {"canva", "anthropic"}

# Estado especial: datos insuficientes para insertar en Sheet
ESTADO_PENDIENTE_EXTRACCION = "PENDIENTE_EXTRACCION_SIN_REGISTRAR"

# Keywords para detectar documentos no fiscales

# Keywords positivos multilingues de factura
_KW_FACTURA_POS = [
    # Espanol
    "factura simplificada", "factura", "recibo fiscal",
    # Portugues
    "fatura ft", "fatura", "recibo",
    # Ingles
    "tax invoice", "paid receipt", "payment receipt", "invoice",
    # Frances
    "facture", "recu fiscal",
    # Italiano
    "fattura", "ricevuta fiscale",
]
# Patrones de recibo fiscal digital (Anthropic, Stripe, etc)
_KW_RECIBO_DIGITAL = [
    "invoice number", "receipt number", "date paid", "amount paid",
    "receipt for", "payment confirmation",
]
# Patron portugues fatura
_PAT_FATURA_PT = [
    "fatura ft", "ft fes.", "ft fes ", "fes.2026/", "fes.2025/",
    "fes_2026_", "fes_2025_", "documento valido apos boa cobranca",
    "documento valido apos", "documento válido após",
]

_KW_ALBARAN = [
    "albarán", "albaran", "albarán de entrega", "nota de entrega",
    "delivery note", "delivery slip", "packing list",
]
_KW_AVISO_BANCARIO = [
    "aviso giro bancario", "aviso de giro", "giro bancario",
    "remesa", "rem26-", "rem25-", "rem24-", "rem23-",
    "aviso de pago", "payment notice", "payment advice",
    "aviso bancario", "domiciliación bancaria",
]
_KW_PRESUPUESTO = [
    "presupuesto", "oferta económica", "propuesta económica",
    "quotation", "quote no", "estimate",
]
_KW_PEDIDO = [
    "orden de compra", "pedido nº", "pedido n°", "orden de pedido",
    "purchase order", "p.o. number", "po number",
]


def clasificar_tipo_documento(texto_pdf: str, remitente: str, exclusiones: list) -> tuple:
    """
    Clasifica el tipo de documento ANTES de registrar en el Sheet.
    Soporta documentos en ES/PT/EN/FR/IT.

    Tipos que SE INSERTAN: factura, factura_simplificada, factura_en_cuerpo, factura_recibo_digital
    Tipos que NO se insertan: albaran, aviso_bancario, presupuesto, pedido,
                              cliente_no_proveedor, desconocido
    """
    # 1. Lista de exclusiones (clientes, no proveedores)
    excl = es_email_excluido(remitente, exclusiones)
    if excl:
        return ("cliente_no_proveedor", excl.get("motivo", "Email en lista de exclusion"))

    t = texto_pdf.lower() if texto_pdf else ""

    # 2. Albaran (prioridad: evitar falsos positivos de facturas que
    #    mencionan numero de albaran en la propia factura)
    # Solo si la PRIMERA linea o cabecera contiene la keyword
    primeras_lineas = " ".join(t.split("\n")[:5]).lower()
    for kw in _KW_ALBARAN:
        if kw in primeras_lineas:
            return ("albaran", "Keyword albaran en cabecera: '{}'".format(kw))

    # 3. Aviso bancario / giro / remesa
    for kw in _KW_AVISO_BANCARIO:
        if kw in t:
            return ("aviso_bancario", "Keyword '{}'".format(kw))

    # 4. Presupuesto
    for kw in _KW_PRESUPUESTO:
        if kw in t:
            return ("presupuesto", "Keyword '{}'".format(kw))

    # 5. Pedido
    for kw in _KW_PEDIDO:
        if kw in t:
            return ("pedido", "Keyword '{}'".format(kw))

    # 6. Recibo fiscal digital (Anthropic, Stripe, etc)
    kw_dig = sum(1 for kw in _KW_RECIBO_DIGITAL if kw in t)
    if kw_dig >= 2:
        return ("factura_recibo_digital", "Recibo digital: {} keywords recibo".format(kw_dig))

    # 7. Fatura portuguesa (FT FES, Fatura FT, etc)
    for pat in _PAT_FATURA_PT:
        if pat in t:
            return ("factura", "Fatura portuguesa: patron '{}'".format(pat))

    # 8. Factura simplificada
    if re.search(r"factura\s+simplificada", t):
        return ("factura_simplificada", "Factura simplificada")

    # 9. Facturas multilingue (ES/EN/PT/FR/IT)
    # Verificar en orden para evitar falsos positivos
    for kw in _KW_FACTURA_POS:
        if kw in t:
            return ("factura", "Keyword factura [{}]: '{}'".format(
                "PT" if kw in ("fatura ft","fatura","ft fes.") else
                "EN" if kw in ("invoice","tax invoice","receipt","paid receipt","payment receipt") else
                "FR" if kw in ("facture","recu fiscal") else
                "IT" if kw in ("fattura","ricevuta fiscale") else "ES",
                kw))

    # 10. Sin clasificacion clara
    return ("desconocido", "No se pudo clasificar (sin keywords factura en texto)")


# ─────────────────────────────────────────────────────────
# GMAIL
# ─────────────────────────────────────────────────────────

def obtener_label_id(gmail, label_name: str) -> str:
    labels = gmail.users().labels().list(userId="me").execute().get("labels", [])
    for l in labels:
        if l["name"] == label_name:
            return l["id"]
    # Crear si no existe
    nuevo = gmail.users().labels().create(
        userId="me",
        body={"name": label_name, "labelListVisibility": "labelShow",
              "messageListVisibility": "show"}
    ).execute()
    log(f"Label creado: {label_name} ({nuevo['id']})")
    return nuevo["id"]


def buscar_mensajes(gmail, query: str) -> list:
    mensajes = []
    req = gmail.users().messages().list(userId="me", q=query, maxResults=500)
    while req:
        res = req.execute()
        mensajes.extend(res.get("messages", []))
        req = gmail.users().messages().list_next(req, res)
    return mensajes


def obtener_metadata(gmail, msg_id: str) -> dict:
    msg = gmail.users().messages().get(
        userId="me", id=msg_id, format="metadata",
        metadataHeaders=["From", "Date", "Subject"]
    ).execute()
    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    remitente_raw = headers.get("From", "")
    m = re.search(r"<(.+?)>", remitente_raw)
    remitente = m.group(1) if m else remitente_raw.strip()
    return {
        "remitente": remitente,
        "fecha_raw": headers.get("Date", ""),
        "asunto": headers.get("Subject", ""),
        "label_ids": msg.get("labelIds", []),
    }


def descargar_adjuntos_pdf(gmail, msg_id: str, tmp_dir: str) -> list:
    """Devuelve lista de {nombre, ruta, attachment_id} para cada PDF encontrado."""
    msg = gmail.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()
    pdfs = []

    def _recorrer(partes):
        for parte in partes:
            if parte.get("parts"):
                _recorrer(parte["parts"])
                continue
            mime = parte.get("mimeType", "")
            nombre = parte.get("filename", "")
            body = parte.get("body", {})
            att_id = body.get("attachmentId")
            data = body.get("data")

            es_pdf = mime == "application/pdf" or nombre.lower().endswith(".pdf")
            if not es_pdf:
                continue

            if att_id:
                att = gmail.users().messages().attachments().get(
                    userId="me", messageId=msg_id, id=att_id
                ).execute()
                data = att["data"]

            if data:
                pdf_bytes = base64.urlsafe_b64decode(data)
                nombre_safe = re.sub(r"[^\w\-\.]", "_", nombre) if nombre else f"adjunto_{msg_id}.pdf"
                ruta = os.path.join(tmp_dir, f"{msg_id}_{nombre_safe}")
                with open(ruta, "wb") as fout:
                    fout.write(pdf_bytes)
                pdfs.append({
                    "nombre": nombre_safe,
                    "ruta": ruta,
                    "attachment_id": att_id or "",
                })

    _recorrer(msg.get("payload", {}).get("parts", [msg.get("payload", {})]))
    return pdfs


def etiquetar_mensaje(gmail, msg_id: str, label_id: str):
    gmail.users().messages().modify(
        userId="me", id=msg_id,
        body={"addLabelIds": [label_id]}
    ).execute()


# ─────────────────────────────────────────────────────────
# GOOGLE DRIVE
# ─────────────────────────────────────────────────────────

def obtener_o_crear_carpeta(drive, nombre: str, parent_id: str) -> str:
    q = (f"name='{nombre}' and mimeType='application/vnd.google-apps.folder' "
         f"and '{parent_id}' in parents and trashed=false")
    res = drive.files().list(q=q, fields="files(id,name)").execute()
    archivos = res.get("files", [])
    if archivos:
        return archivos[0]["id"]
    carpeta = drive.files().create(
        body={"name": nombre,
              "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        fields="id"
    ).execute()
    return carpeta["id"]


def subir_pdf_a_drive(drive, ruta_local: str, nombre_drive: str,
                      root_folder_id: str, trimestre: str) -> str:
    """Sube PDF a Drive en /Facturas 2026/Q2-2026/ etc. Devuelve URL."""
    # Estructura: root / "Facturas 2026" / trimestre
    folder_year = obtener_o_crear_carpeta(drive, "Facturas 2026", root_folder_id)
    folder_q = obtener_o_crear_carpeta(drive, trimestre, folder_year)

    meta = {"name": nombre_drive, "parents": [folder_q]}
    media = MediaFileUpload(ruta_local, mimetype="application/pdf", resumable=False)
    archivo = drive.files().create(body=meta, media_body=media, fields="id,webViewLink").execute()
    return archivo.get("webViewLink", f"https://drive.google.com/file/d/{archivo['id']}/view")


# ─────────────────────────────────────────────────────────
# EXTRACCIÓN PDF
# ─────────────────────────────────────────────────────────

def _extraer_num_fatura_pt(texto: str) -> str:
    """Extrae numero de fatura portuguesa: FT FES.2026/1519, FES_2026_1519, etc."""
    for pat in [
        r"Fatura\s+FT\s+FES[.\s]+?(\d{4})[/\\](\d+)",
        r"FT\s+FES[.\s]+(\d{4})[/\\](\d+)",
        r"FES[._](\d{4})[_/](\d+)",
        r"FES\.?(\d{4})/(\d+)",
    ]:
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            return "FES.{}/{}".format(m.group(1), m.group(2))
    return ""


def _extraer_total_zona_resumen(texto: str) -> float | None:
    """
    Extrae total del documento.
    1. Patron prioritario: Total ( EUR ) 105,60  (Fatura PT)
    2. Ultimas 60 lineas, excluye "A Transportar"
    3. Patrones multilingue ES/PT/EN
    4. Candidato mas alto del pie
    """
    if not texto:
        return None
    # Patron prioritario: Total ( EUR ) 105,60
    m_eur = re.search(r"Total\s*\(\s*EUR\s*\)\s*([\d\s.,]+)", texto, re.I)
    if m_eur:
        g = m_eur.group(1).strip()
        raw = g.split()[-1] if " " in g else g
        v = parse_importe(raw)
        if v and v > 0.01:
            return v
    # Zona pie: ultimas 60 lineas
    lineas = texto.strip().split("\n")
    zona = "\n".join(lineas[-60:]) if len(lineas) > 60 else texto
    # Excluir "A Transportar" (subtotal de hoja)
    zona = "\n".join(
        l for l in zona.split("\n")
        if "a transportar" not in l.lower()
    )
    patrones = [
        r"Total\s*\(\s*EUR\s*\)[:\s]*([\d\s.,]+)",
        r"Total\s+Documento[:\s]+([\d\s.,]+)",
        r"Total\s+Neto[:\s]+([\d\s.,]+)",
        r"Valor\s+a\s+pagar[:\s]+([\d\s.,]+)",
        r"Total\s+(?:com\s+)?IVA[:\s]+([\d\s.,]+)",
        r"Mercadoria[:\s]+([\d\s.,]+)",
        r"TOTAL\s+A\s+PAGAR[:\s]+([\d\s.,]+)",
        r"IMPORTE\s+TOTAL[:\s]+([\d\s.,]+)",
        r"Total\s+Factura[:\s]+([\d\s.,]+)",
        r"TOTAL\s+EUR[:\s]+([\d\s.,]+)",
        r"Amount\s+paid[:\s]*\$?\s*([\d.,]+)",
        r"Amount\s+[Dd]ue[:\s]*\$?\s*([\d.,]+)",
        r"Grand\s+Total[:\s]*\$?\s*([\d.,]+)",
        r"Total\s+Amount[:\s]*\$?\s*([\d.,]+)",
        r"(?:^|\n)\s*TOTAL[:\s]+([\d.,]+)\s*(?:EUR)?",
        r"(?:^|\n)\s*Total[:\s]+([\d.,]+)\s*(?:EUR)?",
    ]
    candidatos = []
    for pat in patrones:
        for m in re.finditer(pat, zona, re.I | re.MULTILINE):
            g = m.group(1).strip()
            raw = g.split()[-1] if " " in g else g
            v = parse_importe(raw)
            if v and v > 0.01:
                candidatos.append(v)
    if not candidatos:
        return None
    candidatos.sort(reverse=True)
    return candidatos[0]

def extraer_datos_pdf(ruta: str) -> dict:
    datos = {
        "num_factura": "", "fecha": "", "base": None,
        "iva_pct": None, "iva_eur": None, "total": None,
        "concepto": "", "notas": "",
        "_texto_raw": "",   # texto completo para clasificación externa
    }
    try:
        with pdfplumber.open(ruta) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)

        datos["_texto_raw"] = texto  # guardar ANTES de procesar

        if not texto.strip():
            datos["notas"] = "PDF sin texto extraible — puede requerir OCR"
            return datos

        t = texto.replace("\xa0", " ")

        # N Factura (multilingue: ES/PT/EN)
        # 1. Patron fatura portuguesa primero
        num_pt = _extraer_num_fatura_pt(t)
        if num_pt:
            datos["num_factura"] = num_pt
        # 2. Recibo Anthropic: Invoice number
        if not datos["num_factura"]:
            m = re.search(r"Invoice\s+number[:\s]+([A-Z0-9\-\/]+)", t, re.I)
            if m: datos["num_factura"] = m.group(1).strip()
        # 3. Receipt number
        if not datos["num_factura"]:
            m = re.search(r"Receipt\s+(?:number|no\.?|#)[:\s]+([A-Z0-9\-\/]+)", t, re.I)
            if m: datos["num_factura"] = m.group(1).strip()
        # 4. SOLS: patron especifico ddddLLddddd (ej: 2606FV05503)
        if not datos["num_factura"]:
            m = re.search(r"\b(\d{4}[A-Z]{2}\d{5})\b", t)
            if m:
                datos["num_factura"] = m.group(1)
        # 5. Patrones generales ES/EN
        if not datos["num_factura"]:
            for pat in [
                r"(?:N[uo]mero|No\.?|Factura\s+N[o]?\.?|Fra\.?\s*N[o]?)[:\s#]*([A-Z0-9\-\/]{3,30})",
                r"(?:Invoice\s+(?:No|Number|#))[:\s]*([A-Z0-9\-\/]+)",
                r"(?:Ref(?:erencia)?)[:\s]+([A-Z0-9][\w\-\/]{2,20})",
            ]:
                m = re.search(pat, t, re.IGNORECASE)
                if m:
                    datos["num_factura"] = m.group(1).strip()
                    break

        # Fecha (ES/PT/EN: Fecha, Data, Date paid, Date)
        for pat in [
            r"(?:Date\s+paid)[:\s]+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",  # Anthropic
            r"(?:Fecha|Data|Date)[:\s]+(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
            r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})",
            r"(\d{4}[\/\-]\d{2}[\/\-]\d{2})",
        ]:
            m = re.search(pat, t, re.IGNORECASE)
            if m:
                datos["fecha"] = m.group(1).strip()
                break

        # Base imponible (ES/PT: Base Imponible, Subtotal, Incidencia/Incidencia tributaria)
        for pat_base in [
            r"(?:Base\s+Imponible|Subtotal\s+sin\s+IVA|Base)[:\s]*([\d\.,]+)\s*€?",
            r"(?:Incid[e\xea]ncia|Valor\s+Tributavel|Base\s+de\s+calculo)[:\s]*([\d\.,]+)",
            r"(?:Subtotal|Sub-?total)[:\s]*([\d\.,]+)\s*€?",
        ]:
            m = re.search(pat_base, t, re.I)
            if m:
                datos["base"] = parse_importe(m.group(1))
                break

        # IVA % (ES/PT)
        m = re.search(r"IVA\s*\(?(\d+)\s*%\)?", t, re.I)
        if m:
            datos["iva_pct"] = int(m.group(1))
        # IVA 0%: exencion RITI, Isento, intracomunitario
        if datos["iva_pct"] is None:
            if re.search(r"(RITI|Isento|Exento.{0,10}IVA|intracomunit|IVA\s*0|taxa\s*0)", t, re.I):
                datos["iva_pct"] = 0
                datos["iva_eur"] = 0.0
                nota_iva = "IVA 0pct exencion/RITI"
                datos["notas"] = (datos.get("notas") or "") + (" | " if datos.get("notas") else "") + nota_iva

        # IVA €
        m = re.search(r"(?:Cuota\s+IVA|IVA\s+\d+\s*%\s*=?|Importe\s+IVA)[:\s]*([\d\.,]+)\s*€?", t, re.I)
        if m:
            v = parse_importe(m.group(1))
            if v and v > 1:
                datos["iva_eur"] = v

        # Total: 1) Anthropic "Amount paid" / "Amount due"
        m_paid = re.search(r"Amount\s+paid[:\s]*[€$]?\s*([\d.,]+)", t, re.I)
        if m_paid:
            v = parse_importe(m_paid.group(1))
            if v and v > 0.01: datos["total"] = v
        # 2) Zona de resumen multilingue (ultima ocurrencia = total real)
        if not datos["total"]:
            datos["total"] = _extraer_total_zona_resumen(t)
        # 3) Fallback patrones simples
        if not datos["total"]:
            for pat in [
                r"(?:TOTAL\s+A\s+PAGAR|IMPORTE\s+TOTAL|Total\s+Factura|TOTAL\s+EUR|TOTAL)[:\s]*([\d\.,]+)\s*€?",
                r"(?:Amount\s+Due|Grand\s+Total|Total\s+Amount)[:\s]*\$?\s*([\d\.,]+)",
                r"([\d]+[,.][\d]{2})\s*€\b",
            ]:
                for m in re.finditer(pat, t, re.I):
                    v = parse_importe(m.group(1))
                    if v and v > 0.01:
                        datos["total"] = v  # ultima
                if datos["total"]:
                    break

        # Calculos de respaldo
        if datos["total"] is None and datos["base"] is not None and datos["iva_eur"] is not None:
            datos["total"] = round(datos["base"] + datos["iva_eur"], 2)
        if datos["base"] is None and datos["total"] and datos["iva_pct"] and datos["iva_pct"] > 0:
            factor = datos["iva_pct"] / 100
            datos["base"] = round(datos["total"] / (1 + factor), 2)
            datos["iva_eur"] = round(datos["total"] - datos["base"], 2)
        # IVA 0% (RITI/exento): base == total
        if datos.get("iva_pct") == 0 and datos["total"] and datos["base"] is None:
            datos["base"] = datos["total"]
            if datos.get("iva_eur") is None:
                datos["iva_eur"] = 0.0

        # Cálculo IVA por diferencia (SOLS y similares que no muestran IVA explícito)
        # Si tenemos base e importe total pero falta IVA€ o IVA%, calculamos por diferencia
        if datos["base"] and datos["total"] and datos["total"] > datos["base"]:
            iva_calc = round(datos["total"] - datos["base"], 2)
            if datos["iva_eur"] is None and iva_calc > 0:
                datos["iva_eur"] = iva_calc
            if datos["iva_pct"] is None and datos["base"] > 0:
                ratio = iva_calc / datos["base"]
                # Redondear al tipo legal más cercano con tolerancia ±1.5%
                for pct in [21, 10, 4, 0]:
                    if abs(ratio - pct / 100) <= 0.015:
                        datos["iva_pct"] = pct
                        break
                if datos["iva_pct"] is None:
                    # No encaja con ningún tipo legal estándar
                    datos["iva_pct"] = round(ratio * 100, 1)
                    datos["notas"] = (
                        (datos.get("notas") or "") +
                        " | IVA calculado {:.1f}% — verificar tipo".format(ratio * 100)
                    ).strip(" |")

        # Concepto
        lineas = [l.strip() for l in t.split("\n") if len(l.strip()) > 10]
        if lineas:
            datos["concepto"] = lineas[0][:120]

        # Notas automaticas
        avisos = []
        if not datos["total"]:
            avisos.append("No se detecta importe total")
        if not datos["num_factura"]:
            avisos.append("No se detecta numero de factura")
        if not datos["fecha"]:
            avisos.append("No se detecta fecha")
        if avisos:
            base_nota = datos.get("notas") or ""
            sep = " | " if base_nota else ""
            datos["notas"] = (base_nota + sep + " | ".join(avisos)).strip(" |")
        # Anti-contaminacion: marcar PENDIENTE si faltan datos criticos
        # Tambien bloquear si num_factura no supera validacion
        num_ok = es_num_factura_valido(datos.get("num_factura", ""))
        if not num_ok and datos.get("num_factura"):
            # Numero extraido pero invalido: anularlo
            datos["notas"] = ((datos.get("notas") or "") +
                f" | num_invalido descartado: {datos['num_factura']!r}").strip(" |")
            datos["num_factura"] = ""
        if not datos.get("total") or datos["total"] == 0:
            datos["_pendiente_extraccion"] = True
        elif not datos.get("num_factura"):
            # num_factura vacio: PENDIENTE salvo excepcion en _ejecutar para REF_TECNICA
            datos["_pendiente_extraccion"] = True
            datos["_sin_num"] = True  # marca para que _ejecutar genere ref tecnica si aplica
        else:
            datos["_pendiente_extraccion"] = False
            datos["_sin_num"] = False

    except Exception as e:
        datos["notas"] = f"Error leyendo PDF: {e}"

    return datos


def determinar_estado(datos_pdf: dict, es_desconocido: bool) -> str:
    if datos_pdf.get("notas") and "Error" in datos_pdf["notas"]:
        return ESTADOS["ERROR"]
    if es_desconocido:
        return ESTADOS["REVISAR"]
    if not datos_pdf.get("total"):
        return ESTADOS["REVISAR"]
    if not datos_pdf.get("num_factura"):
        return ESTADOS["REVISAR"]
    return ESTADOS["REGISTRADA"]


# ─────────────────────────────────────────────────────────
# ANTI-DUPLICADOS
# ─────────────────────────────────────────────────────────

class AntiDuplicados:
    """
    Mantiene un indice en memoria de facturas ya registradas.
    Capa 1: hash SHA256 del PDF binario          (col Q)
    Capa 2: clave MD5 prov+num+fecha+total       (col R)
    Capa 3: Gmail message_id + attachment_id     (col O+P)
    Capa 4: URL / nombre en Drive                (col K)
    Capa 5: prov_norm + num_factura_norm         (cols C+E, solo si num no vacio)
    Capa 6: prov_norm + fecha_factura + total    (cols C+A+J)
    """

    def __init__(self, sheet):
        self._hashes = set()
        self._claves = set()
        self._msg_att = set()
        self._rutas = set()
        self._prov_num = set()
        self._prov_fecha_total = set()
        self._cargar(sheet)

    def _cargar(self, sheet):
        log("Cargando indice anti-duplicados del Sheet...")
        try:
            filas = sheet.get_all_values()
            for fila in filas[1:]:
                fecha    = (fila[0]  if len(fila) > 0  else "").strip()
                prov     = (fila[2]  if len(fila) > 2  else "").strip()
                num      = (fila[4]  if len(fila) > 4  else "").strip()
                total    = (fila[9]  if len(fila) > 9  else "").strip()
                ruta     = (fila[10] if len(fila) > 10 else "").strip()
                msg_id   = (fila[14] if len(fila) > 14 else "").strip()
                att_id   = (fila[15] if len(fila) > 15 else "").strip()
                pdf_hash = (fila[16] if len(fila) > 16 else "").strip()
                clave    = (fila[17] if len(fila) > 17 else "").strip()

                if ruta:      self._rutas.add(ruta)
                if msg_id and att_id: self._msg_att.add(f"{msg_id}::{att_id}")
                if pdf_hash:  self._hashes.add(pdf_hash)
                if clave:     self._claves.add(clave)
                prov_n = normalizar_texto(prov)
                num_n  = normalizar_texto(num)
                if prov_n and num_n:
                    self._prov_num.add(f"{prov_n}::{num_n}")
                fecha_n = fecha[:10]
                total_n = normalizar_texto(total)
                if prov_n and fecha_n and total_n:
                    self._prov_fecha_total.add(f"{prov_n}::{fecha_n}::{total_n}")
        except Exception as e:
            log(f"Aviso al cargar anti-duplicados: {e}", "WARN")

    def es_duplicado(self, pdf_hash: str, clave: str, msg_id: str, att_id: str,
                     ruta: str, prov: str = "", num: str = "",
                     fecha: str = "", total: str = "") -> str:
        """Devuelve motivo de duplicado o None si es nuevo."""
        if pdf_hash and pdf_hash in self._hashes:
            return f"Hash PDF ya existe: {pdf_hash[:16]}..."
        if clave and clave in self._claves:
            return f"Clave unica ya existe: {clave[:16]}..."
        if msg_id and att_id and f"{msg_id}::{att_id}" in self._msg_att:
            return "Gmail msg/attachment ya procesado"
        if ruta and ruta in self._rutas:
            return "Ruta Drive ya existe"
        prov_n = normalizar_texto(prov)
        num_n  = normalizar_texto(num)
        if prov_n and num_n and f"{prov_n}::{num_n}" in self._prov_num:
            return f"Proveedor+NumFactura ya existe: {prov}/{num}"
        fecha_n = (fecha or "")[:10]
        total_n = normalizar_texto(str(total))
        if prov_n and fecha_n and total_n and f"{prov_n}::{fecha_n}::{total_n}" in self._prov_fecha_total:
            return f"Proveedor+Fecha+Total ya existe: {prov}/{fecha}/{total}"
        return None

    def registrar(self, pdf_hash: str, clave: str, msg_id: str, att_id: str,
                  ruta: str, prov: str = "", num: str = "",
                  fecha: str = "", total: str = ""):
        if pdf_hash:  self._hashes.add(pdf_hash)
        if clave:     self._claves.add(clave)
        if msg_id and att_id: self._msg_att.add(f"{msg_id}::{att_id}")
        if ruta:      self._rutas.add(ruta)
        prov_n = normalizar_texto(prov)
        num_n  = normalizar_texto(num)
        if prov_n and num_n: self._prov_num.add(f"{prov_n}::{num_n}")
        fecha_n = (fecha or "")[:10]
        total_n = normalizar_texto(str(total))
        if prov_n and fecha_n and total_n:
            self._prov_fecha_total.add(f"{prov_n}::{fecha_n}::{total_n}")


# ─────────────────────────────────────────────────────────
# SHEET
# ─────────────────────────────────────────────────────────

def verificar_headers(sheet):
    """Lee headers reales del Sheet, detecta si faltan columnas fiscales.
    NUNCA desplaza columnas O-R (indices 14-17: MSG_ID, ATT_ID, HASH, CLAVE_UNICA).
    """
    headers = sheet.row_values(1)
    h_lower = [h.strip().lower() for h in headers]

    # Columnas fiscales y alternativas de nombre
    COLS_FISCALES = [
        ("BASE",    ["base", "base imponible", "base eur"]),
        ("IVA_PCT", ["iva%", "iva pct", "iva porcentaje", "iva_pct", "iva %"]),
        ("IVA_EUR", ["iva eur", "iva_eur", "iva euros"]),
        ("TOTAL",   ["total", "total eur", "importe total"]),
    ]
    # Columnas protegidas O-R (indices 14-17)
    COLS_PROT = [
        "Gmail Message ID", "Gmail Attachment ID", "Hash PDF", "Clave Unica Factura"
    ]

    # Verificar protegidas
    for i, h in enumerate(COLS_PROT, start=14):
        if len(headers) <= i or not headers[i]:
            log(f"WARN: Columna protegida {chr(65+i)} ('{h}') no encontrada", "WARN")

    # Detectar columnas fiscales faltantes
    faltantes = []
    for nombre, alts in COLS_FISCALES:
        if not any(a in h_lower for a in alts):
            faltantes.append(nombre)
    if faltantes:
        log(f"Columnas fiscales no detectadas en Sheet: {faltantes}", "WARN")
        log("Verifica que la fila 1 del Sheet contenga: BASE, IVA_PCT, IVA_EUR, TOTAL", "WARN")


def escribir_fila(sheet, datos_email: dict, datos_pdf: dict, extras: dict):
    fecha = datos_pdf.get("fecha") or datos_email.get("fecha_email", "")
    # Calcular trimestre
    trimestre = ""
    try:
        dt = dateparser.parse(fecha, dayfirst=True)
        if dt:
            trimestre = calcular_trimestre(dt)
    except Exception:
        pass

    fila = [
        fecha,                                              # A
        trimestre,                                          # B
        datos_email.get("proveedor_nombre", ""),           # C
        datos_email.get("remitente", ""),                  # D
        datos_pdf.get("num_factura", ""),                  # E
        (datos_pdf.get("concepto") or "")[:120],           # F
        datos_pdf.get("base", ""),                         # G
        datos_pdf.get("iva_pct", ""),                      # H
        datos_pdf.get("iva_eur", ""),                      # I
        datos_pdf.get("total", ""),                        # J
        extras.get("url_drive", extras.get("nombre_pdf", "")),  # K
        extras.get("estado", ESTADOS["REGISTRADA"]),       # L
        datos_pdf.get("notas", ""),                        # M
        datetime.now().strftime("%Y-%m-%d %H:%M"),         # N
        extras.get("msg_id", ""),                          # O
        extras.get("att_id", ""),                          # P
        extras.get("hash_pdf", ""),                        # Q
        extras.get("clave_unica", ""),                     # R
    ]
    sheet.append_row(fila, value_input_option="USER_ENTERED")
    return trimestre


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    # Banner de inicio — siempre visible, antes de cualquier error (L-010)
    print("\n" + "=" * 60, flush=True)
    print("  BORDAGRAN FISCAL — Iniciando procesamiento de facturas", flush=True)
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"), flush=True)
    print("=" * 60, flush=True)

    parser = argparse.ArgumentParser(
        description="Bordagran Fiscal: procesa facturas de Gmail → Drive → Sheets",
    )
    parser.add_argument("--modo", choices=["incremental", "backfill"], default="incremental",
                        help="incremental (últimos N días) o backfill (rango de fechas)")
    parser.add_argument("--desde", default=None, metavar="YYYY-MM-DD",
                        help="Fecha inicio (solo backfill)")
    parser.add_argument("--hasta", default=None, metavar="YYYY-MM-DD",
                        help="Fecha fin (solo backfill)")
    parser.add_argument("--dias", type=int, default=7,
                        help="Días hacia atrás en modo incremental (default: 7)")
    parser.add_argument("--skill-dir", default=None, metavar="RUTA",
                        help="Ruta al directorio del skill")
    parser.add_argument("--forzar", action="store_true",
                        help="Ignorar lock file de ejecuciones previas bloqueadas")
    parser.add_argument("--dry-run", action="store_true",
                        help="Simular sin escribir en Sheet/Drive/Gmail (modo seguro)")
    args = parser.parse_args()

    print(f"  Modo     : {args.modo}", flush=True)
    if args.dry_run:
        print("  DRY-RUN  : SI — no se escribira nada (Sheet/Drive/Gmail intactos)", flush=True)
    if args.modo == "backfill":
        print(f"  Desde    : {args.desde}", flush=True)
        print(f"  Hasta    : {args.hasta}", flush=True)
    else:
        print(f"  Dias     : {args.dias}", flush=True)
    print("", flush=True)

    # Localizar skill-dir
    if args.skill_dir:
        skill_dir = Path(args.skill_dir)
    else:
        skill_dir = encontrar_skill_dir()
        if not skill_dir:
            print("❌ No se encontró la carpeta del skill.", flush=True)
            print("   Usa --skill-dir /ruta/al/gmail-facturas-bordagran", flush=True)
            sys.exit(1)

    print(f"  Skill dir: {skill_dir}", flush=True)

    # Lock
    lock = Lock(skill_dir)
    if args.forzar:
        lock.liberar()
        print("  [INFO] Lock forzado: archivo de bloqueo eliminado.", flush=True)

    if not lock.adquirir():
        print("\n❌ BLOQUEADO: Ya hay una ejecución en curso (lock activo < 60 min).", flush=True)
        print(f"   Lock file: {lock.path}", flush=True)
        print("   Si el proceso anterior falló, usa --forzar para continuar:", flush=True)
        print("   python scripts/procesar_facturas.py --modo incremental --forzar --skill-dir .", flush=True)
        sys.exit(1)

    try:
        _ejecutar(args, skill_dir, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\n⚠️  Interrumpido por usuario (Ctrl+C)", flush=True)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ ERROR CRÍTICO: {e}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        lock.liberar()


# ────────────────────────────────────────────────────────────
# EXTRACCION CUERPO EMAIL (para emails sin PDF adjunto)
# ────────────────────────────────────────────────────────────

def extraer_texto_email(gmail, msg_id: str) -> str:
    """
    Extrae el texto plano del cuerpo del email.
    Util cuando no hay PDF adjunto pero el email puede contener
    datos fiscales en el cuerpo (ej: SOLS Aviso Giro Bancario).
    """
    try:
        msg = gmail.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
        partes = msg.get("payload", {}).get("parts", [msg.get("payload", {})])

        def _extraer_texto(partes_list):
            textos = []
            for parte in partes_list:
                mime = parte.get("mimeType", "")
                sub = parte.get("parts")
                if sub:
                    textos.extend(_extraer_texto(sub))
                    continue
                if mime in ("text/plain", "text/html"):
                    data = parte.get("body", {}).get("data", "")
                    if data:
                        import base64
                        try:
                            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                            if mime == "text/html":
                                decoded = re.sub(r"<[^>]+>", " ", decoded)
                            textos.append(decoded)
                        except Exception:
                            pass
            return textos

        partes_texto = _extraer_texto(partes)
        return "\n".join(partes_texto)[:8000]  # limitar longitud
    except Exception as e:
        log(f"  No se pudo extraer cuerpo del email: {e}", "WARN")
        return ""


def tiene_datos_fiscales(texto: str) -> bool:
    """Heuristica multilingue: importe + referencia fiscal (ES/PT/EN + REM26/CL)."""
    if not texto: return False
    t = texto.lower()
    tiene_importe = bool(re.search(r"\b\d+[,.]\d{2}\s*(?:€|eur)?\b", t))
    tiene_referencia = bool(re.search(
        r"(factura|fatura|invoice|receipt|fra|n[ou]mero|referencia|ref\.?\s*\d|"
        r"num\.?\s*\d|cl0\d{4}|rem2[0-9]|cobro|domiciliacion|vencimiento|"
        r"recibo|abono|cargo|paid|amount|subtotal|total\s+a|importe)", t, re.I))
    return tiene_importe and tiene_referencia

def es_num_factura_valido(num: str) -> bool:
    """
    True si es numero de factura fiscalmente valido.
    Rechaza: <4 chars, sin digito, palabras comunes, logistica.
    """
    if not num:
        return False
    s = num.strip()
    if len(s) < 3:
        return False
    if not any(ch.isdigit() for ch in s):
        return False
    # Fast-pass: referencias tecnicas del sistema (CANVA_YYYY-MM-DD_TT.tt_msgid)
    if re.match(r"^[A-Z]{2,10}_\d{4}-\d{2}-\d{2}_[\d.]+_[0-9a-f]{6,}$", s):
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
    util = [ch for ch in s if ch.isalnum()]
    if len(util) < 3:
        return False
    # Referencias tecnicas autogeneradas no son numeros fiscales reales
    sl_lower = s.lower()
    if sl_lower.startswith("tecn_") or sl_lower.startswith("temp-"):
        return False
    return True


def extraer_datos_de_texto(texto: str) -> dict:
    """Extrae datos fiscales desde texto plano del cuerpo de un email."""
    datos = {
        "num_factura": "", "fecha": "", "base": None,
        "iva_pct": None, "iva_eur": None, "total": None,
        "concepto": "", "notas": "",
    }
    if not texto:
        return datos
    t = texto.replace("\xa0", " ")
    # Palabras comunes que NO son numero de factura
    _PALABRAS_EXCLUIR_NUM = {
        "continuacion", "tinuaci", "siguiente", "anterior", "adjunto",
        "attachment", "document", "payment", "account", "invoice",
        "receipt", "thank", "regards", "please", "click", "here",
        "pro", "teams", "plan", "monthly", "annual", "subscription",
    }
    for pat in [
        r"(?:Invoice\s+(?:No|Number|#))[:\s]*([A-Z0-9\-\/]+)",
        r"(?:Receipt\s+(?:No|Number|#))[:\s]*([A-Z0-9\-\/]+)",
        r"(?:N[uo]mero|N[o]?\.?|Factura\s+N[o]?\.?|Fra\.?\s*N[o]?)[:\s#]*([A-Z0-9\-\/]{3,30})",
        r"(?:Ref(?:erencia)?)[:\s]+([A-Z0-9][\w\-\/]{3,20})",
        r"Order\s+(?:ID|#|No)[:\s]*([A-Z0-9\-\/]+)",
    ]:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            candidato = m.group(1).strip()
            # Filtrar palabras comunes que no son referencia fiscal
            if (candidato.lower() not in _PALABRAS_EXCLUIR_NUM
                    and es_num_factura_valido(candidato)):
                datos["num_factura"] = candidato
                break
    for pat in [
        r"(?:Fecha[:\s]+)(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4})",
    ]:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            datos["fecha"] = m.group(1).strip()
            break
    m = re.search(r"(?:Base|Subtotal)[:\s]*([\d\.,]+)\s*€?", t, re.I)
    if m: datos["base"] = parse_importe(m.group(1))
    m = re.search(r"IVA\s*\(?([0-9]+)\s*%\)?", t, re.I)
    if m: datos["iva_pct"] = int(m.group(1))
    for pat in [
        r"(?:TOTAL|Importe\s+total|Amount\s+due)[:\s]*([\d\.,]+)\s*€?",
        r"([\d]+[,\.][\d]{2})\s*€",
    ]:
        m = re.search(pat, t, re.I)
        if m:
            v = parse_importe(m.group(1))
            if v and v > 0.01:
                datos["total"] = v
                break
    if datos["base"] and datos["total"] and datos["total"] > datos["base"]:
        if datos["iva_eur"] is None:
            datos["iva_eur"] = round(datos["total"] - datos["base"], 2)
    lineas = [l.strip() for l in t.split("\n") if len(l.strip()) > 10]
    if lineas: datos["concepto"] = lineas[0][:120]
    return datos

def _diag_sols(cuerpo: str, proveedor: str, msg_id: str, skill_dir) -> None:
    """Diagnostico detallado del cuerpo email de aviso bancario."""
    kw_buscar = [
        "factura", "n factura", "num", "total", "base", "iva",
        "importe", "cl09268", "rem26", "rem25", "sols", "cobro",
        "euros", "euro", "€", "fecha", "vencimiento", "domiciliacion",
    ]
    encontradas = [kw for kw in kw_buscar if kw in cuerpo.lower()]
    tiene_fis = tiene_datos_fiscales(cuerpo)
    tipo_cls, motivo_cls = clasificar_tipo_documento(cuerpo, "", [])
    lineas = [l.strip() for l in cuerpo.split("\n") if l.strip()]

    log(f"  [DIAG SOLS] Proveedor: {proveedor} | msg:{msg_id[:10]}")
    log(f"  [DIAG SOLS] Longitud cuerpo: {len(cuerpo)} chars | Lineas: {len(lineas)}")
    log(f"  [DIAG SOLS] tiene_datos_fiscales: {tiene_fis}")
    log(f"  [DIAG SOLS] clasificar_tipo_documento: {tipo_cls} | {motivo_cls}")
    log(f"  [DIAG SOLS] Keywords encontradas: {encontradas}")
    log(f"  [DIAG SOLS] Primeras 8 lineas del cuerpo:")
    for ln in lineas[:8]:
        log(f"    | {ln[:120]}")

    # Guardar diagnostico sanitizado en runtime/
    try:
        import pathlib
        rt = pathlib.Path(skill_dir) / "runtime"
        rt.mkdir(exist_ok=True)
        diag_path = rt / f"diagnostico_sols_{msg_id[:8]}.txt"
        with open(diag_path, "w", encoding="utf-8") as fh:
            fh.write(f"=== DIAGNOSTICO SOLS aviso bancario ===\n")
            fh.write(f"Proveedor : {proveedor}\n")
            fh.write(f"msg_id    : {msg_id}\n")
            fh.write(f"Longitud  : {len(cuerpo)} chars\n")
            fh.write(f"Fiscales  : {tiene_fis}\n")
            fh.write(f"Tipo cls  : {tipo_cls} | {motivo_cls}\n")
            fh.write(f"Keywords  : {encontradas}\n")
            fh.write("\n--- Cuerpo (primeras 80 lineas) ---\n")
            for ln in lineas[:80]:
                fh.write(ln[:160] + "\n")
        log(f"  [DIAG SOLS] Guardado: {diag_path.name}")
    except Exception as ex:
        log(f"  [DIAG SOLS] Error guardando diagnostico: {ex}", "WARN")

def _fecha_iso_de_raw(fecha_raw: str, fallback: str = "") -> str:
    """Convierte fecha RFC email (Fri, 19 Jun 2026 12:34:56 +0000) a YYYY-MM-DD.
    Si falla devuelve fallback o fecha de hoy.
    """
    if not fecha_raw:
        return fallback or datetime.now().strftime("%Y-%m-%d")
    # Intentar dateparser primero
    try:
        import dateparser as _dp
        dt = _dp.parse(fecha_raw, settings={"RETURN_AS_TIMEZONE_AWARE": False})
        if dt:
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    # Fallback: regex YYYY-MM-DD o DD/MM/YYYY dentro del string
    m = re.search(r"(\d{4}-\d{2}-\d{2})", fecha_raw)
    if m:
        return m.group(1)
    m2 = re.search(r"(\d{1,2})[/ ](\w{3})[/ ](\d{4})", fecha_raw)
    if m2:
        meses = {"jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
                 "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12"}
        mes = meses.get(m2.group(2).lower()[:3], "01")
        return f"{m2.group(3)}-{mes}-{int(m2.group(1)):02d}"
    return fallback or datetime.now().strftime("%Y-%m-%d")


def _diag_thclothes(texto_pdf: str, proveedor: str, msg_id: str, nombre_pdf: str, skill_dir) -> None:
    """Diagnostico detallado cuando THClothes/Fatura PT no extrae total."""
    import pathlib
    kw = ["total", "eur", "iva", "base", "fatura", "fes", "transportar", "mercadoria",
           "documento", "importe", "valor", "subtotal", "riti", "isento"]
    lineas = texto_pdf.split("\n") if texto_pdf else []
    ultimas = lineas[-100:] if len(lineas) > 100 else lineas
    kw_lines = [l for l in ultimas if any(k in l.lower() for k in kw)]
    log(f"  [DIAG THCLOTHES] {nombre_pdf}: {len(lineas)} lineas, {len(kw_lines)} con keywords")
    try:
        rt = pathlib.Path(skill_dir) / "runtime"
        rt.mkdir(exist_ok=True)
        diag = rt / f"diagnostico_thclothes_{msg_id[:8]}.txt"
        with open(diag, "w", encoding="utf-8") as fh:
            fh.write(f"=== DIAGNOSTICO THCLOTHES total=None ===\n")
            fh.write(f"Proveedor : {proveedor}\n")
            fh.write(f"PDF       : {nombre_pdf}\n")
            fh.write(f"msg_id    : {msg_id}\n")
            fh.write(f"Lineas    : {len(lineas)}\n")
            fh.write("\n--- Ultimas 100 lineas del PDF ---\n")
            for l in ultimas:
                fh.write(l[:200] + "\n")
            fh.write("\n--- Lineas con keywords fiscales ---\n")
            for l in kw_lines:
                fh.write(l[:200] + "\n")
        log(f"  [DIAG THCLOTHES] Guardado: {diag.name}")
    except Exception as ex:
        log(f"  [DIAG THCLOTHES] Error guardando: {ex}", "WARN")


def _ejecutar(args, skill_dir: Path, dry_run: bool = False):
    # Cargar config
    with open(skill_dir / "config.json") as f:
        config = json.load(f)

    # Auth
    log("Autenticando...")
    creds = autenticar(skill_dir)
    gmail = build("gmail", "v1", credentials=creds)
    drive = build("drive", "v3", credentials=creds)
    gc = gspread.authorize(creds)

    # Sheet
    try:
        ss = gc.open_by_key(config["SHEET_FACTURAS_ID"])
        sheet = ss.worksheet(config["SHEET_FACTURAS_NAME"])
        log(f"Sheet abierto: '{config['SHEET_FACTURAS_NAME']}'")
    except Exception as e:
        log(f"❌ No se puede abrir Sheet: {e}", "ERROR")
        log(f"   ID: {config['SHEET_FACTURAS_ID']}", "ERROR")
        sys.exit(1)

    verificar_headers(sheet)

    # Label IDs
    label_procesadas_id = obtener_label_id(gmail, config["LABEL_PROCESADAS"])
    label_pendiente_id = obtener_label_id(gmail, config["LABEL_PENDIENTE"])

    # Anti-duplicados
    anti_dup = AntiDuplicados(sheet)

    # Proveedores y exclusiones
    proveedores = cargar_proveedores(skill_dir)
    log(f"{len(proveedores)} proveedores cargados")
    exclusiones = cargar_exclusiones(skill_dir)
    log(f"{len(exclusiones)} exclusiones cargadas")

    # Construir query Gmail con rango de fechas
    if args.desde and args.hasta:
        # Rango explicito: funciona en incremental y backfill
        desde_dt = datetime.strptime(args.desde, "%Y-%m-%d")
        hasta_dt = datetime.strptime(args.hasta, "%Y-%m-%d")
        # Gmail "before:" es EXCLUSIVO -> sumar 1 dia
        hasta_excl = hasta_dt + timedelta(days=1)
        rango = (f"after:{desde_dt.strftime('%Y/%m/%d')} "
                 f"before:{hasta_excl.strftime('%Y/%m/%d')}")
        log(f"Rango: {args.desde} -> {args.hasta} (Gmail before: {hasta_excl.strftime('%Y/%m/%d')})")
    elif args.modo == "backfill":
        log("❌ Modo backfill requiere --desde YYYY-MM-DD y --hasta YYYY-MM-DD", "ERROR")
        sys.exit(1)
    else:
        hace_n = datetime.now() - timedelta(days=args.dias)
        rango = f"after:{hace_n.strftime('%Y/%m/%d')}"
        log(f"Incremental: ultimos {args.dias} dias")

    # Query principal: PDFs de todos los proveedores
    queries = [
        f"has:attachment filename:pdf {rango}",
    ]
    # Queries complementarias para proveedores digitales sin PDF adjunto
    queries += [
        f"from:(invoice+statements@mail.anthropic.com OR billing@anthropic.com) {rango}",
        f"from:(canva.com OR no-reply@canva.com OR team@canva.com) {rango} (invoice OR receipt OR factura OR paid)",
        f"from:(thclothes.com OR marta.nazario@thclothes.com) {rango} (fatura OR invoice OR FES OR FT)",
        f"from:(clientes@sols.es OR no-reply@sols.es OR sols.es) {rango} (factura OR albaran OR REM26 OR aviso)",
    ]
    # Unificar resultados por msg_id para no procesar dos veces el mismo correo
    seen_ids: set = set()
    mensajes = []
    for q in queries:
        log(f"Query Gmail: {q}")
        for msg in buscar_mensajes(gmail, q):
            if msg["id"] not in seen_ids:
                seen_ids.add(msg["id"])
                mensajes.append(msg)
    log(f"{len(mensajes)} mensajes unicos encontrados ({len(queries)} queries)")

    # Resultados
    r = {"procesados": [], "duplicados": [], "sin_pdf": [], "errores": [],
         "no_fiscales": [], "pendientes": [], "factura_en_cuerpo": [],
         "total_eur": 0.0, "iva_total": 0.0, "base_total": 0.0}

    with tempfile.TemporaryDirectory() as tmp_dir:
        for i, msg_info in enumerate(mensajes):
            msg_id = msg_info["id"]
            time.sleep(0.25)

            try:
                meta = obtener_metadata(gmail, msg_id)
                remitente = meta["remitente"]
                prov = identificar_proveedor(remitente, proveedores)
                es_desconocido = prov.get("_desconocido", False)

                log(f"[{i+1}/{len(mensajes)}] {prov['nombre']} <{remitente}>")

                pdfs = descargar_adjuntos_pdf(gmail, msg_id, tmp_dir)
                if not pdfs:
                    # Sin PDF: intentar parsear cuerpo (ej: SOLS Aviso Giro)
                    cuerpo = extraer_texto_email(gmail, msg_id)
                    if cuerpo and tiene_datos_fiscales(cuerpo):
                        tipo_c, motivo_c = clasificar_tipo_documento(
                            cuerpo, remitente, exclusiones
                        )
                        if tipo_c in TIPOS_FISCALES:
                            log(f"  Factura en cuerpo email [{tipo_c}]")
                            datos_c = extraer_datos_de_texto(cuerpo)
                            # Fallback num_factura si no se extrajo referencia clara
                            # Validar num_factura: si invalido, solo generar ref tecnica para REF_TECNICA providers
                            prov_norm_cuerpo = prov["nombre"].lower().replace(" ","")
                            es_rt_cuerpo = any(rt in prov_norm_cuerpo for rt in PROVEEDORES_REF_TECNICA)
                            if not es_num_factura_valido(datos_c.get("num_factura","")):
                                if es_rt_cuerpo:
                                    # Referencia tecnica limpia para proveedor digital
                                    fecha_iso_c = (_fecha_iso_de_raw(meta.get("fecha_raw",""))
                                                   or datos_c.get("fecha")
                                                   or datetime.now().strftime("%Y-%m-%d"))
                                    total_c = datos_c.get("total") or 0
                                    prov_code_c = re.sub(r"[^A-Z0-9]","", prov["nombre"].upper())[:8]
                                    datos_c["num_factura"] = f"{prov_code_c}_{fecha_iso_c}_{total_c:.2f}_{msg_id[:8]}"
                                    datos_c["notas"] = ((datos_c.get("notas") or "") +
                                        " | Ref.tecnica autogenerada (proveedor digital sin num fiscal)").strip(" |")
                                else:
                                    # Proveedor normal sin num -> marcar pendiente, no insertar
                                    log(f"  [PENDIENTE cuerpo] {prov['nombre']}: num invalido/vacio, sin ref tecnica permitida")
                                    r["pendientes"].append({"nombre": f"BODY:{msg_id[:8]}",
                                        "proveedor": prov["nombre"],
                                        "tipo": ESTADO_PENDIENTE_EXTRACCION,
                                        "motivo": "num_factura invalido/vacio en cuerpo email"})
                                    if not dry_run:
                                        etiquetar_mensaje(gmail, msg_id, label_pendiente_id)
                                    continue
                            r["factura_en_cuerpo"].append({
                                "proveedor": prov["nombre"],
                                "datos": datos_c, "dry_run": dry_run,
                            })
                            if not dry_run:
                                c_u = clave_unica(prov["nombre"],
                                    datos_c.get("num_factura",""),
                                    datos_c.get("fecha",""),
                                    datos_c.get("total") or 0.0)
                                dup_c = anti_dup.es_duplicado(
                                    "", c_u, msg_id, "BODY", "",
                                    prov=prov["nombre"],
                                    num=datos_c.get("num_factura",""),
                                    fecha=datos_c.get("fecha",""),
                                    total=str(datos_c.get("total") or ""))
                                if dup_c:
                                    log(f"  -> Dup cuerpo: {dup_c}")
                                    r["duplicados"].append({"nombre": f"BODY:{msg_id[:8]}", "motivo": dup_c})
                                else:
                                    estado_c = "Registrada" if datos_c.get("total") else "Revisar"
                                    datos_c["notas"] = (datos_c.get("notas") or "Factura en cuerpo email, sin PDF adjunto")
                                    de = {"proveedor_nombre": prov["nombre"], "remitente": remitente, "fecha_email": meta["fecha_raw"]}
                                    ex = {"url_drive": "Factura en cuerpo email", "nombre_pdf": f"EMAIL:{msg_id[:8]}", "estado": estado_c, "msg_id": msg_id, "att_id": "BODY", "hash_pdf": "", "clave_unica": c_u}
                                    escribir_fila(sheet, de, datos_c, ex)
                                    anti_dup.registrar("", c_u, msg_id, "BODY", "",
                                        prov=prov["nombre"],
                                        num=datos_c.get("num_factura",""),
                                        fecha=datos_c.get("fecha",""),
                                        total=str(datos_c.get("total") or ""))
                                    etiquetar_mensaje(gmail, msg_id, label_procesadas_id)
                                    log(f"  Registrada factura cuerpo: {estado_c}")
                        else:
                            log(f"  Cuerpo con datos pero tipo [{tipo_c}]: {motivo_c}")
                            r["no_fiscales"].append({"nombre": f"EMAIL:{msg_id[:8]}", "proveedor": prov["nombre"], "tipo": tipo_c, "motivo": motivo_c})
                    else:
                        r["sin_pdf"].append(remitente)
                        log(f"  -> Sin PDF ni datos fiscales en cuerpo")
                    continue

                algun_pdf_nuevo = False

                for pdf_info in pdfs:
                    nombre_pdf = pdf_info["nombre"]
                    ruta_local = pdf_info["ruta"]
                    att_id = pdf_info["attachment_id"]

                    # Hash
                    pdf_hash = hash_pdf(ruta_local)

                    # Extraer datos PDF
                    datos_pdf = extraer_datos_pdf(ruta_local)
                    texto_raw = datos_pdf.pop("_texto_raw", "")

                    # ── CLASIFICACIÓN FISCAL (gating) ────────────────────
                    tipo_doc, motivo_tipo = clasificar_tipo_documento(
                        texto_raw, remitente, exclusiones
                    )
                    if tipo_doc not in TIPOS_FISCALES:
                        log(f"  [!] No fiscal [{tipo_doc}]: {motivo_tipo} | {nombre_pdf}")
                        # Caso especial: aviso bancario -> intentar leer cuerpo del email
                        # El PDF es aviso bancario pero el CUERPO puede tener la factura real
                        if tipo_doc == "aviso_bancario":
                            log(f"  -> Aviso bancario: revisando cuerpo del email...")
                            cuerpo_av = extraer_texto_email(gmail, msg_id)
                            # Diagnostico detallado en dry-run
                            if dry_run and cuerpo_av:
                                _diag_sols(cuerpo_av, prov["nombre"], msg_id, skill_dir)
                            elif dry_run and not cuerpo_av:
                                log(f"  [DIAG] Cuerpo del email VACIO o no extraible")
                            if cuerpo_av and tiene_datos_fiscales(cuerpo_av):
                                tipo_c2, motivo_c2 = clasificar_tipo_documento(
                                    cuerpo_av, remitente, exclusiones)
                                if tipo_c2 in TIPOS_FISCALES:
                                    log(f"  -> Factura encontrada en cuerpo de aviso bancario [{tipo_c2}]")
                                    datos_c2 = extraer_datos_de_texto(cuerpo_av)
                                    r["factura_en_cuerpo"].append({"proveedor": prov["nombre"], "datos": datos_c2, "dry_run": dry_run})
                                    if not dry_run:
                                        c_u2 = clave_unica(prov["nombre"], datos_c2.get("num_factura",""), datos_c2.get("fecha",""), datos_c2.get("total") or 0.0)
                                        dup2 = anti_dup.es_duplicado("", c_u2, msg_id, "BODY_AV", "", prov=prov["nombre"], num=datos_c2.get("num_factura",""), fecha=datos_c2.get("fecha",""), total=str(datos_c2.get("total") or ""))
                                        if not dup2 and datos_c2.get("total") and datos_c2.get("_pendiente_extraccion") is False:
                                            datos_c2["notas"] = "Factura en cuerpo de aviso bancario"
                                            de2 = {"proveedor_nombre": prov["nombre"], "remitente": remitente, "fecha_email": meta["fecha_raw"]}
                                            ex2 = {"url_drive": "Cuerpo aviso bancario", "nombre_pdf": f"AVBODY:{msg_id[:8]}", "estado": "Registrada", "msg_id": msg_id, "att_id": "BODY_AV", "hash_pdf": "", "clave_unica": c_u2}
                                            escribir_fila(sheet, de2, datos_c2, ex2)
                                            anti_dup.registrar("", c_u2, msg_id, "BODY_AV", "", prov=prov["nombre"], num=datos_c2.get("num_factura",""), fecha=datos_c2.get("fecha",""), total=str(datos_c2.get("total") or ""))
                                            etiquetar_mensaje(gmail, msg_id, label_procesadas_id)
                                        elif dup2:
                                            log(f"  -> Dup cuerpo aviso: {dup2}")
                        r["no_fiscales"].append({"nombre": nombre_pdf, "proveedor": prov["nombre"], "tipo": tipo_doc, "motivo": motivo_tipo})
                        if not dry_run:
                            etiquetar_mensaje(gmail, msg_id, label_pendiente_id)
                        continue
                    log(f"  Tipo fiscal: {tipo_doc}")
                    # -----------------------------------------------

                    # Clave única
                    c_unica = clave_unica(
                        prov["nombre"],
                        datos_pdf.get("num_factura", ""),
                        datos_pdf.get("fecha", ""),
                        datos_pdf.get("total") or 0.0
                    )

                    # Calcular trimestre para nombre Drive
                    trimestre_str = ""
                    if datos_pdf.get("fecha"):
                        try:
                            dt = dateparser.parse(datos_pdf["fecha"], dayfirst=True)
                            if dt:
                                trimestre_str = calcular_trimestre(dt)
                        except Exception:
                            pass
                    if not trimestre_str:
                        trimestre_str = calcular_trimestre(datetime.now())

                    # Nombre normalizado para Drive
                    fecha_norm = datetime.now().strftime("%Y-%m-%d")
                    if datos_pdf.get("fecha"):
                        try:
                            dt = dateparser.parse(datos_pdf["fecha"], dayfirst=True)
                            if dt:
                                fecha_norm = dt.strftime("%Y-%m-%d")
                        except Exception:
                            pass

                    prov_norm = re.sub(r"[^\w]", "_", prov["nombre"])[:20]
                    num_norm = re.sub(r"[^\w]", "_", datos_pdf.get("num_factura", ""))[:15]
                    total_norm = f"{datos_pdf.get('total', 0):.0f}EUR" if datos_pdf.get("total") else "REV"
                    if num_norm:
                        nombre_drive = f"{fecha_norm}_{prov_norm}_{num_norm}_{total_norm}.pdf"
                    else:
                        nombre_drive = f"{fecha_norm}_{prov_norm}_REVISION_{msg_id[:8]}.pdf"

                    # Anti-duplicado (6 capas)
                    motivo_dup = anti_dup.es_duplicado(
                        pdf_hash, c_unica, msg_id, att_id, nombre_drive,
                        prov=prov["nombre"],
                        num=datos_pdf.get("num_factura",""),
                        fecha=datos_pdf.get("fecha",""),
                        total=str(datos_pdf.get("total") or ""))
                    if motivo_dup:
                        log(f"  → Duplicado: {motivo_dup}")
                        r["duplicados"].append({"nombre": nombre_pdf, "motivo": motivo_dup})
                        continue

                    # Subir a Drive (solo si no es dry-run)
                    if dry_run:
                        url_drive = f"[DRY-RUN] {nombre_drive}"
                        log(f"  [DRY-RUN] Habria subido: {nombre_drive}")
                    else:
                        try:
                            url_drive = subir_pdf_a_drive(
                                drive, ruta_local, nombre_drive,
                                config["DRIVE_ROOT_FOLDER_ID"], trimestre_str
                            )
                            log(f"  -> Drive: {nombre_drive}")
                        except Exception as e:
                            url_drive = nombre_drive
                            log(f"  -> Drive error: {e}", "WARN")
                            datos_pdf["notas"] = (datos_pdf.get("notas", "") +
                                                  f" | Error Drive: {str(e)[:50]}").strip(" |")

                    # Anti-contaminacion: bloquear insercion si datos criticos faltan
                    # Excepcion: proveedores digitales en PROVEEDORES_REF_TECNICA
                    # pueden insertar con referencia tecnica limpia cuando falta num_factura
                    prov_norm_l = prov["nombre"].lower().replace(" ", "")
                    es_ref_tecnica_ok = any(
                        rt in prov_norm_l for rt in PROVEEDORES_REF_TECNICA
                    )
                    if datos_pdf.get("_pendiente_extraccion"):
                        sin_num = datos_pdf.get("_sin_num", False)
                        tiene_total = bool(datos_pdf.get("total") and datos_pdf["total"] > 0)
                        # Excepcion REF_TECNICA: solo si sin_num (tiene total/fecha) y prov digital
                        if sin_num and tiene_total and es_ref_tecnica_ok:
                            # Generar referencia tecnica limpia
                            fecha_iso = (_fecha_iso_de_raw(meta.get("fecha_raw",""))
                                         or datetime.now().strftime("%Y-%m-%d"))
                            total_str = f"{datos_pdf['total']:.2f}"
                            prov_code = re.sub(r"[^A-Z0-9]", "", prov["nombre"].upper())[:8]
                            datos_pdf["num_factura"] = f"{prov_code}_{fecha_iso}_{total_str}_{msg_id[:8]}"
                            datos_pdf["notas"] = ((datos_pdf.get("notas") or "") +
                                " | Ref.tecnica autogenerada (proveedor digital sin num fiscal)").strip(" |")
                            datos_pdf["_pendiente_extraccion"] = False
                            datos_pdf.pop("_sin_num", None)
                            log(f"  [REF_TECNICA] {prov['nombre']}: {datos_pdf['num_factura']}")
                        else:
                            log(f"  [PENDIENTE] {ESTADO_PENDIENTE_EXTRACCION}: total={datos_pdf.get('total')} num={datos_pdf.get('num_factura')}")
                            # Diagnostico especifico para THClothes/Fatura PT sin total
                            nombre_prov_l = prov["nombre"].lower()
                            if (any(kp in nombre_prov_l for kp in ["thclothes", "biscana", "fes", "fatura"])
                                    or any(kp in texto_raw.lower() for kp in ["fatura ft", "fes.20"])):
                                _diag_thclothes(texto_raw, prov["nombre"], msg_id, nombre_pdf, skill_dir)
                            r["pendientes"].append({"nombre": nombre_pdf, "proveedor": prov["nombre"],
                                "tipo": ESTADO_PENDIENTE_EXTRACCION,
                                "motivo": datos_pdf.get("notas","Datos insuficientes")})
                            if not dry_run:
                                etiquetar_mensaje(gmail, msg_id, label_pendiente_id)
                            continue  # NO insertar en Sheet
                    datos_pdf.pop("_pendiente_extraccion", None)

                    # Determinar estado
                    estado = determinar_estado(datos_pdf, es_desconocido)
                    if es_desconocido:
                        datos_pdf["notas"] = (datos_pdf.get("notas", "") +
                                              " | Proveedor no reconocido").strip(" |")
                        etiquetar_mensaje(gmail, msg_id, label_pendiente_id)
                    # Añadir tipo_documento a notas para trazabilidad
                    datos_pdf["notas"] = (
                        (datos_pdf.get("notas") or "") +
                        " | tipo:{}".format(tipo_doc)
                    ).strip(" |")

                    # Escribir en Sheet
                    datos_email = {
                        "proveedor_nombre": prov["nombre"],
                        "remitente": remitente,
                        "fecha_email": meta["fecha_raw"],
                    }
                    extras = {
                        "url_drive": url_drive,
                        "nombre_pdf": nombre_drive,
                        "estado": estado,
                        "msg_id": msg_id,
                        "att_id": att_id,
                        "hash_pdf": pdf_hash,
                        "clave_unica": c_unica,
                    }
                    if not dry_run:
                        escribir_fila(sheet, datos_email, datos_pdf, extras)
                    else:
                        log(f"  [DRY-RUN] Habria insertado: {prov['nombre']} | {datos_pdf.get('num_factura','?')} | {datos_pdf.get('total','?')}EUR")

                    # Actualizar indice anti-dup (siempre, tambien en dry-run)
                    anti_dup.registrar(
                        pdf_hash, c_unica, msg_id, att_id, url_drive,
                        prov=prov["nombre"],
                        num=datos_pdf.get("num_factura",""),
                        fecha=datos_pdf.get("fecha",""),
                        total=str(datos_pdf.get("total") or ""))
                    algun_pdf_nuevo = True

                    total = datos_pdf.get("total") or 0.0
                    iva = datos_pdf.get("iva_eur") or 0.0
                    r["procesados"].append({
                        "nombre": nombre_drive, "proveedor": prov["nombre"],
                        "total": total, "estado": estado,
                    })
                    r["total_eur"] += total
                    r["iva_total"] += iva
                    r["base_total"] += datos_pdf.get("base", 0) or 0
                    log(f"  ✅ Registrado | {total:.2f}€ | {estado}")

                # Etiquetar email como procesado (solo si no es dry-run)
                if algun_pdf_nuevo and not dry_run:
                    etiquetar_mensaje(gmail, msg_id, label_procesadas_id)

            except Exception as e:
                log(f"  ❌ Error: {e}", "ERROR")
                r["errores"].append({"msg_id": msg_id, "error": str(e)})

    # Resumen final
    modo_str = f"{args.modo} [DRY-RUN]" if dry_run else args.modo
    print("\n" + "=" * 60)
    print("BORDAGRAN FISCAL -- Resumen procesamiento")
    print(f"Modo: {modo_str} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    if dry_run:
        print("  *** DRY-RUN: no se ha escrito nada en Sheet/Drive/Gmail ***")
    print("-" * 60)
    label_reg = "Habria registrado" if dry_run else "Facturas registradas"
    print(f"  OK  {label_reg:<28}: {len(r['procesados'])}")
    print(f"  DUP Duplicados ignorados       : {len(r['duplicados'])}")
    print(f"  NF  No fiscales omitidos       : {len(r['no_fiscales'])}")
    print(f"  PEN Pendientes sin registrar   : {len(r['pendientes'])}")
    print(f"  CUE Facturas en cuerpo         : {len(r['factura_en_cuerpo'])}")
    print(f"  PDF Sin PDF ni datos           : {len(r['sin_pdf'])}")
    print(f"  ERR Errores                    : {len(r['errores'])}")
    if r["pendientes"]:
        print("  PENDIENTES_EXTRACCION (revisar manualmente):")
        for p in r["pendientes"]:
            print(f"    - {p['proveedor']} | {p['nombre']} | {p['motivo']}")
    if r["no_fiscales"]:
        print("  No fiscales omitidos (albaran/aviso/excluidos):")
        for nf in r["no_fiscales"]:
            print(f"    - [{nf['tipo']}] {nf['proveedor']} | {nf['nombre']} | {nf['motivo']}")
    if r["factura_en_cuerpo"]:
        print("  Facturas detectadas en cuerpo email:")
        for fc in r["factura_en_cuerpo"]:
            d = fc.get("datos",{})
            print(f"    - {fc['proveedor']} | num:{d.get('num_factura','?')} | {d.get('total','?')}EUR")
    if r["duplicados"]:
        print("  Detalle duplicados:")
        for dup in r["duplicados"]:
            print(f"    - {dup['nombre']}: {dup['motivo']}")
    print(f"  EUR Base imponible total  : {r['base_total']:.2f} EUR")
    print(f"  IVA IVA total             : {r['iva_total']:.2f} EUR")
    print(f"  EUR Importe total         : {r['total_eur']:.2f} EUR")
    print("=" * 60 + "\n")

    # Guardar resultado JSON
    try:
        runtime_dir = skill_dir / "runtime"
        runtime_dir.mkdir(exist_ok=True)
        resultado_path = runtime_dir / "ultimo_resultado.json"
        with open(resultado_path, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
        print(f"Resultado guardado en: {resultado_path}")
    except Exception as e:
        print(f"ADVERTENCIA: no se pudo guardar ultimo_resultado.json: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
