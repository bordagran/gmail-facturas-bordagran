/**
 * Dashboard Fiscal Bordagran — v3.3.0
 * SOLO LECTURA. No contiene ninguna función de escritura.
 *
 * Regla permanente: este archivo no debe contener ninguna de las
 * siguientes funciones: setValue, setValues, appendRow, clear,
 * deleteRow, insertRow, update, remove, move, copyTo, sort,
 * protect, setNumberFormat, setBackground, setFont, setFormula.
 *
 * Verificar con: python scripts/verificar_dashboard_solo_lectura.py
 */

var SHEET_ID = PropertiesService.getScriptProperties().getProperty("SHEET_FACTURAS_ID");
var HOJA_FACTURAS = "FACTURA PROVEEDORES";
var HOJA_MAESTRO  = "MAESTRO_PROVEEDORES";


/**
 * Punto de entrada principal del Web App.
 * Solo devuelve HTML — no modifica ningún dato.
 */
function doGet() {
  return HtmlService
    .createTemplateFromFile("Index")
    .evaluate()
    .setTitle("Dashboard Fiscal Bordagran");
}


/**
 * Helper para incluir archivos HTML (styles, scripts).
 * Reemplaza <?!= include('styles') ?> en Index.html.
 */
function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}


/**
 * Lee todas las filas de FACTURA PROVEEDORES.
 * Devuelve { headers: [...], rows: [[...], ...] }
 * SOLO LECTURA — solo usa getValues().
 */
function getFacturas() {
  try {
    var ss    = SpreadsheetApp.openById(SHEET_ID);
    var sheet = ss.getSheetByName(HOJA_FACTURAS);
    if (!sheet) return { error: "Pestaña '" + HOJA_FACTURAS + "' no encontrada." };

    var data = sheet.getDataRange().getValues();
    if (!data || data.length < 2) return { headers: [], rows: [] };

    var headers = data[0].map(function(h) { return String(h).trim(); });
    var rows    = data.slice(1).map(function(row) {
      return row.map(function(cell) {
        if (cell instanceof Date) {
          // Formatear fecha como dd/mm/aaaa para visualización
          var d = cell;
          return (
            ("0" + d.getDate()).slice(-2) + "/" +
            ("0" + (d.getMonth() + 1)).slice(-2) + "/" +
            d.getFullYear()
          );
        }
        return cell;
      });
    });

    return { headers: headers, rows: rows };
  } catch (ex) {
    return { error: String(ex) };
  }
}


/**
 * Lee todas las filas de MAESTRO_PROVEEDORES.
 * SOLO LECTURA — solo usa getValues().
 */
function getMaestro() {
  try {
    var ss    = SpreadsheetApp.openById(SHEET_ID);
    var sheet = ss.getSheetByName(HOJA_MAESTRO);
    if (!sheet) return { maestro: [], warning: "Pestaña MAESTRO_PROVEEDORES no encontrada. Se usarán valores por defecto." };

    var data = sheet.getDataRange().getValues();
    if (!data || data.length < 2) return { maestro: [] };

    var headers = data[0].map(function(h) { return String(h).trim(); });
    var maestro = data.slice(1).map(function(row) {
      var obj = {};
      headers.forEach(function(h, i) { obj[h] = row[i]; });
      return obj;
    });

    return { maestro: maestro };
  } catch (ex) {
    return { error: String(ex) };
  }
}


/**
 * Parseo seguro de IVA%: parseFloat("0") || null = null (falsy trap).
 * Esta función devuelve 0 correctamente cuando el valor es "0" o "0%".
 * SOLO LECTURA — función auxiliar pura.
 */
function parseIvaPctDashboard(valor) {
  if (valor === null || valor === undefined) return null;
  var txt = String(valor).trim();
  if (!txt || txt === "-") return null;
  txt = txt.replace(/%/g, "").replace(",", ".").trim();
  var n = parseFloat(txt);
  return isNaN(n) ? null : n;
}


/**
 * Devuelve un resumen consolidado: KPIs, alertas, agrupaciones.
 * Todo el cálculo ocurre en memoria — SOLO LECTURA.
 */
function getResumen() {
  var facturas = getFacturas();
  var maestroData = getMaestro();

  if (facturas.error) return { error: facturas.error };

  var headers = facturas.headers;
  var rows    = facturas.rows;

  // Índices de columnas por nombre
  var idx = {};
  headers.forEach(function(h, i) { idx[h.toUpperCase()] = i; });

  var idxFecha    = idx["FECHA"]          !== undefined ? idx["FECHA"]          : 0;
  var idxTrim     = idx["TRIMESTRE"]      !== undefined ? idx["TRIMESTRE"]      : 1;
  var idxProv     = idx["PROVEEDOR"]      !== undefined ? idx["PROVEEDOR"]      : 2;
  var idxBase     = idx["BASE"]           !== undefined ? idx["BASE"]           : 6;
  var idxIvaPct   = idx["IVA_PCT"]        !== undefined ? idx["IVA_PCT"]        : 7;
  var idxIvaEur   = idx["IVA_EUR"]        !== undefined ? idx["IVA_EUR"]        : 8;
  var idxTotal    = idx["TOTAL"]          !== undefined ? idx["TOTAL"]          : 9;
  var idxEstado   = idx["ESTADO"]         !== undefined ? idx["ESTADO"]         : 11;
  var idxNotas    = idx["NOTAS"]          !== undefined ? idx["NOTAS"]          : 12;
  var idxNumFact  = idx["NUM_FACTURA"]    !== undefined ? idx["NUM_FACTURA"]    : 4;
  var idxRuta     = idx["RUTA_PDF"]       !== undefined ? idx["RUTA_PDF"]       : 10;

  // Mapa del Maestro: proveedor_normalizado -> datos
  var maestroMap = {};
  (maestroData.maestro || []).forEach(function(m) {
    var key = String(m["Proveedor detectado"] || m["Proveedor normalizado"] || "")
              .toLowerCase().replace(/\s+/g, "");
    if (key) maestroMap[key] = m;
  });

  // ── Exclusión visual v3.4.0 ──────────────────────────────────
  // Proveedores que NO deben aparecer en KPIs, alertas ni ranking.
  // No borra filas del Sheet. Solo filtra en memoria antes de calcular.
  // Cubre ESCUELAARTEGRANADA y cualquier entrada con estado "Excluido"
  // en MAESTRO_PROVEEDORES, más las variantes de nombre hard-coded.
  var _EXCLUIDOS_VISUAL = [
    "escuelaartegranada",
    "escuelaartegranadada",   // typo defensivo
    "escuelaartegranada",
    "escuelaartegranada",
  ];
  // Añadir entradas Excluido del Maestro dinámicamente
  Object.keys(maestroMap).forEach(function(k) {
    var ev = String(
      maestroMap[k]["Estado validación proveedor"] ||
      maestroMap[k]["Estado validacion proveedor"] || ""
    ).trim().toLowerCase();
    if (ev === "excluido") { _EXCLUIDOS_VISUAL.push(k); }
  });
  function _esExcluidoVisual(nombreProv) {
    var norm = nombreProv.toLowerCase().replace(/\s+/g, "");
    // Variantes con "de" y sin "de"
    var variantes = [
      norm,
      norm.replace("dearte", "arte"),   // "escueladeartegranada" -> "escuelaartegranada"
      norm.replace("escueladearte", "escuelaarte")
    ];
    for (var vi = 0; vi < variantes.length; vi++) {
      if (_EXCLUIDOS_VISUAL.indexOf(variantes[vi]) >= 0) return true;
    }
    return false;
  }
  // ── Fin exclusión visual ──────────────────────────────────────

  // KPIs
  var totalFacturas    = 0;
  var sumaBase         = 0;
  var sumaIvaEur       = 0;
  var sumaTotal        = 0;
  var countRegistrada  = 0;
  var countRevisar     = 0;
  var countPendiente   = 0;
  var countError       = 0;
  var countValidada    = 0;
  var sinPdf           = 0;
  var ivaCero          = 0;
  var fechaSospechosa  = 0;
  var intracomunitario = 0;

  var alertas = [];
  var porProveedor = {};
  var porTrimestre = {};
  var porMes       = {};
  var proveedoresNuevos = [];

  rows.forEach(function(row, i) {
    if (!row[idxProv] && !row[idxTotal]) return; // fila vacía

    // v3.4.0: excluir visualmente antes de KPIs, alertas y ranking
    var _provCheck = String(row[idxProv] || "").trim();
    if (_esExcluidoVisual(_provCheck)) return;

    totalFacturas++;

    var base    = parseFloat(row[idxBase])   || 0;
    var ivaEur  = parseFloat(row[idxIvaEur]) || 0;
    var total   = parseFloat(row[idxTotal])  || 0;
    var estado  = String(row[idxEstado] || "").trim();
    var prov    = String(row[idxProv]   || "").trim();
    var notas   = String(row[idxNotas]  || "").toLowerCase();
    var trim    = String(row[idxTrim]   || "").trim();
    var fecha   = String(row[idxFecha]  || "").trim();
    var numFact = String(row[idxNumFact]|| "").trim();
    var ruta    = String(row[idxRuta]   || "").trim();
    var ivaPct  = parseIvaPctDashboard(row[idxIvaPct]);

    sumaBase    += base;
    sumaIvaEur  += ivaEur;
    sumaTotal   += total;

    // Contadores de estado
    if (estado === "Registrada")          countRegistrada++;
    else if (estado === "Revisar")        countRevisar++;
    else if (estado === "Validada Carlos") countValidada++;
    else if (estado === "Error lectura")  countError++;
    else                                   countPendiente++;

    // Sin PDF real
    if (!ruta || ruta === "" || ruta.indexOf("EMAIL:") === 0 || ruta.indexOf("BODY:") === 0) {
      sinPdf++;
    }

    // Maestro lookup — debe ir antes de ivaCero para incluir intracomunitarias
    var provKey = prov.toLowerCase().replace(/\s+/g, "");
    var maestroEntry = maestroMap[provKey];
    var esIntracomunitario = maestroEntry &&
      String(maestroEntry["Tipo fiscal"] || "").indexOf("Intracomunitario") >= 0;

    // Intracomunitario / RITI (contador separado)
    if (esIntracomunitario) {
      intracomunitario++;
    }

    // IVA 0%: IVA% explícito = 0 O proveedor intracomunitario en Maestro
    // Garantiza: KPI IVA 0% >= KPI Intracomunit. siempre
    if (ivaPct === 0 || esIntracomunitario) {
      ivaCero++;
    }

    // Fecha sospechosa: trimestre en columna B no cuadra con fecha
    if (fecha && trim) {
      var partes = fecha.split("/");
      if (partes.length === 3) {
        var mes = parseInt(partes[1], 10);
        var anio = partes[2];
        var trimEsperado = "Q" + Math.ceil(mes / 3) + "-" + anio;
        if (trimEsperado !== trim) {
          fechaSospechosa++;
          alertas.push({
            tipo: "rojo",
            fila: i + 2,
            proveedor: prov,
            num_factura: numFact,
            mensaje: "Fecha sospechosa: fecha=" + fecha + " pero trimestre=" + trim + " (esperado " + trimEsperado + ")"
          });
        }
      }
    }

    // Alerta THClothes sin Revisar
    if (prov.toLowerCase().indexOf("thclothes") >= 0 && estado !== "Revisar" && estado !== "Validada Carlos") {
      alertas.push({
        tipo: "rojo",
        fila: i + 2,
        proveedor: prov,
        num_factura: numFact,
        mensaje: "THClothes debería estar en Revisar (L-053, RITI/IVA0). Estado actual: " + estado
      });
    }

    // Proveedor nuevo (no en Maestro)
    if (!maestroEntry) {
      var yaListado = proveedoresNuevos.some(function(p) { return p.proveedor === prov; });
      if (!yaListado && prov) {
        proveedoresNuevos.push({ proveedor: prov, fila: i + 2 });
        alertas.push({
          tipo: "amarillo",
          fila: i + 2,
          proveedor: prov,
          num_factura: numFact,
          mensaje: "Proveedor nuevo sin clasificar en MAESTRO_PROVEEDORES"
        });
      }
    }

    // Factura sin num
    if (!numFact) {
      alertas.push({
        tipo: "amarillo",
        fila: i + 2,
        proveedor: prov,
        num_factura: "",
        mensaje: "Factura sin número"
      });
    }

    // Por proveedor
    if (!porProveedor[prov]) porProveedor[prov] = { total: 0, count: 0 };
    porProveedor[prov].total += total;
    porProveedor[prov].count++;

    // Por trimestre
    if (trim) {
      if (!porTrimestre[trim]) porTrimestre[trim] = { total: 0, base: 0, iva: 0, count: 0 };
      porTrimestre[trim].total += total;
      porTrimestre[trim].base  += base;
      porTrimestre[trim].iva   += ivaEur;
      porTrimestre[trim].count++;
    }

    // Por mes (dd/mm/aaaa -> mm/aaaa)
    if (fecha && fecha.indexOf("/") >= 0) {
      var pf = fecha.split("/");
      if (pf.length === 3) {
        var mesClave = pf[1] + "/" + pf[2];
        if (!porMes[mesClave]) porMes[mesClave] = { total: 0, base: 0, iva: 0, count: 0 };
        porMes[mesClave].total += total;
        porMes[mesClave].base  += base;
        porMes[mesClave].iva   += ivaEur;
        porMes[mesClave].count++;
      }
    }
  });

  return {
    kpis: {
      total_facturas:     totalFacturas,
      suma_base:          Math.round(sumaBase    * 100) / 100,
      suma_iva:           Math.round(sumaIvaEur  * 100) / 100,
      suma_total:         Math.round(sumaTotal   * 100) / 100,
      count_registrada:   countRegistrada,
      count_revisar:      countRevisar,
      count_validada:     countValidada,
      count_error:        countError,
      count_pendiente:    countPendiente,
      sin_pdf:            sinPdf,
      iva_cero:           ivaCero,
      fecha_sospechosa:   fechaSospechosa,
      intracomunitario:   intracomunitario,
      proveedores_nuevos: proveedoresNuevos.length
    },
    alertas:          alertas,
    por_proveedor:    porProveedor,
    por_trimestre:    porTrimestre,
    por_mes:          porMes,
    proveedores_nuevos: proveedoresNuevos,
    maestro_warning:  maestroData.warning || null
  };
}
