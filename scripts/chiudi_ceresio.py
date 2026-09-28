#!/usr/bin/env python3
"""Geometria definitiva del Ceresio, dopo la conferma dei punti.

Aggiunge il Lirone fino alla foce, porta il canneto sulla riva, accorcia il Tresa
che entra nel Verbano e spezza i tratti confermati. Non pubblica da solo.
"""

from __future__ import annotations

import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

import osm_client
from build_ceresio import buffer_m
from config import CAPISALDI_VERIFICATI, CERESIO_RAW, CERESIO_TRATTI
from fetch_osm_data import _come_geom, _unisci, _way_line_from_api
from geo_utils import feature, geom_distance_m, line_length_m, locate_m, substring_m

VALLE_VERBANO = Point(8.71, 46.008)
RITAGLIO_M = 25.0
FOCE_TELO = (9.084980490938772, 46.00907168549124)
LIRONE_WAYS = (56676168, 848395585, 848395586)


def _parts(geom) -> list:
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(_parts(g))
        return out
    if geom.geom_type.startswith("Multi"):
        return [g for g in geom.geoms if not g.is_empty]
    return [geom]


def _linee(geom) -> list[LineString]:
    return [g for g in _parts(geom) if g.geom_type == "LineString" and line_length_m(g) > 5]


def _pins() -> dict:
    doc = json.loads(CAPISALDI_VERIFICATI.read_text(encoding="utf-8"))
    return {k: Point(v["lon"], v["lat"]) for k, v in doc["punti"].items()}


def riva_verbano():
    q = """[out:json][timeout:50];
relation(11758);
way(r)(45.988,8.700,46.015,8.760);
out geom;
"""
    data = osm_client.overpass(q) or {}
    lines = []
    for e in data.get("elements") or []:
        coords = [(p["lon"], p["lat"]) for p in e.get("geometry") or [] if "lon" in p]
        if len(coords) >= 2:
            lines.append(LineString(coords))
    if not lines:
        raise RuntimeError("Riva del Verbano non disponibile")
    return unary_union(lines)


def taglia_verbano(ln: LineString, shore) -> LineString:
    """Tiene il corso fino a riva e toglie il tratto che entra nel Lago Maggiore."""
    if ln.is_empty or not ln.intersects(shore):
        return ln
    hit = ln.intersection(shore)
    if hit.geom_type == "Point":
        pts = [hit]
    elif hit.geom_type == "MultiPoint":
        pts = list(hit.geoms)
    else:
        return ln
    if geom_distance_m(Point(ln.coords[0]), VALLE_VERBANO) < geom_distance_m(Point(ln.coords[-1]), VALLE_VERBANO):
        ln = LineString(list(ln.coords)[::-1])
    cut = max(locate_m(ln, p) for p in pts)
    totale = line_length_m(ln)
    if totale - cut < 80:
        return ln
    tenuto = substring_m(ln, 0, max(30.0, cut - RITAGLIO_M))
    print(f"  Tresa accorciato di {totale - line_length_m(tenuto):.0f} m alla riva del Verbano")
    return tenuto


def arco_riva(lago, a: Point, b: Point) -> LineString:
    """Arco di riva più corto tra due punti, sulla porzione di lago più vicina."""
    parti = [g for g in _parts(lago) if g.geom_type == "Polygon"]
    if not parti:
        raise RuntimeError("Lago senza anello di riva")
    poly = min(parti, key=lambda g: geom_distance_m(g.boundary, a) + geom_distance_m(g.boundary, b))
    ring = LineString(poly.exterior.coords)
    d0 = locate_m(ring, ring.interpolate(ring.project(a)))
    d1 = locate_m(ring, ring.interpolate(ring.project(b)))
    if d1 < d0:
        d0, d1 = d1, d0
    totale = line_length_m(ring)
    diretto = substring_m(ring, d0, d1)
    coda = substring_m(ring, d1, totale)
    testa = substring_m(ring, 0, d0)
    coords = list(coda.coords) + list(testa.coords)[1:]
    altro = LineString(coords) if len(coords) >= 2 else diretto
    scelto = diretto if line_length_m(diretto) <= line_length_m(altro) else altro
    print(f"  Riva dello stretto: {line_length_m(scelto):.0f} m")
    return scelto


def _su(ln: LineString, pt: Point):
    proj = ln.interpolate(ln.project(pt))
    return locate_m(ln, proj), geom_distance_m(ln, pt)


def _intervallo_meta(d_chiusa: float, d_ponte: float):
    span = abs(d_ponte - d_chiusa)
    if d_ponte >= d_chiusa:
        meta = d_chiusa + span * 0.5
        return (d_chiusa, meta), (meta, d_ponte)
    meta = d_chiusa - span * 0.5
    return (meta, d_chiusa), (d_ponte, meta)


def _spezza(ln: LineString, intervalli: list[tuple[float, float, str]]) -> list[tuple[LineString, str | None]]:
    totale = line_length_m(ln)
    marks = {0.0, totale}
    for a, b, _sid in intervalli:
        marks.add(max(0.0, min(totale, min(a, b))))
        marks.add(max(0.0, min(totale, max(a, b))))
    punti = sorted(marks)
    out = []
    for a, b in zip(punti, punti[1:]):
        if b - a < 8:
            continue
        mid = (a + b) / 2
        seg = None
        for x0, x1, sid in intervalli:
            lo, hi = min(x0, x1), max(x0, x1)
            if lo - 1 <= mid <= hi + 1:
                seg = sid
                break
        out.append((substring_m(ln, a, b), seg))
    return out


def _linea_base(props: dict, geom: LineString, segmento_id: str | None) -> dict:
    p = dict(props)
    p["segmento_id"] = segmento_id
    p["lunghezza_m"] = round(line_length_m(geom))
    p["geometria"] = "linea"
    if segmento_id == "tresa_divieto_lavena":
        p["bank"] = "left"
    return feature(geom, p)


def _lirone() -> LineString | None:
    linee = []
    for osm_id in LIRONE_WAYS:
        ln, tags = _way_line_from_api(osm_id)
        if ln is None:
            print(f"  Lirone way {osm_id} senza geometria")
            continue
        print(f"  Lirone {osm_id} {tags.get('name') or ''} {line_length_m(ln):.0f} m")
        linee.append(ln)
    parts = _unisci(linee)
    return _come_geom(parts)


def main() -> None:
    pins = _pins()
    raw = json.loads(CERESIO_RAW.read_text(encoding="utf-8"))
    tratti = json.loads(CERESIO_TRATTI.read_text(encoding="utf-8"))
    shore = riva_verbano()

    for feat in raw["features"]:
        if feat["properties"].get("corpo_id") != "tresa":
            continue
        geom = shape(feat["geometry"])
        nuove = [taglia_verbano(ln, shore) for ln in _linee(geom)]
        if len(nuove) == 1:
            feat["geometry"] = mapping(nuove[0])
        elif nuove:
            feat["geometry"] = mapping(MultiLineString(nuove))

    lirone = _lirone()
    if lirone is not None:
        raw["features"] = [f for f in raw["features"] if f["properties"].get("corpo_id") != "lirone"]
        raw["features"].append(feature(lirone, {
            "corpo_id": "lirone",
            "nome": "Torrente Lirone",
            "osm_type": "way",
            "osm_id": 848395585,
            "osm_ids": list(LIRONE_WAYS),
            "specie_attesa": "linea",
        }))
        metri = sum(line_length_m(p) for p in _linee(lirone))
        print(f"  Lirone unito: {metri:.0f} m")

    CERESIO_RAW.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")

    features = []
    tresa = []
    trallo = []
    lago = None
    for feat in tratti["features"]:
        p = feat["properties"]
        cid = p.get("corpo_id")
        geom = shape(feat["geometry"])
        if cid == "tresa" and geom.geom_type == "LineString":
            geom = taglia_verbano(geom, shore)
            tresa.append((geom, p))
            continue
        if cid == "trallo" and geom.geom_type == "LineString":
            trallo.append((geom, p))
            continue
        if cid == "lirone":
            continue
        if cid == "lago_lugano" and not p.get("segmento_id"):
            lago = geom
            continue
        if p.get("segmento_id") in ("lago_lugano_restrizione_telo", "lago_lugano_restrizione_rezzo", "lago_lugano_canneto_lavena"):
            continue
        features.append(feat)

    if lirone is not None:
        for parte in _linee(lirone):
            features.append(feature(parte, {
                "corpo_id": "lirone",
                "nome": "Torrente Lirone",
                "geometria": "linea",
                "clip": "intero_in_italia",
                "bank": "both",
                "segmento_id": None,
                "lunghezza_m": round(line_length_m(parte)),
                "spazio": "sponda",
            }))
        foce = Point(*FOCE_TELO)
        print(f"  Foce Lirone/Telo a {geom_distance_m(lirone, foce):.0f} m dall'asta")

    if lago is not None:
        for pid, seg, etichetta in (
            ("foce_rezzo", "lago_lugano_restrizione_rezzo", "Restrizione foce Rezzo (50 m, solo la parte di lago)"),
            ("foce_telo", "lago_lugano_restrizione_telo", "Restrizione foce Telo (50 m, solo la parte di lago)"),
        ):
            centro = pins[pid] if pid != "foce_telo" else Point(*FOCE_TELO)
            zona = make_valid(lago.intersection(buffer_m(centro, 50)))
            if zona.is_empty:
                print(f"  {etichetta}: vuota")
                continue
            features.append(feature(zona, {
                "corpo_id": "lago_lugano",
                "nome": etichetta,
                "geometria": "poligono",
                "clip": "foce_confermata",
                "bank": None,
                "segmento_id": seg,
                "spazio": "interno",
            }))
            print(f"  {etichetta}")
        riva = arco_riva(lago, pins["vecchia_filanda"], pins["grotto_bagat"])
        features.append(feature(riva, {
            "corpo_id": "lago_lugano",
            "nome": "Canneto dello stretto di Lavena",
            "geometria": "linea",
            "clip": "riva",
            "bank": "left",
            "segmento_id": "lago_lugano_canneto_lavena",
            "lunghezza_m": round(line_length_m(riva)),
            "spazio": "sponda",
        }))

    def migliore(candidati, *punti):
        return min(candidati, key=lambda item: sum(geom_distance_m(item[0], p) for p in punti))

    if tresa and any(p.get("segmento_id") for _ln, p in tresa):
        for ln, props in tresa:
            features.append(_linea_base(props, ln, props.get("segmento_id")))
        tresa = []

    if tresa:
        lavena_i = tresa.index(migliore(tresa, pins["chiusa_regolazione"], pins["ponte_dogana"]))
        bassa_i = tresa.index(migliore(tresa, pins["ponte_biviglione"], pins["diga_creva"]))
        for i, (ln, props) in enumerate(tresa):
            intervalli = []
            if i == lavena_i:
                d_ch, dist_ch = _su(ln, pins["chiusa_regolazione"])
                d_po, dist_po = _su(ln, pins["ponte_dogana"])
                if dist_ch < 40 and dist_po < 40:
                    divieto, notturna = _intervallo_meta(d_ch, d_po)
                    intervalli.append((*divieto, "tresa_divieto_lavena"))
                    intervalli.append((*notturna, "tresa_notturna_dogana_chiusa"))
                    print(f"  Divieto Lavena {abs(divieto[1] - divieto[0]):.0f} m, notturna {abs(notturna[1] - notturna[0]):.0f} m")
            if i == bassa_i:
                d_bi, dist_bi = _su(ln, pins["ponte_biviglione"])
                d_di, dist_di = _su(ln, pins["diga_creva"])
                if dist_bi < 40 and dist_di < 40:
                    intervalli.append((d_bi, d_di, "tresa_notturna_bottatrice"))
                    print(f"  Bottatrice {abs(d_di - d_bi):.0f} m")
            for parte, seg in _spezza(ln, intervalli):
                features.append(_linea_base(props, parte, seg))

    if trallo and any(p.get("segmento_id") for _ln, p in trallo):
        for ln, props in trallo:
            features.append(_linea_base(props, ln, props.get("segmento_id")))
        trallo = []

    if trallo:
        ln, props = migliore(trallo, pins["ponte_bigattini"])
        d_po, dist_po = _su(ln, pins["ponte_bigattini"])
        foce_geom = None
        if lago is not None and ln.intersects(lago.boundary):
            hit = ln.intersection(lago.boundary)
            if hit.geom_type == "Point":
                foce_geom = hit
            elif hit.geom_type == "MultiPoint":
                foce_geom = min(hit.geoms, key=lambda p: geom_distance_m(p, pins["ponte_bigattini"]))
        if foce_geom is None:
            foce_geom = Point(ln.coords[-1])
        d_fo, _dist_fo = _su(ln, foce_geom)
        if dist_po < 40:
            for parte, seg in _spezza(ln, [(d_po, d_fo, "trallo_divieto_foce")]):
                features.append(_linea_base(props, parte, seg))
            print(f"  Divieto Trallo {abs(d_fo - d_po):.0f} m, ponte a {dist_po:.0f} m")
        else:
            features.append(_linea_base(props, ln, None))
        for altra, p in trallo:
            if altra is ln:
                continue
            features.append(_linea_base(p, altra, None))

    if lago is not None:
        features.append(feature(lago, {
            "corpo_id": "lago_lugano",
            "nome": "Lago di Lugano",
            "geometria": "poligono",
            "clip": "confine_stato",
            "bank": None,
            "segmento_id": None,
            "spazio": "interno",
        }))

    CERESIO_TRATTI.write_text(json.dumps({
        "type": "FeatureCollection",
        "name": "ceresio_tratti",
        "features": features,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"Tratti chiusi: {len(features)}")


if __name__ == "__main__":
    main()
