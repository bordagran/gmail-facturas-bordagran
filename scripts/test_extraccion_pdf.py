"""
test_extraccion_pdf.py — Bordagran Fiscal v2.0
Test manual de extracción de datos desde un PDF de factura.

Uso:
    python scripts/test_extraccion_pdf.py ruta/al/factura.pdf
    python scripts/test_extraccion_pdf.py ruta/al/factura.pdf --verbose
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

# Añadir parent para importar procesar_facturas
sys.path.insert(0, str(Path(__file__).parent))
from procesar_facturas import extraer_datos_pdf, hash_pdf


def test_pdf(ruta: str, verbose: bool = False):
    path = Path(ruta)
    if not path.exists():
        print(f"❌ Archivo no encontrado: {ruta}")
        sys.exit(1)

    print(f"\n📄 Analizando: {path.name}")
    print(f"   Tamaño: {path.stat().st_size / 1024:.1f} KB")
    print(f"   Hash  : {hash_pdf(ruta)[:32]}...")
    print()

    if verbose:
        try:
            import pdfplumber
            with pdfplumber.open(ruta) as pdf:
                print(f"   Páginas: {len(pdf.pages)}")
                for i, page in enumerate(pdf.pages[:3]):
                    texto = page.extract_text() or ""
                    print(f"\n--- Página {i+1} (primeras 500 chars) ---")
                    print(texto[:500])
            print("\n" + "=" * 50 + "\n")
        except Exception as e:
            print(f"⚠️  Error leyendo texto: {e}\n")

    datos = extraer_datos_pdf(ruta)

    # Evaluar calidad
    campos_ok = sum(1 for v in [
        datos.get("num_factura"),
        datos.get("fecha"),
        datos.get("total"),
        datos.get("base"),
    ] if v)

    if campos_ok == 4:
        estado_ext = "✅ Extracción completa"
    elif campos_ok >= 2:
        estado_ext = "⚠️  Extracción parcial"
    else:
        estado_ext = "❌ Extracción fallida"

    print(f"Resultado: {estado_ext} ({campos_ok}/4 campos clave)")
    print("-" * 40)
    print(f"  Nº Factura   : {datos.get('num_factura') or '—'}")
    print(f"  Fecha        : {datos.get('fecha') or '—'}")
    print(f"  Concepto     : {(datos.get('concepto') or '—')[:60]}")
    print(f"  Base Impon.  : {datos.get('base') or '—'}")
    print(f"  IVA %        : {datos.get('iva_pct') or '—'}")
    print(f"  IVA €        : {datos.get('iva_eur') or '—'}")
    print(f"  Total        : {datos.get('total') or '—'}")
    if datos.get("notas"):
        print(f"  ⚠️  Notas     : {datos['notas']}")
    print()

    return datos


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", help="Ruta al PDF a testear")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Mostrar texto extraído del PDF")
    parser.add_argument("--json", action="store_true",
                        help="Mostrar output en formato JSON")
    args = parser.parse_args()

    datos = test_pdf(args.pdf, args.verbose)

    if args.json:
        print(json.dumps(datos, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
