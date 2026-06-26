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
 * Normaliza una cabecera de columna para comparación robusta.
 * Mayúsculas, sin tildes, sin caracteres especiales, espacios normalizados.
 * Ejemplo: "Ruta PDF (Drive)" → "RUTA PDF DRIVE"
 * SOLO LECTURA — función pura.
 */
function normHdrGs_(txt) {
  return String(txt || "").toUpperCase()
    .replace(/[ÁÀÄÂ]/g,"A").replace(/[ÉÈËÊ]/g,"E")
    .replace(/[ÍÌÏÎ]/g,"I").replace(/[ÓÒÖÔ]/g,"O")
    .replace(/[ÚÙÜÛ]/g,"U").replace(/Ñ/g,"N")
    .replace(/[^A-Z0-9]+/g," ").trim();
}


/**
 * Lee todas las filas de FACTURA PROVEEDORES.
 * Devuelve { headers: [...], rows: [[...], ...], debug_urls: N }
 *
 * Añade columna virtual URL_FACTURA_DASHBOARD (no existe en el Sheet).
 * Para cada fila, busca la URL del PDF en este orden:
 *   1. Valor texto directo que empiece por http (columnas Ruta PDF)
 *   2. Hipervínculo en rich text (getRichTextValues)
 *   3. Fórmula HYPERLINK (getFormulas)
 *   4. Mismo proceso en columna Nº Factura (por si el enlace está ahí)
 *
 * SOLO LECTURA — solo usa getValues, getRichTextValues, getFormulas.
 */
function getFacturas() {
  try {
    var ss    = SpreadsheetApp.openById(SHEET_ID);
    var sheet = ss.getSheetByName(HOJA_FACTURAS);
    if (!sheet) return { error: "Pestaña '" + HOJA_FACTURAS + "' no encontrada." };

    var range = sheet.getDataRange();
    var data  = range.getValues();
    if (!data || data.length < 2) return { headers: [], rows: [] };

    // Leer fuentes adicionales para extraer hipervínculos (solo lectura)
    var rich, formulas;
    try { rich     = range.getRichTextValues(); } catch(e) { rich     = null; }
    try { formulas = range.getFormulas();       } catch(e) { formulas = null; }

    var headers = data[0].map(function(h) { return String(h).trim(); });

    // Localizar columna "Ruta PDF (Drive)" o cualquier variante.
    // Usa subcadena sobre el header normalizado para máxima tolerancia:
    //   "Ruta PDF (Drive)" → norm → "RUTA PDF DRIVE" → contiene "RUTA PDF" → encontrado
    //   "Ruta PDF"         → norm → "RUTA PDF"        → contiene "RUTA PDF" → encontrado
    //   "URL PDF"          → norm → "URL PDF"          → contiene "URL PDF"  → encontrado
    var PDF_KEYWORDS = ["RUTA PDF", "URL PDF", "ENLACE PDF", "FACTURA PDF", "RUTA DRIVE"];
    var idxRuta = -1;
    for (var c = 0; c < headers.length; c++) {
      var hn = normHdrGs_(headers[c]);
      for (var k = 0; k < PDF_KEYWORDS.length; k++) {
        if (hn.indexOf(PDF_KEYWORDS[k]) >= 0) { idxRuta = c; break; }
      }
      if (idxRuta >= 0) break;
    }

    // Extrae URL de una celda: texto plano → rich text link → fórmula HYPERLINK
    function extractUrl_(ri, ci) {
      // 1. Valor texto directo
      var val = String(data[ri][ci] === null || data[ri][ci] === undefined ? "" : data[ri][ci]).trim();
      if (/^https?:\/\//i.test(val)) return val;

      // 2. Rich text hipervínculo (getRichTextValues)
      if (rich && rich[ri] && rich[ri][ci]) {
        try {
          var rtv = rich[ri][ci];
          var lu = rtv.getLinkUrl();
          if (lu && /^https?:\/\//i.test(lu)) return lu;
          var runs = rtv.getRuns ? rtv.getRuns() : [];
          for (var r = 0; r < runs.length; r++) {
            var ru = runs[r].getLinkUrl ? runs[r].getLinkUrl() : null;
            if (ru && /^https?:\/\//i.test(ru)) return ru;
          }
        } catch(e) {}
      }

      // 3. Fórmula HYPERLINK: =HYPERLINK("https://...","texto") — sep , o ;
      if (formulas && formulas[ri] && formulas[ri][ci]) {
        var f = String(formulas[ri][ci]);
        var m = f.match(/=HYPERLINK\s*\(\s*["']([^"']+)["']/i);
        if (m && /^https?:\/\//i.test(m[1])) return m[1];
      }

      return "";
    }

    var VIRTUAL_HDR = "URL_FACTURA_DASHBOARD";
    var urlsDetectadas = 0;

    var rows = data.slice(1).map(function(row, ri) {
      var rowIdx = ri + 1; // +1 por la fila de cabecera

      var mappedRow = row.map(function(cell) {
        if (cell instanceof Date) {
          var d = cell;
          return (
            ("0" + d.getDate()).slice(-2) + "/" +
            ("0" + (d.getMonth() + 1)).slice(-2) + "/" +
            d.getFullYear()
          );
        }
        return cell;
      });

      var url = (idxRuta >= 0) ? extractUrl_(rowIdx, idxRuta) : "";
      if (url) urlsDetectadas++;
      mappedRow.push(url);
      return mappedRow;
    });

    return {
      headers: headers.concat([VIRTUAL_HDR]),
      rows: rows,
      debug_urls: urlsDetectadas
    };
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
