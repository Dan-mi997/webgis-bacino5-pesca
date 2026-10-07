#!/usr/bin/env python3
"""Segmentazione dinamica sul reticolo ufficiale della Regione Lombardia.

Nessuna chiamata a OpenStreetMap. Lo script:

1. legge un GeoJSON locale di linee (default: Fiumi.json del Geoportale);
2. legge i poligoni dei laghi, se il file c'è;
3. tiene solo i sottobacini del Bacino 5;
4. legge un elenco di capisaldi (lat, lon);
5. spezza ogni linea nel punto più vicino a ciascun caposaldo, con Shapely;
6. incolla su ogni pezzo le regole risolte da struttura_dati_regole.json.

Uso:
  py -3 scripts/segmenta_rete.py --elenco
  py -3 scripts/segmenta_rete.py
  py -3 scripts/segmenta_rete.py --corpo margorabbia
  py -3 scripts/segmenta_rete.py --rete data/geojson/AcqueLombardia/Fiumi.json --capisaldi data/geojson/capisaldi_verificati.json
  py -3 scripts/segmenta_rete.py --self-test

Il layer Leaflet (docs/geo_data.js) si riscrive solo con --pubblica-leaflet,
dopo la validazione. Senza quel flag la mappa pubblicata non cambia.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import LineString, Point, shape
from shapely.ops import split

import config as cfg
from geo_utils import (
    feature,
    geom_distance_m,
    line_length_m,
    locate_m,
    point_feature,
    project_info,
    pt_dist_m,
    substring_m,
)
from regole import Matrice

# Un taglio a meno di così da un estremo non crea un moncone: il caposaldo
# resta il limite dell'intervallo, agganciato all'estremo.
_MIN_PEZZO_M = 15.0
_CLASSE = re.compile(
    r"^(fiume|torrente|lago|laghetto|canale|roggia|colatore|cavo)\s+"
    r"(di\s+|dello\s+|della\s+|dell'|dei\s+|degli\s+)?",
    re.IGNORECASE,
)
_NOME_TIPO = re.compile(r"^(.+?)\s*\(([^)]+)\)\s*$")


def _chiave(nome: str) -> str:
    s = re.sub(r"\s+", " ", nome.lower().replace("’", "'")).strip()
    return _CLASSE.sub("", s).strip()


def _parti_nome(nome: str) -> list[str]:
    """Idronimi di una feature regionale.

    «Grantorella (Torrente) - Margorabbia (Fiume)» ha due idronimi e non si
    assegna a un corpo solo. «Lugano (lago) - bacino nord» è un lago solo:
    il trattino è un qualificatore, non un secondo corso.
    """
    chunks = [c.strip() for c in re.split(r"\s+-\s+", (nome or "").strip()) if c.strip()]
    if not chunks:
        return []
    typed = []
    for chunk in chunks:
        match = _NOME_TIPO.match(chunk)
        typed.append(match.group(1).strip() if match else None)
    if len(chunks) > 1 and any(part is None for part in typed):
        return [typed[0] or chunks[0]]
    return [part if part is not None else chunk for part, chunk in zip(typed, chunks)]


def _chiavi_corpo(corpo: dict) -> set[str]:
    chiavi = set()
    etichette = [corpo.get("nome"), *(corpo.get("alias_osm") or []), *(corpo.get("alias_regionale") or [])]
    for raw in etichette:
        if not raw:
            continue
        for extra in re.findall(r"\(([^)]+)\)", raw):
            chiave = _chiave(extra)
            if chiave and chiave not in {"torrente", "fiume", "lago", "canale", "roggia"}:
                chiavi.add(chiave)
        base = re.sub(r"\([^)]*\)", " ", raw)
        chiave = _chiave(base)
        if chiave:
            chiavi.add(chiave)
    return chiavi


def _carica_fc(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    feats = data.get("features")
    if not isinstance(feats, list):
        raise ValueError(f"{path.name}: atteso un FeatureCollection")
    return feats


def _nel_bacino(props: dict) -> bool:
    return (props or {}).get("SOTTOBACIN") in cfg.SOTTOBACINI_BACINO_5


# Laghi del prontuario che il Geoportale mette fuori dai tre sottobacini.
_CORPI_FUORI_AMMESSI = {"pusiano", "garlate", "segrino", "alserio", "montorfano"}
_LAGHI_FUORI_SOTTOBACINO = {"garlate", "segrino", "alserio", "montorfano"}
# Idronimo regionale del tratto limite → corpo nel grafo. Il residuo non sta qui.
_IDRONIMO_CORPO = {
    "adda": "adda",
    "lambro": "lambro",
    "olona": "olona",
    "ticino": "ticino",
    "lura": "lura",
    "seveso": "seveso",
}
# Idronimo, caposaldo che chiude a valle, ancora (lon, lat) verso i laghi del bacino.
_LIMITI_VALLE = (
    ("adda", "ponte_lavello", (9.41, 45.82)),
    ("ticino", "ponte_sesto_calende", (8.70, 45.90)),
    ("olona", "ponte_vedano", (8.84, 45.84)),
    ("lambro", "ponte_nibionno", (9.27, 45.82)),
    ("lura", "sp342_lura", (9.00, 45.82)),
    ("seveso", "sp342_seveso", (9.05, 45.82)),
)
_NOTA_SENZA_SCHEDA = (
    "Geometria del reticolo regionale dentro il Bacino 5. "
    "La scheda del prontuario non è ancora nel grafo: non è acqua libera e il regime non è stato assegnato."
)


def _idronimo(nome: str) -> str | None:
    parti = _parti_nome(nome)
    if len(parti) != 1:
        return None
    chiave = _chiave(parti[0])
    return chiave or None


def _props_senza_scheda(nome: str, regionale: dict, geom, nota: str) -> dict:
    props = {
        "nome_tratto": nome,
        "corpo_idrico": "reticolo_" + re.sub(r"[^a-z0-9]+", "_", _chiave(nome) or "corso").strip("_"),
        "corpo_nome": nome,
        "layer": "reticolo",
        "scheda_inserita": False,
        "regime": "scheda_non_inserita",
        "regime_etichetta": "Nel reticolo, scheda non ancora inserita",
        "pesca_consentita": None,
        "geometria": geom.geom_type,
        "bank": "both" if geom.geom_type in ("LineString", "MultiLineString") else None,
        "fonte_geometria": "reticolo_regionale_lombardia",
        "nome_regionale": regionale.get("NOME"),
        "bacino_regionale": regionale.get("BACINO"),
        "sottobacino": regionale.get("SOTTOBACIN"),
        "cod_ptua16": regionale.get("COD_PTUA16"),
        "natura": regionale.get("NATURA"),
        "regole": {
            "regime": "scheda_non_inserita",
            "pesca_consentita": None,
            "note_corpo": nota,
        },
    }
    if props["bank"] is None:
        del props["bank"]
    if geom.geom_type in ("LineString", "MultiLineString"):
        parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        props["lunghezza_m"] = round(sum(line_length_m(p) for p in parts if p.geom_type == "LineString"))
    return props


def _linee_verso_ancora(line: LineString, pin: dict | None, anchor: tuple[float, float],
                        cappa_m: float | None = None) -> list[LineString]:
    """Tiene il tratto a monte del caposaldo di valle, quello più vicino ai laghi."""
    if pin is None or "lat" not in pin:
        return [line]
    _proj, _metri, dist = project_info(line, float(pin["lon"]), float(pin["lat"]))
    ancora = Point(anchor[0], anchor[1])
    if dist > cfg.MAX_SNAP_CAPOSALDO_M:
        if geom_distance_m(line.interpolate(0.5, normalized=True), ancora) + 200 >= geom_distance_m(Point(float(pin["lon"]), float(pin["lat"])), ancora):
            return []
        if cappa_m and line_length_m(line) > cappa_m * 2:
            _vicino, quota, _dist = project_info(line, anchor[0], anchor[1])
            totale = line_length_m(line)
            return [substring_m(line, max(0.0, quota - cappa_m), min(totale, quota + cappa_m))]
        return [line]
    pezzi = split_linea(line, [Point(float(pin["lon"]), float(pin["lat"]))])
    if len(pezzi) == 1:
        centro = line.interpolate(0.5, normalized=True)
        if geom_distance_m(centro, ancora) > geom_distance_m(Point(float(pin["lon"]), float(pin["lat"])), ancora) + 150:
            return []
        return pezzi

    def _mezzo(piece: LineString) -> float:
        centro = piece.interpolate(0.5, normalized=True)
        return geom_distance_m(centro, ancora)

    return [min(pezzi, key=_mezzo)]


def _pezzi_utili(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "LineString" and len(list(geom.coords)) >= 2:
        return [geom]
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiLineString", "MultiPolygon", "GeometryCollection"):
        out = []
        for part in geom.geoms:
            out.extend(_pezzi_utili(part))
        return out
    return []


def _tratto_kennedy(line: LineString, punti: dict) -> LineString | None:
    """Adda fra ponte Kennedy e ponte Manzoni, se entrambi cadono sulla linea."""
    a = punti.get("ponte_kennedy") or {}
    b = punti.get("ponte_manzoni") or {}
    if "lat" not in a or "lat" not in b:
        return None
    _pa, ma, da = project_info(line, float(a["lon"]), float(a["lat"]))
    _pb, mb, db = project_info(line, float(b["lon"]), float(b["lat"]))
    if da > cfg.MAX_SNAP_CAPOSALDO_M or db > cfg.MAX_SNAP_CAPOSALDO_M:
        return None
    lo, hi = (ma, mb) if ma <= mb else (mb, ma)
    if hi - lo < 30 or hi - lo > 4000:
        return None
    return substring_m(line, lo, hi)


def _corpo_nominato(nome: str, matrice: Matrice) -> str | None:
    """Se il nome regionale cita un solo corpo a linea, usa quello.

    «Grantorella - Margorabbia» tiene il tributario: l'asta è già un'altra feature.
    """
    indice: dict[str, set[str]] = {}
    for corpo_id, corpo in matrice.corpi.items():
        if corpo.get("geometria") != "linea":
            continue
        if corpo_id.startswith("residuo_"):
            continue
        for chiave in _chiavi_corpo(corpo):
            indice.setdefault(chiave, set()).add(corpo_id)
    chiavi = [_chiave(p) for p in _parti_nome(nome) if _chiave(p)]
    hits = []
    for chiave in chiavi:
        ids = indice.get(chiave) or set()
        if len(ids) == 1:
            hits.append(next(iter(ids)))
    unici = list(dict.fromkeys(hits))
    if len(unici) == 1:
        return unici[0]
    if len(unici) > 1:
        tributari = [c for c in unici if c not in {"margorabbia", "tresa", "adda", "lambro", "olona"}]
        if len(tributari) == 1:
            return tributari[0]
    return None


def _corpo_residuo(props: dict, idr: str | None, nome: str = "") -> str:
    """Tipo B di chiusura del par. 4.10, con la deroga dei giorni dove il prontuario la scrive."""
    chiavi = {_chiave(p) for p in _parti_nome(nome) if _chiave(p)}
    # Grantorella e Rancina sono affluenti del Margorabbia: la deroga del Maggiore non li copre.
    if chiavi & {"grantorella", "rancina", "caprera"}:
        return "residuo_b"
    sotto = props.get("SOTTOBACIN") or ""
    if sotto == "Lago Maggiore (Verbano)" or idr == "breggia":
        return "residuo_b_verbano"
    if sotto == "Olona" and idr != "lanza":
        return "residuo_b_olona"
    return "residuo_b"


def _completa_reticolo(fiumi: list[dict], laghi: list[dict], consumati: set[int], punti: dict,
                       features: list[dict], report: dict, matrice: Matrice) -> None:
    """Assegna la scheda ai corsi già disegnati che il nome non ha agganciato a un corpo."""
    grigi = []
    usati: set[str] = set()

    def _emetti(geom, props_reg: dict, corpo_id: str | None, nota: str) -> None:
        nome = props_reg.get("NOME") or "Corso"
        atteso = None if corpo_id is None else (matrice.corpi.get(corpo_id) or {}).get("geometria")
        lineare = geom.geom_type in ("LineString", "MultiLineString")
        compatibile = (lineare and atteso == "linea") or (not lineare and atteso == "poligono")
        if corpo_id and compatibile:
            props = _props_base(matrice, corpo_id, None, nome, props_reg, geom)
            if nota:
                props["regole"]["note_corpo"] = ((props["regole"].get("note_corpo") or "") + " " + nota).strip()
            features.append(feature(geom, props))
            usati.add(corpo_id)
            return
        features.append(feature(geom, _props_senza_scheda(nome, props_reg, geom, nota or _NOTA_SENZA_SCHEDA)))
        grigi.append(nome)

    def _emetti_linea(line: LineString, props_reg: dict, corpo_id: str | None, nota: str) -> None:
        if corpo_id == "adda":
            tratto = _tratto_kennedy(line, punti)
            if tratto is not None:
                _emetti(tratto, props_reg, "adda_lecco_tipo_c", "Dal ponte Kennedy al ponte Manzoni.")
                return
        _emetti(line, props_reg, corpo_id, nota)

    for ft in fiumi + laghi:
        if id(ft) in consumati:
            continue
        props = ft.get("properties") or {}
        nome = props.get("NOME") or ""
        if "mezzola" in nome.lower():
            continue
        if not _nel_bacino(props) and _idronimo(nome) not in _LAGHI_FUORI_SOTTOBACINO:
            continue
        if not ft.get("geometry"):
            continue
        geom = shape(ft["geometry"])
        idr = _idronimo(nome)
        if geom.geom_type in ("LineString", "MultiLineString"):
            corpo_id = _corpo_nominato(nome, matrice) or _corpo_residuo(props, idr, nome)
            for line in _linee(geom):
                _emetti_linea(line, props, corpo_id, "")
        elif geom.geom_type in ("Polygon", "MultiPolygon"):
            _emetti(geom, props, None, _NOTA_SENZA_SCHEDA)

    limiti = {idr: (pid, ancora) for idr, pid, ancora in _LIMITI_VALLE}
    for ft in fiumi:
        if id(ft) in consumati or not ft.get("geometry"):
            continue
        props = ft.get("properties") or {}
        nome = props.get("NOME") or ""
        if _nel_bacino(props) or "mezzola" in nome.lower():
            continue
        idr = _idronimo(nome)
        sotto = props.get("SOTTOBACIN") or ""
        if idr == "bevera" and sotto == "Olona":
            for line in _linee(shape(ft["geometry"])):
                _emetti_linea(line, props, "residuo_b_olona", "Bevera di Cantello, affluente dell'Olona.")
            continue
        if idr == "adda" and "Sopra" in sotto:
            bocca = Point(9.40, 46.15)
            for line in _linee(shape(ft["geometry"])):
                if geom_distance_m(line, bocca) > 4000 or line_length_m(line) < 30:
                    continue
                if line_length_m(line) > 4000:
                    _vicino, quota, _dist = project_info(line, bocca.x, bocca.y)
                    totale = line_length_m(line)
                    line = substring_m(line, max(0.0, quota - 4000), min(totale, quota + 4000))
                _emetti_linea(line, props, "adda", "Foce dell'Adda nel Lario: la Valtellina è in Sondrio.")
            continue
        idr_clip = "lambro" if idr == "bevera" and "Lambro" in sotto else idr
        spec = limiti.get(idr_clip or "")
        if not spec:
            continue
        pid, ancora = spec
        if idr == "bevera":
            corpo_id = "residuo_b"
        else:
            corpo_id = _IDRONIMO_CORPO.get(idr or "")
        for line in _linee(shape(ft["geometry"])):
            for piece in _linee_verso_ancora(line, punti.get(pid), ancora):
                if line_length_m(piece) < 30:
                    continue
                _emetti_linea(piece, props, corpo_id, f"Tratto tenuto fino al caposaldo {pid}.")
    report["reticolo_senza_scheda"] = grigi
    report["corpi_senza_geometria"] = [
        row for row in report["corpi_senza_geometria"] if row["corpo_idrico"] not in usati
    ]


def _clip_lombardia(features: list[dict], report: dict) -> None:
    """Toglie dal disegno la parte di lago che sta in Svizzera o in Piemonte."""
    path = cfg.CONFINE_LOMBARDIA
    if not path.exists():
        report["clip_lombardia"] = "confine assente, specchi non tagliati"
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    confine = shape(data["features"][0]["geometry"])
    if not confine.is_valid:
        confine = confine.buffer(0)
    tenuti = []
    intersecate = 0
    for ft in features:
        geom = shape(ft["geometry"])
        if geom.geom_type not in ("Polygon", "MultiPolygon"):
            tenuti.append(ft)
            continue
        inter = geom if confine.covers(geom) else geom.intersection(confine)
        if inter is geom:
            tenuti.append(ft)
            continue
        pezzi = _pezzi_utili(inter)
        intersecate += 1
        for piece in pezzi:
            props = dict(ft["properties"])
            props["geometria"] = piece.geom_type
            props["clip_lombardia"] = True
            if piece.geom_type == "LineString":
                props["lunghezza_m"] = round(line_length_m(piece))
            tenuti.append(feature(piece, props))
    features.clear()
    features.extend(tenuti)
    report["clip_lombardia"] = {"feature_in_uscita": len(tenuti), "geometrie_intersecate": intersecate}


def carica_capisaldi(path: Path) -> dict[str, dict]:
    """Accetta il dizionario del progetto oppure un GeoJSON di punti."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("type") == "FeatureCollection":
        out = {}
        for i, ft in enumerate(data.get("features") or []):
            geom = ft.get("geometry") or {}
            if geom.get("type") != "Point":
                continue
            lon, lat = geom["coordinates"][:2]
            props = dict(ft.get("properties") or {})
            pid = str(props.get("id") or props.get("caposaldo_id") or f"p{i:03d}")
            props.update({"lat": float(lat), "lon": float(lon)})
            out[pid] = props
        return out
    punti = data.get("punti")
    if not isinstance(punti, dict):
        raise ValueError(f"{path.name}: atteso 'punti' oppure un FeatureCollection di Point")
    return punti


def _corpi_del_punto(pid: str, punto: dict, segmenti: list[dict]) -> set[str]:
    esplicito = punto.get("corpo_idrico") or punto.get("corpo")
    if esplicito:
        return {str(esplicito)}
    return {
        s["corpo_idrico"]
        for s in segmenti
        if pid in (s.get("monte"), s.get("valle")) and s.get("corpo_idrico")
    }


def _indicizza(matrice: Matrice) -> dict[str, dict[str, str]]:
    """geometria normativa -> chiave idronimo -> corpo_id. Le chiavi ambigue si scartano."""
    grezzo: dict[str, dict[str, set[str]]] = {"linea": {}, "poligono": {}}
    for corpo_id, corpo in matrice.corpi.items():
        geom = corpo.get("geometria")
        if geom not in grezzo:
            continue
        for chiave in _chiavi_corpo(corpo):
            grezzo[geom].setdefault(chiave, set()).add(corpo_id)
    indice = {"linea": {}, "poligono": {}}
    ambigui = []
    for geom, table in grezzo.items():
        for chiave, ids in table.items():
            if len(ids) == 1:
                indice[geom][chiave] = next(iter(ids))
            else:
                ambigui.append({"chiave": chiave, "geometria": geom, "corpi": sorted(ids)})
    return {"indice": indice, "ambigui": ambigui}


def _abbina(nome: str, geometria: str, indice: dict[str, str]) -> tuple[str | None, list[str]]:
    parti = _parti_nome(nome)
    chiavi = [_chiave(p) for p in parti if _chiave(p)]
    if len(chiavi) != 1:
        return None, chiavi
    return indice.get(chiavi[0]), chiavi


def _join_close(parts: list[LineString]) -> list[LineString]:
    """Unisce due parti della stessa feature se gli estremi distano al massimo MAX_JOIN_GAP_M."""
    parts = list(parts)
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(parts):
            for j, b in enumerate(parts):
                if i == j:
                    continue
                gap = pt_dist_m(a.coords[-1], b.coords[0])
                if gap <= cfg.MAX_JOIN_GAP_M:
                    coords = list(a.coords) + list(b.coords)[(1 if gap == 0 else 0):]
                    parts = [p for k, p in enumerate(parts) if k not in (i, j)] + [LineString(coords)]
                    changed = True
                    break
            if changed:
                break
    return parts


def _linee(geom) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "LineString":
        raw = [geom]
    elif geom.geom_type == "MultiLineString":
        raw = [g for g in geom.geoms if g.geom_type == "LineString"]
    else:
        return []
    raw = [g for g in raw if len(list(g.coords)) >= 2]
    return _join_close(raw) if raw else []


def _inserisci_vertice(line: LineString, point: Point) -> tuple[LineString, Point]:
    """Inserisce sulla linea il vertice proiettato, così Shapely split può tagliare."""
    dist = line.project(point)
    loc = line.interpolate(dist)
    coords = [(c[0], c[1]) for c in line.coords]
    if Point(coords[0]).distance(loc) <= 1e-12:
        return line, Point(coords[0])
    if Point(coords[-1]).distance(loc) <= 1e-12:
        return line, Point(coords[-1])
    acc = 0.0
    out = [coords[0]]
    placed = None
    for a, b in zip(coords, coords[1:]):
        seg_len = LineString([a, b]).length
        if placed is None and acc + seg_len + 1e-15 >= dist:
            if Point(a).distance(loc) <= 1e-12:
                placed = Point(a)
            elif Point(b).distance(loc) <= 1e-12:
                placed = Point(b)
            else:
                placed = Point(loc.x, loc.y)
                out.append((placed.x, placed.y))
        out.append(b)
        acc += seg_len
    if placed is None:
        placed = Point(coords[-1])
    clean = [out[0]]
    for coord in out[1:]:
        if coord != clean[-1]:
            clean.append(coord)
    if len(clean) < 2:
        return line, placed
    return LineString(clean), placed


def split_linea(line: LineString, points: list[Point]) -> list[LineString]:
    """Taglia la linea sui punti proiettati. I punti fuori dagli estremi non creano pezzi vuoti."""
    if not points:
        return [line]
    prepared = line
    vertici = []
    for point in points:
        prepared, vertex = _inserisci_vertice(prepared, point)
        vertici.append(vertex)
    parts = [prepared]
    for vertex in vertici:
        nuovi = []
        for part in parts:
            if part.distance(vertex) > 1e-8:
                nuovi.append(part)
                continue
            taglio = split(part, vertex)
            geoms = list(taglio.geoms) if hasattr(taglio, "geoms") else [taglio]
            linee = [g for g in geoms if g.geom_type == "LineString" and len(list(g.coords)) >= 2]
            nuovi.extend(linee or [part])
        parts = nuovi
    parts = [p for p in parts if line_length_m(p) >= 1.0]
    parts.sort(key=lambda p: line.project(Point(p.interpolate(0.5, normalized=True))))
    return parts or [line]


def _misura_taglio(line: LineString, lon: float, lat: float) -> float:
    _proj, metri, _dist = project_info(line, lon, lat)
    total = line_length_m(line)
    if metri < _MIN_PEZZO_M:
        return 0.0
    if total - metri < _MIN_PEZZO_M:
        return total
    return metri


def _segmento_a(metri: float, partials: list[tuple[dict, float, float]], interi: list[dict]) -> str | None:
    best_id, best_pr = None, -1
    for seg in interi:
        pr = int(seg.get("priorita") or 0)
        if pr > best_pr:
            best_id, best_pr = seg["id"], pr
    for seg, a, b in partials:
        if a - 1 <= metri <= b + 1:
            pr = int(seg.get("priorita") or 0)
            if pr > best_pr:
                best_id, best_pr = seg["id"], pr
    return best_id


def _props_base(matrice: Matrice, corpo_id: str, segmento_id: str | None, nome_tratto: str, regionale: dict, geom) -> dict:
    poly = geom.geom_type in ("Polygon", "MultiPolygon")
    risolto = matrice.risolvi(corpo_id, segmento_id, "sponda")
    corpo = matrice.corpi[corpo_id]
    segmento = matrice.segmenti.get(segmento_id) if segmento_id else None
    props = {
        "nome_tratto": nome_tratto,
        "corpo_idrico": corpo_id,
        "corpo_nome": corpo["nome"],
        "layer": "base",
        "segmento_id": segmento_id,
        "bank": (segmento or corpo).get("bank") or ("both" if not poly else None),
        "zona_id": risolto["zona_id"],
        "regime": risolto["regime"],
        "regime_etichetta": risolto["regime_etichetta"],
        "tipo_acqua": risolto["tipo_acqua"],
        "pesca_consentita": risolto["pesca_consentita"],
        "geometria": geom.geom_type,
        "matrice": risolto["matrice"],
        "regole": risolto,
        "fonte_geometria": "reticolo_regionale_lombardia",
        "nome_regionale": regionale.get("NOME"),
        "bacino_regionale": regionale.get("BACINO"),
        "sottobacino": regionale.get("SOTTOBACIN"),
        "cod_ptua16": regionale.get("COD_PTUA16"),
        "natura": regionale.get("NATURA"),
    }
    if props["bank"] is None:
        del props["bank"]
    if poly:
        props["regole_natante"] = matrice.risolvi(corpo_id, segmento_id, "natante")
    if geom.geom_type in ("LineString", "MultiLineString"):
        parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        props["lunghezza_m"] = round(sum(line_length_m(p) for p in parts))
    return props


def segmenta(matrice: Matrice, fiumi: list[dict], laghi: list[dict], punti: dict[str, dict],
             corpi_filtro: set[str] | None, max_snap_m: float) -> tuple[list[dict], dict]:
    built = _indicizza(matrice)
    indice = built["indice"]
    report = {
        "fonte_linee": str(cfg.RETICOLO_FIUMI.relative_to(cfg.ROOT)).replace("\\", "/"),
        "fonte_laghi": str(cfg.RETICOLO_LAGHI.relative_to(cfg.ROOT)).replace("\\", "/"),
        "sottobacini": list(cfg.SOTTOBACINI_BACINO_5),
        "max_snap_m": max_snap_m,
        "chiavi_ambigue": built["ambigui"],
        "abbinati": [],
        "corpi_senza_geometria": [],
        "geometrie_composte": [],
        "capisaldi": [],
        "segmenti_non_applicati": [],
        "geometrie_scartate": {"fuori_bacino_5": 0, "senza_geometria": 0, "non_in_normativa": 0},
    }

    linee_per_corpo: dict[str, list[tuple[LineString, dict]]] = {}
    specchi_per_corpo: dict[str, list[tuple[object, dict]]] = {}
    consumati: set[int] = set()

    def _consuma(feats: list[dict], geometria: str, destinazione: dict, come_linee: bool) -> None:
        for ft in feats:
            props = ft.get("properties") or {}
            geom_raw = ft.get("geometry")
            if not geom_raw:
                report["geometrie_scartate"]["senza_geometria"] += 1
                continue
            corpo_id, chiavi = _abbina(props.get("NOME") or "", geometria, indice[geometria])
            if not _nel_bacino(props) and corpo_id not in _CORPI_FUORI_AMMESSI:
                report["geometrie_scartate"]["fuori_bacino_5"] += 1
                continue
            if len(chiavi) != 1:
                if any(indice[geometria].get(_chiave(c)) for c in chiavi):
                    report["geometrie_composte"].append({
                        "nome": props.get("NOME"),
                        "sottobacino": props.get("SOTTOBACIN"),
                        "idronimi": chiavi,
                    })
                else:
                    report["geometrie_scartate"]["non_in_normativa"] += 1
                continue
            if corpo_id is None:
                report["geometrie_scartate"]["non_in_normativa"] += 1
                continue
            if corpi_filtro and corpo_id not in corpi_filtro:
                continue
            geom = shape(geom_raw)
            if come_linee:
                for line in _linee(geom):
                    destinazione.setdefault(corpo_id, []).append((line, props))
            else:
                destinazione.setdefault(corpo_id, []).append((geom, props))
            consumati.add(id(ft))

    _consuma(fiumi, "linea", linee_per_corpo, True)
    _consuma(laghi, "poligono", specchi_per_corpo, False)

    punti_per_corpo: dict[str, dict[str, dict]] = {}
    for pid, punto in punti.items():
        if "lat" not in punto or "lon" not in punto:
            report["capisaldi"].append({"id": pid, "esito": "coordinate_assenti"})
            continue
        corpi = _corpi_del_punto(pid, punto, matrice.spec["segmenti"])
        if not corpi:
            overlay = [
                o["id"] for o in (matrice.spec.get("overlay_temporanei") or [])
                if pid in (o.get("monte"), o.get("valle"))
            ]
            report["capisaldi"].append({
                "id": pid,
                "nome": punto.get("nome"),
                "esito": "overlay_non_spezza" if overlay else "senza_corpo_nel_grafo",
                "overlay": overlay,
            })
            continue
        for corpo_id in corpi:
            if corpi_filtro and corpo_id not in corpi_filtro:
                continue
            punti_per_corpo.setdefault(corpo_id, {})[pid] = punto

    features: list[dict] = []
    visti: set[str] = set()

    for corpo_id, linee in sorted(linee_per_corpo.items()):
        visti.add(corpo_id)
        locali = punti_per_corpo.get(corpo_id, {})
        assegnati: dict[str, tuple[int, float, float]] = {}
        for pid, punto in locali.items():
            pt = Point(float(punto["lon"]), float(punto["lat"]))
            best = None
            for i, (line, _props) in enumerate(linee):
                _proj, metri, dist = project_info(line, pt.x, pt.y)
                if best is None or dist < best[0]:
                    best = (dist, i, metri)
            if best is None:
                continue
            dist, idx, metri = best
            voce = {
                "id": pid,
                "nome": punto.get("nome"),
                "corpo_idrico": corpo_id,
                "dist_m": round(dist, 1),
                "progressiva_m": round(metri, 1),
            }
            if dist > max_snap_m:
                voce["esito"] = "troppo_lontano"
                report["capisaldi"].append(voce)
                continue
            voce["esito"] = "proiettato"
            voce["linea"] = idx
            report["capisaldi"].append(voce)
            assegnati[pid] = (idx, metri, dist)

        tagli = [s for s in matrice.tagli(corpo_id) if not s.get("intero_corpo")]
        interi = matrice.tagli(corpo_id, intero=True)
        for seg in tagli:
            monte, valle = seg.get("monte"), seg.get("valle")
            if not monte or not valle:
                report["segmenti_non_applicati"].append({
                    "id": seg["id"],
                    "corpo_idrico": corpo_id,
                    "motivo": "senza_estremi_monte_valle",
                })
                continue
            if monte not in assegnati or valle not in assegnati:
                report["segmenti_non_applicati"].append({
                    "id": seg["id"],
                    "corpo_idrico": corpo_id,
                    "motivo": "caposaldo_non_proiettato",
                    "monte": monte,
                    "valle": valle,
                })
                continue
            if assegnati[monte][0] != assegnati[valle][0]:
                report["segmenti_non_applicati"].append({
                    "id": seg["id"],
                    "corpo_idrico": corpo_id,
                    "motivo": "capisaldi_su_parti_diverse",
                    "monte": monte,
                    "valle": valle,
                })

        for idx, (line, reg_props) in enumerate(linee):
            sulla_linea = {pid: vals for pid, vals in assegnati.items() if vals[0] == idx}
            misure = {}
            punti_taglio = []
            for pid, (_i, metri, _dist) in sulla_linea.items():
                quota = _misura_taglio(line, float(locali[pid]["lon"]), float(locali[pid]["lat"]))
                misure[pid] = quota
                total = line_length_m(line)
                if _MIN_PEZZO_M <= quota <= total - _MIN_PEZZO_M:
                    proj, _, _ = project_info(line, float(locali[pid]["lon"]), float(locali[pid]["lat"]))
                    punti_taglio.append(proj)
            partials = []
            for seg in tagli:
                monte, valle = seg.get("monte"), seg.get("valle")
                if monte in misure and valle in misure:
                    a, b = misure[monte], misure[valle]
                    partials.append((seg, min(a, b), max(a, b)))
            pezzi = split_linea(line, punti_taglio)
            for piece in pezzi:
                centro = piece.interpolate(0.5, normalized=True)
                mid = locate_m(line, centro)
                segmento_id = _segmento_a(mid, partials, interi)
                nome = matrice.segmenti[segmento_id]["nome"] if segmento_id else matrice.corpi[corpo_id]["nome"]
                props = _props_base(matrice, corpo_id, segmento_id, nome, reg_props, piece)
                estremi = [pid for pid, quota in misure.items() if abs(quota - locate_m(line, Point(piece.coords[0]))) <= _MIN_PEZZO_M + 1 or abs(quota - locate_m(line, Point(piece.coords[-1]))) <= _MIN_PEZZO_M + 1]
                props["capisaldi_estremi"] = estremi
                features.append(feature(piece, props))
        report["abbinati"].append({
            "corpo_idrico": corpo_id,
            "geometria": "linea",
            "parti": len(linee),
            "nome_regionale": linee[0][1].get("NOME"),
            "capisaldi_proiettati": len(assegnati),
        })

    for corpo_id, specchi in sorted(specchi_per_corpo.items()):
        visti.add(corpo_id)
        interi = matrice.tagli(corpo_id, intero=True)
        segmento_id = interi[0]["id"] if len(interi) == 1 else (max(interi, key=lambda s: int(s.get("priorita") or 0))["id"] if interi else None)
        for seg in matrice.tagli(corpo_id):
            if not seg.get("intero_corpo"):
                report["segmenti_non_applicati"].append({
                    "id": seg["id"],
                    "corpo_idrico": corpo_id,
                    "motivo": "taglio_su_poligono_non_spezzato",
                })
        for geom, reg_props in specchi:
            nome = matrice.segmenti[segmento_id]["nome"] if segmento_id else matrice.corpi[corpo_id]["nome"]
            props = _props_base(matrice, corpo_id, segmento_id, nome, reg_props, geom)
            features.append(feature(geom, props))
        report["abbinati"].append({
            "corpo_idrico": corpo_id,
            "geometria": "poligono",
            "parti": len(specchi),
            "nome_regionale": specchi[0][1].get("NOME"),
        })

    attesi = set(corpi_filtro) if corpi_filtro else set(matrice.corpi)
    for corpo_id in sorted(attesi - visti):
        if corpi_filtro and corpo_id not in corpi_filtro:
            continue
        report["corpi_senza_geometria"].append({
            "corpo_idrico": corpo_id,
            "nome": matrice.corpi[corpo_id]["nome"],
            "geometria": matrice.corpi[corpo_id].get("geometria"),
        })

    _completa_reticolo(fiumi, laghi, consumati, punti, features, report, matrice)
    _clip_lombardia(features, report)

    for i, ft in enumerate(features, start=1):
        ft["properties"]["id"] = f"{ft['properties']['corpo_idrico']}_{i:03d}"
    return features, report


def _stampa(report: dict, n_feature: int) -> None:
    print(f"Feature nel layer: {n_feature}")
    print(f"Scartate fuori Bacino 5: {report['geometrie_scartate']['fuori_bacino_5']}")
    print("Abbinati:")
    for row in report["abbinati"]:
        extra = f", capisaldi {row['capisaldi_proiettati']}" if "capisaldi_proiettati" in row else ""
        print(f"  {row['corpo_idrico']:16} {row['geometria']:8} {row['parti']} parti  {row['nome_regionale']}{extra}")
    if report["corpi_senza_geometria"]:
        print("Senza geometria regionale:")
        for row in report["corpi_senza_geometria"]:
            print(f"  {row['corpo_idrico']:16} {row['nome']}")
    if report["geometrie_composte"]:
        print("Geometrie composte, non assegnate:")
        for row in report["geometrie_composte"]:
            print(f"  {row['nome']}  ({row['sottobacino']})")
    esiti: dict[str, int] = {}
    for row in report["capisaldi"]:
        esiti[row.get("esito") or "?"] = esiti.get(row.get("esito") or "?", 0) + 1
    if esiti:
        print("Capisaldi: " + ", ".join(f"{k} {v}" for k, v in sorted(esiti.items())))
    senza = report.get("reticolo_senza_scheda") or []
    if senza:
        print(f"Reticolo senza scheda: {len(senza)} geometrie")
    clip = report.get("clip_lombardia")
    if clip:
        print(f"Clip Lombardia: {clip}")
    lontani = [c for c in report["capisaldi"] if c.get("esito") == "troppo_lontano"]
    if lontani:
        print("Capisaldi oltre la soglia di snap:")
        for row in lontani:
            print(f"  {row['id']}  {row['dist_m']} m  {row.get('corpo_idrico')}")
    if report["segmenti_non_applicati"]:
        print("Segmenti normativi non applicati alla geometria:")
        for row in report["segmenti_non_applicati"]:
            print(f"  {row['id']}  {row['motivo']}")


def pubblica_leaflet(features: list[dict], punti: dict[str, dict], matrice: Matrice) -> None:
    """Scrive il bundle letto da docs/index.html. Solo dopo la validazione."""
    fc = {"type": "FeatureCollection", "features": features}
    fc_ov = {"type": "FeatureCollection", "features": []}
    fc_cap = {
        "type": "FeatureCollection",
        "features": [
            point_feature(float(p["lon"]), float(p["lat"]), {"id": pid, "nome": p.get("nome"), "note": p.get("note")})
            for pid, p in punti.items()
            if "lat" in p and "lon" in p
        ],
    }
    fc_todo = {"type": "FeatureCollection", "features": []}
    d = matrice.base.data
    vocabolari = json.loads(json.dumps(d["vocabolari"]))
    vocabolari["regimi"]["scheda_non_inserita"] = {
        "etichetta": "Nel reticolo, scheda non ancora inserita",
        "descrizione": "Geometria del reticolo regionale nel Bacino 5. Non è pesca libera: la scheda del prontuario non è ancora nel grafo.",
        "colore": "#64748b",
        "tratteggio": "2 6",
        "pesca_consentita": None,
    }
    regole_web = {k: d[k] for k in ("meta", "schema", "definizioni_temporali")}
    regole_web["vocabolari"] = vocabolari
    regole_web["struttura"] = {"schema": matrice.spec["schema"], "esempi": matrice.spec["esempi"]}
    js = "".join(
        f"window.{name} = {json.dumps(obj, ensure_ascii=False)};\n"
        for name, obj in (
            ("MARGORABBIA_TRATTI", fc),
            ("MARGORABBIA_OVERLAY", fc_ov),
            ("MARGORABBIA_CAPISALDI", fc_cap),
            ("MARGORABBIA_TODO", fc_todo),
            ("MARGORABBIA_REGOLE", regole_web),
        )
    )
    cfg.OUT_WEB_JS.write_text(js, encoding="utf-8")
    print(f"Bundle Leaflet scritto: {cfg.OUT_WEB_JS.relative_to(cfg.ROOT)}")


def self_test() -> None:
    linea = LineString([(8.70, 45.90), (8.70, 45.95), (8.80, 45.95)])
    pezzi = split_linea(linea, [Point(8.70, 45.92), Point(8.75, 45.95)])
    if len(pezzi) != 3:
        raise SystemExit(f"self-test split: attesi 3 pezzi, ottenuti {len(pezzi)}")
    assert _parti_nome("Grantorella (Torrente) - Margorabbia (Fiume)") == ["Grantorella", "Margorabbia"]
    assert _parti_nome("Lugano (lago) - bacino nord") == ["Lugano"]
    assert _chiave("Lago di Ghirla") == "ghirla"
    assert _chiave("Torrente Telo di Osteno") == "telo di osteno"
    assert _chiave("Rio Boesio") == "rio boesio"
    print("self-test ok: split in 3 e idronimi")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--rete", type=Path, default=cfg.RETICOLO_FIUMI, help="GeoJSON locale delle linee")
    ap.add_argument("--laghi", type=Path, default=cfg.RETICOLO_LAGHI, help="GeoJSON locale dei poligoni lacustri")
    ap.add_argument("--capisaldi", type=Path, default=cfg.CAPISALDI_VERIFICATI, help="punti caposaldo (JSON o GeoJSON)")
    ap.add_argument("--out", type=Path, default=cfg.OUT_RETICOLO_SEGMENTATO)
    ap.add_argument("--report", type=Path, default=cfg.OUT_SEGMENTAZIONE_REPORT)
    ap.add_argument("--corpo", action="append", default=None, help="limita a un corpo_id; ripetibile")
    ap.add_argument("--max-snap-m", type=float, default=cfg.MAX_SNAP_CAPOSALDO_M)
    ap.add_argument("--elenco", action="store_true", help="mostra gli abbinamenti e non scrive i layer")
    ap.add_argument("--pubblica-leaflet", action="store_true", help="riscrive docs/geo_data.js (solo layer validati)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        self_test()
        return

    if not args.rete.exists():
        raise SystemExit(
            f"Manca il reticolo lineare: {args.rete}\n"
            "Va messo in data/geojson/AcqueLombardia/Fiumi.json (export del Geoportale)."
        )

    print("Segmentazione sul reticolo regionale (nessuna chiamata OSM)")
    matrice = Matrice()
    fiumi = _carica_fc(args.rete)
    laghi = _carica_fc(args.laghi) if args.laghi.exists() else []
    if not args.laghi.exists():
        print(f"Laghi assenti, si segmentano solo le linee: {args.laghi}")
    punti = carica_capisaldi(args.capisaldi) if args.capisaldi.exists() else {}
    if not args.capisaldi.exists():
        print(f"Capisaldi assenti, nessuna spezzatura: {args.capisaldi}")

    # Il report cita i percorsi di config: si allineano ai file davvero letti.
    cfg.RETICOLO_FIUMI = args.rete if args.rete.is_absolute() else cfg.ROOT / args.rete
    cfg.RETICOLO_LAGHI = args.laghi if args.laghi.is_absolute() else cfg.ROOT / args.laghi

    features, report = segmenta(
        matrice,
        fiumi,
        laghi,
        punti,
        set(args.corpo) if args.corpo else None,
        args.max_snap_m,
    )
    _stampa(report, len(features))
    if args.elenco:
        print("Elenco soltanto: nessun file scritto.")
        return

    fc = {"type": "FeatureCollection", "features": features}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Scritto {args.out.relative_to(cfg.ROOT)}")
    print(f"Scritto {args.report.relative_to(cfg.ROOT)}")
    if args.pubblica_leaflet:
        pubblica_leaflet(features, punti, matrice)


if __name__ == "__main__":
    main()
