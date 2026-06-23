#!/usr/bin/env python3
"""
verificar_dashboard_solo_lectura.py - v3.3.0
Valida que dashboard/ no contiene funciones de escritura a Google Sheets.

Uso:
    python scripts/verificar_dashboard_solo_lectura.py
"""

import re
import sys
import pathlib

FUNCIONES_PROHIBIDAS = [
    "setValue", "setValues", "appendRow", "clear",
    "deleteRow", "insertRow", "protect",
    "setNumberFormat", "setBackground", "setFont", "setFormula",
]

# Solo prohibidas en .gs (GAS servidor) - en .html son JS nativo legitimo
FUNCIONES_PROHIBIDAS_SOLO_GS = [
    "sort", "copyTo", "remove", "move", "update",
]

PATRON_BASE = r"(?<!\w)(?:[\w.]+\.)?{fn}\s*\("

DASHBOARD_DIR = pathlib.Path(__file__).parent.parent / "dashboard"
ARCHIVOS_VERIFICAR = [
    DASHBOARD_DIR / "Code.gs",
    DASHBOARD_DIR / "Index.html",
    DASHBOARD_DIR / "styles.html",
    DASHBOARD_DIR / "scripts.html",
]


def es_linea_comentario(linea, pos):
    antes = linea[:pos]
    if "//" in antes:
        return True
    stripped = linea.strip()
    if stripped.startswith(("//", "*", "#", "<!--", "*/")):
        return True
    return False


def verificar_archivo(ruta):
    hallazgos = []
    if not ruta.exists():
        return []

    texto = ruta.read_text(encoding="utf-8", errors="replace")
    lineas = texto.splitlines()

    es_gs = ruta.suffix.lower() == ".gs"
    funciones = list(FUNCIONES_PROHIBIDAS)
    if es_gs:
        funciones += FUNCIONES_PROHIBIDAS_SOLO_GS

    for fn in funciones:
        patron = re.compile(PATRON_BASE.format(fn=fn))
        for i, linea in enumerate(lineas, start=1):
            for m in patron.finditer(linea):
                if es_linea_comentario(linea, m.start()):
                    continue
                antes = linea[:m.start()].rstrip()
                if antes and antes[-1] in ('"', "'", "[", ">"):
                    continue
                hallazgos.append((i, fn, linea.rstrip()))

    return hallazgos


def main():
    sep = "=" * 60
    print(sep)
    print("Verificador solo lectura - Dashboard Fiscal Bordagran v3.3.0")
    print(sep)

    if not DASHBOARD_DIR.exists():
        print("AVISO: Directorio dashboard/ no encontrado: " + str(DASHBOARD_DIR))
        return 1

    total = 0
    errores = 0
    ok = 0

    for ruta in ARCHIVOS_VERIFICAR:
        if not ruta.exists():
            print("  AVISO: Archivo no encontrado: " + ruta.name)
            continue

        hallazgos = verificar_archivo(ruta)

        if hallazgos:
            errores += 1
            print("\nFALLO en " + ruta.name + ":")
            for num_linea, fn, linea in hallazgos:
                print("  Linea {:4d} [{}]: {}".format(num_linea, fn, linea[:120]))
                total += 1
        else:
            ok += 1
            print("  OK " + ruta.name)

    print()

    if total == 0:
        print("OK - dashboard limpio de funciones de escritura")
        print("   Archivos verificados: " + str(ok))
        print()
        print("Nota: Array.sort() y metodos DOM en .html no se verifican")
        print("como escritura Sheets - son JS nativo del navegador.")
        return 0
    else:
        print("FALLO - " + str(total) + " funcion(es) prohibida(s) en "
              + str(errores) + " archivo(s)")
        print()
        print("Funciones prohibidas en todos los archivos:")
        for fn in FUNCIONES_PROHIBIDAS:
            print("  - " + fn)
        print()
        print("Funciones prohibidas solo en .gs (GAS servidor):")
        for fn in FUNCIONES_PROHIBIDAS_SOLO_GS:
            print("  - " + fn)
        print()
        print("El dashboard nunca debe modificar Google Sheets.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
