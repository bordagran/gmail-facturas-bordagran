"""
verificar_entorno.py — Bordagran Fiscal v2.3
Comprueba que el entorno está listo ANTES de ejecutar procesar_facturas.py.

Verificaciones:
  1. Skill-dir encontrado y accesible
  2. Archivos requeridos presentes (incluye exclusiones.json)
  3. Scripts Python sin SyntaxError (py_compile) + test --help
  4. config.json completo y válido (SHEET_FACTURAS_NAME = FACTURA PROVEEDORES)
  5. Dependencias Python instaladas
  6. .gitignore excluye archivos sensibles
  7. token.pickle presente y válido (OAuth)

Uso:
    python scripts/verificar_entorno.py --skill-dir .
    python scripts/verificar_entorno.py --skill-dir "C:\\ClaudeProyectos\\Bordagran\\gmail-facturas-bordagran"
"""

import argparse
import json
import os
import pickle
import py_compile
import sys
from pathlib import Path


# ── Helpers de terminal ───────────────────────────────────
def ok(msg):    print("  OK  " + str(msg))
def fallo(msg): print("  ERR " + str(msg)); return False
def warn(msg):  print("  AVS " + str(msg))
def sep(titulo): print("\n-- " + titulo + " " + "-" * max(0, 44 - len(titulo)))


def encontrar_skill_dir():
    appdata = os.environ.get("APPDATA", "")
    localappdata = os.environ.get("LOCALAPPDATA", "")
    for base in [Path(appdata) / "Claude", Path(localappdata) / "Packages"]:
        if not base.exists():
            continue
        for p in base.rglob("gmail-facturas-bordagran"):
            if p.is_dir() and (p / "SKILL.md").exists():
                return p
    return None


# ─────────────────────────────────────────────────────────
# VERIFICACIONES
# ─────────────────────────────────────────────────────────

def verificar_archivos(skill_dir):
    sep("Archivos requeridos")
    requeridos = [
        "SKILL.md", "config.json", "requirements.txt",
        "references/proveedores.json",
        "references/exclusiones.json",
        "scripts/procesar_facturas.py",
        "scripts/resumen.py",
        "scripts/verificar_entorno.py",
    ]
    todos_ok = True
    for f in requeridos:
        if (skill_dir / f).exists():
            ok(f)
        else:
            fallo("FALTA: " + f)
            todos_ok = False

    # Advertencias (no bloquean)
    for f in ["credentials.json", "token.pickle"]:
        if (skill_dir / f).exists():
            ok(f + " presente")
        else:
            warn(f + " no encontrado (necesario para ejecutar)")
    return todos_ok


def _verificar_help_procesar(skill_dir):
    """
    Ejecuta procesar_facturas.py --help con ruta absoluta, cwd=skill_dir y
    encoding seguro en Windows. Devuelve (exito: bool, detalle: str).
    """
    import subprocess

    script = (skill_dir / "scripts" / "procesar_facturas.py").resolve()
    cmd = [sys.executable, str(script), "--help"]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        r = subprocess.run(
            cmd,
            cwd=str(skill_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return False, "Timeout (>30s) ejecutando procesar_facturas.py --help"
    except Exception as e:
        return False, "Error lanzando --help: {}: {}".format(type(e).__name__, e)

    # Banner puede ir a stderr; argparse --help siempre a stdout
    # Unir ambos para la comprobacion
    salida = (r.stdout or "") + "\n" + (r.stderr or "")

    checks = {
        "returncode == 0": r.returncode == 0,
        "'usage:' en salida": "usage:" in salida.lower(),
        "'--modo' en salida": "--modo" in salida,
        "'--skill-dir' en salida": "--skill-dir" in salida,
        "'--forzar' en salida": "--forzar" in salida,
    }

    if all(checks.values()):
        return True, "procesar_facturas.py --help OK"

    fallidos = [k for k, v in checks.items() if not v]
    detalle = (
        "checks fallidos: {}\n"
        "  CMD      : {}\n"
        "  CWD      : {}\n"
        "  returncode: {}\n"
        "  STDOUT   :\n{}\n"
        "  STDERR   :\n{}"
    ).format(
        ", ".join(fallidos),
        " ".join(cmd),
        skill_dir,
        r.returncode,
        (r.stdout or "").strip() or "(vacio)",
        (r.stderr or "").strip() or "(vacio)",
    )
    return False, detalle


def verificar_sintaxis_python(skill_dir):
    """Compila todos los scripts .py y verifica que procesar_facturas responde a --help."""
    sep("Sintaxis Python (py_compile + --help)")
    scripts = list((skill_dir / "scripts").glob("*.py"))
    todos_ok = True
    for script in sorted(scripts):
        try:
            py_compile.compile(str(script), doraise=True)
            ok(script.name + " -- sintaxis OK")
        except py_compile.PyCompileError as e:
            msg = str(e).split(":", 1)[-1].strip()[:120]
            fallo(script.name + " -- SyntaxError: " + msg)
            todos_ok = False

    if not todos_ok:
        print("\n  Hay scripts con SyntaxError. El entorno NO esta listo.")
        print("  Corrige los errores antes de ejecutar procesar_facturas.py")
        return False

    # Test --help robusto (ruta absoluta, cwd, encoding, checks completos)
    principal = skill_dir / "scripts" / "procesar_facturas.py"
    if principal.exists():
        exito, detalle = _verificar_help_procesar(skill_dir)
        if exito:
            ok(detalle)
        else:
            fallo("procesar_facturas.py --help no respondio como se esperaba")
            for linea in detalle.splitlines():
                print("     " + linea)
            todos_ok = False

    return todos_ok


def verificar_config(skill_dir):
    sep("config.json")
    config_path = skill_dir / "config.json"
    if not config_path.exists():
        return fallo("config.json no encontrado")

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return fallo("config.json invalido: " + str(e))

    campos = [
        "SHEET_FACTURAS_ID", "SHEET_FACTURAS_NAME",
        "LABEL_PROCESADAS", "LABEL_PENDIENTE",
        "OWNER_EMAIL", "DRIVE_ROOT_FOLDER_ID",
    ]
    todos_ok = True
    for campo in campos:
        if config.get(campo):
            ok("{} = {}".format(campo, config[campo]))
        else:
            fallo("Campo faltante o vacio: " + campo)
            todos_ok = False

    # Verificar nombre de pestana — debe ser "FACTURA PROVEEDORES" (L-002, v2.3)
    nombre_hoja = config.get("SHEET_FACTURAS_NAME", "")
    if nombre_hoja == "FACTURA PROVEEDORES":
        ok("SHEET_FACTURAS_NAME = 'FACTURA PROVEEDORES' (correcto)")
    elif nombre_hoja == "Facturas":
        fallo("SHEET_FACTURAS_NAME = 'Facturas' -- debe ser 'FACTURA PROVEEDORES'. Actualiza config.json.")
        todos_ok = False
    else:
        warn("SHEET_FACTURAS_NAME = '{}' -- verifica que coincida con la pestana real del Sheet".format(nombre_hoja))

    return todos_ok


def verificar_dependencias():
    sep("Dependencias Python")
    requeridas = [
        ("pdfplumber",           "pdfplumber"),
        ("google.auth",          "google-auth"),
        ("google_auth_oauthlib", "google-auth-oauthlib"),
        ("googleapiclient",      "google-api-python-client"),
        ("gspread",              "gspread"),
        ("dateutil",             "python-dateutil"),
    ]
    todos_ok = True
    for modulo, paquete in requeridas:
        try:
            __import__(modulo)
            ok(paquete)
        except ImportError:
            fallo(paquete + " no instalado -- ejecuta: pip install " + paquete + " --break-system-packages")
            todos_ok = False
    return todos_ok


def verificar_gitignore(skill_dir):
    sep(".gitignore (seguridad)")
    gi_path = skill_dir / ".gitignore"
    if not gi_path.exists():
        warn(".gitignore no encontrado")
        return True
    contenido = gi_path.read_text(encoding="utf-8", errors="replace")
    criticos = ["credentials.json", "token.pickle", "*.pdf", "downloads/"]
    todos_ok = True
    for item in criticos:
        if item in contenido:
            ok("excluye '" + item + "'")
        else:
            fallo("'" + item + "' NO esta en .gitignore -- riesgo de subir datos sensibles")
            todos_ok = False
    return todos_ok


def verificar_token(skill_dir):
    sep("OAuth token")
    token_path = skill_dir / "token.pickle"
    if not token_path.exists():
        warn("token.pickle no encontrado -- se generara en la primera ejecucion")
        return True
    try:
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        if creds.valid:
            ok("token valido")
        elif creds.expired and creds.refresh_token:
            warn("token expirado pero renovable (se renovara automaticamente)")
        else:
            warn("token invalido -- puede requerir re-autenticacion")
    except Exception as e:
        warn("No se pudo leer token.pickle: " + str(e))
    return True


# ─────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bordagran Fiscal -- verificacion de entorno"
    )
    parser.add_argument("--skill-dir", default=None,
                        help="Ruta al directorio del skill")
    args = parser.parse_args()

    print("\n================================================")
    print("  Bordagran Fiscal -- Verificacion de entorno")
    print("================================================")

    # Localizar skill-dir
    if args.skill_dir:
        skill_dir = Path(args.skill_dir).resolve()
    else:
        skill_dir = encontrar_skill_dir()
        if not skill_dir:
            print("\nNo se encontro la carpeta del skill automaticamente.")
            print("Usa: python scripts/verificar_entorno.py --skill-dir .")
            sys.exit(1)

    print("\n  Skill-dir: " + str(skill_dir))

    if not skill_dir.exists():
        print("\nLa ruta no existe: " + str(skill_dir))
        sys.exit(1)


    # Ejecutar todas las verificaciones
    resultados = [
        verificar_archivos(skill_dir),
        verificar_sintaxis_python(skill_dir),
        verificar_config(skill_dir),
        verificar_dependencias(),
        verificar_gitignore(skill_dir),
        verificar_token(skill_dir),
    ]

    print()
    print('=' * 48)
    if all(resultados):
        print('OK  ENTORNO OK -- listo para ejecutar')
        print()
        print('   Siguiente paso:')
        print('   python scripts/procesar_facturas.py --modo incremental --skill-dir .')
    else:
        print('ERROR  ENTORNO CON ERRORES -- corrige los problemas antes de continuar')
        import sys; sys.exit(1)
    print('=' * 48)
    print()


if __name__ == "__main__":
    main()
