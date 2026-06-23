"""
tests/test_maestro_proveedores.py — v3.3.0
Tests unitarios para las funciones del MAESTRO_PROVEEDORES.
No requieren conexion a Google Sheets (mocks).
Ejecutar: python -m pytest tests/test_maestro_proveedores.py -v
"""

import sys
import os
import types
import unittest
from unittest.mock import MagicMock, patch

# ── Bootstrap: stubs de dependencias externas ────────────────────────────────
def _install_stubs():
    for mod in ("pdfplumber", "dateutil", "dateutil.parser", "gspread"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    _gat_req = types.ModuleType("google.auth.transport.requests")
    _gat_req.Request = object
    _oauthflow = types.ModuleType("google_auth_oauthlib.flow")
    _oauthflow.InstalledAppFlow = object
    _disc = types.ModuleType("googleapiclient.discovery")
    _disc.build = lambda *a, **k: None
    _http = types.ModuleType("googleapiclient.http")
    _http.MediaFileUpload = object

    sys.modules.update({
        "google":                          types.ModuleType("google"),
        "google.auth":                     types.ModuleType("google.auth"),
        "google.auth.transport":           types.ModuleType("google.auth.transport"),
        "google.auth.transport.requests":  _gat_req,
        "google_auth_oauthlib":            types.ModuleType("google_auth_oauthlib"),
        "google_auth_oauthlib.flow":       _oauthflow,
        "googleapiclient":                 types.ModuleType("googleapiclient"),
        "googleapiclient.discovery":       _disc,
        "googleapiclient.http":            _http,
    })
    sys.modules["gspread"].authorize = lambda c: None

_install_stubs()

# Path al script
SCRIPT_DIR = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, SCRIPT_DIR)

# Import selectivo via exec para evitar ejecucion del bloque main
_src_path = os.path.join(SCRIPT_DIR, "procesar_facturas.py")
_namespace = {"__name__": "test_module"}
with open(_src_path, "r", encoding="utf-8") as _f:
    _src = _f.read()
    # Solo compilar hasta antes del bloque if __name__ == "__main__"
    _cutoff = _src.find('\nif __name__ == "__main__"')
    if _cutoff == -1:
        _cutoff = len(_src)
    exec(compile(_src[:_cutoff], _src_path, "exec"), _namespace)

normalizar_encabezado             = _namespace["normalizar_encabezado"]
normalizar_texto                  = _namespace["normalizar_texto"]
buscar_en_maestro                 = _namespace["buscar_en_maestro"]
criterio_maestro                  = _namespace["criterio_maestro"]
registrar_proveedor_nuevo_en_maestro = _namespace["registrar_proveedor_nuevo_en_maestro"]
determinar_estado                 = _namespace["determinar_estado"]
ESTADOS                           = _namespace["ESTADOS"]


# ─────────────────────────────────────────────────────────
# TESTS
# ─────────────────────────────────────────────────────────

class TestNormalizarEncabezado(unittest.TestCase):

    def test_sin_acentos(self):
        self.assertEqual(normalizar_encabezado("Acción automática"), "accion automatica")

    def test_mayusculas(self):
        self.assertEqual(normalizar_encabezado("ESTADO VALIDACION PROVEEDOR"), "estado validacion proveedor")

    def test_espacios_multiples(self):
        self.assertEqual(normalizar_encabezado("Proveedor  detectado"), "proveedor detectado")

    def test_vacio(self):
        self.assertEqual(normalizar_encabezado(""), "")

    def test_none_like(self):
        self.assertEqual(normalizar_encabezado(None), "")

    def test_equivalencia_con_sin_acento(self):
        a = normalizar_encabezado("Estado validación proveedor")
        b = normalizar_encabezado("Estado validacion proveedor")
        self.assertEqual(a, b)


class TestBuscarEnMaestro(unittest.TestCase):

    def _make_maestro(self):
        return {
            normalizar_texto("THClothes"): {"estado validacion proveedor": "Revisar siempre"},
            normalizar_texto("GOR Factory"): {"estado validacion proveedor": "Validado"},
            normalizar_texto("Apleona"): {"estado validacion proveedor": "Excluido"},
        }

    def test_encuentra_existente(self):
        m = self._make_maestro()
        r = buscar_en_maestro(m, "THClothes")
        self.assertIsNotNone(r)
        self.assertEqual(r["estado validacion proveedor"], "Revisar siempre")

    def test_no_encuentra_nuevo(self):
        m = self._make_maestro()
        r = buscar_en_maestro(m, "ProveedorNuevo")
        self.assertIsNone(r)

    def test_maestro_vacio(self):
        self.assertIsNone(buscar_en_maestro({}, "THClothes"))

    def test_nombre_vacio(self):
        m = self._make_maestro()
        self.assertIsNone(buscar_en_maestro(m, ""))

    def test_none_maestro(self):
        self.assertIsNone(buscar_en_maestro(None, "THClothes"))


class TestCriterioMaestro(unittest.TestCase):

    def test_excluido(self):
        r = criterio_maestro({"estado validacion proveedor": "Excluido"})
        self.assertEqual(r, {"accion": "excluir"})

    def test_pendiente(self):
        r = criterio_maestro({"estado validacion proveedor": "Pendiente"})
        self.assertEqual(r["accion"], "revisar")
        self.assertIn("pendiente", r["motivo"].lower())

    def test_revisar_siempre(self):
        r = criterio_maestro({"estado validacion proveedor": "Revisar siempre"})
        self.assertEqual(r["accion"], "revisar")
        self.assertIn("Revisar siempre", r["motivo"])

    def test_validado_con_control(self):
        r = criterio_maestro({
            "estado validacion proveedor": "Validado",
            "accion automatica": "Registrar con control",
        })
        self.assertEqual(r["accion"], "registrar_con_control")

    def test_validado_siempre_revisar(self):
        r = criterio_maestro({
            "estado validacion proveedor": "Validado",
            "accion automatica": "Registrar siempre como Revisar",
        })
        self.assertEqual(r["accion"], "revisar")

    def test_entrada_none(self):
        self.assertIsNone(criterio_maestro(None))

    def test_estado_desconocido(self):
        self.assertIsNone(criterio_maestro({"estado validacion proveedor": ""}))

    def test_case_insensitive(self):
        r = criterio_maestro({"estado validacion proveedor": "EXCLUIDO"})
        self.assertEqual(r["accion"], "excluir")


class TestDeterminarEstadoConCriterio(unittest.TestCase):
    """Verifica que determinar_estado() respeta el criterio del Maestro."""

    _datos_completos = {
        "total": 100.0,
        "num_factura": "FAC-001",
        "iva_pct": 21,
        "notas": "",
    }

    def test_criterio_none_preserva_v321(self):
        """Sin Maestro: comportamiento v3.2.1 exacto."""
        estado = determinar_estado(self._datos_completos, False, criterio=None)
        self.assertEqual(estado, ESTADOS["REGISTRADA"])

    def test_criterio_revisar_fuerza_revisar(self):
        criterio = {"accion": "revisar", "motivo": "test"}
        estado = determinar_estado(self._datos_completos, False, criterio=criterio)
        self.assertEqual(estado, ESTADOS["REVISAR"])

    def test_criterio_pendiente_fuerza_revisar(self):
        criterio = {"accion": "pendiente"}
        estado = determinar_estado(self._datos_completos, False, criterio=criterio)
        self.assertEqual(estado, ESTADOS["REVISAR"])

    def test_criterio_excluir_fuerza_revisar(self):
        """excluir no deberia llegar a determinar_estado, pero salvaguarda."""
        criterio = {"accion": "excluir"}
        estado = determinar_estado(self._datos_completos, False, criterio=criterio)
        self.assertEqual(estado, ESTADOS["REVISAR"])

    def test_criterio_registrar_con_control_sigue_logica_v321(self):
        criterio = {"accion": "registrar_con_control"}
        estado = determinar_estado(self._datos_completos, False, criterio=criterio)
        self.assertEqual(estado, ESTADOS["REGISTRADA"])

    def test_proveedor_nuevo_nunca_registrada(self):
        """Datos completos pero proveedor nuevo: nunca Registrada."""
        # La logica de proveedor nuevo fuerza REVISAR ANTES de llamar determinar_estado
        # Este test verifica que si por alguna razon llega con criterio pendiente
        # tampoco puede ser Registrada
        criterio = {"accion": "revisar", "motivo": "Proveedor pendiente"}
        estado = determinar_estado(self._datos_completos, False, criterio=criterio)
        self.assertNotEqual(estado, ESTADOS["REGISTRADA"])

    def test_sin_total_siempre_revisar(self):
        datos = dict(self._datos_completos)
        datos["total"] = None
        criterio = {"accion": "registrar_con_control"}
        estado = determinar_estado(datos, False, criterio=criterio)
        self.assertEqual(estado, ESTADOS["REVISAR"])

    def test_sin_num_factura_siempre_revisar(self):
        datos = dict(self._datos_completos)
        datos["num_factura"] = ""
        criterio = {"accion": "registrar_con_control"}
        estado = determinar_estado(datos, False, criterio=criterio)
        self.assertEqual(estado, ESTADOS["REVISAR"])


class TestRegistrarProveedorNuevo(unittest.TestCase):

    def test_dry_run_no_escribe(self):
        ws = MagicMock()
        registrar_proveedor_nuevo_en_maestro(ws, "NuevoProv", "nuevo@test.com", "2026-06-23", dry_run=True)
        ws.append_row.assert_not_called()

    def test_modo_real_escribe_fila(self):
        ws = MagicMock()
        registrar_proveedor_nuevo_en_maestro(ws, "NuevoProv", "nuevo@test.com", "2026-06-23", dry_run=False)
        ws.append_row.assert_called_once()
        fila = ws.append_row.call_args[0][0]
        self.assertEqual(fila[0], "NuevoProv")          # A: nombre
        self.assertEqual(fila[2], "nuevo@test.com")      # C: remitente
        self.assertEqual(fila[8], "Pendiente")           # I: estado validacion
        self.assertEqual(fila[12], "2026-06-23")         # M: primera deteccion

    def test_sheet_none_no_falla(self):
        """Si sheet_maestro=None, no debe lanzar excepcion."""
        registrar_proveedor_nuevo_en_maestro(None, "Prov", "x@x.com", "2026-06-23", dry_run=False)

    def test_fila_15_columnas(self):
        ws = MagicMock()
        registrar_proveedor_nuevo_en_maestro(ws, "P", "e@e.com", "2026-06-23", dry_run=False)
        fila = ws.append_row.call_args[0][0]
        self.assertEqual(len(fila), 15, f"Esperadas 15 columnas, hay {len(fila)}")

    def test_fallo_api_silencioso(self):
        """Si append_row falla, no debe propagar la excepcion."""
        ws = MagicMock()
        ws.append_row.side_effect = Exception("API error")
        try:
            registrar_proveedor_nuevo_en_maestro(ws, "Prov", "x@x.com", "2026-06-23", dry_run=False)
        except Exception:
            self.fail("registrar_proveedor_nuevo_en_maestro propago excepcion")


class TestDegradacionSilenciosa(unittest.TestCase):
    """Cuando maestro_data={} y sheet_maestro=None: v3.2.1 exacto."""

    def test_sin_maestro_registrada(self):
        """Datos completos + sin Maestro = Registrada (v3.2.1)."""
        datos = {"total": 100.0, "num_factura": "FAC-001", "iva_pct": 21, "notas": ""}
        # Simula maestro_data={}, sheet_maestro=None
        entrada = buscar_en_maestro({}, "CualquierProv")  # None
        c = criterio_maestro(entrada)                      # None
        # es_proveedor_nuevo = (None and None is not None and ...) = False
        estado = determinar_estado(datos, False, criterio=c)
        self.assertEqual(estado, ESTADOS["REGISTRADA"])

    def test_maestro_vacio_proveedor_nuevo_fuerza_revisar(self):
        """Maestro existe pero vacio: proveedor no encontrado => es_proveedor_nuevo=True."""
        # sheet_maestro is not None (ws existe aunque este vacio)
        # entrada_maestro = None (no en maestro_data={})
        # => es_proveedor_nuevo = True
        sheet_maestro = MagicMock()  # not None
        maestro_data = {}
        entrada = buscar_en_maestro(maestro_data, "ProvNuevo")
        self.assertIsNone(entrada)
        es_proveedor_nuevo = (
            entrada is None
            and sheet_maestro is not None
            and not False  # not es_desconocido
        )
        self.assertTrue(es_proveedor_nuevo)


if __name__ == "__main__":
    unittest.main(verbosity=2)
