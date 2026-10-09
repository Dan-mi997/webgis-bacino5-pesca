# Memoria del progetto FIPSAS

Documento vivo: aggiornarlo al termine di ogni sessione di lavoro sostanziale.  
Serve alle chat successive per riprendere il contesto senza ricostruire tutto da zero.

**Ultimo aggiornamento:** 2026-10-09 tardi (Brinzio e Brivola a diritti esclusivi, interno del Piano azzurro, fasce e no-kill dai capisaldi già misurati)

---

## Perimetro del WebGIS

Queste quattro righe guidano ogni elaborazione successiva.

- **Obiettivo finale:** WebGIS della pesca sportiva per l’intera Regione Lombardia.
- **Focus attuale:** Bacino 5, acque di competenza regionale delle province di **Varese, Como e Lecco**. Tassativamente escluse le acque in territorio svizzero / Canton Ticino e quelle della provincia di Sondrio.
- **Completato:** Torrente Margorabbia (pilota). Bacino del Ceresio pubblicato il 2026-09-28: parte italiana del lago, Lago di Piano, Tresa, Cuccio, Rezzo, Soldo, Trallo, Telo, Lirone, Canale Lagadone.
- **In lavorazione:** i punti ancora da misurare e i corsi assenti dal reticolo. Laghi di Varese, Comabbio, Monate, Lario, Verbano, Ceresio e i fiumi di limite sono in mappa con classe e permesso.

Il prontuario di riferimento resta *Prontuario bacino 5 – Verbano Ceresio e Lario (2026)* (Regione Lombardia / ATS Prealpi – FIPSAS). Protocollo: `WORKFLOW_PROTOCOLS.md`.

**Geometrie, dal 2026-10-09.** La mappa in `docs/` ha 413 feature. Le linee disegnate a mano stanno in `data/geojson/AcqueLombardia/integrazioni.geojson` e si uniscono al Geoportale in lettura. Ogni lago è due entità: costa (`sponda`, LineString sulla costa reale) e interno (`natante`, poligono). I fiumi restano linee. `py -3 scripts/segmenta_rete.py --pubblica-leaflet` riscrive `docs/geo_data.js`.

Classi paritetiche: **A, B, C, CISPP**. Niente `fuori_cap4` e niente regime Italo-Svizzera. Verbano, Ceresio e Tresa prendono le regole solo dal Capitolo 5 del prontuario. Il regime amministrativo è solo `fipsas` o `diritti_esclusivi`. Mai «libera».

Diritti esclusivi, con geometria: Pusiano, Segrino, Montorfano, Monate e Comabbio interi (sponda e natante). Varese: sponda FIPSAS (contributo ridotto), natante esclusivo (Cooperativa, importo assente). Annone: il bacino est è tutto esclusivo Citterio (vincolo `parte_regionale` sul poligono «Annone Est»). La retta fra `[45.8196464, 9.3397611]` e `[45.8196905, 9.3240939]` taglia solo il bacino ovest: nord FIPSAS, sud Citterio.

Lugano: `lago_lugano` (CISPP, permessi varesini) è ormai solo il bacino sud e il bacino di Ponte Tresa. Il bacino nord (`lago_lugano_nord`, scelto dal qualificatore del nome regionale «bacino nord») e Campione d’Italia (`lago_lugano_campione`, i pezzi dentro l’enclave del confine lombardo) sono classe A con i permessi di Como, riva `fipsas_co_lc_riva` e barca `fipsas_co_lc_barca`. Le foci di Rezzo, Soldo, Telo e Cuccio sono passate al bacino nord.

Lario: 57 aree di ormeggio (p. 39–40), divieto dal 1° dicembre al 30 aprile. Il prontuario non dà un perimetro: cerchio di 50 m attorno al pin, marcato `raggio_stimato`. Il periodo vietato è un `periodo_speciale` con `vietata: true`. Sulla mappa normale l’area ha il colore della zona; diventa rossa solo dal 1° dicembre al 30 aprile, in base alla data scelta. Con «Colora la mappa per data/ora» vale il calendario intero (verde o rosso). Il tratteggio nero è solo per una regola tecnica (no-kill, tecniche, prelievo), non per il solo diritto esclusivo. Verbano, zona Ranco/Angera: poligono sui quattro vertici, lati di terra sulla costa e lati d’acqua sul confine regionale (~14,6 km²). Uso civico Pescarenico: Adda, sponda sinistra idrografica, centerline di 1111 m dal punto fino al Garlate. Sul Garlate la zona è un triangolo sulla sponda est: costa da `[45.838846, 9.399603]` a `[45.814915, 9.419778]`, poi rette al vertice d’acqua `[45.812187, 9.413738]` e di nuovo al primo punto (`vertici_acqua` in `poligono_due_punti_costa`), circa 1,1 km². Lago di Brinzio (tipo C) e Rio Brivola (tipo B) sono diritti esclusivi dell'Associazione Pescatori Dilettanti di Brinzio: costa e rio arancio, interno del lago rosso perché il par. 4.9 non consente il natante. Il tratto del rio dal ponte di via Piave alla confluenza con il Valmolina è divieto (653 m disegnati, prontuario circa 980). Lago di Piano: la riva resta gialla (`fipsas_co_lc_riva`); l'interno è azzurro (`fipsas_co_lc_barca`, contributo 30 €) perché il par. 4.9 ammette il natante. Il motore resta vietato.

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

`docs/index.html` + `docs/geo_data.js` (generato). Nel prelievo, accanto alla taglia, c’è il periodo di divieto della specie (par. 4.4) quando il dizionario lo ha. Sulle acque di tipo A non compare il fermo di trota fario e marmorata. Su CISPP la scheda dice che i periodi del Capitolo 5 non sono ancora inseriti. Due viste mutuamente esclusive: **Categoria** (A, B, C, CISPP, un solo tratto neutro `#334155`, senza colore per classe) e **Permessi** (esclusivi arancio `#f97316`, FIPSAS base giallo `#facc15`, contributo ridotto verde `#22c55e`, contributo intero azzurro `#38bdf8`, tesserino Maggiore rosa `#f472b6`). I divieti permanenti restano rossi (`#dc2626`) anche a layer spenti. Un divieto solo stagionale ha il colore della zona fuori dal suo periodo. Le segmentazioni parziali tengono il colore della sezione e un tratteggio alternato con il nero. Costa e interno sono feature distinte; il popup lo dice. «Posso pescare?» colora la base.

---

## Cosa è ancora aperto / da non dimenticare

- Dal 2026-10-09 tardi i capisaldi già misurati che chiudevano un tratto sono in mappa, dove la geometria lo permette. Nuovi: tutele del Lario (Inganna, Varenna, Fiumelatte, Mandello, Menaggio, Dongo, Laglio, foci di Adda Liro e Livo, limitazioni di Dervio e Bellano), divieto di costa a Villa Monastero (manca lo specchio fino a metà lago), canneto Brebbia–Ispra, insenatura Partegora, foce del Giona (50 m) e divieto sul torrente (348 m), Bevera di Varese Cantello–Gissone, no-kill di Varrone, Breggia e Pioverna (517 m disegnati, prontuario circa 800). Fiumelatte, Mandello e Dervio sono stagionali (1° marzo–10 agosto) ma il tratteggio resta tutto l’anno: la data è nella scheda. Non disegnati: Meria no-kill (i due capi stanno su pezzi scollegati), tutela dell’Adda a Olginate (i punti distano 1,5 km dalla centerline), Argegno (manca il punto a 100 m a nord della foce del Telo), Lambro no-kill e Lambro immissario (manca la cabina Enel), Caldone e Troggia fino alle sorgenti, riserva del Pioverna e del Livo (manca il punto a 200 m), Varrone a esche artificiali (manca la briglia a 900 m), foce del Tresa nel Verbano (raggio non misurato).
- Aree di ormeggio del Lario: i 50 m sono una stima. Vanno sostituiti con il perimetro reale dei porti; i primi 28 pin sono indicati come non del tutto certi. La tabella par. 4.4 nel dizionario ha trota fario, marmorata, barbo, carpa e luccio; il prontuario dice «ecc.», quindi altri fermi di specie non sono in scheda. Il verde/rosso della mappa non applica ancora questi fermi.
- Il raggio del divieto Cuccio (metà alveo + 50 m) non è misurato e non è disegnato. Il canneto di Lavena resta a 442 m dalla costa clippata. L’Adda di Pescarenico è la centerline marcata sponda sinistra, 1111 m, e arriva al Garlate; non è un offset di sponda rilevato. `outlet_ghirla` e `chiusa_enel` ora cadono sul Margorabbia in uscita dal Ghirla (snap 3 m e 5 m). I campi gara restano overlay, con vincolo fra capisaldi, e non sono nel GeoJSON pubblicato.
- Dal 2026-10-09 notte: il Soldo regionale è la Solda (Ceresio). Il Nosee è la Valle Nosè del geoportale, unita in un solo nome con la Valle Marvia, e si immette nella Valle di Toff; il divieto di 300 m a monte è disegnato (circa 270 m sulla centerline, confluenza non del tutto certa). Il tratto che esce dal Ghirla, prima chiamato Grantorella–Margorabbia, è solo Margorabbia; i rami a sud del lago restano Grantorella. La Roggia Barona di Acquanegra non è stata aggiunta. Integrazioni: Lisascora, Rialto, Brugo, Roggia di Alserio, Trallo, Tinella, Tarca, Brinzio, Brivola, Valmolina, Viganella, Lanza/Gaggiola (solo a monte della S.P. 342), Chiesone/Gesone, Boggione, Serio sul Lario. Brinzio e Brivola non sono più predisposti. Brugo, Rialto, Roggia di Alserio e Valmolina sono divieto sull’intero corso disegnato. Tarca è in mappa ma il divieto di 250 m è ancora da misurare. Il Serio disegnato sbocca nel Lario (non è il Serio bergamasco) e prende la classe B di chiusura, senza scheda propria. La Gallavesa manca ancora. Il controllo del 2026-10-07 aveva segnalato assenti Tinella, Trallo, Soldo, Chiesone, Boggione, Lanza, Gallavesa, Nosee, Valmolina e Brivola. Il Meria c’è come Valle Meria e arriva al lago. Adda, Ticino, Olona, Lambro, Lura, Seveso e la Bevera di Cantello arrivano al limite del bacino. Il Rezzo è assegnato dal nome composto con la Valle del Cagna. Grantorella e Rancina pure, dal nome composto, con i giorni tipo B.
- Estratto integrale del prontuario (2026-10-06): `data/normativa/estratto_bacino5_2026.json`. In `capisaldi_verificati.json` ci sono 155 punti: i 20 di Margorabbia e Ceresio, 78 estremi di regola e tutti i 57 ormeggi del Lario (senza corpo idrico, quindi non spezzano la rete). I primi 28 ormeggi e alcuni estremi di regola del 2026-10-07 sono indicati come non del tutto certi. Contenitori a parte, anche con coordinata già inserita, e fuori dai capisaldi: pesca subacquea (23, uso `subacquea`) e zone riservate alla pesca dilettantistica (19, uso `dilettantistica`). Restano tra le regole la scalinata del Minigolf (apre la tutela di Menaggio) e la foce del Liro (chiude la tutela della foce). A Musso la zona dilettantistica è tutto il litorale comunale, senza estremi nominati. Restano 11 estremi di regola da misurare. Il Nosee si immette nel Tuf: il prontuario scrive Toff. Fuori dai capisaldi: San Bernardino a Intra (Piemonte); Sasso di Dascio e la foce del Mera pinata a Dascio di Sorico (Sondrio). Il grafo `struttura_dati_regole.json` non è ancora allargato: la segmentazione del 2026-10-07 disegna tutto il reticolo, ma i capisaldi nuovi non spezzano Lario, Verbano e gli sbocchi perché quei corpi non sono nel grafo. Il canvas precompila i punti che hanno già lat e lon; le bozze non archiviate si perdono quando il canvas viene rigenerato.
- Lago di Varese, Comabbio e Monate sono in mappa. Comabbio e Monate: diritti esclusivi, solo residenti rivieraschi, natante vietato. La barca del Varese è il permesso della Cooperativa, senza importo nel prontuario.
- Grantorella: i rami a sud del Ghirla restano il torrente Grantorella (giorni tipo B). L’asta in uscita dal lago è il Margorabbia.
- Giorni sull’asta vs affluenti: **interpretazione** (deroga Tresa sull’asta; tipo B sugli affluenti).
- Protocollo: `WORKFLOW_PROTOCOLS.md` (STEP 0–4). Niente Overpass. STEP 1 estrae regole e capisaldi di tutto il prontuario; STEP 2 sono le coordinate; STEP 3 segmenta; STEP 4 pubblica solo dopo conferma. `bank` obbligatoria sui segmenti lineari nuovi; il pilota Margorabbia è ancora implicito `both`.
- Ceresio pubblicato. Lirone intero (9,5 km) fino alla foce confermata 46.009072, 9.084980: è la foce che il prontuario chiama Telo; il cerchio da 50 m è solo la parte di specchio. Il Telo OSM resta a monte e non arriva a riva. Lagadone 2,6 km, non citato nel prontuario, in mappa come tipo B. Canneto di Lavena: 438 m sulla riva tra i due estremi, divieto; la fascia d'acqua fino ai gavitelli non è disegnata. Tresa tagliato a riva del Verbano (tolti circa 1,8 km di centerline che entrava nel lago; la punta resta a 8.72638, 45.99685). Divieto Lavena ~199 m, sponda sinistra idrografica (sud). Trallo ponte–foce 650 m (prontuario ~500). Foce Tresa nel Verbano e raggio del Cuccio (metà alveo + 50 m) ancora aperti. Campi gara fuori. Sponda svizzera esclusa.
- Senza geometria regionale restano la Barona (tenuta da parte) e il Rio Boesio. La riva di Sondrio sul Lario non è clippata: il sottobacino non ha la provincia. Zone subacquee e dilettantistiche restano fuori.
- Il sottobacino «Lago di Como (Lario)» non ha un attributo di provincia: un affluente in Sondrio classificato lì non è ancora clippato.
- La pipeline OpenStreetMap è in `old/` (script, scarichi, tratti, overlay, anteprime, cache). `docs/` è la mappa del Bacino 5 pubblicata il 2026-10-07. Si rigenera con `py -3 scripts/segmenta_rete.py --pubblica-leaflet`. `py -3 scripts/regole.py --verifica` controlla il grafo.
- Il CLI `regole.py --zona` non è la cascata nuova: usare `--matrice` / `--verifica`.
- Identità git locale usata al primo commit: `Daniele` / `daniele@users.noreply.github.com` (senza scrivere la git config globale). Git/`gh` portable in `%LOCALAPPDATA%\Programs\MinGit` e `...\gh`.
- Non committare `old/cache/` né `__pycache__`.

---

## Come aggiornare questo file

Dopo un lavoro che cambia dati, capisaldi, regole, mappa o pubblicazione: aggiornare la data in cima, i punti salienti e la sezione «aperto». Non duplicare changelog minuti: solo decisioni e stato.
