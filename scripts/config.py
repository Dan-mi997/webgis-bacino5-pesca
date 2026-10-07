"""Percorsi e parametri della pipeline attuale.

La pipeline OpenStreetMap (build_geo_data, osm_*, fetch del Ceresio e di Varese)
sta in old/scripts. Qui restano solo la segmentazione sul reticolo regionale
e la lettura del grafo normativo.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMATIVA_DIR = DATA_DIR / "normativa"
GEOJSON_DIR = DATA_DIR / "geojson"
WEB_DIR = ROOT / "docs"
PREVIEW_DIR = ROOT / "preview"

# Reticolo ufficiale Regione Lombardia (Geoportale). Copre tutta la regione:
# la segmentazione tiene solo i sottobacini del Bacino 5.
ACQUE_LOMBARDIA_DIR = GEOJSON_DIR / "AcqueLombardia"
RETICOLO_FIUMI = ACQUE_LOMBARDIA_DIR / "Fiumi.json"
RETICOLO_LAGHI = ACQUE_LOMBARDIA_DIR / "Laghi.json"
# Confine regionale semplificato: taglia Verbano e Ceresio sulla Lombardia
# (il poligono del Geoportale comprende anche Svizzera e Piemonte).
CONFINE_LOMBARDIA = GEOJSON_DIR / "lombardia.geojson"
SOTTOBACINI_BACINO_5 = (
    "Lago Maggiore (Verbano)",
    "Lago di Lugano (Ceresio)",
    "Lago di Como (Lario)",
)

# Un caposaldo più lontano di così non spezza la linea: resta nel report.
MAX_SNAP_CAPOSALDO_M = 300.0
# Due pezzi della stessa feature si uniscono solo se gli estremi distano al massimo così.
MAX_JOIN_GAP_M = 60.0

OUT_RETICOLO_SEGMENTATO = GEOJSON_DIR / "reticolo_segmentato.geojson"
OUT_SEGMENTAZIONE_REPORT = GEOJSON_DIR / "segmentazione_report.json"
CAPISALDI_VERIFICATI = GEOJSON_DIR / "capisaldi_verificati.json"

# Grafo (matrice, eccezioni, tagli). I dizionari restano in REGOLE_JSON.
STRUTTURA_JSON = NORMATIVA_DIR / "struttura_dati_regole.json"
REGOLE_JSON = NORMATIVA_DIR / "margorabbia_regole.json"

# Pubblicazione GitHub Pages. Si riscrive solo allo STEP 4, dopo conferma.
OUT_WEB_JS = WEB_DIR / "geo_data.js"
