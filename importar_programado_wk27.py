"""
importar_programado_wk27.py
───────────────────────────
Lee el CSV "Cronograma_Entregas_Captura Wk 27.csv" y sube los datos
a Supabase con exactamente el mismo formato que usa la app cuando el
usuario hace "+SEM → escribe 27 → Guardar".

Estructura en Supabase (tabla walmex_resumen_captura, fila id='captura_global'):
{
  "data": {
    "sem": {
      "PRODUCTO\u241FTIENDA": {          ← \x00 (NULL) reemplazado por \u241F para Supabase
        "visibleInitial": 0,
        "rows": [
          { "sem": "27", "values": ["v_lun","v_mar",...], "hidden": false, "saved": true }
        ]
      }
    },
    "norm": {},
    "_meta": {}
  }
}

La clave interna usa \x00 (NULL byte) para separar PRODUCTO y TIENDA,
pero al guardar en Supabase se reemplaza por \u241F (el mismo swap que
hace _captureForSupabase en el JS).

El CSV tiene:
  - Fila 0: título (ignorar)
  - Fila 1: cabeceras → [Ruta, Tienda, Dia/Periodo, PROD1, PROD2, ...]
  - Filas 2+: datos por tienda+día
    * Columnas A=Ruta, B=Tienda, C=Dia/Periodo, D..=cantidades por producto

Los 'values' de cada entrada corresponden a los 7 días de la semana
(en el orden Lun, Mar, Mié, Jue, Vie, Sáb, Dom) que usa la app.
Solo se incluyen los días que tienen cantidad > 0 en alguna tienda+producto
(si no hay ninguno para ese día, el valor es "" en ese índice).

IMPORTANTE: el script MERGEA los datos existentes en Supabase con los
nuevos — no borra lo que ya estaba guardado para otras semanas.
"""

import csv
import json
import os
import sys
import urllib.request
import urllib.error

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
SUPABASE_URL         = "https://fzrhklskjjuscckfvvfa.supabase.co"
SUPABASE_SERVICE_KEY = "sb_publishable_63XnbBC_gPjZwxqjPnOBOg_4Qnxz5y9"  # publishable_key (mismos permisos que el browser)
SUPABASE_TABLE       = "walmex_resumen_captura"
SUPABASE_ROW_ID      = "captura_global"

CSV_FILE = os.path.join(os.path.dirname(__file__), "Cronograma_Entregas_Captura Wk 27.csv")
SEMANA   = "27"   # ← número de semana a importar

# Separador interno de la app (NULL byte) y el seguro para Supabase
NULL_SEP = "\x00"
SAFE_SEP = "\u241f"   # ␟ UNIT SEPARATOR — mismo que usa el JS

# Orden de días tal como los itera el JS:  diasOrden = [1,2,3,4,5,6,0]
# → Lun(1), Mar(2), Mié(3), Jue(4), Vie(5), Sáb(6), Dom(0)
DIAS_ORDEN = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
# ──────────────────────────────────────────────────────────────────────────────


def supabase_headers(extra=None):
    h = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def supabase_get(path: str) -> dict:
    url = SUPABASE_URL + path
    req = urllib.request.Request(url, headers=supabase_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"GET {path} → {e.code}: {body}")


def supabase_patch(path: str, payload: dict) -> None:
    url = SUPABASE_URL + path
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers=supabase_headers({"Prefer": "return=minimal"}),
        method="PATCH"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            _ = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"PATCH {path} → {e.code}: {body}")


def supabase_upsert(path: str, payload: dict) -> None:
    url = SUPABASE_URL + path + "?on_conflict=id"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data,
        headers=supabase_headers({
            "Prefer": "resolution=merge-duplicates,return=minimal"
        }),
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            _ = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"UPSERT {path} → {e.code}: {body}")


def swap_sep(obj, from_sep: str, to_sep: str):
    """Intercambia separadores en todas las claves del dict (recursivo)."""
    if isinstance(obj, list):
        return [swap_sep(item, from_sep, to_sep) for item in obj]
    if isinstance(obj, dict):
        return {
            (k.replace(from_sep, to_sep) if from_sep in k else k): swap_sep(v, from_sep, to_sep)
            for k, v in obj.items()
        }
    return obj


def leer_csv(path: str):
    """
    Devuelve:
      productos   : list[str]   — nombres de columnas de producto
      datos       : dict        — { tienda: { dia: { producto: cantidad_str } } }
    """
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)

    # Fila 0 → título, Fila 1 → cabeceras
    if len(rows) < 2:
        raise ValueError("El CSV no tiene suficientes filas.")

    cabeceras = rows[1]
    # Columnas 0=Ruta, 1=Tienda, 2=Dia/Periodo; desde col 3 en adelante = productos
    productos = [c.strip() for c in cabeceras[3:] if c.strip()]
    n_prod = len(productos)

    datos = {}          # { tienda: { dia: { prod: valor } } }
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


def normalizar_dia(dia_str: str) -> str | None:
    """Normaliza variaciones de nombre de día al nombre canónico del CSV."""
    dia_lower = dia_str.lower().replace("é", "e").replace("á", "a")
    mapa = {
        "lunes": "Lunes",
        "martes": "Martes",
        "miercoles": "Miercoles",
        "miércoles": "Miercoles",
        "jueves": "Jueves",
        "viernes": "Viernes",
        "sabado": "Sabado",
        "sábado": "Sabado",
        "domingo": "Domingo",
    }
    return mapa.get(dia_lower)


def construir_capture_sem(productos, datos, semana: str):
    """
    Construye el dict capture.sem que va a Supabase:
      {
        "PROD\x00TIENDA": {
          "visibleInitial": 0,
          "rows": [{ "sem": "27", "values": ["v_lun","v_mar",...], "hidden": False, "saved": True }]
        }
      }

    values[] tiene 7 posiciones (una por día Lun→Dom).
    Si no hay dato para ese día, la posición es "".
    Solo se incluye la entrada si la fila tiene al menos un valor > 0.
    """
    capture_sem = {}

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

            if not tiene_dato:
                continue

            # Clave interna: PROD + NULL_SEP + TIENDA
            sk = prod + NULL_SEP + tienda
            if sk not in capture_sem:
                capture_sem[sk] = {"visibleInitial": 0, "rows": []}

            # Agregar fila de semana 27
            capture_sem[sk]["rows"].append({
                "sem":    semana,
                "values": values,
                "hidden": False,
                "saved":  True
            })

    return capture_sem


def main():
    print(f"📂 Leyendo: {CSV_FILE}")
    if not os.path.exists(CSV_FILE):
        print(f"❌ No se encontró el archivo: {CSV_FILE}")
        sys.exit(1)

    productos, datos = leer_csv(CSV_FILE)
    print(f"   → {len(productos)} productos: {productos[:5]}{'...' if len(productos)>5 else ''}")
    print(f"   → {len(datos)} tiendas: {list(datos.keys())[:5]}{'...' if len(datos)>5 else ''}")

    nueva_capture_sem = construir_capture_sem(productos, datos, SEMANA)
    print(f"   → {len(nueva_capture_sem)} entradas (prod+tienda) con datos para sem {SEMANA}")

    if not nueva_capture_sem:
        print("⚠️  No se encontraron datos con valores > 0. Revisa el CSV.")
        sys.exit(0)

    # ── Obtener captura actual de Supabase ──
    print(f"\n🌐 Conectando a Supabase: {SUPABASE_URL}")
    rows = supabase_get(
        f"/rest/v1/{SUPABASE_TABLE}"
        f"?id=eq.{SUPABASE_ROW_ID}"
        f"&select=data"
    )

    capture_actual = {"sem": {}, "norm": {}, "_meta": {}}
    if rows and rows[0].get("data"):
        raw = rows[0]["data"]
        # Convertir \u241F → \x00 (interno) al leer de Supabase
        capture_actual = swap_sep(raw, SAFE_SEP, NULL_SEP)
        print("   → Captura existente encontrada en Supabase.")
    else:
        print("   → No hay captura previa — se creará nueva.")

    if "sem" not in capture_actual:
        capture_actual["sem"] = {}
    if "norm" not in capture_actual:
        capture_actual["norm"] = {}
    if "_meta" not in capture_actual:
        capture_actual["_meta"] = {}

    # ── MERGE: añadir datos de semana 27 sin borrar las demás semanas ──
    print(f"\n🔀 Mergeando semana {SEMANA} en la captura existente...")
    merged = 0
    skipped_dup = 0

    for sk, entry in nueva_capture_sem.items():
        if sk not in capture_actual["sem"]:
            capture_actual["sem"][sk] = {"visibleInitial": 0, "rows": []}

        existing_rows = capture_actual["sem"][sk].get("rows", [])
        existing_sems = {str(r.get("sem", "")).strip() for r in existing_rows if r.get("saved")}

        for row in entry["rows"]:
            sem_val = str(row.get("sem", "")).strip()
            if sem_val and sem_val in existing_sems:
                print(f"   ⚠️  Sem {sem_val} ya existe para '{sk.replace(NULL_SEP,'|')}' — SKIP (no sobrescribir)")
                skipped_dup += 1
            else:
                existing_rows.append(row)
                merged += 1

        capture_actual["sem"][sk]["rows"] = existing_rows
        capture_actual["sem"][sk]["visibleInitial"] = 0

    print(f"   → {merged} filas nuevas agregadas, {skipped_dup} duplicadas omitidas.")

    if merged == 0:
        print(f"\n✅ No había nada nuevo que agregar (todo ya estaba en semana {SEMANA}).")
        sys.exit(0)

    # ── Convertir \x00 → \u241F antes de mandar a Supabase ──
    capture_para_supabase = swap_sep(capture_actual, NULL_SEP, SAFE_SEP)

    payload = {
        "id": SUPABASE_ROW_ID,
        "data": capture_para_supabase,
        "updated_at": __import__("datetime").datetime.utcnow().isoformat() + "Z"
    }

    print(f"\n💾 Subiendo a Supabase ({SUPABASE_TABLE})...")
    supabase_upsert(f"/rest/v1/{SUPABASE_TABLE}", payload)

    print(f"\n✅ ¡Listo! Semana {SEMANA} subida como Programado.")
    print(f"   Recarga el dashboard para ver los cambios.")


if __name__ == "__main__":
    main()
