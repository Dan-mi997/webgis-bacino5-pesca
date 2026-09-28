# Protocolli operativi — WebGIS Bacino 5

Procedura unica per ogni nuova area (Ceresio, Lario, sottobacini successivi). Gli step sono rigidi: uno step AI si ferma e attende l’umano; non si anticipa lo step seguente.

Pilota già ingerito con la pipeline precedente: reticolo Margorabbia. Da questo protocollo in poi ogni area nuova lo segue per intero.

---

## Invarianti architetturali permanenti

Valgono per ogni step e per ogni bacino. Non si derogano in una singola area.

### 1. Perimetro territoriale del Bacino 5

Si cartografano solo acque nelle province di **Varese, Como e Lecco**.

Restano fuori, senza eccezioni:

- acque territoriali svizzere e del Canton Ticino;
- la provincia di Sondrio.

Su un corpo di confine (Ceresio, Tresa, Lario dove il confine taglia lo specchio) entra nel grafo solo la parte italiana. La geometria svizzera non si importa, non si clippa e non si pubblica. Se il file grezzo la contiene, si scarta in STEP 3.

### 2. Supporto topologico delle sponde

Ogni segmento normativo lineare porta la proprietà obbligatoria `bank`:

| Valore | Significato |
| --- | --- |
| `both` | Entrambe le sponde, o il prontuario non distingue |
| `left` | Solo sponda sinistra, nel senso di scorrimento (monte → valle) |
| `right` | Solo sponda destra, nello stesso senso |

`left` e `right` sono idrografici, non «a est / a ovest» sulla mappa. Un divieto o un no-kill che cita una sola sponda non si estende all’altra: o si taglia la geometria, o si registrano due segmenti con `bank` diverso. I poligoni (specchi) non usano `bank`; distinguono sponda e natante con la modalità di pesca già prevista dalla matrice.

Il pilota Margorabbia è precedente a questa proprietà: i tratti già pubblicati vanno trattati come `both` finché un passo di allineamento non la scrive. Ogni area nuova la compila già in STEP 3.

### 3. Campi gara fuori perimetro

Dal 2026-09-28 i campi gara non sono oggetto del WebGIS. Non si elencano nello STEP 1, non si cercano i capisaldi, non si disegnano overlay. Restano nel prontuario come testo. Il pilota Margorabbia ha già un overlay pubblicato: non si estende e non fa da modello per le aree nuove.

### 4. Mappa di impalcatura

Dopo l’identificazione teorica dei punti, prima della conferma, la mappa si vede comunque. Sta in `preview/{nome_area}_impalcatura.html` (il Ceresio: `preview/ceresio_impalcatura.html`). I punti indicati si mostrano anche se la geometria è ancora provvisoria: serve a capire lo stato e a confermarli. Non è la pubblicazione. Niente `verificato: true`, niente commit, niente GitHub Pages finché la conferma non è arrivata. La cartella `preview/` non è la sorgente di GitHub Pages.

---

## Percorsi canonici

| Cosa | Percorso |
| --- | --- |
| Prontuario | `data/raw/` |
| Geometrie grezze dell’area | `data/raw/{nome_area}_raw.geojson` |
| Grafo normativo | `data/normativa/struttura_dati_regole.json` |
| Dizionari (calendari, documenti, specie, blocchi) | `data/normativa/margorabbia_regole.json` |
| Pipeline | `scripts/build_geo_data.py` |
| Layer intermedi | `data/geojson/` |
| Web app pubblicata (GitHub Pages, cartella `/docs`) | `docs/index.html`, `docs/geo_data.js` |
| Capisaldi confermati | `data/geojson/capisaldi_verificati.json` |

`{nome_area}` è uno slug stabile, minuscolo, senza spazi (es. `ceresio`, `lario`). La cartella `web/data/` non esiste: i layer che la mappa legge sono `data/geojson/` e il bundle `docs/geo_data.js`.

---

## Standard Operating Procedure (SOP) — Aggiunta nuovi corpi idrici

### STEP 1 — AI, ricognizione normativa

**Input.** Nome dell’area o del sottobacino indicato dall’utente.

**Compito.** Analizzare il prontuario e restituire unicamente:

1. Elenco dei corsi e degli specchi menzionati esplicitamente, con le eccezioni normative (divieti, no-kill, riserve) e il vincolo di sponda `bank` (`left` / `right` / `both`). I campi gara non si elencano e non si geometrizzano.
2. Elenco dei corpi idrici principali non menzionati che, nel perimetro VA–CO–LC, ereditano le regole generali di base.

**Output.** Tabella dei toponimi esatti (nome di prontuario, alias OSM se già noto, `bank`, eccezione o «eredita la base»).

**Stop.** Nessuna geometria, nessuno script, nessun aggiornamento del JSON normativo. Si attende il file grezzo.

### STEP 2 — Umano, estrazione delle geometrie grezze

L’utente estrae da Overpass Turbo il GeoJSON pulito dei toponimi dello STEP 1 e lo salva in:

`data/raw/{nome_area}_raw.geojson`

Il file contiene solo i corpi dello STEP 1 che ricadono nel perimetro italiano (VA, CO, LC).

### STEP 3 — AI, integrazione dati e clipping geometrico

**Input.** `data/raw/{nome_area}_raw.geojson` e il prontuario.

**Compito.**

1. Aggiornare `data/normativa/struttura_dati_regole.json` con la matrice (regime amministrativo + classe biologica), le eccezioni locali e i tagli dell’area. Ogni segmento lineare riceve `bank`.
2. Aggiornare ed eseguire `scripts/build_geo_data.py`, spezzando le geometrie sui capisaldi noti (ponti, briglie, confini, confluenze). I campi gara non si disegnano. Le deroghe temporanee diverse dai campi gara restano overlay: non tagliano la geometria base.
3. Segnare coordinate ambigue o capisaldi non univoci. I pin già presenti in `capisaldi_verificati.json` non si rimettono in discussione.
4. Scrivere la mappa di impalcatura in `preview/{nome_area}_impalcatura.html`, con i punti identificati in teoria anche se non sono ancora confermati.

**Output.** Tabella dei capisaldi incerti o da verificare, con coordinate stimate e il motivo del dubbio. Mappa di impalcatura apribile in locale.

**Stop.** Nessuna pubblicazione su GitHub Pages e nessun `verificato: true`. Si attende la conferma sui punti, guardando la mappa.

### STEP 4 — Umano, validazione dei capisaldi

L’utente verifica i punti critici e fornisce le coordinate definitive. Vanno scritte in `data/geojson/capisaldi_verificati.json` (`verificato: true`). Un punto senza conferma resta fuori dalla geometria pubblicata.

### STEP 5 — AI, compilazione finale, validazione e deploy

**Compito.**

1. Rigenerare i layer definitivi consumati dalla web app: `data/geojson/` e `docs/geo_data.js` (`py -3 scripts/build_geo_data.py`).
2. Validare la consistenza: `py -3 scripts/regole.py --verifica`, controllo topologico della pipeline (anomalie a zero o spiegate), presenza di `bank` su ogni segmento lineare nuovo, nessuna geometria fuori da VA–CO–LC.
3. Predisporre il commit Git per GitHub Pages (branch `main`, sorgente `/docs`). Il commit si esegue solo se l’utente lo chiede in modo esplicito.

**Output.** Mappa aggiornata in locale e, dopo il commit richiesto, su https://dan-mi997.github.io/webgis-bacino5-pesca/.

---

## Regole di stop

| Dopo | Chi attende | Cosa non si fa |
| --- | --- | --- |
| STEP 1 | L’umano, con il GeoJSON grezzo | Non si cercano geometrie OSM e non si modifica il grafo |
| STEP 3 | L’umano, con i capisaldi confermati sulla mappa di impalcatura | Non si pubblica su GitHub Pages e non si marca `verificato: true` al posto dell’utente |
| STEP 5 | — | Il commit parte solo su richiesta esplicita |
