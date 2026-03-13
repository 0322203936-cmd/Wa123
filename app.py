"""
Walmex Dashboard — CFBC
Reporte ejecutivo estilo Walmart
"""
import json, base64, openpyxl
from collections import defaultdict
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Walmex · CFBC", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
.main .block-container { padding: 0 !important; max-width: 100% !important; margin: 0 !important; }
.main { padding: 0 !important; overflow: hidden !important; }
.stApp { margin: 0 !important; }
[data-testid="stHeader"],[data-testid="stSidebar"],[data-testid="stToolbar"],
[data-testid="stDecoration"],[data-testid="stStatusWidget"],
#MainMenu, header, footer {
    display: none !important; visibility: hidden !important; height: 0 !important;
}
.stDeployButton { display: none !important; }
div[style*="bottom: 1.5rem"], div[style*="bottom: 15px"],
div[style*="position: fixed"][style*="bottom"][style*="right"],
iframe[src*="badge"] {
    display: none !important; opacity: 0 !important;
    pointer-events: none !important; visibility: hidden !important;
}
[data-testid='stVerticalBlock'] { gap: 0 !important; padding: 0 !important; }
div[data-testid='stHtml'] { padding: 0 !important; margin: 0 !important; line-height: 0 !important; }
iframe { display: block !important; margin: 0 !important; border: none !important; }
</style>
""", unsafe_allow_html=True)

@st.cache_data(ttl=3600, show_spinner=False)
def cargar_datos(url: str = "") -> dict:
    paths = ["Analisis_Walmart.xlsx", "Analisis Walmart.xlsx"]
    excel_path = next((p for p in paths if Path(p).exists()), None)
    if not excel_path:
        raise FileNotFoundError("No se encontró Analisis_Walmart.xlsx. Súbelo al repo de GitHub.")
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb['Data']

    def sv(v):
        try: return float(v) if v is not None else 0.0
        except: return 0.0

    # Mapear columnas por nombre de encabezado — fila 1
    headers = [str(c.value).strip() if c.value else '' for c in ws[1]]
    def col(name):
        for i, h in enumerate(headers):
            if h == name: return i
        raise ValueError(f'Columna "{name}" no encontrada. Encabezados: {headers}')

    # Log headers para diagnóstico si alguna columna falla
    import sys
    _col_names = [h for h in headers if h]
    
    idx_producto = col('Desc Art 1')
    idx_tienda   = col('Nombre Tienda/Club')
    idx_semana   = col('SEM')
    idx_fecha    = col('Diario')
    idx_ventas   = col('Cnt POS')       # Unidades vendidas (Cnt POS)
    idx_embarque = col('Cntd Embarque') # Unidades embarcadas
    idx_merma_vc = col('Cant VC Tienda') # Merma (Cant VC Tienda)
    
    # Columnas opcionales para Tienda — intentar varios nombres posibles
    idx_venta_cfbc = None
    for _n in ['Venta CFBC / Costo (Facturado)', 'Venta CFBC/Costo (Facturado)',
               'Venta CFBC', 'CFBC']:
        try: idx_venta_cfbc = col(_n); break
        except: pass

    idx_retail_vc = None
    for _n in ['Suma de Retail VC Tienda', 'Retail VC Tienda',
               'Suma Retail VC Tienda', 'Retail VC', 'Suma de Retail VC',
               'Suma de Retail VC Tienda ']:  # trailing space variant
        try: idx_retail_vc = col(_n); break
        except: pass

    # Advertir si columnas clave no se encontraron
    if idx_retail_vc is None:
        import streamlit as _st
        _st.warning(
            f"⚠️ No se encontró columna 'Retail VC Tienda'. "
            f"Columnas disponibles: {[h for h in headers if h and 'VC' in h or 'Retail' in h or 'retail' in h.lower() if h]}\n"
            f"Todos los encabezados: {[h for h in headers if h]}"
        )

    records = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        producto  = str(row[idx_producto]).strip() if row[idx_producto] else None
        tienda    = str(row[idx_tienda]).strip()   if row[idx_tienda]   else None
        # Semana: valor simple como 50, 51 etc
        try:
            semana_num = int(float(row[idx_semana])) if row[idx_semana] is not None else None
        except:
            semana_num = None

        # Fecha: puede venir como datetime o string MM/DD/YYYY
        from datetime import datetime as _dt
        fecha_raw = row[idx_fecha]
        anio = None
        if hasattr(fecha_raw, 'strftime'):
            fecha = fecha_raw.strftime('%d/%m/%Y')
            anio  = fecha_raw.year
        elif fecha_raw:
            s_fecha = str(fecha_raw).strip()
            for fmt in ('%m/%d/%Y','%d/%m/%Y','%Y-%m-%d'):
                try:
                    dt   = _dt.strptime(s_fecha, fmt)
                    fecha = dt.strftime('%d/%m/%Y')
                    anio  = dt.year
                    break
                except:
                    continue
            else:
                fecha = s_fecha
        else:
            fecha = ''

        if not producto or not tienda or not semana_num: continue

        # Clave semana = año*100 + num  (ej: 202550)
        semana = (anio * 100 + semana_num) if anio else semana_num
        records.append({
            'producto':   producto,
            'tienda':     tienda,
            'semana':     semana,
            'fecha':      fecha,
            'ventas_u':   sv(row[idx_ventas]),
            'embarque_u': sv(row[idx_embarque]),
            'merma_u':    sv(row[idx_merma_vc]),  # Tomar directamente de Cant VC Tienda
            'venta_cfbc': sv(row[idx_venta_cfbc]) if idx_venta_cfbc is not None else 0,  # Venta CFBC
            'retail_vc':  sv(row[idx_retail_vc]) if idx_retail_vc is not None else 0,   # Retail VC Tienda
        })

    semanas   = sorted(set(r['semana'] for r in records))
    tiendas   = sorted(set(r['tienda']  for r in records))
    productos = sorted(set(r['producto'] for r in records))

    by_stp = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
    for r in records:
        by_stp[r['semana']][r['tienda']][r['producto']]['ventas_u']   += r['ventas_u']
        by_stp[r['semana']][r['tienda']][r['producto']]['embarque_u'] += r['embarque_u']
        by_stp[r['semana']][r['tienda']][r['producto']]['merma_u']    += r['merma_u']
        by_stp[r['semana']][r['tienda']][r['producto']]['venta_cfbc'] += r['venta_cfbc']
        by_stp[r['semana']][r['tienda']][r['producto']]['retail_vc']  += r['retail_vc']

    # Fecha real del Excel por semana
    fecha_por_semana = {}
    for r in records:
        if r['fecha']:
            fecha_por_semana[r['semana']] = r['fecha']

    result = {}
    for t in tiendas:
        result[t] = {}
        for s in semanas:
            idx    = semanas.index(s)
            last12 = semanas[max(0, idx-11):idx+1]
            last3  = semanas[max(0, idx-2):idx+1]
            prod_data = {}
            for p in productos:
                v12  = sum(by_stp[sem][t][p]['ventas_u']   for sem in last12)
                v3   = sum(by_stp[sem][t][p]['ventas_u']   for sem in last3)
                emb3 = sum(by_stp[sem][t][p]['embarque_u'] for sem in last3)  # embarque 3 semanas
                m3   = sum(by_stp[sem][t][p]['merma_u']    for sem in last3)  # merma 3 semanas (Cant VC Tienda)
                cfbc3 = sum(by_stp[sem][t][p].get('venta_cfbc', 0) for sem in last3)  # Venta CFBC 3 semanas
                retail3 = sum(by_stp[sem][t][p].get('retail_vc', 0) for sem in last3)  # Retail VC 3 semanas
                avg  = v3 / len(last3) if last3 else 0  # Promedio = 3 semanas / 3
                
                # Proyección = Venta Promedio / (1 - Índice Merma %)
                merma_ratio = m3 / emb3 if emb3 > 0 else 0  # Ratio de merma como decimal
                proj = avg / (1 - merma_ratio) if merma_ratio < 1 else avg  # Evitar división por cero
                
                prod_data[p] = {
                    'v12': round(v12), 'v3': round(v3),
                    'emb': round(emb3), 'm3': round(m3),
                    'avg': round(avg, 1), 'proj': round(proj),
                    'pct_merma': round(m3/emb3*100) if emb3 > 0 else 0,
                    'cfbc': round(cfbc3), 'retail': round(retail3),
                }
            result[t][s] = prod_data

    # Totales crudos acumulados por tienda — GLOBAL (todas las fechas, sin ventanas deslizantes)
    totales_tienda = defaultdict(lambda: defaultdict(float))
    # Totales crudos por tienda+semana — para filtrar por semana específica
    raw_semana = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    # Totales crudos por tienda+semana+producto — para cuadrar tablas inferiores con superiores
    totales_prod_tienda = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in records:
        totales_tienda[r['tienda']]['embarque_u'] += r['embarque_u']
        totales_tienda[r['tienda']]['venta_cfbc'] += r['venta_cfbc']
        totales_tienda[r['tienda']]['merma_u']    += r['merma_u']
        totales_tienda[r['tienda']]['retail_vc']  += r['retail_vc']
        raw_semana[r['tienda']][r['semana']]['embarque_u'] += r['embarque_u']
        raw_semana[r['tienda']][r['semana']]['venta_cfbc'] += r['venta_cfbc']
        raw_semana[r['tienda']][r['semana']]['merma_u']    += r['merma_u']
        raw_semana[r['tienda']][r['semana']]['retail_vc']  += r['retail_vc']
        totales_prod_tienda[r['tienda']][r['producto']]['embarque_u'] += r['embarque_u']
        totales_prod_tienda[r['tienda']][r['producto']]['venta_cfbc'] += r['venta_cfbc']
        totales_prod_tienda[r['tienda']][r['producto']]['merma_u']    += r['merma_u']
        totales_prod_tienda[r['tienda']][r['producto']]['retail_vc']  += r['retail_vc']
        totales_prod_tienda[r['tienda']][r['producto']]['ventas_u']   += r['ventas_u']

    # raw por tienda+semana+producto (exactamente la semana seleccionada)
    raw_prod_semana = {}
    for t in tiendas:
        raw_prod_semana[t] = {}
        for s in semanas:
            raw_prod_semana[t][str(s)] = {}
            for p in productos:
                d = by_stp[s][t][p]
                if any(d[k] for k in ['ventas_u','venta_cfbc','merma_u','retail_vc','embarque_u']):
                    raw_prod_semana[t][str(s)][p] = {
                        'ventas_u':   round(d['ventas_u']),
                        'venta_cfbc': round(d['venta_cfbc']),
                        'merma_u':    round(d['merma_u']),
                        'retail_vc':  round(d['retail_vc']),
                        'embarque_u': round(d['embarque_u']),
                    }

    return {
        'semanas':           semanas,
        'tiendas':           tiendas,
        'productos':         productos,
        'fecha_por_semana':  fecha_por_semana,
        'data':              {t: {str(s): v for s, v in sv2.items()} for t, sv2 in result.items()},
        'totales_tienda':    {t: dict(v) for t, v in totales_tienda.items()},
        'raw_semana':        {t: {str(s): dict(v) for s, v in sv.items()} for t, sv in raw_semana.items()},
        'raw_prod_semana':   raw_prod_semana,
        'totales_prod_tienda': {t: {p: dict(v) for p, v in pd.items()} for t, pd in totales_prod_tienda.items()},
    }

try:
    DATA = cargar_datos()
except Exception as e:
    st.error(f"❌ Error cargando datos: {e}")
    st.stop()

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#fff;font-family:Arial,sans-serif;font-size:12px;color:#111}
.hdr{display:flex;align-items:center;justify-content:space-between;padding:6px 16px 4px;border-bottom:1px solid #ccc}
.wm-logo{display:flex;align-items:center;gap:4px}
.wm-text{font-size:1.2rem;font-weight:700;color:#0071ce;letter-spacing:-0.5px}
.wm-spark{color:#ffc220;font-size:1.3rem;line-height:1}
.hdr-right{display:flex;align-items:center;gap:12px;font-size:.72rem;color:#333;line-height:1.6}
.hdr-tienda{padding:3px 16px 4px;font-size:.78rem;color:#333;border-bottom:1px solid #ddd}
.hdr-tienda strong{font-size:.8rem}
.btn-print{
  display:inline-flex;align-items:center;gap:5px;
  padding:4px 14px;border-radius:4px;border:1px solid #0071ce;
  background:#fff;color:#0071ce;font-size:.7rem;font-weight:700;
  cursor:pointer;transition:.15s;white-space:nowrap;flex-shrink:0;
}
.btn-print:hover{background:#0071ce;color:#fff}
.ctrl{display:flex;align-items:center;gap:8px;padding:5px 16px;background:#f5f7fa;border-bottom:1px solid #ddd;flex-wrap:wrap}
.ctrl label{font-size:.7rem;color:#555;font-weight:600}
select{border:1px solid #bbb;border-radius:4px;padding:3px 7px;font-size:.72rem;cursor:pointer;background:#fff}
.chip-wrap{display:flex;flex-wrap:wrap;gap:4px;flex:1}
.chip{padding:2px 9px;border-radius:12px;font-size:.67rem;cursor:pointer;border:1px solid #bbb;color:#333;background:#fff;transition:.15s}
.chip:hover{border-color:#0071ce;color:#0071ce}
.sem-item{display:flex;align-items:center;gap:6px;padding:4px 10px;font-size:.72rem;cursor:pointer;color:#333;white-space:nowrap}
.sem-item:hover{background:#f0f7ff}
.sem-item.on{background:#e8f0fe;color:#0071ce;font-weight:600}
.sem-item input{accent-color:#0071ce;cursor:pointer;width:13px;height:13px;flex-shrink:0}
.grid{display:grid;grid-template-columns:1fr 1fr;padding:8px 16px;gap:8px;width:100%;box-sizing:border-box}
.box{border:1px solid #bbb;border-radius:4px;overflow:visible}
.box-hdr{background:#f0f0f0;border-bottom:1px solid #bbb;padding:4px 10px;text-align:center;font-size:.74rem;font-weight:700;color:#111}
table.t{width:100%;border-collapse:collapse;font-size:.71rem}
table.t th{padding:3px 8px;font-size:.66rem;font-weight:700;color:#333;border-bottom:1px solid #ccc;text-align:right;background:#fafafa}
table.t th:first-child{text-align:left}
table.t td{padding:2px 8px;font-size:.71rem;text-align:right;color:#222}
table.t td:first-child{text-align:left;color:#111}
table.t tr.total td{font-weight:700;border-top:1px solid #ddd;background:#f5f5f5}
.red{color:#c00;font-weight:600}
.bold{font-weight:700}
#viewTienda table.t tr:not(.total):hover td{background:#f0f7ff;cursor:pointer}
#viewTienda{overflow:visible}
html,body{height:auto;overflow-y:auto}
#app{height:auto;overflow:visible}
@media(max-width:1200px){
  .grid{grid-template-columns:1fr;gap:8px}
}
@media(max-width:768px){
  .grid{gap:6px;padding:6px 12px}
  table.t th,table.t td{padding:1px 6px;font-size:.68rem}
}
#loader{position:fixed;inset:0;background:#fff;display:flex;align-items:center;justify-content:center;z-index:99;flex-direction:column;gap:10px}
.ld-txt{font-size:.85rem;color:#0071ce;font-weight:600}
.ld-bar{width:160px;height:3px;background:#dde;border-radius:2px;overflow:hidden}
.ld-fill{height:100%;background:#0071ce;animation:ld .9s ease-in-out infinite}
@keyframes ld{0%{transform:translateX(-100%)}100%{transform:translateX(200%)}}
</style>
</head>
<body>

<div id="loader">
  <div class="ld-txt">Cargando...</div>
  <div class="ld-bar"><div class="ld-fill"></div></div>
</div>

<div id="app" style="display:none">

  <div class="hdr">
    <div class="wm-logo">
      <div class="wm-text">Walmart</div>
      <img src="data:image/png;base64,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AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA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" style="height:22px;width:22px;object-fit:contain">
    </div>
    <div class="hdr-right">
      <div>
        <div id="hdrFecha">—</div>
        <div>Semana&nbsp;&nbsp;<strong id="hdrSem">—</strong></div>
      </div>
      <button class="btn-print" onclick="imprimirReporte()">🖨️ Imprimir</button>
    </div>
  </div>
  <div class="hdr-tienda">Nombre de Tienda&nbsp;&nbsp;<strong id="hdrTienda">—</strong></div>

  <div class="ctrl">
    <label>Semana:</label>
    <div style="position:relative;display:inline-block" id="semDropWrap">
      <button id="semDropBtn" onclick="toggleSemDrop()" style="border:1px solid #bbb;border-radius:4px;padding:3px 24px 3px 7px;font-size:.72rem;cursor:pointer;background:#fff;min-width:160px;text-align:left;position:relative">
        <span id="semDropLabel">— Seleccionar semanas —</span>
        <span style="position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:.6rem">▼</span>
      </button>
      <div id="semDropMenu" style="display:none;position:absolute;top:100%;left:0;z-index:999;background:#fff;border:1px solid #bbb;border-radius:4px;box-shadow:0 3px 10px rgba(0,0,0,.15);min-width:200px;max-height:260px;overflow-y:auto;padding:4px 0"></div>
    </div>
    <label>Tienda:</label>
    <div class="chip-wrap" id="chips"></div>
    <div style="margin-top:12px; display:flex; gap:8px;">
      <button onclick="setView('producto')" id="btnProd" style="padding:6px 12px; background:#0071ce; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:600;">📊 Producto</button>
      <button onclick="setView('tienda')" id="btnTiend" style="padding:6px 12px; background:#ccc; color:#333; border:none; border-radius:4px; cursor:pointer; font-weight:600;">🏪 Tienda</button>
    </div>
  </div>

  <div class="grid" id="viewProducto">
    <div class="box">
      <div class="box-hdr">Ventas Históricas</div>
      <table class="t"><thead><tr><th>Producto</th><th>12 Semanas</th><th>3 Semanas</th></tr></thead>
      <tbody id="tHist"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr">Índice de Merma por Artículo Últimas 3 Semanas</div>
      <table class="t"><thead><tr><th>Producto</th><th>Embarque</th><th>Merma</th><th>Merma %</th></tr></thead>
      <tbody id="tMerma"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr">Venta Promedio Semanal</div>
      <table class="t"><thead><tr><th>Producto</th><th>Promedio</th></tr></thead>
      <tbody id="tAvg"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr" id="projTitle">Proyección Semana Siguiente</div>
      <table class="t"><thead><tr><th>Producto</th><th>Proyección</th></tr></thead>
      <tbody id="tProj"></tbody></table>
    </div>
  </div>

  <div class="grid" id="viewTienda" style="display:none">
    <div class="box">
      <div class="box-hdr">Top Venta</div>
      <table class="t"><thead><tr><th>Tienda</th><th>UNIDADES</th><th>VENTA</th><th>%</th></tr></thead>
      <tbody id="tHistT"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr">Top Merma</div>
      <table class="t"><thead><tr><th>Tienda</th><th>UNIDADES</th><th>$</th><th>CANTIDAD</th><th>%</th></tr></thead>
      <tbody id="tMermaT"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr" id="avgTTitle">Venta Promedio Semanal</div>
      <table class="t"><thead><tr><th>Producto</th><th>Venta</th><th>Unidades</th></tr></thead>
      <tbody id="tAvgT"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr" id="projTTitle">Comparacion Ultimas 3 Semanas</div>
      <table class="t"><thead><tr><th>Merma Producto</th><th>Unidades</th><th>Cantidad</th></tr></thead>
      <tbody id="tProjT"></tbody></table>
    </div>
  </div>
</div>

<script>
var DATA = JSON.parse(atob('__DATA_JSON__'));
var state = { semana: null, semanas_sel: null, tienda: null, view: 'producto', tiendaT: null };
var DIAS  = ['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
var MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];

function fmt(v){ return Math.round(v||0).toLocaleString('es-MX'); }

function init(){
  window.onerror = function(m,s,l){
    document.body.innerHTML='<p style="padding:20px;color:red">Error: '+m+' (línea '+l+')</p>';
  };
  var menu = document.getElementById('semDropMenu');
  DATA.semanas.forEach(function(s){
    var yr = Math.floor(s/100), wk = s%100;
    var labelTxt = (yr >= 2000) ? yr+' · Semana '+String(wk).padStart(2,'0') : 'Semana '+String(s).padStart(2,'0');
    var isLast = (s === DATA.semanas[DATA.semanas.length-1]);
    var row = document.createElement('label');
    row.className = 'sem-item' + (isLast ? ' on' : '');
    row.id = 'sem-row-'+s;
    var chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.value = s;
    chk.checked = isLast;
    chk.onchange = function(){ onSemChk(); };
    row.appendChild(chk);
    row.appendChild(document.createTextNode(labelTxt));
    menu.appendChild(row);
  });
  // Cerrar dropdown al clicar fuera
  document.addEventListener('click', function(e){
    var wrap = document.getElementById('semDropWrap');
    if(wrap && !wrap.contains(e.target)) closeSemDrop();
  });
  state.semana = DATA.semanas[DATA.semanas.length-1];
  state.semanas_sel = [state.semana];
  state.tienda = DATA.tiendas[0];
  buildChips(); updateHeader(); updateSemLabel(); render();
  document.getElementById('loader').style.display = 'none';
  document.getElementById('app').style.display    = 'block';
}

function toggleSemDrop(){
  var menu = document.getElementById('semDropMenu');
  menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
}
function closeSemDrop(){
  document.getElementById('semDropMenu').style.display = 'none';
}

function updateSemLabel(){
  var sel = state.semanas_sel;
  var lbl = document.getElementById('semDropLabel');
  if(!sel || sel.length === 0){
    lbl.textContent = '— Todas las semanas —';
  } else if(sel.length === 1){
    var s = sel[0], yr = Math.floor(s/100), wk = s%100;
    lbl.textContent = (yr >= 2000) ? yr+' · Semana '+String(wk).padStart(2,'0') : 'Semana '+String(s).padStart(2,'0');
  } else {
    lbl.textContent = sel.length+' semanas seleccionadas';
  }
}

function onSemChk(){
  var chks = document.querySelectorAll('#semDropMenu input[type=checkbox]');
  var selected = [];
  chks.forEach(function(c){
    var s = parseInt(c.value);
    var row = document.getElementById('sem-row-'+s);
    if(c.checked){
      selected.push(s);
      if(row) row.className = 'sem-item on';
    } else {
      if(row) row.className = 'sem-item';
    }
  });
  state.semanas_sel = selected;
  state.semana = selected.length > 0 ? selected[selected.length-1] : 'all';
  state.tiendaT = null;
  updateSemLabel();
  updateHeader();
  if(state.view==='producto') render(); else renderTienda();
}

function onSem(sel){ onSemChk(); }

function buildChips(){
  document.getElementById('chips').innerHTML = DATA.tiendas.map(function(t){
    var n = t.replace('SC ','');
    return '<button class="chip'+(t===state.tienda?' on':'')+'" onclick="selTienda(\''+t+'\')">'+n+'</button>';
  }).join('');
}

function selTienda(t){ state.tienda=t; buildChips(); updateHeader(); if(state.view==='producto') render(); else renderTienda(); }
function onSem(sel){
  var selected = [];
  for(var i=0;i<sel.options.length;i++){
    if(sel.options[i].selected) selected.push(parseInt(sel.options[i].value));
  }
  state.semanas_sel = selected;
  state.semana = selected.length > 0 ? selected[selected.length-1] : 'all';
  state.tiendaT = null;
  updateHeader();
  if(state.view==='producto') render(); else renderTienda();
}

function updateHeader(){
  var sems = getSemanasActivas();
  var isAll = (!state.semanas_sel || state.semanas_sel.length === 0);
  document.getElementById('hdrTienda').textContent = state.tienda;
  if(isAll){
    var s0 = DATA.semanas[0], sN = DATA.semanas[DATA.semanas.length-1];
    var f0 = (DATA.fecha_por_semana && (DATA.fecha_por_semana[String(s0)] || DATA.fecha_por_semana[s0])) || '—';
    var fN = (DATA.fecha_por_semana && (DATA.fecha_por_semana[String(sN)] || DATA.fecha_por_semana[sN])) || '—';
    document.getElementById('hdrFecha').textContent  = f0 + ' — ' + fN;
    document.getElementById('hdrSem').textContent    = 'Global';
    document.getElementById('projTitle').textContent = 'Proyección';
    return;
  }
  if(sems.length > 1){
    var semNums = sems.map(function(s){ return s > 9999 ? s%100 : s; });
    document.getElementById('hdrFecha').textContent  = sems.length + ' semanas seleccionadas';
    document.getElementById('hdrSem').textContent    = 'Sem ' + semNums.join(', ');
    document.getElementById('projTitle').textContent = 'Proyección';
    return;
  }
  var semKey = String(state.semana);
  var fecha = DATA.fecha_por_semana && DATA.fecha_por_semana[semKey]
    ? DATA.fecha_por_semana[semKey]
    : DATA.fecha_por_semana && DATA.fecha_por_semana[state.semana]
    ? DATA.fecha_por_semana[state.semana]
    : '—';
  document.getElementById('hdrFecha').textContent   = fecha;
  var semNum = state.semana > 9999 ? state.semana%100 : state.semana;
  var semAnio = state.semana > 9999 ? Math.floor(state.semana/100) : '';
  document.getElementById('hdrSem').textContent     = (semAnio ? semAnio+' · ' : '')+'Semana '+String(semNum).padStart(2,'0');
  document.getElementById('projTitle').textContent  = 'Proyección Semana '+(semNum+1);
}

function getSemanasActivas(){
  if(!state.semanas_sel || state.semanas_sel.length === 0) return DATA.semanas;
  return state.semanas_sel;
}

function getD(){
  var sems = getSemanasActivas();
  var prods = DATA.productos;
  var merged = {};
  prods.forEach(function(p){
    var v12=0,v3=0,emb=0,m3=0,cfbc=0,retail=0;
    sems.forEach(function(s){
      var key = String(s);
      var d = (DATA.data[state.tienda]&&DATA.data[state.tienda][key]&&DATA.data[state.tienda][key][p]) || {};
      v12   += d.v12   || 0;
      v3    += d.v3    || 0;
      emb   += d.emb   || 0;
      m3    += d.m3    || 0;
      cfbc  += d.cfbc  || 0;
      retail+= d.retail|| 0;
    });
    var avg = sems.length > 0 ? v3 / sems.length : 0;
    var merma_ratio = emb > 0 ? m3/emb : 0;
    var proj = merma_ratio < 1 ? avg/(1-merma_ratio) : avg;
    merged[p] = {
      v12: v12, v3: v3, emb: emb, m3: m3,
      avg: avg, proj: proj,
      pct_merma: emb > 0 ? Math.round(m3/emb*100) : 0,
      cfbc: cfbc, retail: retail
    };
  });
  return merged;
}

function render(){
  var d = getD(), prods = DATA.productos;
  var totV12=0,totV3=0,totEmb=0,totM3=0,totAvg=0,totProj=0,totEmb2=0;
  var histRows='',mermaRows='',avgRows='',projRows='';

  // Construir array y ordenar cada tabla de mayor a menor
  var prodArr = prods.map(function(p){ return {p:p, v:d[p]||{v12:0,v3:0,emb:0,m3:0,avg:0,proj:0,pct_merma:0}}; });

  prodArr.forEach(function(o){ var v=o.v; totV12+=v.v12; totV3+=v.v3; totEmb+=v.emb; totM3+=v.m3; totAvg+=v.avg; totProj+=v.proj; totEmb2+=v.emb; });

  prodArr.slice().sort(function(a,b){ return b.v.v12-a.v.v12; }).forEach(function(o){
    var name=o.p.replace('BQT ',''), v=o.v;
    histRows += '<tr><td>'+name+'</td><td>'+fmt(v.v12)+'</td><td>'+fmt(v.v3)+'</td></tr>';
  });
  prodArr.slice().sort(function(a,b){ return b.v.m3-a.v.m3; }).forEach(function(o){
    var name=o.p.replace('BQT ',''), v=o.v;
    mermaRows += '<tr><td>'+name+'</td><td>'+fmt(v.emb)+'</td><td class="'+(v.m3>0?'red':'')+'">'+fmt(v.m3)+'</td><td class="'+(v.pct_merma>0?'red':'')+'">'+v.pct_merma+'%</td></tr>';
  });
  prodArr.slice().sort(function(a,b){ return b.v.avg-a.v.avg; }).forEach(function(o){
    var name=o.p.replace('BQT ',''), v=o.v;
    avgRows += '<tr><td>'+name+'</td><td>'+Math.round(v.avg)+'</td></tr>';
  });
  prodArr.slice().sort(function(a,b){ return b.v.proj-a.v.proj; }).forEach(function(o){
    var name=o.p.replace('BQT ',''), v=o.v;
    projRows += '<tr><td>'+name+'</td><td class="bold">'+fmt(v.proj)+'</td></tr>';
  });

  histRows  += '<tr class="total"><td>Total</td><td>'+fmt(totV12)+'</td><td>'+fmt(totV3)+'</td></tr>';
  var pct_merma_total = totEmb2 > 0 ? Math.round(totM3/totEmb2*100) : 0;
  mermaRows += '<tr class="total"><td>Total</td><td>'+fmt(totEmb)+'</td><td class="red">'+fmt(totM3)+'</td><td class="red">'+pct_merma_total+'%</td></tr>';
  avgRows   += '<tr class="total"><td>Total</td><td>'+Math.round(totAvg)+'</td></tr>';
  projRows  += '<tr class="total"><td>Total</td><td>'+fmt(totProj)+'</td></tr>';
  document.getElementById('tHist').innerHTML  = histRows;
  document.getElementById('tMerma').innerHTML = mermaRows;
  document.getElementById('tAvg').innerHTML   = avgRows;
  document.getElementById('tProj').innerHTML  = projRows;
}

function setView(v){
  state.view = v;
  document.getElementById('btnProd').style.background = v==='producto' ? '#0071ce' : '#ccc';
  document.getElementById('btnProd').style.color = v==='producto' ? 'white' : '#333';
  document.getElementById('btnTiend').style.background = v==='tienda' ? '#0071ce' : '#ccc';
  document.getElementById('btnTiend').style.color = v==='tienda' ? 'white' : '#333';
  document.getElementById('viewProducto').style.display = v==='producto' ? 'grid' : 'none';
  document.getElementById('viewTienda').style.display = v==='tienda' ? 'grid' : 'none';
  
  // Ocultar filtros de tienda en vista Tienda
  var chipWrap = document.querySelector('.chip-wrap');
  var tiendaLabel = Array.from(document.querySelectorAll('.ctrl label')).find(el => el.textContent === 'Tienda:');
  if(v==='tienda'){
    if(chipWrap) chipWrap.style.display = 'none';
    if(tiendaLabel) tiendaLabel.style.display = 'none';
  } else {
    if(chipWrap) chipWrap.style.display = 'flex';
    if(tiendaLabel) tiendaLabel.style.display = 'block';
  }
  
  if(v==='tienda'){ state.tiendaT = null; renderTienda(); }
  else render();
}

function selTiendaT(t){
  // Toggle: si ya está seleccionada, deseleccionar
  state.tiendaT = (state.tiendaT === t) ? null : t;
  renderTienda();
}

function renderTienda(){
  var tiendas = DATA.tiendas;
  var sems = getSemanasActivas();
  var isAll = (!state.semanas_sel || state.semanas_sel.length === 0);

  // ── Obtener totales por tienda según semanas activas ──
  var totEmb=0, totCfbc=0, totMerma=0, totRetail=0;
  var tiendaData = [];

  tiendas.forEach(function(tienda){
    var emb=0, cfbc=0, merma=0, retail=0;
    if(isAll){
      var tot = (DATA.totales_tienda && DATA.totales_tienda[tienda]) || {};
      emb    = tot.embarque_u || 0;
      cfbc   = tot.venta_cfbc || 0;
      merma  = tot.merma_u    || 0;
      retail = tot.retail_vc  || 0;
    } else {
      sems.forEach(function(s){
        var raw = (DATA.raw_semana && DATA.raw_semana[tienda] && DATA.raw_semana[tienda][String(s)]) || {};
        emb    += raw.embarque_u || 0;
        cfbc   += raw.venta_cfbc || 0;
        merma  += raw.merma_u    || 0;
        retail += raw.retail_vc  || 0;
      });
    }
    totEmb+=emb; totCfbc+=cfbc; totMerma+=merma; totRetail+=retail;
    tiendaData.push({tienda:tienda, emb:emb, cfbc:cfbc, merma:merma, retail:retail});
  });

  // ── TOP VENTA: ordenar por VENTA (cfbc) de mayor a menor ──
  var histRows='';
  tiendaData.slice().sort(function(a,b){ return b.cfbc-a.cfbc; }).forEach(function(t){
    var pct = totCfbc > 0 ? Math.round(t.cfbc/totCfbc*100) : 0;
    var sel = state.tiendaT === t.tienda;
    var style = sel ? 'style="background:#e8f0fe;font-weight:700;cursor:pointer"' : 'style="cursor:pointer"';
    histRows += '<tr '+style+' onclick="selTiendaT(\''+t.tienda.replace(/'/g,"\\'")+'\')">'
      +'<td>'+t.tienda+'</td><td>'+fmt(t.emb)+'</td><td>$'+fmt(t.cfbc)+'</td><td>'+pct+'%</td></tr>';
  });
  histRows += '<tr class="total"><td>Total</td><td>'+fmt(totEmb)+'</td><td>$'+fmt(totCfbc)+'</td><td>100%</td></tr>';

  // ── TOP MERMA: ordenar por RETAIL (cantidad $) de mayor a menor ──
  var mermaRows='';
  tiendaData.slice().sort(function(a,b){ return b.retail-a.retail; }).forEach(function(t){
    var pct_retail = totRetail > 0 ? Math.round(t.retail/totRetail*100) : 0;
    var sel = state.tiendaT === t.tienda;
    var style = sel ? 'style="background:#fff0f0;font-weight:700;cursor:pointer"' : 'style="cursor:pointer"';
    mermaRows += '<tr '+style+' onclick="selTiendaT(\''+t.tienda.replace(/'/g,"\\'")+'\')">'
      +'<td>'+t.tienda+'</td>'
      +'<td class="'+(t.merma>0?'red':'')+'">'+fmt(t.merma)+'</td>'
      +'<td>$</td>'
      +'<td class="'+(t.retail>0?'red':'')+'">'+fmt(t.retail)+'</td>'
      +'<td class="'+(pct_retail>0?'red':'')+'">'+pct_retail+'%</td></tr>';
  });
  mermaRows += '<tr class="total"><td>Total</td><td class="red">'+fmt(totMerma)+'</td><td>$</td><td class="red">'+fmt(totRetail)+'</td><td class="red">100%</td></tr>';

  // ── Semana clave para productos (última activa) ──
  var semKeyProd = sems.length > 0 ? String(sems[sems.length-1]) : String(DATA.semanas[DATA.semanas.length-1]);
  var prods = DATA.productos;

  // Determinar qué tiendas y productos mostrar en las tablas inferiores
  var avgRows='', projRows='';

  if(state.tiendaT){
    var tSel = state.tiendaT;
    var tName = tSel.replace('SC ','');
    document.getElementById('avgTTitle').textContent  = 'Venta — '+tName;
    document.getElementById('projTTitle').textContent = 'Merma — '+tName;

    var totVenta=0, totUnid=0, totMermaU=0, totMermaR=0;
    // Construir array con datos por producto
    var prodItems = prods.map(function(p){
      var d;
      if(isAll){
        d = (DATA.totales_prod_tienda && DATA.totales_prod_tienda[tSel] && DATA.totales_prod_tienda[tSel][p]) || {};
      } else {
        d = (DATA.raw_prod_semana && DATA.raw_prod_semana[tSel] && DATA.raw_prod_semana[tSel][semKeyProd] && DATA.raw_prod_semana[tSel][semKeyProd][p]) || {};
      }
      return { p:p, venta:d.venta_cfbc||0, unid:d.embarque_u||0, mermaU:d.merma_u||0, mermaR:d.retail_vc||0 };
    });
    prodItems.forEach(function(o){ totVenta+=o.venta; totUnid+=o.unid; totMermaU+=o.mermaU; totMermaR+=o.mermaR; });
    // Venta: ordenar por venta desc
    prodItems.slice().sort(function(a,b){ return b.venta-a.venta; }).forEach(function(o){
      var pname = o.p.replace('BQT ','');
      avgRows += '<tr><td>'+pname+'</td><td>$'+fmt(o.venta)+'</td><td>'+fmt(o.unid)+'</td></tr>';
    });
    // Merma: ordenar por mermaR desc
    prodItems.slice().sort(function(a,b){ return b.mermaR-a.mermaR; }).forEach(function(o){
      var pname = o.p.replace('BQT ','');
      projRows += '<tr><td>'+pname+'</td>'
        +'<td class="'+(o.mermaU>0?'red':'')+'">'+fmt(o.mermaU)+'</td>'
        +'<td class="'+(o.mermaR>0?'red':'')+'">$'+fmt(o.mermaR)+'</td></tr>';
    });
    avgRows  += '<tr class="total"><td>Total</td><td>$'+fmt(totVenta)+'</td><td>'+fmt(totUnid)+'</td></tr>';
    projRows += '<tr class="total"><td>Total</td><td class="red">'+fmt(totMermaU)+'</td><td class="red">$'+fmt(totMermaR)+'</td></tr>';

  } else {
    document.getElementById('avgTTitle').textContent  = 'Venta Promedio Semanal';
    document.getElementById('projTTitle').textContent = 'Comparacion Ultimas 3 Semanas';

    var totVenta=0, totUnid=0, totMermaU=0, totMermaR=0;
    // Construir array sumando todas las tiendas
    var prodItems = prods.map(function(p){
      var ventaSum=0, unidSum=0, mermaUSum=0, mermaRSum=0;
      tiendas.forEach(function(t){
        var d;
        if(isAll){
          d = (DATA.totales_prod_tienda && DATA.totales_prod_tienda[t] && DATA.totales_prod_tienda[t][p]) || {};
          ventaSum  += d.venta_cfbc || 0;
          unidSum   += d.embarque_u || 0;
          mermaUSum += d.merma_u    || 0;
          mermaRSum += d.retail_vc  || 0;
        } else {
          d = (DATA.raw_prod_semana && DATA.raw_prod_semana[t] && DATA.raw_prod_semana[t][semKeyProd] && DATA.raw_prod_semana[t][semKeyProd][p]) || {};
          ventaSum  += d.venta_cfbc || 0;
          unidSum   += d.embarque_u || 0;
          mermaUSum += d.merma_u    || 0;
          mermaRSum += d.retail_vc  || 0;
        }
      });
      return { p:p, venta:ventaSum, unid:unidSum, mermaU:mermaUSum, mermaR:mermaRSum };
    }).filter(function(o){ return o.venta||o.unid||o.mermaU||o.mermaR; });

    prodItems.forEach(function(o){ totVenta+=o.venta; totUnid+=o.unid; totMermaU+=o.mermaU; totMermaR+=o.mermaR; });
    // Venta: ordenar por venta desc
    prodItems.slice().sort(function(a,b){ return b.venta-a.venta; }).forEach(function(o){
      var pname = o.p.replace('BQT ','');
      avgRows += '<tr><td>'+pname+'</td><td>$'+fmt(o.venta)+'</td><td>'+fmt(o.unid)+'</td></tr>';
    });
    // Merma: ordenar por mermaR desc
    prodItems.slice().sort(function(a,b){ return b.mermaR-a.mermaR; }).forEach(function(o){
      var pname = o.p.replace('BQT ','');
      projRows += '<tr><td>'+pname+'</td>'
        +'<td class="'+(o.mermaU>0?'red':'')+'">'+fmt(o.mermaU)+'</td>'
        +'<td class="'+(o.mermaR>0?'red':'')+'">$'+fmt(o.mermaR)+'</td></tr>';
    });
    avgRows  += '<tr class="total"><td>Total</td><td>$'+fmt(totVenta)+'</td><td>'+fmt(totUnid)+'</td></tr>';
    projRows += '<tr class="total"><td>Total</td><td class="red">'+fmt(totMermaU)+'</td><td class="red">$'+fmt(totMermaR)+'</td></tr>';
  }

  document.getElementById('tHistT').innerHTML  = histRows;
  document.getElementById('tMermaT').innerHTML = mermaRows;
  document.getElementById('tAvgT').innerHTML   = avgRows;
  document.getElementById('tProjT').innerHTML  = projRows;
}

// ─── IMPRIMIR ───────────────────────────────────────────────────────────────
// Construye un HTML completo en memoria y lo abre en una pestaña nueva.
// onafterprint cierra la pestaña para que no quede about:blank.
// No hay footer con fecha — la fecha solo está en el encabezado.
// ────────────────────────────────────────────────────────────────────────────
function imprimirReporte(){
  var tienda  = document.getElementById('hdrTienda').textContent;
  var semana  = document.getElementById('hdrSem').textContent;
  var fecha   = document.getElementById('hdrFecha').textContent;
  var projTit = document.getElementById('projTitle').textContent;
  var tHist   = document.getElementById('tHist').innerHTML;
  var tMerma  = document.getElementById('tMerma').innerHTML;
  var tAvg    = document.getElementById('tAvg').innerHTML;
  var tProj   = document.getElementById('tProj').innerHTML;

  var css = [
    '*{box-sizing:border-box;margin:0;padding:0}',
    'body{background:#fff;font-family:Arial,sans-serif;font-size:12px;color:#111;padding:16px}',
    '.hdr{display:flex;align-items:center;justify-content:space-between;',
          'padding-bottom:8px;border-bottom:2px solid #0071ce;margin-bottom:8px}',
    '.logo{display:flex;align-items:center;gap:5px}',
    '.wm-text{font-size:1.3rem;font-weight:700;color:#0071ce}',
    '.wm-spark{color:#ffc220;font-size:1.4rem}',
    '.hdr-info{text-align:right;font-size:.72rem;color:#333;line-height:1.7}',
    '.sub{font-size:.78rem;color:#333;padding:4px 0 10px;',
         'border-bottom:1px solid #ddd;margin-bottom:12px}',
    '.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}',
    '.box{border:1px solid #bbb;border-radius:4px;overflow:hidden;break-inside:avoid}',
    '.box-hdr{background:#f0f0f0;border-bottom:1px solid #bbb;padding:4px 10px;',
             'text-align:center;font-size:.74rem;font-weight:700}',
    'table{width:100%;border-collapse:collapse}',
    'th{padding:3px 10px;font-size:.67rem;font-weight:700;color:#333;',
       'border-bottom:1px solid #ccc;text-align:right;background:#fafafa}',
    'th:first-child{text-align:left}',
    'td{padding:2px 10px;font-size:.72rem;text-align:right;color:#222;white-space:nowrap}',
    'td:first-child{text-align:left;color:#111}',
    'tr.total td{font-weight:700;border-top:1px solid #ddd;background:#f5f5f5}',
    '.red{color:#c00;font-weight:600}.bold{font-weight:700}',
    '@page{margin:10mm}',
    '@media print{body{padding:0}.aviso{display:none!important}}',
    '.aviso{background:#fffbe6;border:1px solid #f0b429;border-radius:6px;',
           'padding:8px 14px;margin-bottom:12px;font-size:.75rem;color:#7a5c00;',
           'display:flex;align-items:center;gap:8px}',
    '.aviso b{font-size:.8rem}'
  ].join('');

  var html = '<!DOCTYPE html><html lang="es"><head>'
    + '<meta charset="UTF-8">'
    + '<title>Walmart CFBC \u00b7 Sem '+semana+' \u00b7 '+tienda+'</title>'
    + '<style>'+css+'</style>'
    + '</head><body>'
    + '<div class="aviso">⚠️ &nbsp;<span>Antes de imprimir, en <b>Más opciones</b> desactiva '
    +   '<b>"Encabezados y pies de página"</b> para un reporte limpio.</span></div>'
    + '<div class="hdr">'
    +   '<div class="logo">'
    +     '<span class="wm-text">Walmart</span>'
    +     '<img src="data:image/png;base64,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AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA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" style="height:20px;width:20px;object-fit:contain">'
    +   '</div>'
    +   '<div class="hdr-info">'
    +     '<div>'+fecha+'</div>'
    +     '<div>Semana &nbsp;<strong>'+semana+'</strong></div>'
    +   '</div>'
    + '</div>'
    + '<div class="sub">Nombre de Tienda &nbsp;<strong>'+tienda+'</strong></div>'
    + '<div class="grid">'
    +   '<div class="box"><div class="box-hdr">Ventas Hist\u00f3ricas</div>'
    +     '<table><thead><tr><th>Producto</th><th>12 Semanas</th><th>3 Semanas</th></tr></thead>'
    +     '<tbody>'+tHist+'</tbody></table></div>'
    +   '<div class="box"><div class="box-hdr">\u00cdndice de Merma por Art\u00edculo \u00daltimas 3 Semanas</div>'
    +     '<table><thead><tr><th>Producto</th><th>Embarque</th><th>Merma</th><th>Merma %</th></tr></thead>'
    +     '<tbody>'+tMerma+'</tbody></table></div>'
    +   '<div class="box"><div class="box-hdr">Venta Promedio Semanal</div>'
    +     '<table><thead><tr><th>Producto</th><th>Promedio</th></tr></thead>'
    +     '<tbody>'+tAvg+'</tbody></table></div>'
    +   '<div class="box"><div class="box-hdr">'+projTit+'</div>'
    +     '<table><thead><tr><th>Producto</th><th>Proyecci\u00f3n</th></tr></thead>'
    +     '<tbody>'+tProj+'</tbody></table></div>'
    + '</div>'
    // ── SIN footer de fecha ──
    + '<script>'
    + 'window.onload=function(){'
    +   'window.onafterprint=function(){window.close();};'
    +   'setTimeout(function(){window.print();},300);'
    + '};'
    + '<\/script>'
    + '</body></html>';

  // Usar Blob + URL para evitar about:blank en la pestaña
  var blob = new Blob([html], {type:'text/html;charset=utf-8'});
  var url  = URL.createObjectURL(blob);
  var win  = window.open(url, '_blank');
  // Liberar URL de objeto cuando la ventana cargue
  if(win){ win.addEventListener('load', function(){ URL.revokeObjectURL(url); }); }
}

window.addEventListener('load', init);

(function fixParent(){
  try {
    var p = window.parent.document;
    var style = p.createElement('style');
    style.textContent = [
      '.main .block-container{padding:0!important;margin:0!important}',
      '.main{padding:0!important}',
      '[data-testid="stAppViewContainer"]{padding:0!important}',
      '[data-testid="stVerticalBlock"]{gap:0!important}',
      'header,[data-testid="stToolbar"],[data-testid="stDecoration"]{display:none!important}',
      'iframe{margin:0!important}',
      'section[data-testid="stMain"]{padding:0!important}',
      '.stMainBlockContainer{padding:0!important}',
      '[data-testid="manage-app-button"]{display:none!important}',
      '.stDeployButton{display:none!important}',
      '#MainMenu{display:none!important}',
      'button[kind="header"]{display:none!important}',
      '.viewerBadge_container__r5tak{display:none!important}',
      '.styles_viewerBadge__CvC9N{display:none!important}',
      'a[href="https://streamlit.io"]{display:none!important}',
      '#stDecoration{display:none!important}',
      'footer{display:none!important}',
      '[data-testid="stBottom"]{display:none!important}',
    ].join('');
    p.head.appendChild(style);
  } catch(e){}
  try {
    var frames = window.parent.document.querySelectorAll('iframe');
    frames.forEach(function(f){
      f.style.height = window.parent.innerHeight + 'px';
      f.style.width  = '100%';
    });
  } catch(e){}

  // Auto-resize iframe to fit full content height after render
  function resizeIframe(){
    try {
      var h = document.documentElement.scrollHeight || document.body.scrollHeight;
      var frames = window.parent.document.querySelectorAll('iframe');
      frames.forEach(function(f){ f.style.height = (h + 20) + 'px'; });
    } catch(e){}
  }
  // Resize on load and after any render
  window.addEventListener('load', function(){ setTimeout(resizeIframe, 300); });
  var _origRender = window.render;
  // Patch render and renderTienda to resize after draw
  var _patchResize = function(fn){
    return function(){ fn.apply(this,arguments); setTimeout(resizeIframe,100); };
  };
  window.addEventListener('load', function(){
    if(typeof render!=='undefined') render = _patchResize(render);
    if(typeof renderTienda!=='undefined') renderTienda = _patchResize(renderTienda);
  });
})();
</script>
</body>
</html>"""

def build_html():
    data_json = base64.b64encode(
        json.dumps(DATA, ensure_ascii=True, default=str).encode('utf-8')
    ).decode('ascii')
    return HTML.replace('__DATA_JSON__', data_json)

components.html(build_html(), height=1400, scrolling=True)
