"""
Walmex Dashboard — CFBC (con vista GASTO)
Reporte ejecutivo estilo WalmartMX + vista de gastos por ruta
"""
import hashlib
import json
import base64
import openpyxl
import pickle
from collections import defaultdict
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components

# Caché en disco: mismo Excel = carga al instante (al abrir, al cambiar código o restablecer)
_CACHE_DIR = Path(__file__).resolve().parent / ".wa123_cache"

def _excel_cache_key():
    paths = ["Analisis_Walmart.xlsx", "Analisis Walmart.xlsx"]
    excel_path = next((p for p in paths if Path(p).exists()), None)
    if not excel_path:
        return None, None, None
    p = Path(excel_path).resolve()
    mtime = p.stat().st_mtime
    key = hashlib.md5(f"{p}{mtime}".encode()).hexdigest()[:16]
    return str(p), mtime, key

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
    excel_path, _, cache_key = _excel_cache_key()
    if not excel_path:
        raise FileNotFoundError("No se encontró Analisis_Walmart.xlsx. Súbelo al repo de GitHub.")
    # Caché en disco: si el Excel no cambió, cargar al instante
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data_cache_file = _CACHE_DIR / f"data_{cache_key}.pkl"
    # if data_cache_file.exists():
    #     with open(data_cache_file, "rb") as f:
    #         return pickle.load(f)
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

    idx_venta_wmx = None
    for _n in ['Venta WMX / Precio Costo (Vendido)', 'Venta WMX/Precio Costo (Vendido)',
               'Venta WMX', 'WMX']:
        try: idx_venta_wmx = col(_n); break
        except: pass

    idx_retail_vc = None
    for _n in ['Suma de Retail VC Tienda', 'Retail VC Tienda',
               'Suma Retail VC Tienda', 'Retail VC', 'Suma de Retail VC',
               'Suma de Retail VC Tienda ']:  # trailing space variant
        try: idx_retail_vc = col(_n); break
        except: pass

    # Columna de inventario actual
    idx_inventario = None
    for _n in ['Cantidad Actual en Existentes de la tienda', 'Cantidad Actual en Existentes',
               'Cantidad Actual', 'Inventario Actual', 'Existentes']:
        try: idx_inventario = col(_n); break
        except: pass

    # Advertir si columnas clave no se encontraron
    if idx_retail_vc is None:
        import streamlit as _st
        _st.warning(
            f"⚠️ No se encontró columna 'Retail VC Tienda'. "
            f"Columnas disponibles: {[h for h in headers if h and 'VC' in h or 'Retail' in h or 'retail' in h.lower() if h]}\n"
            f"Todos los encabezados: {[h for h in headers if h]}"
        )
    
    if idx_inventario is None:
        import streamlit as _st
        _st.warning(
            f"⚠️ No se encontró columna 'Cantidad Actual en Existentes de la tienda'. "
            f"Inventario no estará disponible. Columnas disponibles: {[h for h in headers if h]}"
        )

    # Columnas de días de la semana (opcionales)
    _dias = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']
    idx_ctd   = {}
    idx_vtas  = {}
    for d in _dias:
        try: idx_ctd[d] = col(f'Ctd {d}')
        except: 
            try: idx_ctd[d] = col(f'Cnt {d}')
            except: idx_ctd[d] = None
        try: idx_vtas[d] = col(f'Ventas {d}')
        except: idx_vtas[d] = None

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

        records.append({
            'producto':   producto,
            'tienda':     tienda,
            '_semana_num': semana_num,
            '_anio':       anio,
            'semana':     (anio * 100 + semana_num) if anio else semana_num,
            'fecha':      fecha,
            'ventas_u':   sv(row[idx_ventas]),
            'embarque_u': sv(row[idx_embarque]),
            'merma_u':    sv(row[idx_merma_vc]),
            'venta_cfbc': sv(row[idx_venta_cfbc]) if idx_venta_cfbc is not None else 0,
            'venta_wmx':  sv(row[idx_venta_wmx]) if idx_venta_wmx is not None else 0,
            'retail_vc':  sv(row[idx_retail_vc]) if idx_retail_vc is not None else 0,
            'inventario': sv(row[idx_inventario]) if idx_inventario is not None else 0,
            **{f'ctd_{d.lower()}':  sv(row[idx_ctd[d]])  if idx_ctd[d]  is not None else 0 for d in _dias},
            **{f'vtas_{d.lower()}': sv(row[idx_vtas[d]]) if idx_vtas[d] is not None else 0 for d in _dias},
        })

    # Inferir año para filas sin fecha usando el año más frecuente del mismo número de semana
    from collections import Counter as _Counter
    _sem_anio_votes = _Counter()
    for r in records:
        if r['_anio']:
            _sem_anio_votes[(r['_semana_num'], r['_anio'])] += 1
    _sem_to_anio = {}
    for (wk, yr) in _sem_anio_votes:
        if wk not in _sem_to_anio or _sem_anio_votes[(wk, yr)] > _sem_anio_votes[(_sem_to_anio[wk], yr)]:
            _sem_to_anio[wk] = yr
    for r in records:
        if not r['_anio']:
            yr_inf = _sem_to_anio.get(r['_semana_num'])
            if yr_inf:
                r['semana'] = yr_inf * 100 + r['_semana_num']

    semanas   = sorted(set(r['semana'] for r in records))
    tiendas   = sorted(set(r['tienda']  for r in records))
    productos = sorted(set(r['producto'] for r in records))

    by_stp = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float))))
    for r in records:
        by_stp[r['semana']][r['tienda']][r['producto']]['ventas_u']   += r['ventas_u']
        by_stp[r['semana']][r['tienda']][r['producto']]['embarque_u'] += r['embarque_u']
        by_stp[r['semana']][r['tienda']][r['producto']]['merma_u']    += r['merma_u']
        by_stp[r['semana']][r['tienda']][r['producto']]['venta_cfbc'] += r['venta_cfbc']
        by_stp[r['semana']][r['tienda']][r['producto']]['venta_wmx']  += r['venta_wmx']
        by_stp[r['semana']][r['tienda']][r['producto']]['retail_vc']  += r['retail_vc']
        for d in ['dom','lun','mar','mie','jue','vie','sab']:
            by_stp[r['semana']][r['tienda']][r['producto']][f'ctd_{d}']  += r.get(f'ctd_{d}', 0)
            by_stp[r['semana']][r['tienda']][r['producto']][f'vtas_{d}'] += r.get(f'vtas_{d}', 0)
        by_stp[r['semana']][r['tienda']][r['producto']]['inventario'] += r['inventario']

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
                avg  = v3 / 3  # Promedio = Ventas 3 semanas / 3
                
                # Proyección = Venta Promedio / (1 - Índice Merma %)
                merma_ratio = m3 / emb3 if emb3 > 0 else 0  # Ratio de merma como decimal
                proj = avg / (1 - merma_ratio) if merma_ratio < 1 else avg  # Evitar división por cero
                
                prod_data[p] = {
                    'v12': round(v12), 'v3': round(v3),
                    'n12': min(s % 100 if s > 9999 else s, 12),
                    'emb': round(emb3), 'm3': round(m3),
                    'avg': round(avg, 1), 'proj': round(proj),
                    'pct_merma': round(m3/emb3*100) if emb3 > 0 else 0,
                    'cfbc': round(cfbc3), 'retail': round(retail3),
                    'wmx': round(sum(by_stp[sem][t][p].get('venta_wmx', 0) for sem in last3))
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
        totales_tienda[r['tienda']]['venta_wmx']  += r['venta_wmx']
        totales_tienda[r['tienda']]['merma_u']    += r['merma_u']
        totales_tienda[r['tienda']]['retail_vc']  += r['retail_vc']
        totales_tienda[r['tienda']]['inventario'] += r['inventario']
        raw_semana[r['semana']][r['tienda']]['ventas_u']   += r['ventas_u']
        raw_semana[r['semana']][r['tienda']]['embarque_u'] += r['embarque_u']
        raw_semana[r['semana']][r['tienda']]['venta_cfbc'] += r['venta_cfbc']
        raw_semana[r['semana']][r['tienda']]['venta_wmx']  += r['venta_wmx']
        raw_semana[r['semana']][r['tienda']]['merma_u']    += r['merma_u']
        raw_semana[r['semana']][r['tienda']]['retail_vc']  += r['retail_vc']
        totales_prod_tienda[r['semana']][r['tienda']][r['producto']]['ventas_u']   += r['ventas_u']
        totales_prod_tienda[r['semana']][r['tienda']][r['producto']]['venta_cfbc'] += r['venta_cfbc']
        totales_prod_tienda[r['semana']][r['tienda']][r['producto']]['venta_wmx']  += r['venta_wmx']
        totales_prod_tienda[r['semana']][r['tienda']][r['producto']]['embarque_u'] += r['embarque_u']
        totales_prod_tienda[r['semana']][r['tienda']][r['producto']]['merma_u']    += r['merma_u']
        totales_prod_tienda[r['semana']][r['tienda']][r['producto']]['retail_vc']  += r['retail_vc']
        for d in ['dom','lun','mar','mie','jue','vie','sab']:
            totales_prod_tienda[r['semana']][r['tienda']][r['producto']][f'ctd_{d}']  += r.get(f'ctd_{d}', 0)
            totales_prod_tienda[r['semana']][r['tienda']][r['producto']][f'vtas_{d}'] += r.get(f'vtas_{d}', 0)

    # ==== MAPEOS PARA VISTA GASTO ====
    # Mapeo: Producto → Gasto
    PRODUCTO_GASTO = {
        'BQT ALSTROEMERI 8T': 15.00,
        'BQT GIRASOL 6T': 10.00,
        'BQT LILI ASIATIC 6T': 15.00,
        'BQT MINI CLAVEL 8T': 15.00,
        'BQT MIXTO 12T': 23.00,
        'BQT MIXTO 15T': 23.00,
        'BQT MIXTO 18 T': 10.00,
        'BQT MIXTO 9T': 15.00,
        'BQT ROSAS 12T': 20.00,
        'BQT ROSAS 12T BAJA': 20.00,
        'BQT ROSAS 6T': 15.00,
        'BQT SNAPDRAGON 8T': 10.00,
        'BQT ROSAS 6T BAJA': 10.00
    }
    
    # Mapeo: Tienda → Ruta
    TIENDA_RUTA = {
        'SC LOMAS DE SANTA FE': 'Rutas Playas',
        'SC ENSENADA CENTRO': 'ENS',
        'SC ENSENADA': 'ENS',
        'SC ROSARITO': 'Rutas Playas',
        'SC PLAYAS DE TIJUANA': 'Rutas Playas',
        'SC MACROPLAZA INSURGENTES': 'Ruta 2000',
        'SC DIAZ ORDAZ': 'Ruta 2000',
        'SC TIJUANA HIPODROMO': 'Ruta 2000',
        'SC PACIFICO': 'Rutas Playas',
        'SC TIJUANA 2000': 'Ruta 2000',
        'SC MEXICALI NOVENA': 'MXL 2',
        'SC PLAZA SAN PEDRO': 'MXL 2',
        'SC GALERIAS DEL VALLE': 'MXL 1',
        'SC MEXICALI': 'MXL 1',
        'SC TECATE GARITA': 'MXL 1',
        'SC NUEVO MEXICALI': 'MXL 2'
    }

    # Procesar datos para vista GASTO: agrupar por ruta/semana/producto
    gasto_data = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for r in records:
        ruta = TIENDA_RUTA.get(r['tienda'])
        gasto = PRODUCTO_GASTO.get(r['producto'], 0)
        if ruta and gasto > 0:
            # Agrupar unidades EMBARCADAS por ruta/semana/producto
            gasto_data[ruta][r['semana']][r['producto']] += r['embarque_u']
    
    # with open(data_cache_file, "wb") as f:
    #     pickle.dump({
    #         'semanas': semanas, 'tiendas': tiendas, 'productos': productos,
    #         'data': result, 'fecha_por_semana': fecha_por_semana,
    #         'totales_tienda': dict(totales_tienda),
    #         'raw_semana': {k: dict(v) for k,v in raw_semana.items()},
    #         'totales_prod_tienda': {k: {t: dict(p) for t,p in v.items()} for k,v in totales_prod_tienda.items()},
    #         'producto_gasto': PRODUCTO_GASTO,
    #         'tienda_ruta': TIENDA_RUTA,
    #         'gasto_data': {k: {s: dict(p) for s,p in v.items()} for k,v in gasto_data.items()}
    #     }, f, protocol=pickle.HIGHEST_PROTOCOL)
    
    return {
        'semanas': semanas, 'tiendas': tiendas, 'productos': productos,
        'data': result, 'fecha_por_semana': fecha_por_semana,
        'totales_tienda': dict(totales_tienda),
        'raw_semana': {k: dict(v) for k,v in raw_semana.items()},
        'totales_prod_tienda': {k: {t: dict(p) for t,p in v.items()} for k,v in totales_prod_tienda.items()},
        'producto_gasto': PRODUCTO_GASTO,
        'tienda_ruta': TIENDA_RUTA,
        'gasto_data': {k: {s: dict(p) for s,p in v.items()} for k,v in gasto_data.items()}
    }

DATA = cargar_datos()

HTML = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Walmex CFBC</title>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0;padding:0;background:#fff;color:#111;font-size:14px}
#app{width:100%;height:100vh;display:flex;flex-direction:column;overflow:hidden}
.hdr{background:#0071ce;color:white;padding:8px 20px 12px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;flex-shrink:0}
.wm-logo{display:flex;align-items:center;gap:8px}
.wm-text{font-size:1.1rem;font-weight:700;letter-spacing:-.5px}
.wm-spark{font-size:1.4rem}
.hdr-info{display:flex;gap:20px;align-items:center;font-size:.72rem;margin-left:auto;font-weight:500}
.hdr-info>div{white-space:nowrap}
.hdr-info strong{font-weight:700}
.ctrl{display:flex;align-items:center;gap:8px;font-size:.72rem}
.ctrl label{font-weight:600;margin-right:3px}
.grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;padding:12px 20px;overflow-y:auto;flex:1}
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
#viewInventario table.t tr:hover td{background:#f0f7ff;cursor:pointer}
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
/* Estilos para vista GASTO */
#viewGasto table.t{font-size:.70rem}
#viewGasto table.t th{font-size:.65rem;padding:3px 8px;white-space:nowrap}
#viewGasto table.t td{padding:2px 8px}
#viewGasto .ruta-row td{background:#e8f4fd;font-weight:700;border-top:2px solid #0071ce;border-bottom:1px solid #bbb}
#viewGasto .unidad-row td{font-size:.68rem}
#viewGasto .unidad-row td:first-child{padding-left:24px;color:#555}
#viewGasto .grand-total td{background:#0071ce;color:white;font-weight:700;border-top:3px solid #004a8a}
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
      <div class="wm-spark">✦</div>
    </div>
    <div class="ctrl">
      <label>Semana:</label>
      <div style="position:relative;display:inline-block" id="semDropWrap">
        <button id="semDropBtn" onclick="toggleSemDrop()" style="border:1px solid #bbb;border-radius:4px;padding:3px 24px 3px 7px;font-size:.72rem;cursor:pointer;background:#fff;min-width:120px;text-align:left;position:relative">
          <span id="semDropLabel"></span>
          <span style="position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:.6rem">▼</span>
        </button>
        <div id="semDropMenu" style="display:none;position:absolute;top:100%;left:0;z-index:999;background:#fff;border:1px solid #bbb;border-radius:4px;box-shadow:0 3px 10px rgba(0,0,0,.15);min-width:200px;max-height:260px;overflow-y:auto;padding:4px 0"></div>
      </div>
    </div>
    <label>Tienda:</label>
    <div style="position:relative;display:inline-block" id="tiendaDropWrap">
      <button id="tiendaDropBtn" onclick="toggleTiendaDrop()" style="border:1px solid #bbb;border-radius:4px;padding:3px 24px 3px 7px;font-size:.72rem;cursor:pointer;background:#fff;min-width:160px;text-align:left;position:relative">
        <span id="tiendaDropLabel">— Seleccionar tiendas —</span>
        <span style="position:absolute;right:6px;top:50%;transform:translateY(-50%);font-size:.6rem">▼</span>
      </button>
      <div id="tiendaDropMenu" style="display:none;position:absolute;top:100%;left:0;z-index:999;background:#fff;border:1px solid #bbb;border-radius:4px;box-shadow:0 3px 10px rgba(0,0,0,.15);min-width:200px;max-height:260px;overflow-y:auto;padding:4px 0"></div>
    </div>
    <div style="margin-top:12px; display:flex; gap:8px;">
      <button onclick="setView('producto')" id="btnProd" style="padding:6px 12px; background:#0071ce; color:white; border:none; border-radius:4px; cursor:pointer; font-weight:600;">📊 Proyección</button>
      <button onclick="setView('tienda')" id="btnTiend" style="padding:6px 12px; background:#ccc; color:#333; border:none; border-radius:4px; cursor:pointer; font-weight:600;">🏪 Tienda</button>
      <button onclick="setView('inventario')" id="btnInv" style="padding:6px 12px; background:#ccc; color:#333; border:none; border-radius:4px; cursor:pointer; font-weight:600;">📦 Inventario Actual</button>
      <button onclick="setView('gasto')" id="btnGasto" style="padding:6px 12px; background:#ccc; color:#333; border:none; border-radius:4px; cursor:pointer; font-weight:600;">💰 GASTO</button>
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
      <table class="t"><thead><tr><th>Producto</th><th>Prom 12 Sem</th><th>Prom 3 Sem</th></tr></thead>
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
      <table class="t"><thead><tr><th>Tienda</th><th>UNIDADES</th><th>VENTA CFBC</th><th>VENTA WMX</th><th>%</th></tr></thead>
      <tbody id="tHistT"></tbody></table>
    </div>
    <div class="box">
      <div class="box-hdr">Top Merma</div>
      <table class="t"><thead><tr><th>Tienda</th><th>UNIDADES</th><th>$</th><th>CANTIDAD</th><th>%</th></tr></thead>
      <tbody id="tMermaT"></tbody></table>
    </div>
    <div class="box" id="boxAvgT" style="display:none">
      <div class="box-hdr" id="avgTTitle">Venta Promedio Semanal</div>
      <table class="t"><thead><tr><th>Producto</th><th>Venta</th><th>Unidades</th></tr></thead>
      <tbody id="tAvgT"></tbody></table>
    </div>
    <div class="box" id="boxProjT" style="display:none">
      <div class="box-hdr" id="projTTitle">Comparacion Ultimas 3 Semanas</div>
      <table class="t"><thead><tr><th>Merma Producto</th><th>Unidades</th><th>Cantidad</th></tr></thead>
      <tbody id="tProjT"></tbody></table>
    </div>
    <div class="box" id="boxDiasT" style="display:none; grid-column: 1 / -1; overflow-x: auto;">
      <div class="box-hdr">Ventas por Día</div>
      <table class="t" style="min-width: 800px;">
        <thead>
          <tr>
            <th>Producto</th>
            <th>Cnt Sab</th><th>Ctd Dom</th><th>Ctd Lun</th><th>Ctd Mar</th><th>Ctd Mie</th><th>Ctd Jue</th><th>Ctd Vie</th>
            <th>Ventas Sab</th><th>Ventas Dom</th><th>Ventas Lun</th><th>Ventas Mar</th><th>Ventas Mie</th><th>Ventas Jue</th><th>Ventas Vie</th>
          </tr>
        </thead>
        <tbody id="tDiasT"></tbody>
      </table>
    </div>
  </div>

  <!-- Vista Inventario Actual -->
  <div class="grid" id="viewInventario" style="display:none">
    <div class="box">
      <div class="box-hdr">Total Inventario por Tienda</div>
      <table class="t">
        <thead><tr><th>Tienda</th><th>Inventario Total</th></tr></thead>
        <tbody id="tInvTienda"></tbody>
      </table>
    </div>
    <div class="box">
      <div class="box-hdr" id="invProductoTitle">Total Inventario por Producto</div>
      <table class="t">
        <thead><tr><th>Producto</th><th>Inventario Total</th></tr></thead>
        <tbody id="tInvProducto"></tbody>
      </table>
    </div>
  </div>

  <!-- Vista GASTO -->
  <div id="viewGasto" style="display:none; padding:12px 20px; overflow-y:auto">
    <div class="box">
      <div class="box-hdr">Presupuesto por Ruta</div>
      <div style="overflow-x:auto">
        <table class="t" id="tGasto">
          <thead id="tGastoHead"></thead>
          <tbody id="tGastoBody"></tbody>
        </table>
      </div>
    </div>
  </div>
</div>

<script>
var DATA = JSON.parse(atob('__DATA_JSON__'));
var state = { semana: null, semanas_sel: null, tienda: null, view: 'producto', tiendaT: null, invMode: null, invSelected: null };
var DIAS  = ['domingo','lunes','martes','miércoles','jueves','viernes','sábado'];
var MESES = ['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];

function fmt(v){ return Math.round(v||0).toLocaleString('es-MX'); }

function toggleTodasSemanas(){
  var chks = document.querySelectorAll('#semDropMenu input[type=checkbox].sem-chk');
  var chkAll = document.getElementById('chkTodasSem');
  var allChecked = chkAll.checked;
  chks.forEach(function(c){
    c.checked = allChecked;
    var s = parseInt(c.value);
    var row = document.getElementById('sem-row-'+s);
    if(row) row.className = 'sem-item' + (allChecked ? ' on' : '');
  });
  onSemChk();
}

function syncChkTodas(){
  var chks = document.querySelectorAll('#semDropMenu input[type=checkbox].sem-chk');
  var chkAll = document.getElementById('chkTodasSem');
  if(!chkAll) return;
  var total = chks.length, checked = 0;
  chks.forEach(function(c){ if(c.checked) checked++; });
  chkAll.checked = (checked === total);
  chkAll.indeterminate = (checked > 0 && checked < total);
}

function init(){
  window.onerror = function(m,s,l){
    document.body.innerHTML='<p style="padding:20px;color:red">Error: '+m+' (línea '+l+')</p>';
  };
  var menu = document.getElementById('semDropMenu');

  // ── Opción "Seleccionar todas" ──
  var rowAll = document.createElement('label');
  rowAll.id = 'sem-row-all';
  rowAll.style.cssText = 'display:flex;align-items:center;gap:6px;padding:5px 10px;cursor:pointer;font-weight:700;border-bottom:1px solid #ddd;background:#f5f5f5;font-size:.72rem';
  var chkAll = document.createElement('input');
  chkAll.type = 'checkbox';
  chkAll.id = 'chkTodasSem';
  chkAll.onchange = function(){ toggleTodasSemanas(); };
  rowAll.appendChild(chkAll);
  rowAll.appendChild(document.createTextNode('Seleccionar todas'));
  menu.appendChild(rowAll);

  // Filtrar semanas sin año si ya existe la versión con año del mismo número de semana
  var semanasConAnio = DATA.semanas.filter(function(s){ return s > 9999; });
  var numsSemConAnio = semanasConAnio.map(function(s){ return s % 100; });
  var semanasRender  = DATA.semanas.filter(function(s){
    if(s > 9999) return true;                       // siempre incluir las que tienen año
    return numsSemConAnio.indexOf(s) === -1;         // bare solo si no hay duplicado con año
  });

  semanasRender.forEach(function(s){
    var yr = Math.floor(s/100), wk = s%100;
    var labelTxt = (yr >= 2000) ? yr+' · Semana '+String(wk).padStart(2,'0') : 'Semana '+String(s).padStart(2,'0');
    var isLast = (s === DATA.semanas[DATA.semanas.length-1]);
    var row = document.createElement('label');
    row.className = 'sem-item' + (isLast ? ' on' : '');
    row.id = 'sem-row-'+s;
    var chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.className = 'sem-chk';
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
    var wrapT = document.getElementById('tiendaDropWrap');
    if(wrapT && !wrapT.contains(e.target)) closeTiendaDrop();
  });
  
  // ── Crear dropdown de tiendas ──
  var menuT = document.getElementById('tiendaDropMenu');
  
  // Opción "Seleccionar todas" para tiendas
  var rowAllT = document.createElement('label');
  rowAllT.id = 'tienda-row-all';
  rowAllT.style.cssText = 'display:flex;align-items:center;gap:6px;padding:5px 10px;cursor:pointer;font-weight:700;border-bottom:1px solid #ddd;background:#f5f5f5;font-size:.72rem';
  var chkAllT = document.createElement('input');
  chkAllT.type = 'checkbox';
  chkAllT.id = 'chkTodasTienda';
  chkAllT.onchange = function(){ toggleTodasTiendas(); };
  rowAllT.appendChild(chkAllT);
  rowAllT.appendChild(document.createTextNode('Seleccionar todas'));
  menuT.appendChild(rowAllT);

  DATA.tiendas.forEach(function(t){
    var row = document.createElement('label');
    row.className = 'tienda-item';
    row.id = 'tienda-row-'+t;
    row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:5px 10px;cursor:pointer;font-size:.72rem';
    var chk = document.createElement('input');
    chk.type = 'checkbox';
    chk.className = 'tienda-chk';
    chk.value = t;
    chk.checked = true; // Por defecto todas seleccionadas
    chk.onchange = function(){ onTiendaChk(); };
    row.appendChild(chk);
    row.appendChild(document.createTextNode(t));
    menuT.appendChild(row);
  });

  // Inicializar última semana
  var last = DATA.semanas[DATA.semanas.length-1];
  state.semana = last;
  state.semanas_sel = [last];
  state.tiendas_sel = DATA.tiendas.slice(); // Todas las tiendas por defecto
  syncChkTodas();
  syncChkTodasTiendas();
  updateHdr();
  render();
  renderTienda();
  renderInventario();
  renderGasto();
  document.getElementById('loader').style.display='none';
  document.getElementById('app').style.display='flex';
}

function toggleTodasTiendas(){
  var chks = document.querySelectorAll('#tiendaDropMenu input[type=checkbox].tienda-chk');
  var chkAll = document.getElementById('chkTodasTienda');
  var allChecked = chkAll.checked;
  chks.forEach(function(c){
    c.checked = allChecked;
    var t = c.value;
    var row = document.getElementById('tienda-row-'+t);
    if(row) row.className = 'tienda-item' + (allChecked ? ' on' : '');
  });
  onTiendaChk();
}

function syncChkTodasTiendas(){
  var chks = document.querySelectorAll('#tiendaDropMenu input[type=checkbox].tienda-chk');
  var chkAll = document.getElementById('chkTodasTienda');
  if(!chkAll) return;
  var total = chks.length, checked = 0;
  chks.forEach(function(c){ if(c.checked) checked++; });
  chkAll.checked = (checked === total);
  chkAll.indeterminate = (checked > 0 && checked < total);
}

function toggleSemDrop(){
  var menu = document.getElementById('semDropMenu');
  var isVis = menu.style.display === 'block';
  menu.style.display = isVis ? 'none' : 'block';
}
function closeSemDrop(){
  document.getElementById('semDropMenu').style.display='none';
}

function toggleTiendaDrop(){
  var menu = document.getElementById('tiendaDropMenu');
  var isVis = menu.style.display === 'block';
  menu.style.display = isVis ? 'none' : 'block';
}
function closeTiendaDrop(){
  document.getElementById('tiendaDropMenu').style.display='none';
}

function onSemChk(){
  var chks = document.querySelectorAll('#semDropMenu input[type=checkbox].sem-chk:checked');
  var sels = Array.from(chks).map(function(c){ return parseInt(c.value); }).sort(function(a,b){ return a-b; });
  state.semanas_sel = sels.length > 0 ? sels : [DATA.semanas[DATA.semanas.length-1]];
  state.semana = state.semanas_sel[state.semanas_sel.length - 1];
  syncChkTodas();
  updateHdr();
  if(state.view === 'producto') render();
  if(state.view === 'tienda') renderTienda();
  if(state.view === 'inventario') renderInventario();
  if(state.view === 'gasto') renderGasto();
}

function onTiendaChk(){
  var chks = document.querySelectorAll('#tiendaDropMenu input[type=checkbox].tienda-chk:checked');
  var sels = Array.from(chks).map(function(c){ return c.value; });
  state.tiendas_sel = sels.length > 0 ? sels : DATA.tiendas.slice();
  syncChkTodasTiendas();
  updateHdr();
  if(state.view === 'producto') render();
  if(state.view === 'tienda') renderTienda();
  if(state.view === 'inventario') renderInventario();
  if(state.view === 'gasto') renderGasto();
}

function updateHdr(){
  var sems = state.semanas_sel;
  var isAll = (sems.length === DATA.semanas.length);
  if(!sems || sems.length === 0){
    document.getElementById('semDropLabel').textContent = 'Todas las Semanas';
  } else if(sems.length === 1){
    var s = sems[0];
    var yr = Math.floor(s/100), wk = s%100;
    var label = (yr >= 2000) ? yr+' · Semana '+String(wk).padStart(2,'0') : 'Semana '+String(s).padStart(2,'0');
    document.getElementById('semDropLabel').textContent = label;
  } else {
    document.getElementById('semDropLabel').textContent = sems.length + ' semanas';
  }
  if(!state.tiendas_sel || state.tiendas_sel.length === 0){
    document.getElementById('tiendaDropLabel').textContent = '— Sin tiendas —';
  } else if(state.tiendas_sel.length === DATA.tiendas.length){
    document.getElementById('tiendaDropLabel').textContent = 'Todas las Tiendas';
  } else if(state.tiendas_sel.length === 1){
    document.getElementById('tiendaDropLabel').textContent = state.tiendas_sel[0];
  } else {
    var tiendasStr = state.tiendas_sel.map(function(t){ return t.replace('SC ',''); }).join(', ');
    if(tiendasStr.length > 40) tiendasStr = state.tiendas_sel.length + ' tiendas';
    document.getElementById('tiendaDropLabel').textContent = tiendasStr;
  }
}

function getSemanasActivas(){
  if(!state.semanas_sel || state.semanas_sel.length === 0) return DATA.semanas;
  return state.semanas_sel;
}

function getTiendasActivas(){
  if(!state.tiendas_sel || state.tiendas_sel.length === 0) return DATA.tiendas;
  return state.tiendas_sel;
}

function getD(){
  var sems = getSemanasActivas();
  var tiendas = getTiendasActivas();
  var prods = DATA.productos;
  var merged = {};
  prods.forEach(function(p){
    var v12=0,v3=0,emb=0,m3=0,cfbc=0,retail=0,n12=0;
    tiendas.forEach(function(t){
      sems.forEach(function(s){
        var key = String(s);
        var d = (DATA.data[t]&&DATA.data[t][key]&&DATA.data[t][key][p]) || {};
        v12   += d.v12   || 0;
        v3    += d.v3    || 0;
        emb   += d.emb   || 0;
        m3    += d.m3    || 0;
        cfbc  += d.cfbc  || 0;
        retail+= d.retail|| 0;
        if((d.n12||0) > n12) n12 = d.n12;
      });
    });
    if(n12 < 1) n12 = 1;
    var avg = sems.length > 0 ? v3 / sems.length : 0;
    var merma_ratio = emb > 0 ? m3/emb : 0;
    var proj = merma_ratio < 1 ? avg/(1-merma_ratio) : avg;
    merged[p] = {
      v12: v12, v3: v3, n12: n12, emb: emb, m3: m3,
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
  prodArr.slice().sort(function(a,b){ return b.v.v12-a.v.v12; }).forEach(function(o){
    var name=o.p.replace('BQT ',''), v=o.v;
    var div12 = (v.n12 && v.n12 > 0) ? v.n12 : 1;
    avgRows += '<tr><td>'+name+'</td><td>'+parseFloat((v.v12/div12).toFixed(3))+'</td><td>'+Math.round(v.v3/3)+'</td></tr>';
  });
  prodArr.slice().sort(function(a,b){ return b.v.proj-a.v.proj; }).forEach(function(o){
    var name=o.p.replace('BQT ',''), v=o.v;
    projRows += '<tr><td>'+name+'</td><td class="bold">'+fmt(v.proj)+'</td></tr>';
  });

  histRows  += '<tr class="total"><td>Total</td><td>'+fmt(totV12)+'</td><td>'+fmt(totV3)+'</td></tr>';
  var pct_merma_total = totEmb2 > 0 ? Math.round(totM3/totEmb2*100) : 0;
  mermaRows += '<tr class="total"><td>Total</td><td>'+fmt(totEmb)+'</td><td class="red">'+fmt(totM3)+'</td><td class="red">'+pct_merma_total+'%</td></tr>';
  var totDiv12 = 1;
  prodArr.forEach(function(o){ if((o.v.n12||0) > totDiv12) totDiv12 = o.v.n12; });
  avgRows   += '<tr class="total"><td>Total</td><td>'+parseFloat((totV12/totDiv12).toFixed(3))+'</td><td>'+Math.round(totV3/3)+'</td></tr>';
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
  document.getElementById('btnInv').style.background = v==='inventario' ? '#0071ce' : '#ccc';
  document.getElementById('btnInv').style.color = v==='inventario' ? 'white' : '#333';
  document.getElementById('btnGasto').style.background = v==='gasto' ? '#0071ce' : '#ccc';
  document.getElementById('btnGasto').style.color = v==='gasto' ? 'white' : '#333';
  document.getElementById('viewProducto').style.display = v==='producto' ? 'grid' : 'none';
  document.getElementById('viewTienda').style.display = v==='tienda' ? 'grid' : 'none';
  document.getElementById('viewInventario').style.display = v==='inventario' ? 'grid' : 'none';
  document.getElementById('viewGasto').style.display = v==='gasto' ? 'block' : 'none';
  
  // Ocultar filtros de tienda en vista Tienda, Inventario y Gasto
  var tiendaDropWrap = document.getElementById('tiendaDropWrap');
  var tiendaLabel = Array.from(document.querySelectorAll('.ctrl label')).find(el => el.textContent === 'Tienda:');
  if(v==='tienda' || v==='inventario' || v==='gasto'){
    if(tiendaDropWrap) tiendaDropWrap.style.display = 'none';
    if(tiendaLabel) tiendaLabel.style.display = 'none';
  } else {
    if(tiendaDropWrap) tiendaDropWrap.style.display = 'inline-block';
    if(tiendaLabel) tiendaLabel.style.display = 'block';
  }
}

// Función de render para vista de tiendas (stub - se completará en la próxima parte)
function renderTienda(){
  // Implementación simplificada
  document.getElementById('tHistT').innerHTML = '<tr><td colspan="5">Vista de tiendas</td></tr>';
  document.getElementById('tMermaT').innerHTML = '<tr><td colspan="5">Vista de tiendas</td></tr>';
}

// Función de render para vista de inventario (stub)
function renderInventario(){
  document.getElementById('tInvTienda').innerHTML = '<tr><td colspan="2">Vista de inventario</td></tr>';
  document.getElementById('tInvProducto').innerHTML = '<tr><td colspan="2">Vista de inventario</td></tr>';
}

// ==== NUEVA FUNCIÓN: renderGasto() ====
function renderGasto(){
  var sems = getSemanasActivas();
  var gData = DATA.gasto_data;
  var pGasto = DATA.producto_gasto;
  
  // Rutas ordenadas
  var rutas = ['ENS', 'MXL 1', 'MXL 2', 'Ruta 2000', 'Rutas Playas'];
  
  // Construir headers de tabla (Ruta/Producto + columnas de semanas)
  var headHTML = '<tr><th>Ruta / Producto</th>';
  sems.forEach(function(s){
    var yr = Math.floor(s/100), wk = s%100;
    var label = (yr >= 2000) ? yr+'-'+String(wk).padStart(2,'0') : String(s).padStart(2,'0');
    headHTML += '<th>'+label+'</th>';
  });
  headHTML += '<th>Grand Total</th></tr>';
  document.getElementById('tGastoHead').innerHTML = headHTML;
  
  // Construir filas de datos
  var bodyHTML = '';
  var grandTotals = {}; // totales de gasto por semana
  var grandTotal = 0;   // gran total global de gasto
  
  sems.forEach(function(s){ grandTotals[s] = 0; });
  
  rutas.forEach(function(ruta){
    var rutaData = gData[ruta] || {};
    
    // Recopilar todos los productos que aparecen en esta ruta en cualquier semana
    var productosSet = new Set();
    sems.forEach(function(s){
      var semData = rutaData[s] || {};
      for(var prod in semData){
        if(semData[prod] > 0) productosSet.add(prod);
      }
    });
    var productos = Array.from(productosSet).sort();
    
    // Si no hay productos, skip esta ruta
    if(productos.length === 0) return;
    
    // Fila de ruta con GASTO total
    var rutaTotal = 0;
    var rutaRow = '<tr class="ruta-row"><td><strong>'+ruta+'</strong></td>';
    sems.forEach(function(s){
      var semData = rutaData[s] || {};
      var gasto = 0;
      for(var prod in semData){
        var unidades = semData[prod];
        var gastoUnit = pGasto[prod] || 0;
        gasto += unidades * gastoUnit;
      }
      rutaTotal += gasto;
      grandTotals[s] += gasto;
      rutaRow += '<td><strong>$'+fmt(gasto)+'</strong></td>';
    });
    rutaRow += '<td><strong>$'+fmt(rutaTotal)+'</strong></td></tr>';
    grandTotal += rutaTotal;
    bodyHTML += rutaRow;
    
    // Filas de productos con UNIDADES embarcadas
    productos.forEach(function(prod){
      var prodName = prod.replace('BQT ','');
      var prodRow = '<tr class="unidad-row"><td>&nbsp;&nbsp;'+prodName+'</td>';
      var prodTotal = 0;
      sems.forEach(function(s){
        var semData = rutaData[s] || {};
        var unidades = semData[prod] || 0;
        prodTotal += unidades;
        prodRow += '<td>'+(unidades > 0 ? Math.round(unidades) : '')+'</td>';
      });
      prodRow += '<td>'+(prodTotal > 0 ? Math.round(prodTotal) : '')+'</td></tr>';
      bodyHTML += prodRow;
    });
  });
  
  // Fila de Grand Total
  var gtRow = '<tr class="grand-total"><td><strong>Grand Total</strong></td>';
  sems.forEach(function(s){
    gtRow += '<td><strong>$'+fmt(grandTotals[s])+'</strong></td>';
  });
  gtRow += '<td><strong>$'+fmt(grandTotal)+'</strong></td></tr>';
  bodyHTML += gtRow;
  
  document.getElementById('tGastoBody').innerHTML = bodyHTML;
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
    if(typeof renderGasto!=='undefined') renderGasto = _patchResize(renderGasto);
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

# Caché del HTML: evita reconstruir el JSON gigante en cada rerun
_, _, html_cache_key = _excel_cache_key()
html_cache_file = _CACHE_DIR / f"html_{html_cache_key}.html" if html_cache_key else None
if html_cache_file and html_cache_file.exists():
    html_content = html_cache_file.read_text(encoding="utf-8")
else:
    html_content = build_html()
    if html_cache_file:
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            html_cache_file.write_text(html_content, encoding="utf-8")
        except Exception:
            pass
components.html(html_content, height=1400, scrolling=True)
