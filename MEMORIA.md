# Memoria del progetto FIPSAS

Documento vivo: aggiornarlo al termine di ogni sessione di lavoro sostanziale.  
Serve alle chat successive per riprendere il contesto senza ricostruire tutto da zero.

**Ultimo aggiornamento:** 2026-10-07 (cartelle riordinate)

---

## Perimetro del WebGIS

Queste quattro righe guidano ogni elaborazione successiva.

- **Obiettivo finale:** WebGIS della pesca sportiva per l’intera Regione Lombardia.
- **Focus attuale:** Bacino 5, acque di competenza regionale delle province di **Varese, Como e Lecco**. Tassativamente escluse le acque in territorio svizzero / Canton Ticino e quelle della provincia di Sondrio.
- **Completato:** Torrente Margorabbia (pilota). Bacino del Ceresio pubblicato il 2026-09-28: parte italiana del lago, Lago di Piano, Tresa, Cuccio, Rezzo, Soldo, Trallo, Telo, Lirone, Canale Lagadone.
- **In lavorazione:** laghi di Varese, Comabbio e Monate. Dal 2026-10-06 la geometria è quella regionale (già nel layer segmentato, non pubblicato). Barona senza geometria. Divieti nel grafo, non tagliati sullo specchio. La foce del Tresa nel Verbano si chiude con il Lago Maggiore. Gli scarichi OSM di Varese e del Ceresio sono in `old/raw/`.

Il prontuario di riferimento resta *Prontuario bacino 5 – Verbano Ceresio e Lario (2026)* (Regione Lombardia / ATS Prealpi – FIPSAS). Protocollo: `WORKFLOW_PROTOCOLS.md`.

**Geometrie, dal 2026-10-06.** Non si interroga più OpenStreetMap. La rete è il GeoJSON del Geoportale regionale in `data/geojson/AcqueLombardia/` (`Fiumi.json`, `Laghi.json`): c’è tutta la Lombardia, lo scope resta il Bacino 5 (sottobacini Verbano, Ceresio, Lario). La segmentazione è `py -3 scripts/segmenta_rete.py`: spezza le linee sui capisaldi e incolla le regole del JSON. Il primo layer meccanico è `data/geojson/reticolo_segmentato.geojson` (44 feature, non pubblicato). `docs/geo_data.js` è ancora il pilota OSM.

Non è acqua «libera» con sola licenza B: le acque in concessione si indicano con il regime amministrativo (FIPSAS, Italo-Svizzera, Diritti esclusivi), mai «Libera».

Non è acqua «libera» con sola licenza B: tutte le acque mappate sono in **concessione FIPSAS**. In interfaccia si usa «Regime Ordinario B (FIPSAS)», mai «Libera».

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

1. **Matrice** — due attributi paralleli: regime amministrativo (FIPSAS, Italo-Svizzera, Diritti esclusivi → permessi e costi) e classe biologica (A, B, C → tecniche e periodi). Tresa = Italo-Svizzera + Cat. C: la classe resta un attributo, il regolamento operativo è il CISPP.
2. **Geometria** — linea = solo sponda. Poligono = una geometria, due fasci (sponda / natante). Ghirla non si spezza.
3. **Eccezioni locali** — solo i delta. Asta: tutti i giorni + temolo protetto. Ghirla: persico 18 e salmerino 30; belly boat solo in natante. Lago di Piano (tipo A, in mappa): libretto della Riserva. Pusiano e Lago di Varese restano esempi non disegnati.
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

`docs/index.html` + `docs/geo_data.js` (generato). Titolo: Bacino 5. Due GeoJSON Leaflet: tratti (tagli) e overlay tratteggiato (sul Margorabbia: campi gara e deroga invernale). Sul poligono il popup ha la scheda natante; la linea è solo sponda. «Posso pescare?» colora la base.

---

## Cosa è ancora aperto / da non dimenticare

- Controllo del 2026-10-07 sul reticolo regionale: mancano, tra gli altri, Tinella, Trallo, Soldo, Chiesone/Gesone, Boggione, Lanza, Gallavesa, Nosee, Valmolina e Brivola. Il Meria c’è come Valle Meria e arriva al lago. Adda, Ticino, Olona, Lambro, Lura, Seveso e la Bevera di Cantello arrivano al limite del bacino e stanno fuori dai tre sottobacini che la segmentazione tiene. Il Rezzo compare solo nel nome composto con la Valle del Cagna. La matrice ha ancora 28 corpi (pilota, Varese, Ceresio): Verbano, Lario e i fiumi appena misurati non hanno regime né classe.
- Estratto integrale del prontuario (2026-10-06): `data/normativa/estratto_bacino5_2026.json`. In `capisaldi_verificati.json` ci sono 155 punti: i 20 di Margorabbia e Ceresio, 78 estremi di regola e tutti i 57 ormeggi del Lario (senza corpo idrico, quindi non spezzano la rete). I primi 28 ormeggi e alcuni estremi di regola del 2026-10-07 sono indicati come non del tutto certi. Contenitori a parte, anche con coordinata già inserita, e fuori dai capisaldi: pesca subacquea (23, uso `subacquea`) e zone riservate alla pesca dilettantistica (19, uso `dilettantistica`). Restano tra le regole la scalinata del Minigolf (apre la tutela di Menaggio) e la foce del Liro (chiude la tutela della foce). A Musso la zona dilettantistica è tutto il litorale comunale, senza estremi nominati. Restano 11 estremi di regola da misurare. Il Nosee si immette nel Tuf: il prontuario scrive Toff. Fuori dai capisaldi: San Bernardino a Intra (Piemonte); Sasso di Dascio e la foce del Mera pinata a Dascio di Sorico (Sondrio). Il grafo `struttura_dati_regole.json` non è ancora allargato e la segmentazione non è stata rilanciata. Il canvas precompila i punti che hanno già lat e lon; le bozze non archiviate si perdono quando il canvas viene rigenerato.
- Lago di Varese non è più solo un esempio: è nel grafo con Comabbio, Monate, Bardello, Brabbia, Acquanegra, Tinella. `mappato` è ancora false. Pusiano resta esempio. Schede Cat. A complete non ingerite: la riva del Varese e gli alvei verdi usano il pacchetto ridotto; la barca del Varese è il permesso della Cooperativa, senza importo. Comabbio e Monate: diritti esclusivi, natante con pesca vietata.
- Grantorella è nel pilota pubblicato via toponimo OSM. Nel reticolo regionale compare solo nel nome composto con il Margorabbia: il layer segmentato non la assegna.
- Giorni sull’asta vs affluenti: **interpretazione** (deroga Tresa sull’asta; tipo B sugli affluenti).
- Protocollo: `WORKFLOW_PROTOCOLS.md` (STEP 0–4). Niente Overpass. STEP 1 estrae regole e capisaldi di tutto il prontuario; STEP 2 sono le coordinate; STEP 3 segmenta; STEP 4 pubblica solo dopo conferma. `bank` obbligatoria sui segmenti lineari nuovi; il pilota Margorabbia è ancora implicito `both`.
- Ceresio pubblicato. Lirone intero (9,5 km) fino alla foce confermata 46.009072, 9.084980: è la foce che il prontuario chiama Telo; il cerchio da 50 m è solo la parte di specchio. Il Telo OSM resta a monte e non arriva a riva. Lagadone 2,6 km, non citato nel prontuario, in mappa come tipo B. Canneto di Lavena: 438 m sulla riva tra i due estremi, divieto; la fascia d'acqua fino ai gavitelli non è disegnata. Tresa tagliato a riva del Verbano (tolti circa 1,8 km di centerline che entrava nel lago; la punta resta a 8.72638, 45.99685). Divieto Lavena ~199 m, sponda sinistra idrografica (sud). Trallo ponte–foce 650 m (prontuario ~500). Foce Tresa nel Verbano e raggio del Cuccio (metà alveo + 50 m) ancora aperti. Campi gara fuori. Sponda svizzera esclusa.
- Prima corsa della segmentazione regionale (2026-10-06), non pubblicata. Snap dei tagli già verificati: Margorabbia 0,9–5,4 m, Tresa 0,5–4,7 m. No-Kill Grantola–Mesenzana sulla centerline regionale: circa 1897 m. Il divieto di foce del Margorabbia non è applicato sulla geometria: `confluenza_tresa` è misurato, la segmentazione non è stata rilanciata. Nomi composti non assegnati: Grantorella–Margorabbia, Rancina–Caprera, Rezzo–Valle del Cagna. Senza geometria nel reticolo filtrato: Boggione, Chiesone, Lisascora, Barona, Rio Boesio, Soldo, Trallo, Tinella; Pusiano è nel Lambro, fuori dai tre sottobacini. I tagli sul poligono (canneto, foci, Schiranna) non spezzano lo specchio.
- Il sottobacino «Lago di Como (Lario)» non ha un attributo di provincia: un affluente in Sondrio classificato lì non è ancora clippato.
- La pipeline OpenStreetMap è in `old/` (script, scarichi, tratti, overlay, anteprime, cache). `docs/` resta la mappa pubblicata e non si rigenera da lì. `py -3 scripts/regole.py --verifica` e `py -3 scripts/segmenta_rete.py` sono i comandi attuali.
- Il CLI `regole.py --zona` non è la cascata nuova: usare `--matrice` / `--verifica`.
- Identità git locale usata al primo commit: `Daniele` / `daniele@users.noreply.github.com` (senza scrivere la git config globale). Git/`gh` portable in `%LOCALAPPDATA%\Programs\MinGit` e `...\gh`.
- Non committare `cache/http/` né `__pycache__`.

---

## Come aggiornare questo file

Dopo un lavoro che cambia dati, capisaldi, regole, mappa o pubblicazione: aggiornare la data in cima, i punti salienti e la sezione «aperto». Non duplicare changelog minuti: solo decisioni e stato.
