"""
fix_importar_sem27.py
─────────────────────
Corrige la importacion de semana 27 directamente en Supabase.
Opera con las claves ya en formato SAFE_SEP (tal como estan en Supabase)
sin conversion intermedia que causaba el problema anterior.
"""
import csv, json, datetime, urllib.request, urllib.error, os, sys

URL      = "https://fzrhklskjjuscckfvvfa.supabase.co"
KEY      = "sb_publishable_63XnbBC_gPjZwxqjPnOBOg_4Qnxz5y9"
TABLE    = "walmex_resumen_captura"
ROW_ID   = "captura_global"
SAFE_SEP = "\u241f"   # separador tal como esta en Supabase
SEMANA   = "27"

CSV_FILE = os.path.join(os.path.dirname(__file__),
                        "Cronograma_Entregas_Captura Wk 27.csv")

DIAS_ORDEN = ["Lunes","Martes","Miercoles","Jueves","Viernes","Sabado","Domingo"]


def http_get(path):
    req = urllib.request.Request(
        URL + path,
        headers={"apikey": KEY, "Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json"},
        method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def http_upsert(path, payload):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        URL + path + "?on_conflict=id",
        data=data,
        headers={"apikey": KEY, "Authorization": "Bearer " + KEY,
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"},
        method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status


def leer_csv(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
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


def main():
    print("Leyendo CSV...")
    productos, datos_csv = leer_csv(CSV_FILE)
    print(f"  {len(productos)} productos, {len(datos_csv)} tiendas")

    # Construir nuevas entradas CSV con clave en SAFE_SEP (igual que Supabase)
    nuevas = {}
    for tienda, dias in datos_csv.items():
        for prod in productos:
            values = [str(dias.get(d, {}).get(prod, "") or "")
                      for d in DIAS_ORDEN]
            if any(v for v in values):
                sk = prod + SAFE_SEP + tienda   # <- clave directamente en formato Supabase
                nuevas[sk] = values
    print(f"  {len(nuevas)} entradas con datos en CSV")

    print("Leyendo Supabase...")
    rows_sb = http_get(f"/rest/v1/{TABLE}?id=eq.{ROW_ID}&select=data")
    raw = rows_sb[0]["data"] if rows_sb and rows_sb[0].get("data") else {}

    # raw ya viene con SAFE_SEP en las claves — no tocar
    if "sem" not in raw:
        raw["sem"] = {}
    if "norm" not in raw:
        raw["norm"] = {}
    if "_meta" not in raw:
        raw["_meta"] = {}

    sem_store = raw["sem"]
    print(f"  {len(sem_store)} claves en sem_store")

    # Limpiar sem=27 duplicados/incorrectos que pudo dejar la primera corrida
    limpios = 0
    for sk, entry in sem_store.items():
        rows_entry = entry.get("rows") or []
        antes = len(rows_entry)
        rows_entry = [r for r in rows_entry
                      if str(r.get("sem", "")).strip() != SEMANA]
        if len(rows_entry) < antes:
            limpios += antes - len(rows_entry)
        entry["rows"] = rows_entry
    if limpios:
        print(f"  Limpiados {limpios} registros previos de sem={SEMANA}")

    # Agregar las entradas del CSV
    agregados = 0
    for sk, values in nuevas.items():
        if sk not in sem_store:
            sem_store[sk] = {"visibleInitial": 0, "rows": []}
        nueva_fila = {
            "sem":    SEMANA,
            "values": values,
            "hidden": False,
            "saved":  True
        }
        sem_store[sk]["rows"].append(nueva_fila)
        sem_store[sk]["visibleInitial"] = 0
        agregados += 1

    raw["sem"] = sem_store

    print(f"  Agregando {agregados} entradas de sem={SEMANA}...")
    payload = {
        "id":         ROW_ID,
        "data":       raw,
        "updated_at": datetime.datetime.utcnow().isoformat() + "Z"
    }
    status = http_upsert(f"/rest/v1/{TABLE}", payload)
    print(f"  Upsert status: {status}")
    print()
    print(f"Listo! {agregados} entradas de semana {SEMANA} subidas correctamente.")


if __name__ == "__main__":
    main()
