# Protocolli operativi — WebGIS Bacino 5

Procedura unica per ogni corpo idrico del Bacino 5. Gli step sono rigidi: uno step AI si ferma e attende l’umano; non si anticipa lo step seguente.

Dal 2026-10-07 `docs/` è la mappa del Bacino 5 sul reticolo regionale. La pipeline OpenStreetMap sta in `old/scripts/` e non si usa.

---

## Invarianti architetturali permanenti

Valgono per ogni step e per ogni bacino. Non si derogano in una singola area.

### 1. Perimetro territoriale del Bacino 5

Si cartografano solo acque nelle province di **Varese, Como e Lecco**.

Restano fuori, senza eccezioni:

- acque territoriali svizzere e del Canton Ticino;
- la provincia di Sondrio.

Il file regionale copre tutta la Lombardia. In STEP 3 si tengono solo i sottobacini `Lago Maggiore (Verbano)`, `Lago di Lugano (Ceresio)` e `Lago di Como (Lario)`. Adda Sopra Lacuale, Mera, Spol e Ticino Sub Lacuale restano fuori. Su un corpo di confine entra nel grafo solo la parte presente nell’export regionale: non si importa geometria svizzera.

### 2. Supporto topologico delle sponde

Ogni segmento normativo lineare porta la proprietà obbligatoria `bank`:

| Valore | Significato |
| --- | --- |
| `both` | Entrambe le sponde, o il prontuario non distingue |
| `left` | Solo sponda sinistra, nel senso di scorrimento (monte → valle) |
| `right` | Solo sponda destra, nello stesso senso |

`left` e `right` sono idrografici, non «a est / a ovest» sulla mappa. Un divieto o un no-kill che cita una sola sponda non si estende all’altra. I poligoni (specchi) non usano `bank`; distinguono sponda e natante con la modalità di pesca già prevista dalla matrice.

Il pilota Margorabbia, finché non è riallineato, si legge come `both`. Ogni segmentazione nuova compila `bank` dallo STEP 1.

### 3. Campi gara fuori perimetro

Dal 2026-09-28 i campi gara non sono oggetto del WebGIS. Non si elencano nello STEP 1, non si cercano i capisaldi, non si disegnano overlay. Un punto che nel grafo è solo estremo di un overlay non spezza la linea. Il pilota Margorabbia ha già un overlay pubblicato: non si estende e non fa da modello per le aree nuove.

### 4. Mappa di controllo prima del deploy

Dopo la segmentazione, prima dello STEP 4, il layer si guarda. Il prodotto canonico è `data/geojson/reticolo_segmentato.geojson` insieme a `data/geojson/segmentazione_report.json`. Se serve una vista in browser, l’AI scrive `preview/{nome_area}_impalcatura.html`. Non è la pubblicazione. Niente riscrittura di `docs/geo_data.js` e niente commit finché la conferma non è arrivata. La cartella `preview/` non è la sorgente di GitHub Pages.

---

## Percorsi canonici

| Cosa | Percorso |
| --- | --- |
| Prontuario | `data/raw/` |
| Reticolo lineare regionale (tutta la Lombardia) | `data/geojson/AcqueLombardia/Fiumi.json` |
| Specchi lacustri regionali | `data/geojson/AcqueLombardia/Laghi.json` |
| Grafo normativo | `data/normativa/struttura_dati_regole.json` |
| Dizionari (calendari, documenti, specie, blocchi) | `data/normativa/margorabbia_regole.json` |
| Segmentazione dinamica | `scripts/segmenta_rete.py` |
| Layer segmentato | `data/geojson/reticolo_segmentato.geojson` |
| Report di segmentazione | `data/geojson/segmentazione_report.json` |
| Capisaldi con coordinate | `data/geojson/capisaldi_verificati.json` |
| Web app pubblicata (GitHub Pages, cartella `/docs`) | `docs/index.html`, `docs/geo_data.js` |

Attributi del GeoJSON regionale, da non rinominare: `NOME`, `BACINO`, `SOTTOBACIN`, `COD_PTUA16`, `NATURA`, `VITA_PESCI` (sui laghi anche `SPECIE_ITT`). Le linee sono `LineString` o `MultiLineString`, i laghi `Polygon`.

Un nome regionale composto (`Grantorella (Torrente) - Margorabbia (Fiume)`) non si assegna da solo a un corpo: resta nel report. Un qualificatore (`Lugano (lago) - bacino nord`) è un solo specchio.

---

## Standard Operating Procedure (SOP)

### STEP 0 — Sorgente geometrica

**Input.** I GeoJSON del Geoportale della Regione Lombardia, già in `data/geojson/AcqueLombardia/`.

**Compito.** Nessuno scarica la rete e nessuno interroga Overpass. Lo scope di lavoro resta il Bacino 5 anche se il file contiene l’intera Lombardia: il filtro per sottobacino è nello STEP 3. Se arriva un export nuovo, si sostituiscono `Fiumi.json` e `Laghi.json` negli stessi percorsi.

**Output.** I due file al loro posto. Non è ancora un layer di pesca.

**Stop.** Non si segmenta e non si pubblica.

### STEP 1 — AI, analisi normativa

**Input.** Il prontuario, non un singolo fiume alla volta.

**Compito.** Estrarre le regole e identificare tutti i capisaldi menzionati (ponti, briglie, dighe, confluenze, foci, limiti di sponda), su ogni corpo idrico citato, non solo sul fiume della sessione. I campi gara non si elencano.

Aggiornare `data/normativa/struttura_dati_regole.json` con la matrice (regime amministrativo + classe biologica), le eccezioni locali e i tagli. Ogni taglio lineare che spezza la linea ha `monte` e `valle` (id del caposaldo), `bank` e `priorita`. Gli id dei capisaldi sono stabili: le coordinate arrivano allo STEP 2. Le deroghe temporanee diverse dai campi gara restano overlay: non hanno effetto di taglio.

**Output.** Tabella dei corpi (nome di prontuario, id del grafo, `bank`, eccezione o «eredita la base») e tabella dei capisaldi (id, nome, corpo, ruolo monte/valle). Senza coordinate.

**Stop.** Nessuna segmentazione. Si attendono le coordinate.

### STEP 2 — Umano, coordinate dei capisaldi

L’utente fornisce le coordinate WGS84 dei capisaldi dello STEP 1. Vanno scritte in `data/geojson/capisaldi_verificati.json`:

```json
"ponte_grantola": {
  "lat": 45.948302,
  "lon": 8.769516,
  "nome": "Ponte di Grantola",
  "corpo_idrico": "margorabbia"
}
```

`corpo_idrico` è facoltativo se l’id è già `monte` o `valle` di un taglio nel grafo. Un punto senza coordinate non spezza nulla. In alternativa lo script accetta un GeoJSON di `Point` con `id` (o `caposaldo_id`), `nome` e `corpo_idrico` nelle properties: le coordinate GeoJSON sono `[lon, lat]`.

Non si scarica geometria e non si scelgono codici OSM.

### STEP 3 — AI, segmentazione dinamica

**Input.** Il reticolo regionale, il grafo normativo e i capisaldi dello STEP 2.

**Compito.** Eseguire:

```text
py -3 scripts/segmenta_rete.py
```

Lo script non chiama API. Legge le linee locali, scarta ciò che è fuori dai tre sottobacini del Bacino 5, proietta ogni caposaldo sul punto più vicino della linea del suo corpo e la taglia con Shapely (`split` sul vertice proiettato). A ogni pezzo incolla gli attributi risolti dalla matrice (regime, classe, `segmento_id`, `bank`, blocco regole). Un caposaldo a più di 300 m dalla linea non taglia: resta nel report. I poligoni lacustri non si spezzano; ricevono le regole del corpo e, se c’è, il taglio `intero_corpo`.

Filtri utili: `--corpo margorabbia`, `--rete`, `--laghi`, `--capisaldi`, `--max-snap-m`. `--elenco` non scrive file.

**Output.** `data/geojson/reticolo_segmentato.geojson` e `data/geojson/segmentazione_report.json` (abbinamenti, composti non assegnati, corpi senza geometria, capisaldi non proiettati, segmenti non applicati). Se serve guardare la mappa, anche `preview/{nome_area}_impalcatura.html`.

**Stop.** Nessuna pubblicazione su GitHub Pages e nessuna riscrittura di `docs/geo_data.js`. Si attende la conferma sul layer e sul report.

### STEP 4 — AI, build e deploy dei layer validati

**Input.** La conferma dell’utente sullo STEP 3.

**Compito.**

1. Rigenerare il bundle Leaflet dai layer confermati: `py -3 scripts/segmenta_rete.py --pubblica-leaflet`. Scrive `docs/geo_data.js` con gli stessi nomi globali che `docs/index.html` già legge.
2. Validare la cascata: `py -3 scripts/regole.py --verifica`. Controllare il report: nessuno snap oltre soglia lasciato senza spiegazione, `bank` sui segmenti lineari nuovi, nessuna geometria fuori dai tre sottobacini.
3. Predisporre il commit Git per GitHub Pages (branch `main`, sorgente `/docs`). Il commit si esegue solo se l’utente lo chiede in modo esplicito.

**Output.** Mappa aggiornata in locale e, dopo il commit richiesto, su https://dan-mi997.github.io/webgis-bacino5-pesca/.

---

## Regole di stop

| Dopo | Chi attende | Cosa non si fa |
| --- | --- | --- |
| STEP 0 | — | Non si segmenta un file che non è ancora al percorso canonico |
| STEP 1 | L’umano, con le coordinate dei capisaldi | Non si tagliano le linee e non si pubblica |
| STEP 3 | L’umano, sul layer segmentato e sul report | Non si riscrive `docs/geo_data.js` e non si marca verificato un punto che l’utente non ha dato |
| STEP 4 | — | Il commit parte solo su richiesta esplicita. Nessuna chiamata a OpenStreetMap |
