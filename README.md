# WebGIS Bacino 5 — Reticolo Margorabbia

Mappa regolamentare della pesca sul Margorabbia e affluenti (Prontuario Bacino 5, 2026).  
Concessione FIPSAS Varese / ATS Prealpi.

## Mappa

Apri `docs/index.html` nel browser, oppure la pubblicazione GitHub Pages del repository.

## Rigenerare i dati

```text
py -3 scripts/build_geo_data.py
```

I capisaldi confermati sono in `data/geojson/capisaldi_verificati.json`. Le regole computabili sono in `data/normativa/margorabbia_regole.json`.
