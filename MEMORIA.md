# Memoria del progetto FIPSAS

Documento vivo: aggiornarlo al termine di ogni sessione di lavoro sostanziale.  
Serve alle chat successive per riprendere il contesto senza ricostruire tutto da zero.

**Ultimo aggiornamento:** 2026-10-09 (classi A/B/C/CISPP, sponda e natante separati, diritti esclusivi geometrici, viste mappa)

---

## Perimetro del WebGIS

Queste quattro righe guidano ogni elaborazione successiva.

- **Obiettivo finale:** WebGIS della pesca sportiva per l’intera Regione Lombardia.
- **Focus attuale:** Bacino 5, acque di competenza regionale delle province di **Varese, Como e Lecco**. Tassativamente escluse le acque in territorio svizzero / Canton Ticino e quelle della provincia di Sondrio.
- **Completato:** Torrente Margorabbia (pilota). Bacino del Ceresio pubblicato il 2026-09-28: parte italiana del lago, Lago di Piano, Tresa, Cuccio, Rezzo, Soldo, Trallo, Telo, Lirone, Canale Lagadone.
- **In lavorazione:** i punti ancora da misurare e i corsi assenti dal reticolo. Laghi di Varese, Comabbio, Monate, Lario, Verbano, Ceresio e i fiumi di limite sono in mappa con classe e permesso.

Il prontuario di riferimento resta *Prontuario bacino 5 – Verbano Ceresio e Lario (2026)* (Regione Lombardia / ATS Prealpi – FIPSAS). Protocollo: `WORKFLOW_PROTOCOLS.md`.

**Geometrie, dal 2026-10-09.** La mappa in `docs/` ha 208 feature. Ogni lago è due entità: costa (`sponda`, LineString sulla costa reale) e interno (`natante`, poligono). I fiumi restano linee. `py -3 scripts/segmenta_rete.py --pubblica-leaflet` riscrive `docs/geo_data.js`.

Classi paritetiche: **A, B, C, CISPP**. Niente `fuori_cap4` e niente regime Italo-Svizzera. Verbano, Ceresio e Tresa prendono le regole solo dal Capitolo 5 del prontuario. Il regime amministrativo è solo `fipsas` o `diritti_esclusivi`. Mai «libera».

Diritti esclusivi, con geometria: Pusiano, Segrino, Montorfano, Monate e Comabbio interi (sponda e natante). Varese: sponda FIPSAS (contributo ridotto), natante esclusivo (Cooperativa, importo assente). Annone tagliato dalla retta fra `[45.8196464, 9.3397611]` e `[45.8196905, 9.3240939]`: nord FIPSAS, sud esclusivo (Citterio). Verbano, zona Ranco/Angera: poligono sui quattro vertici, lati di terra sulla costa e lati d’acqua sul confine regionale (~14,6 km²). Uso civico Pescarenico: Adda, sponda sinistra idrografica, centerline di 1111 m dal punto fino al Garlate; sul Garlate il poligono chiuso sulla costa. Lago di Brinzio e Rio Briviola sono nel grafo con `stato: predisposto`, senza regole e senza geometria.

**Pubblicazione**
- Repo: https://github.com/Dan-mi997/webgis-bacino5-pesca
- Mappa: https://dan-mi997.github.io/webgis-bacino5-pesca/
- Sorgente Pages: branch `main`, cartella `/docs`

---

## Struttura delle cartelle

```
data/raw/                         Prontuario PDF
data/normativa/                   estratto, struttura_dati_regole.json (matrice), margorabbia_regole.json (dizionari)
data/geojson/AcqueLombardia/      Fiumi.json + Laghi.json (Geoportale, intera Lombardia)
data/geojson/                     capisaldi_verificati.json, reticolo_segmentato.geojson, segmentazione_report.json
scripts/                          segmenta_rete.py e regole.py
docs/                             frontend Leaflet pubblicato (GitHub Pages)
preview/                          vista di controllo, prima dello STEP 4
old/                              pipeline OpenStreetMap e i suoi prodotti
```

Segmentazione: `py -3 scripts/segmenta_rete.py` (`--elenco` non scrive; `--pubblica-leaflet` solo allo STEP 4). Percorsi in `scripts/config.py`. I capisaldi stanno in `data/geojson/capisaldi_verificati.json`.

---

## Schema normativo

Due file, una cascata. `struttura_dati_regole.json` è il grafo (Bacino 5). `margorabbia_regole.json` resta il dizionario (calendari, documenti, specie, blocchi). Motore: `Matrice` in `scripts/regole.py`. Controllo: `py -3 scripts/regole.py --verifica`.

1. **Matrice** — schema 3.0.0. Classe biologica A, B, C o CISPP (tecniche, periodi, misure). Regime amministrativo solo `fipsas` o `diritti_esclusivi` (permessi e costi). CISPP non è un regime: Verbano, Ceresio e Tresa usano i blocchi del Capitolo 5 (`cispp_lago` / `cispp_fiume`).
2. **Geometria** — un corpo, due entità sui laghi (`entita.sponda` e `entita.natante`). Ogni regola particolare è un segmento con `geometria_vincolo` (tratto A–B, semipiano, poligono sulla costa, raggio, fascia). I tagli spaziali stanno in `scripts/tagli_geometrici.py`. Ghirla non si spezza.
3. **Eccezioni locali** — solo i delta. Asta: tutti i giorni + temolo protetto. Ghirla: persico 18 e salmerino 30; belly boat solo in natante. Lago di Piano (tipo A, in mappa): libretto della Riserva. Pusiano (tipo A, diritto Egirent, no-kill) è in mappa. Lago di Varese: riva con contributo ridotto, barca con il permesso della Cooperativa.
4. **Tagli** — spezzano la linea: No-Kill, divieti. Ereditano 1–3 e applicano l’override restrittivo.
5. **Overlay** — deroga invernale. Non taglia la geometria. I campi gara, dal 2026-09-28, sono fuori perimetro: non si cercano e non si disegnano sulle aree nuove. Sul pilota Margorabbia l'overlay già pubblicato resta (Mesenzana sopra il No-Kill per ~505 m) e non si estende.

Il CLI `--zona` legge ancora le zone storiche del dizionario. La mappa no.

---

## Geografia (decisioni già prese)

- Solo **asta continua del Margorabbia** + affluenti **nominati**: Rancina, Gesone/Chiesone, Boggione, Rio Boesio, Grantorella. Ruscelli senza `name` scartati.
- **Niente corde** attraverso laghi o versanti: `linemerge` solo con contiguità reale (gap ≤ 60 m). I laghi restano poligoni chiusi. I tronchi a monte di Ghirla restano geometrie separate.
- **Chiesone = Gesone** (OSM). Ponte «S.P. 54» del prontuario identificato con la **S.S. 394** (45.950148, 8.765776). Ponte di via Pianazzo confermato. Divieto OSM ≈ **954 m** (prontuario ~970 m).
- **Lisascora:** divieto in normativa, **non in mappa** (nome assente da OSM, corso troppo piccolo).
- **Grantorella, Rancina, Rio Boesio:** non citati nel prontuario → residuale Ordinario B (giorni tipo B, non la deroga «tutti i giorni» dell’asta).

---

## Capisaldi

Tutti i capisaldi operativi sono **verificati a mano**. Lista in `capisaldi_verificati.json`: Margorabbia e, dal 2026-09-28, i punti del Ceresio.

Sull’asta, da monte a valle (dopo Ghirla): ponte Ghirla → chiusa Enel Ghetto (campo gara ~300 m) → Ponte Grantola (inizio No-Kill) → Carrefour Mesenzana (inizio campo gara) → briglia Passeri Opel (fine No-Kill) → Ponte del Cucco + 200 m (fine campo gara) → prima briglia foce → confluenza Tresa.

**Sovrapposizione No-Kill ∩ campo gara (~505 m):** la briglia Passeri è a valle del Carrefour. Il No-Kill resta un solo tratto. Il campo gara è un overlay (`old/geojson/margorabbia_overlay.geojson`), spezzato solo dove cambia il regime sotto (No-Kill / ordinario), senza tagliare l’asta. Toyota Mesenzana scartata.

Boggione: Monumento ai Caduti (ok) → attraversamento Marzio–Boarezzo (ok). Divieto ~2,1 km.

---

## Frontend

`docs/index.html` + `docs/geo_data.js` (generato). Due viste mutuamente esclusive: **Categoria** (A, B, C, CISPP, un solo tratto neutro `#334155`, senza colore per classe) e **Permessi** (esclusivi arancio `#f97316`, FIPSAS base giallo `#eab308`, contributo ridotto verde `#22c55e`, contributo intero azzurro `#38bdf8`, tesserino Maggiore rosa `#f472b6`). I divieti restano rossi (`#dc2626`) anche a layer spenti. Le segmentazioni parziali tengono il colore della sezione e un tratteggio alternato con il nero. Costa e interno sono feature distinte; il popup lo dice. «Posso pescare?» colora la base.

---

## Cosa è ancora aperto / da non dimenticare

- Dal 2026-10-09: Lago di Brinzio e Rio Briviola sono predisposti nel grafo (`stato: predisposto`) e aspettano le regole. Il raggio del divieto Cuccio (metà alveo + 50 m) non è misurato e non è disegnato. L’Adda di Pescarenico è la centerline marcata sponda sinistra, 1111 m, e arriva al Garlate; non è un offset di sponda rilevato. `outlet_ghirla` e `chiusa_enel` restano oltre la soglia di snap (~4 km). I campi gara restano overlay, con vincolo fra capisaldi, e non sono nel GeoJSON pubblicato.
- Controllo del 2026-10-07 sul reticolo regionale: mancano, tra gli altri, Tinella, Trallo, Soldo, Chiesone/Gesone, Boggione, Lanza, Gallavesa, Nosee, Valmolina e Brivola. Il Meria c’è come Valle Meria e arriva al lago. Adda, Ticino, Olona, Lambro, Lura, Seveso e la Bevera di Cantello arrivano al limite del bacino. Il Rezzo è assegnato dal nome composto con la Valle del Cagna. Grantorella e Rancina pure, dal nome composto, con i giorni tipo B.
- Estratto integrale del prontuario (2026-10-06): `data/normativa/estratto_bacino5_2026.json`. In `capisaldi_verificati.json` ci sono 155 punti: i 20 di Margorabbia e Ceresio, 78 estremi di regola e tutti i 57 ormeggi del Lario (senza corpo idrico, quindi non spezzano la rete). I primi 28 ormeggi e alcuni estremi di regola del 2026-10-07 sono indicati come non del tutto certi. Contenitori a parte, anche con coordinata già inserita, e fuori dai capisaldi: pesca subacquea (23, uso `subacquea`) e zone riservate alla pesca dilettantistica (19, uso `dilettantistica`). Restano tra le regole la scalinata del Minigolf (apre la tutela di Menaggio) e la foce del Liro (chiude la tutela della foce). A Musso la zona dilettantistica è tutto il litorale comunale, senza estremi nominati. Restano 11 estremi di regola da misurare. Il Nosee si immette nel Tuf: il prontuario scrive Toff. Fuori dai capisaldi: San Bernardino a Intra (Piemonte); Sasso di Dascio e la foce del Mera pinata a Dascio di Sorico (Sondrio). Il grafo `struttura_dati_regole.json` non è ancora allargato: la segmentazione del 2026-10-07 disegna tutto il reticolo, ma i capisaldi nuovi non spezzano Lario, Verbano e gli sbocchi perché quei corpi non sono nel grafo. Il canvas precompila i punti che hanno già lat e lon; le bozze non archiviate si perdono quando il canvas viene rigenerato.
- Lago di Varese, Comabbio e Monate sono in mappa. Comabbio e Monate: diritti esclusivi, solo residenti rivieraschi, natante vietato. La barca del Varese è il permesso della Cooperativa, senza importo nel prontuario.
- Grantorella, nel reticolo regionale, sta nel nome composto con il Margorabbia e in mappa è il corpo Grantorella (giorni tipo B).
- Giorni sull’asta vs affluenti: **interpretazione** (deroga Tresa sull’asta; tipo B sugli affluenti).
- Protocollo: `WORKFLOW_PROTOCOLS.md` (STEP 0–4). Niente Overpass. STEP 1 estrae regole e capisaldi di tutto il prontuario; STEP 2 sono le coordinate; STEP 3 segmenta; STEP 4 pubblica solo dopo conferma. `bank` obbligatoria sui segmenti lineari nuovi; il pilota Margorabbia è ancora implicito `both`.
- Ceresio pubblicato. Lirone intero (9,5 km) fino alla foce confermata 46.009072, 9.084980: è la foce che il prontuario chiama Telo; il cerchio da 50 m è solo la parte di specchio. Il Telo OSM resta a monte e non arriva a riva. Lagadone 2,6 km, non citato nel prontuario, in mappa come tipo B. Canneto di Lavena: 438 m sulla riva tra i due estremi, divieto; la fascia d'acqua fino ai gavitelli non è disegnata. Tresa tagliato a riva del Verbano (tolti circa 1,8 km di centerline che entrava nel lago; la punta resta a 8.72638, 45.99685). Divieto Lavena ~199 m, sponda sinistra idrografica (sud). Trallo ponte–foce 650 m (prontuario ~500). Foce Tresa nel Verbano e raggio del Cuccio (metà alveo + 50 m) ancora aperti. Campi gara fuori. Sponda svizzera esclusa.
- Pubblicazione del 2026-10-09: 208 feature in `docs/`. I laghi si spezzano in costa e interno; Annone, Ranco/Angera, Pescarenico e Garlate sono tagli geometrici. Senza geometria regionale: Barona, Boggione, Chiesone, Lisascora, Rio Boesio, Soldo, Tinella, Trallo, e i predisposti Brinzio e Briviola. La riva di Sondrio sul Lario non è clippata: il sottobacino non ha la provincia. Zone subacquee e dilettantistiche restano fuori.
- Il sottobacino «Lago di Como (Lario)» non ha un attributo di provincia: un affluente in Sondrio classificato lì non è ancora clippato.
- La pipeline OpenStreetMap è in `old/` (script, scarichi, tratti, overlay, anteprime, cache). `docs/` è la mappa del Bacino 5 pubblicata il 2026-10-07. Si rigenera con `py -3 scripts/segmenta_rete.py --pubblica-leaflet`. `py -3 scripts/regole.py --verifica` controlla il grafo.
- Il CLI `regole.py --zona` non è la cascata nuova: usare `--matrice` / `--verifica`.
- Identità git locale usata al primo commit: `Daniele` / `daniele@users.noreply.github.com` (senza scrivere la git config globale). Git/`gh` portable in `%LOCALAPPDATA%\Programs\MinGit` e `...\gh`.
- Non committare `old/cache/` né `__pycache__`.

---

## Come aggiornare questo file

Dopo un lavoro che cambia dati, capisaldi, regole, mappa o pubblicazione: aggiornare la data in cima, i punti salienti e la sezione «aperto». Non duplicare changelog minuti: solo decisioni e stato.
