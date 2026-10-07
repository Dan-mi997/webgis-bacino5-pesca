# Archivio

Qui sta la pipeline precedente, quella che scaricava le geometrie da OpenStreetMap. Dal 2026-10-06 la rete è il GeoJSON del Geoportale regionale e questi file non entrano nel lavoro corrente. La mappa già online resta in `docs/`: è stata generata da qui, e non si rigenera da questa cartella.

| Cartella | Contenuto |
| --- | --- |
| `scripts/` | `build_geo_data.py`, moduli `osm_*`, fetch e impalcature di Ceresio e Varese |
| `geojson/` | Tratti e overlay del Margorabbia, tratti e capisaldi del Ceresio, elenchi di punti da verificare |
| `raw/` | Scarichi OSM del Ceresio–Tresa e di Varese, Comabbio e Monate |
| `preview/` | Mappe di controllo costruite su quegli scarichi |
| `cache/` | Risposte HTTP di Overpass e Nominatim. È rigenerabile e non va committata |

Gli script archiviati importavano `config.py` dalla cartella `scripts/` di allora. Quella configurazione è stata ridotta ai percorsi attuali: da qui non si rilanciano.
