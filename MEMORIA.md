# Memoria del progetto FIPSAS

Documento vivo: aggiornarlo al termine di ogni sessione di lavoro sostanziale.  
Serve alle chat successive per riprendere il contesto senza ricostruire tutto da zero.

**Ultimo aggiornamento:** 2026-09-28

---

## Perimetro del WebGIS

Queste quattro righe guidano ogni elaborazione successiva.

- **Obiettivo finale:** WebGIS della pesca sportiva per l’intera Regione Lombardia.
- **Focus attuale:** Bacino 5, acque di competenza regionale delle province di **Varese, Como e Lecco**. Tassativamente escluse le acque in territorio svizzero / Canton Ticino e quelle della provincia di Sondrio.
- **Completato:** Torrente Margorabbia (pilota). Bacino del Ceresio pubblicato il 2026-09-28: parte italiana del lago, Lago di Piano, Tresa, Cuccio, Rezzo, Soldo, Trallo, Telo, Lirone, Canale Lagadone.
- **In lavorazione:** il resto del Bacino 5. La foce del Tresa nel Verbano si chiude con il Lago Maggiore.

Il prontuario di riferimento resta *Prontuario bacino 5 – Verbano Ceresio e Lario (2026)* (Regione Lombardia / ATS Prealpi – FIPSAS). Protocollo aree nuove: `WORKFLOW_PROTOCOLS.md`.

Non è acqua «libera» con sola licenza B: le acque in concessione si indicano con il regime amministrativo (FIPSAS, Italo-Svizzera, Diritti esclusivi), mai «Libera».

Non è acqua «libera» con sola licenza B: tutte le acque mappate sono in **concessione FIPSAS**. In interfaccia si usa «Regime Ordinario B (FIPSAS)», mai «Libera».

**Pubblicazione**
- Repo: https://github.com/Dan-mi997/webgis-bacino5-pesca
- Mappa: https://dan-mi997.github.io/webgis-bacino5-pesca/
- Sorgente Pages: branch `main`, cartella `/docs`

---

## Struttura delle cartelle

```
data/raw/            Prontuario PDF
data/normativa/      regolamento.md + struttura_dati_regole.json (matrice) + margorabbia_regole.json (dizionari)
data/geojson/        tratti, overlay, capisaldi
scripts/             pipeline Python
docs/                frontend Leaflet (GitHub Pages)
cache/               osm_cache_waterways.json (tenuta); cache/http/ (gitignore)
```

Rigenerazione: `py -3 scripts/build_geo_data.py`  
Percorsi centralizzati in `scripts/config.py`. I pin confermati in `data/geojson/capisaldi_verificati.json` hanno priorità su OSM.

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

**Sovrapposizione No-Kill ∩ campo gara (~505 m):** la briglia Passeri è a valle del Carrefour. Il No-Kill resta un solo tratto. Il campo gara è un overlay (`margorabbia_overlay.geojson`), spezzato solo dove cambia il regime sotto (No-Kill / ordinario), senza tagliare l’asta. Toyota Mesenzana scartata.

Boggione: Monumento ai Caduti (ok) → attraversamento Marzio–Boarezzo (ok). Divieto ~2,1 km.

---

## Frontend

`docs/index.html` + `docs/geo_data.js` (generato). Titolo: Bacino 5. Due GeoJSON Leaflet: tratti (tagli) e overlay tratteggiato (sul Margorabbia: campi gara e deroga invernale). Sul poligono il popup ha la scheda natante; la linea è solo sponda. «Posso pescare?» colora la base.

---

## Cosa è ancora aperto / da non dimenticare

- Lisascora solo testuale.
- Lago di Varese e Pusiano sono nel grafo come esempi, non in mappa. Schede permessi Cat. A complete e diritti esclusivi non ingerite (il Piano usa lo scheletro A più l'eccezione della Riserva).
- Grantorella in mappa per toponimo OSM; si può togliere da `MAJOR_TRIBUTARIES` se non si vuole.
- Giorni sull’asta vs affluenti: **interpretazione** (deroga Tresa sull’asta; tipo B sugli affluenti).
- Protocollo aree nuove: `WORKFLOW_PROTOCOLS.md` (5 step, stop dopo 1 e 3). Perimetro solo VA–CO–LC. Proprietà `bank` obbligatoria sui segmenti lineari nuovi; il pilota Margorabbia è ancora implicito `both`.
- Ceresio pubblicato. Lirone intero (9,5 km) fino alla foce confermata 46.009072, 9.084980: è la foce che il prontuario chiama Telo; il cerchio da 50 m è solo la parte di specchio. Il Telo OSM resta a monte e non arriva a riva. Lagadone 2,6 km, non citato nel prontuario, in mappa come tipo B. Canneto di Lavena: 438 m sulla riva tra i due estremi, divieto; la fascia d'acqua fino ai gavitelli non è disegnata. Tresa tagliato a riva del Verbano (tolti circa 1,8 km di centerline che entrava nel lago; la punta resta a 8.72638, 45.99685). Divieto Lavena ~199 m, sponda sinistra idrografica (sud). Trallo ponte–foce 650 m (prontuario ~500). Foce Tresa nel Verbano e raggio del Cuccio (metà alveo + 50 m) ancora aperti. Campi gara fuori. Sponda svizzera esclusa.
- Protocollo: `WORKFLOW_PROTOCOLS.md`. Dopo l'identificazione teorica dei punti la mappa di impalcatura si vede comunque, in `preview/`, prima della conferma.
- Il CLI `regole.py --zona` non è la cascata nuova: usare `--matrice` / `--verifica`.
- Identità git locale usata al primo commit: `Daniele` / `daniele@users.noreply.github.com` (senza scrivere la git config globale). Git/`gh` portable in `%LOCALAPPDATA%\Programs\MinGit` e `...\gh`.
- Non committare `cache/http/` né `__pycache__`.

---

## Come aggiornare questo file

Dopo un lavoro che cambia dati, capisaldi, regole, mappa o pubblicazione: aggiornare la data in cima, i punti salienti e la sezione «aperto». Non duplicare changelog minuti: solo decisioni e stato.
