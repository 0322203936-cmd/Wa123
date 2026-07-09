import streamlit as st
import json
import requests
import sys
import requests

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
    
    # 1. Traer datos antiguos
    print("Obteniendo datos de walmex_resumen_captura (captura_global)...")
    fetch_url = f"{url}/rest/v1/walmex_resumen_captura?id=eq.captura_global&select=data"
    resp = requests.get(fetch_url, headers=headers)
    
    if not resp.ok:
        print("Error fetching:", resp.text)
        return
        
    res_data = resp.json()
    if not res_data:
        print("No se encontró la fila 'captura_global'.")
        return
        
    old_data_str = res_data[0].get("data")
    if not old_data_str:
        print("El campo 'data' está vacío.")
        return
        
    try:
        old_data = json.loads(old_data_str)
    except Exception as e:
        # En caso de que ya sea un dict
        if isinstance(old_data_str, dict):
            old_data = old_data_str
        else:
            print("Error parseando JSON:", e)
            return
            
    # 2. Desglosar datos
    records_to_insert = []
    SAFE_SEP = '\u241F'
    NULL_SEP = '\x00'
    
    for mode_key in ["sem", "norm"]:
        if mode_key not in old_data:
            continue
        store_data = old_data[mode_key]
        for combo_key, value in store_data.items():
            if SAFE_SEP in combo_key:
                parts = combo_key.split(SAFE_SEP)
            elif NULL_SEP in combo_key:
                parts = combo_key.split(NULL_SEP)
            else:
                continue
                
            if len(parts) != 2:
                continue
                
            producto = parts[0]
            tienda = parts[1]
            
            rows = value.get("rows", [])
            for row in rows:
                semana = str(row.get("sem", "")).strip()
                if not semana:
                    continue
                valores = row.get("values", [])
                
                # Check guardado real
                try:
                    has_vals = any(v != '' and float(v) > 0 for v in valores if v)
                except:
                    has_vals = False
                saved = row.get("saved", has_vals)
                
                if not saved:
                    continue
                    
                records_to_insert.append({
                    "mode": mode_key,
                    "producto": producto,
                    "tienda": tienda,
                    "semana": semana,
                    "valores": valores
                })
                
    print(f"Se encontraron {len(records_to_insert)} registros validos guardados.")
    
    if not records_to_insert:
        print("No hay nada que migrar.")
        return
        
    # 3. Insertar en walmex_resumen_captura_v2
    print("Insertando en walmex_resumen_captura_v2...")
    batch_size = 100
    for i in range(0, len(records_to_insert), batch_size):
        batch = records_to_insert[i:i+batch_size]
        try:
            post_url = f"{url}/rest/v1/walmex_resumen_captura_v2?on_conflict=mode,producto,tienda,semana"
            post_headers = headers.copy()
            post_headers['Prefer'] = 'resolution=merge-duplicates,return=minimal'
            
            p_resp = requests.post(post_url, headers=post_headers, json=batch)
            if not p_resp.ok:
                print(f"Error insertando lote {i}:", p_resp.text)
                print("¿Aseguraste ejecutar el código SQL en Supabase para crear la tabla walmex_resumen_captura_v2?")
                sys.exit(1)
                
            print(f" -> Lote {i} a {i+len(batch)-1} migrado correctamente.")
        except Exception as e:
            print(f"Error insertando lote {i}: {e}")
            print("¿Aseguraste ejecutar el código SQL en Supabase para crear la tabla walmex_resumen_captura_v2?")
            sys.exit(1)
            
    print("\n✅ MIGRACION COMPLETADA EXITOSAMENTE ✅")

if __name__ == "__main__":
    run()
