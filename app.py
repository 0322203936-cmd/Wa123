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
    for r in records:
        totales_tienda[r['tienda']]['embarque_u'] += r['embarque_u']
        totales_tienda[r['tienda']]['venta_cfbc'] += r['venta_cfbc']
        totales_tienda[r['tienda']]['merma_u']    += r['merma_u']
        totales_tienda[r['tienda']]['retail_vc']  += r['retail_vc']
        raw_semana[r['tienda']][r['semana']]['embarque_u'] += r['embarque_u']
        raw_semana[r['tienda']][r['semana']]['venta_cfbc'] += r['venta_cfbc']
        raw_semana[r['tienda']][r['semana']]['merma_u']    += r['merma_u']
        raw_semana[r['tienda']][r['semana']]['retail_vc']  += r['retail_vc']

    return {
        'semanas':          semanas,
        'tiendas':          tiendas,
        'productos':        productos,
        'fecha_por_semana': fecha_por_semana,
        'data':             {t: {str(s): v for s, v in sv2.items()} for t, sv2 in result.items()},
        'totales_tienda':   {t: dict(v) for t, v in totales_tienda.items()},
        'raw_semana':       {t: {str(s): dict(v) for s, v in sv.items()} for t, sv in raw_semana.items()},
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
.chip.on{background:#0071ce;color:#fff;border-color:#0071ce}
.grid{display:grid;grid-template-columns:1fr 1fr;padding:8px 16px;gap:8px;width:100%;box-sizing:border-box}
.box{border:1px solid #bbb;border-radius:4px;overflow:hidden}
.box-hdr{background:#f0f0f0;border-bottom:1px solid #bbb;padding:4px 10px;text-align:center;font-size:.74rem;font-weight:700;color:#111}
table.t{width:100%;border-collapse:collapse;font-size:.71rem}
table.t th{padding:3px 8px;font-size:.66rem;font-weight:700;color:#333;border-bottom:1px solid #ccc;text-align:right;background:#fafafa}
table.t th:first-child{text-align:left}
table.t td{padding:2px 8px;font-size:.71rem;text-align:right;color:#222}
table.t td:first-child{text-align:left;color:#111}
table.t tr.total td{font-weight:700;border-top:1px solid #ddd;background:#f5f5f5}
.red{color:#c00;font-weight:600}
.bold{font-weight:700}
#viewTienda{overflow:visible}
@media(max-width:1200px){
  .grid{grid-template-columns:1fr;gap:8px}
  .box{overflow-y:auto;max-height:500px}
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
      <div class="wm-spark">&#10022;</div>
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
    <select id="semSel" onchange="onSem(this.value)"></select>
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
      <div class="box-hdr">Venta Promedio Semanal</div>
      <table class="t"><thead><tr><th>Tienda</th><th></th></tr></thead>
      <tbody id="tAvgT"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr">Comparacion Ultimas 3 Semanas</div>
      <table class="t"><thead><tr><th>Tienda</th><th></th></tr></thead>
      <tbody id="tProjT"></tbody></table>
    </div>
  </div>
</div>

<script>
var DATA = JSON.parse(atob('__DATA_JSON__'));
var state = { semana: null, tienda: null, view: 'producto' };
var DIAS  = ['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
var MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];

function fmt(v){ return Math.round(v||0).toLocaleString('es-MX'); }

function init(){
  window.onerror = function(m,s,l){
    document.body.innerHTML='<p style="padding:20px;color:red">Error: '+m+' (línea '+l+')</p>';
  };
  var sel = document.getElementById('semSel');
  // Opción global al inicio
  var optAll = document.createElement('option');
  optAll.value = 'all';
  optAll.textContent = '— Todas las semanas —';
  sel.appendChild(optAll);
  DATA.semanas.forEach(function(s){
    var opt = document.createElement('option');
    opt.value = s;
    var yr = Math.floor(s/100), wk = s%100;
    opt.textContent = yr+' · Semana '+String(wk).padStart(2,'0');
    if(yr < 2000){ opt.textContent = 'Semana '+String(s).padStart(2,'0'); }
    sel.appendChild(opt);
  });
  state.semana = DATA.semanas[DATA.semanas.length-1];
  sel.value    = state.semana;
  state.tienda = DATA.tiendas[0];
  buildChips(); updateHeader(); render();
  document.getElementById('loader').style.display = 'none';
  document.getElementById('app').style.display    = 'block';
}

function buildChips(){
  document.getElementById('chips').innerHTML = DATA.tiendas.map(function(t){
    var n = t.replace('SC ','');
    return '<button class="chip'+(t===state.tienda?' on':'')+'" onclick="selTienda(\''+t+'\')">'+n+'</button>';
  }).join('');
}

function selTienda(t){ state.tienda=t; buildChips(); updateHeader(); if(state.view==='producto') render(); else renderTienda(); }
function onSem(v){ state.semana = (v==='all') ? 'all' : parseInt(v); updateHeader(); if(state.view==='producto') render(); else renderTienda(); }

function updateHeader(){
  if(state.semana === 'all'){
    var s0 = DATA.semanas[0], sN = DATA.semanas[DATA.semanas.length-1];
    var f0 = (DATA.fecha_por_semana && (DATA.fecha_por_semana[String(s0)] || DATA.fecha_por_semana[s0])) || '—';
    var fN = (DATA.fecha_por_semana && (DATA.fecha_por_semana[String(sN)] || DATA.fecha_por_semana[sN])) || '—';
    document.getElementById('hdrFecha').textContent  = f0 + ' — ' + fN;
    document.getElementById('hdrSem').textContent    = 'Global';
    document.getElementById('hdrTienda').textContent = state.tienda;
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
  document.getElementById('hdrTienda').textContent  = state.tienda;
  document.getElementById('projTitle').textContent  = 'Proyección Semana '+(semNum+1);
}

function getD(){
  var key = state.semana === 'all' ? String(DATA.semanas[DATA.semanas.length-1]) : String(state.semana);
  return (DATA.data[state.tienda]&&DATA.data[state.tienda][key]) || {};
}

function render(){
  var d = getD(), prods = DATA.productos;
  var totV12=0,totV3=0,totEmb=0,totM3=0,totAvg=0,totProj=0,totEmb2=0;
  var histRows='',mermaRows='',avgRows='',projRows='';
  prods.forEach(function(p){
    var v = d[p]||{v12:0,v3:0,emb:0,m3:0,avg:0,proj:0,pct_merma:0};
    var name = p.replace('BQT ','');
    totV12+=v.v12; totV3+=v.v3; totEmb+=v.emb; totM3+=v.m3; totAvg+=v.avg; totProj+=v.proj; totEmb2+=v.emb;
    histRows  += '<tr><td>'+name+'</td><td>'+fmt(v.v12)+'</td><td>'+fmt(v.v3)+'</td></tr>';
    mermaRows += '<tr><td>'+name+'</td><td>'+fmt(v.emb)+'</td><td class="'+(v.m3>0?'red':'')+'">'+fmt(v.m3)+'</td><td class="'+(v.pct_merma>0?'red':'')+'">'+v.pct_merma+'%</td></tr>';
    avgRows   += '<tr><td>'+name+'</td><td>'+Math.round(v.avg)+'</td></tr>';
    projRows  += '<tr><td>'+name+'</td><td class="bold">'+fmt(v.proj)+'</td></tr>';
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
  
  if(v==='tienda') renderTienda();
  else render();
}

function renderTienda(){
  var tiendas = DATA.tiendas;
  var key = String(state.semana);
  var isAll = (state.semana === 'all');

  // ── Obtener totales por tienda según si es global o semana específica ──
  var totEmb=0, totCfbc=0, totMerma=0, totRetail=0;
  var tiendaData = [];

  tiendas.forEach(function(tienda){
    var emb=0, cfbc=0, merma=0, retail=0;
    if(isAll){
      // Usar totales globales precalculados en Python
      var tot = (DATA.totales_tienda && DATA.totales_tienda[tienda]) || {};
      emb    = tot.embarque_u || 0;
      cfbc   = tot.venta_cfbc || 0;
      merma  = tot.merma_u    || 0;
      retail = tot.retail_vc  || 0;
    } else {
      // Usar raw de la semana seleccionada
      var raw = (DATA.raw_semana && DATA.raw_semana[tienda] && DATA.raw_semana[tienda][key]) || {};
      emb    = raw.embarque_u || 0;
      cfbc   = raw.venta_cfbc || 0;
      merma  = raw.merma_u    || 0;
      retail = raw.retail_vc  || 0;
    }
    totEmb+=emb; totCfbc+=cfbc; totMerma+=merma; totRetail+=retail;
    tiendaData.push({tienda:tienda, emb:emb, cfbc:cfbc, merma:merma, retail:retail});
  });

  // ── TOP VENTA: UNIDADES = Cntd Embarque | VENTA = Venta CFBC ──
  var histRows='';
  tiendaData.forEach(function(t){
    var pct = totCfbc > 0 ? Math.round(t.cfbc/totCfbc*100) : 0;
    histRows += '<tr><td>'+t.tienda+'</td><td>'+fmt(t.emb)+'</td><td>$'+fmt(t.cfbc)+'</td><td>'+pct+'%</td></tr>';
  });
  histRows += '<tr class="total"><td>Total</td><td>'+fmt(totEmb)+'</td><td>$'+fmt(totCfbc)+'</td><td>100%</td></tr>';

  // ── TOP MERMA: UNIDADES = Cant VC Tienda | CANTIDAD = Retail VC Tienda ──
  var mermaRows='';
  tiendaData.forEach(function(t){
    var pct_retail = totRetail > 0 ? Math.round(t.retail/totRetail*100) : 0;
    mermaRows += '<tr><td>'+t.tienda+'</td><td class="'+(t.merma>0?'red':'')+'">'+fmt(t.merma)+'</td><td>$</td><td class="'+(t.retail>0?'red':'')+'">'+fmt(t.retail)+'</td><td class="'+(pct_retail>0?'red':'')+'">'+pct_retail+'%</td></tr>';
  });
  mermaRows += '<tr class="total"><td>Total</td><td class="red">'+fmt(totMerma)+'</td><td>$</td><td class="red">'+fmt(totRetail)+'</td><td class="red">100%</td></tr>';
  
  // ── Venta Promedio y Comparación: usar semana actual (o última si global) ──
  var semKeyProd = isAll ? String(DATA.semanas[DATA.semanas.length-1]) : key;
  var prods = DATA.productos;
  var totAvg=0, totProj=0;
  var tiendaDataSem = [];
  tiendas.forEach(function(tienda){
    var v3t=0, avg3t=0, proj3t=0;
    prods.forEach(function(p){
      var d = (DATA.data[tienda]&&DATA.data[tienda][semKeyProd]&&DATA.data[tienda][semKeyProd][p]) || {v3:0,avg:0,proj:0};
      v3t+=d.v3||0; avg3t+=d.avg||0; proj3t+=d.proj||0;
    });
    totAvg+=avg3t; totProj+=proj3t;
    tiendaDataSem.push({tienda:tienda, v3:v3t, avg:avg3t, proj:proj3t});
  });
  
  // Generar filas para Venta Promedio (datos de la semana actual)
  var avgRows='';
  tiendaDataSem.forEach(function(t){
    var avg_semanal = t.v3 / 3;
    avgRows   += '<tr><td>'+t.tienda+'</td><td>'+Math.round(avg_semanal)+'</td></tr>';
  });
  avgRows   += '<tr class="total"><td>Total</td><td>'+Math.round(totAvg/tiendas.length)+'</td></tr>';
  
  // Generar filas para Comparación (datos de la semana actual)
  var projRows='';
  tiendaDataSem.forEach(function(t){
    projRows  += '<tr><td>'+t.tienda+'</td><td class="bold">'+fmt(t.proj)+'</td></tr>';
  });
  projRows  += '<tr class="total"><td>Total</td><td>'+fmt(totProj)+'</td></tr>';
  
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
    +     '<span class="wm-spark">&#10022;</span>'
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
})();
</script>
</body>
</html>"""

def build_html():
    data_json = base64.b64encode(
        json.dumps(DATA, ensure_ascii=True, default=str).encode('utf-8')
    ).decode('ascii')
    return HTML.replace('__DATA_JSON__', data_json)

components.html(build_html(), height=980, scrolling=False)
