import streamlit as st
import requests
import sys
import csv
import os

def leer_csv(path: str):
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    if len(rows) < 2:
        raise ValueError("El CSV no tiene suficientes filas.")

    cabeceras = rows[1]
    productos = [c.strip() for c in cabeceras[3:] if c.strip()]

    datos = {}
    tienda_actual = ""

    for row in rows[2:]:
        if not any(c.strip() for c in row):
            continue

        tienda_cell = row[1].strip() if len(row) > 1 else ""
        dia_cell    = row[2].strip() if len(row) > 2 else ""

        if tienda_cell:
            tienda_actual = tienda_cell
        if not tienda_actual or not dia_cell:
            continue

        if tienda_actual not in datos:
            datos[tienda_actual] = {}
        if dia_cell not in datos[tienda_actual]:
            datos[tienda_actual][dia_cell] = {}

        for i, prod in enumerate(productos):
            col_idx = 3 + i
            val = row[col_idx].strip() if col_idx < len(row) else ""
            if val:
                datos[tienda_actual][dia_cell][prod] = val

    return productos, datos

def run():
    print("Conectando a Supabase...")
    try:
        if "supabase" in st.secrets:
            url = st.secrets["supabase"]["url"]
            key = st.secrets["supabase"].get("publishable_key", st.secrets["supabase"].get("service_role_key", ""))
        else:
            url = st.secrets["SUPABASE_URL"]
            key = st.secrets["SUPABASE_KEY"]
    except Exception as e:
        print("Error leyendo st.secrets.", e)
        return
        
    headers = {
        'apikey': key,
        'Authorization': 'Bearer ' + key,
        'Content-Type': 'application/json'
    }
    
    # 1. Leer y parsear el CSV
    csv_file = os.path.join(os.path.dirname(__file__), "cronograma28.csv")
    print(f"Leyendo: {csv_file}")
    productos, datos = leer_csv(csv_file)
    
    DIAS_ORDEN = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    
    records_to_insert = []
    
    for tienda, dias_data in datos.items():
        for prod in productos:
            values = []
            tiene_dato = False

            for dia_nombre in DIAS_ORDEN:
                prod_vals = dias_data.get(dia_nombre, {})
                v = prod_vals.get(prod, "")
                values.append(str(v) if v else "")
                if v and float(str(v).replace(",", "") or 0) > 0:
                    tiene_dato = True

            if tiene_dato:
                records_to_insert.append({
                    "mode": "sem",
                    "producto": prod,
                    "tienda": tienda,
                    "semana": "28",
                    "valores": values
                })
                
    print(f"Se encontraron {len(records_to_insert)} registros para insertar de la semana 28.")
    
    if not records_to_insert:
        print("No hay nada que importar.")
        return
        
    # 2. Borrar datos existentes de semana 28 programado
    print("Borrando datos anteriores de semana 28 (mode=sem)...")
    delete_url = f"{url}/rest/v1/walmex_resumen_captura_v2?mode=eq.sem&semana=eq.28"
    del_resp = requests.delete(delete_url, headers=headers)
    if not del_resp.ok:
        print("Error borrando:", del_resp.text)
        sys.exit(1)
        
    # 3. Insertar nuevos datos
    print("Insertando nuevos registros...")
    batch_size = 100
    for i in range(0, len(records_to_insert), batch_size):
        batch = records_to_insert[i:i+batch_size]
        post_url = f"{url}/rest/v1/walmex_resumen_captura_v2?on_conflict=mode,producto,tienda,semana"
        post_headers = headers.copy()
        post_headers['Prefer'] = 'resolution=merge-duplicates,return=minimal'
        
        p_resp = requests.post(post_url, headers=post_headers, json=batch)
        if not p_resp.ok:
            print(f"Error insertando lote {i}:", p_resp.text)
            sys.exit(1)
            
        print(f" -> Lote {i} a {i+len(batch)-1} insertado correctamente.")
        
    print("\nIMPORTACION DE SEMANA 28 COMPLETADA EXITOSAMENTE")

if __name__ == "__main__":
    run()
