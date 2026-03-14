 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app.py b/app.py
index 5c50810cdcdd59ad0d7875dbdd7964c598f04808..0750cfb29915d46ef2f0c36cb2d4af90f8cc5e8c 100644
--- a/app.py
+++ b/app.py
@@ -1,84 +1,83 @@
 """
 Walmex Dashboard — CFBC
 Reporte ejecutivo estilo Walmart
 """
-import json, base64, openpyxl
+import base64, openpyxl
 from collections import defaultdict
+from datetime import datetime as _dt
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
-def cargar_datos(url: str = "") -> dict:
+def cargar_datos() -> dict:
     paths = ["Analisis_Walmart.xlsx", "Analisis Walmart.xlsx"]
     excel_path = next((p for p in paths if Path(p).exists()), None)
     if not excel_path:
         raise FileNotFoundError("No se encontró Analisis_Walmart.xlsx. Súbelo al repo de GitHub.")
-    wb = openpyxl.load_workbook(excel_path, data_only=True)
+    # `read_only=True` mejora bastante el tiempo de apertura en archivos grandes.
+    wb = openpyxl.load_workbook(excel_path, data_only=True, read_only=True)
     ws = wb['Data']
 
     def sv(v):
         try: return float(v) if v is not None else 0.0
         except: return 0.0
 
     # Mapear columnas por nombre de encabezado — fila 1
-    headers = [str(c.value).strip() if c.value else '' for c in ws[1]]
+    first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
+    headers = [str(c).strip() if c else '' for c in first_row]
     def col(name):
         for i, h in enumerate(headers):
             if h == name: return i
         raise ValueError(f'Columna "{name}" no encontrada. Encabezados: {headers}')
 
-    # Log headers para diagnóstico si alguna columna falla
-    import sys
-    _col_names = [h for h in headers if h]
-    
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
 
     # Columna de inventario actual
     idx_inventario = None
     for _n in ['Cantidad Actual en Existentes de la tienda', 'Cantidad Actual en Existentes',
@@ -103,226 +102,232 @@ def cargar_datos(url: str = "") -> dict:
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
-        from datetime import datetime as _dt
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
-    for (wk, yr) in _sem_anio_votes:
-        if wk not in _sem_to_anio or _sem_anio_votes[(wk, yr)] > _sem_anio_votes[(_sem_to_anio[wk], yr)]:
+    for (wk, yr), cnt in _sem_anio_votes.items():
+        curr_yr = _sem_to_anio.get(wk)
+        curr_cnt = _sem_anio_votes.get((wk, curr_yr), -1)
+        if curr_yr is None or cnt > curr_cnt:
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
-        for s in semanas:
-            idx    = semanas.index(s)
+        for idx, s in enumerate(semanas):
             last12 = semanas[max(0, idx-11):idx+1]
             last3  = semanas[max(0, idx-2):idx+1]
+
+            # Solo procesar productos que realmente tengan datos en esta tienda/ventana.
+            prod_keys = set()
+            for sem in last12:
+                prod_keys.update(by_stp[sem][t].keys())
+
             prod_data = {}
-            for p in productos:
+            for p in prod_keys:
                 v12  = sum(by_stp[sem][t][p]['ventas_u']   for sem in last12)
                 v3   = sum(by_stp[sem][t][p]['ventas_u']   for sem in last3)
-                emb3 = sum(by_stp[sem][t][p]['embarque_u'] for sem in last3)  # embarque 3 semanas
-                m3   = sum(by_stp[sem][t][p]['merma_u']    for sem in last3)  # merma 3 semanas (Cant VC Tienda)
-                cfbc3 = sum(by_stp[sem][t][p].get('venta_cfbc', 0) for sem in last3)  # Venta CFBC 3 semanas
-                retail3 = sum(by_stp[sem][t][p].get('retail_vc', 0) for sem in last3)  # Retail VC 3 semanas
-                avg  = v3 / 3  # Promedio = Ventas 3 semanas / 3
-                
-                # Proyección = Venta Promedio / (1 - Índice Merma %)
-                merma_ratio = m3 / emb3 if emb3 > 0 else 0  # Ratio de merma como decimal
-                proj = avg / (1 - merma_ratio) if merma_ratio < 1 else avg  # Evitar división por cero
-                
+                emb3 = sum(by_stp[sem][t][p]['embarque_u'] for sem in last3)
+                m3   = sum(by_stp[sem][t][p]['merma_u']    for sem in last3)
+                cfbc3 = sum(by_stp[sem][t][p].get('venta_cfbc', 0) for sem in last3)
+                retail3 = sum(by_stp[sem][t][p].get('retail_vc', 0) for sem in last3)
+                avg  = v3 / 3
+
+                merma_ratio = m3 / emb3 if emb3 > 0 else 0
+                proj = avg / (1 - merma_ratio) if merma_ratio < 1 else avg
+
                 prod_data[p] = {
                     'v12': round(v12), 'v3': round(v3),
                     'n12': min(s % 100 if s > 9999 else s, 12),
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
         totales_tienda[r['tienda']]['inventario'] += r['inventario']
         raw_semana[r['tienda']][r['semana']]['embarque_u'] += r['embarque_u']
         raw_semana[r['tienda']][r['semana']]['venta_cfbc'] += r['venta_cfbc']
         raw_semana[r['tienda']][r['semana']]['merma_u']    += r['merma_u']
         raw_semana[r['tienda']][r['semana']]['retail_vc']  += r['retail_vc']
         raw_semana[r['tienda']][r['semana']]['inventario'] += r['inventario']
         totales_prod_tienda[r['tienda']][r['producto']]['embarque_u'] += r['embarque_u']
         totales_prod_tienda[r['tienda']][r['producto']]['venta_cfbc'] += r['venta_cfbc']
         totales_prod_tienda[r['tienda']][r['producto']]['merma_u']    += r['merma_u']
         totales_prod_tienda[r['tienda']][r['producto']]['retail_vc']  += r['retail_vc']
         totales_prod_tienda[r['tienda']][r['producto']]['ventas_u']   += r['ventas_u']
         totales_prod_tienda[r['tienda']][r['producto']]['inventario'] += r['inventario']
         for d in ['dom','lun','mar','mie','jue','vie','sab']:
             totales_prod_tienda[r['tienda']][r['producto']][f'ctd_{d}']  += r.get(f'ctd_{d}', 0)
             totales_prod_tienda[r['tienda']][r['producto']][f'vtas_{d}'] += r.get(f'vtas_{d}', 0)
 
     # raw por tienda+semana+producto (exactamente la semana seleccionada)
     raw_prod_semana = {}
     for t in tiendas:
         raw_prod_semana[t] = {}
         for s in semanas:
             raw_prod_semana[t][str(s)] = {}
-            for p in productos:
-                d = by_stp[s][t][p]
+            for p, d in by_stp[s][t].items():
                 if any(d[k] for k in ['ventas_u','venta_cfbc','merma_u','retail_vc','embarque_u','inventario']):
                     raw_prod_semana[t][str(s)][p] = {
                         'ventas_u':   round(d['ventas_u']),
                         'venta_cfbc': round(d['venta_cfbc']),
                         'merma_u':    round(d['merma_u']),
                         'retail_vc':  round(d['retail_vc']),
                         'embarque_u': round(d['embarque_u']),
                         'inventario': round(d['inventario']),
                         **{f'ctd_{d_str}': round(d[f'ctd_{d_str}']) for d_str in ['dom','lun','mar','mie','jue','vie','sab']},
                         **{f'vtas_{d_str}': round(d[f'vtas_{d_str}']) for d_str in ['dom','lun','mar','mie','jue','vie','sab']}
                     }
 
     # Agregaciones de inventario por tienda (suma de todos los productos)
     inventario_por_tienda = {}
     for t in tiendas:
         total_inv = sum(totales_prod_tienda[t][p].get('inventario', 0) for p in productos)
         inventario_por_tienda[t] = {
             'total': round(total_inv),
             'productos': {p: round(totales_prod_tienda[t][p].get('inventario', 0)) 
                          for p in productos if totales_prod_tienda[t][p].get('inventario', 0) > 0}
         }
     
     # Agregaciones de inventario por producto (suma de todas las tiendas)
     inventario_por_producto = {}
     for p in productos:
         total_inv = sum(totales_prod_tienda[t][p].get('inventario', 0) for t in tiendas)
         inventario_por_producto[p] = {
             'total': round(total_inv),
             'tiendas': {t: round(totales_prod_tienda[t][p].get('inventario', 0)) 
                        for t in tiendas if totales_prod_tienda[t][p].get('inventario', 0) > 0}
         }
 
+    wb.close()
+
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
         'inventario_por_tienda': inventario_por_tienda,
         'inventario_por_producto': inventario_por_producto,
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
 
EOF
)
