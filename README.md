# WebGIS Bacino 5

Mappa della pesca sportiva sulle acque lombarde di Varese, Como e Lecco (prontuario 2026). Le acque in concessione si indicano con il regime (FIPSAS, Italo-Svizzera, Diritti esclusivi), mai «Libera».

La mappa pubblicata è ancora il pilota Margorabbia e Ceresio. Il lavoro in corso usa il reticolo della Regione e non è ancora stato pubblicato.

## Da dove partire

| Se cerchi | Apri |
| --- | --- |
| Stato, decisioni, punti aperti | `MEMORIA.md` |
| Come si procede (STEP 0–4) | `WORKFLOW_PROTOCOLS.md` |
| Cosa dice il prontuario, punto per punto | `data/normativa/estratto_bacino5_2026.json` |
| Come si combinano permesso, categoria e regole | `data/normativa/struttura_dati_regole.json` |
| Calendari, documenti, specie, blocchi | `data/normativa/margorabbia_regole.json` |
| Il Margorabbia in lettura | `data/normativa/margorabbia_regolamento.md` |
| Il prontuario originale | `data/raw/` |
| Coordinate già confermate | `data/geojson/capisaldi_verificati.json` |
| Fiumi e laghi della Lombardia | `data/geojson/AcqueLombardia/` |
| Prima segmentazione, non pubblicata | `data/geojson/reticolo_segmentato.geojson` e `segmentazione_report.json` |
| La mappa online | `docs/index.html` |

## Comandi

```text
py -3 scripts/regole.py --verifica
py -3 scripts/segmenta_rete.py
```

`segmenta_rete.py` legge il reticolo regionale e i capisaldi, e scrive il layer segmentato. Non pubblica. La pubblicazione (`--pubblica-leaflet`) arriva solo dopo una conferma esplicita.

## Cartelle

```text
data/raw/            prontuario
data/normativa/      estratto, grafo, dizionari
data/geojson/        reticolo regionale, capisaldi, layer segmentato
scripts/             segmentazione e motore delle regole
docs/                mappa pubblicata (GitHub Pages)
preview/             vista di controllo, prima di pubblicare
old/                 pipeline OpenStreetMap e i suoi prodotti
```

Archivio: https://github.com/Dan-mi997/webgis-bacino5-pesca  
Mappa: https://dan-mi997.github.io/webgis-bacino5-pesca/
