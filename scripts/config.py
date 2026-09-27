"""Percorsi del progetto e parametri della pipeline geografica."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
NORMATIVA_DIR = DATA_DIR / "normativa"
GEOJSON_DIR = DATA_DIR / "geojson"
WEB_DIR = ROOT / "docs"
CACHE_DIR = ROOT / "cache"
HTTP_CACHE_DIR = CACHE_DIR / "http"

REGOLE_JSON = NORMATIVA_DIR / "margorabbia_regole.json"
WATERWAYS_CACHE = CACHE_DIR / "osm_cache_waterways.json"

CAPISALDI_VERIFICATI = GEOJSON_DIR / "capisaldi_verificati.json"
OUT_TRATTI = GEOJSON_DIR / "margorabbia_tratti.geojson"
OUT_CAPISALDI = GEOJSON_DIR / "capisaldi.geojson"
OUT_TODO_GEOJSON = GEOJSON_DIR / "punti_da_verificare.geojson"
OUT_REPORT = GEOJSON_DIR / "punti_da_verificare.json"
OUT_WEB_JS = WEB_DIR / "geo_data.js"

USER_AGENT = "ProgettoFIPSAS/2.0 (mappa regolamentare locale; uso personale)"

BBOX = (45.875, 8.70, 46.005, 8.87)  # (sud, ovest, nord, est)

OSM_LAKES = {
    "lago_ghirla": {"osm_type": "relation", "osm_id": 21250532, "name": "Lago di Ghirla"},
    "lago_ganna": {"osm_type": "relation", "osm_id": 18050127, "name": "Lago di Ganna"},
}

# Reticolo tenuto in mappa: asta + affluenti maggiori con toponimo OSM noto.
# Chiave = corpo idrico in margorabbia_regole.json, valore = nomi OSM esatti.
STEM_OSM_NAMES = ("Fiume Margorabbia", "Torrente Margorabbia")
MAJOR_TRIBUTARIES = {
    "rancina": ("Torrente Rancina",),
    "chiesone": ("Torrente Gesone", "Torrente Chiesone"),
    "boggione": ("Torrente Boggione",),
    "rio_boesio": ("Torrente Rio Boesio",),
    "grantorella": ("Torrente Grantorella",),
}

RECEIVER_OSM_NAMES = ("Fiume Tresa",)
RECEIVER_HALF_REACH_M = 800.0  # tratto del Tresa mostrato attorno alla confluenza

# Due pezzi di waterway vengono uniti solo se i loro estremi distano meno di così
# (lacune di digitalizzazione); oltre, restano geometrie separate.
MAX_JOIN_GAP_M = 60.0
# Parti più corte di così dopo la fusione (monconi, rami secondari) vengono scartate.
MIN_ISOLATED_FRAGMENT_M = 100.0
