#!/usr/bin/env python3
"""Mappa di impalcatura del Ceresio, con i punti indicati e ancora da confermare.

Non pubblica e non scrive verificato: true.
Output: data/geojson/ceresio_impalcatura.geojson e preview/ceresio_impalcatura.js
"""

from __future__ import annotations

import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import linemerge, polygonize, unary_union
from shapely.validation import make_valid

import osm_client
from build_ceresio import STATI_CHIUSI, applica_indicazioni
from config import (
    CERESIO_IMPALCATURA,
    CERESIO_IMPALCATURA_JS,
    CERESIO_INCERTI,
    CERESIO_INDICATI,
    CERESIO_RAW,
    CERESIO_TRATTI,
    PREVIEW_DIR,
)
from geo_utils import feature, geom_distance_m, line_length_m, locate_m, substring_m

CAMPI_GARA = {
    "ponte_sovera",
    "mulino_carlazzo",
    "ponte_maggioni",
    "cascata_mulino_porlezza",
    "ponte_via_prati",
    "ponte_castello",
    "cimitero_brusimpiano",
    "crotto_zolla",
    "fontana_letizia",
    "crotto_del_lago",
    "pontile_cima",
    "piazza_osteno",
    "burgantun",
    "burgant_minica",
}


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
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "MultiLineString":
        geom = linemerge(geom)
    return [g for g in _parts(geom) if g.geom_type == "LineString" and line_length_m(g) > 5]


def _geom_osm(data: dict):
    nodes, ways, rels = {}, {}, []
    for el in data.get("elements") or []:
        if el.get("type") == "node":
            nodes[el["id"]] = (el["lon"], el["lat"])
        elif el.get("type") == "way":
            ways[el["id"]] = el
        elif el.get("type") == "relation":
            rels.append(el)

    def way_line(way):
        coords = [nodes[i] for i in way.get("nodes") or [] if i in nodes]
        if len(coords) >= 2:
            return LineString(coords)
        return None

    if rels:
        lines = []
        for m in rels[0].get("members") or []:
            if m.get("type") == "way" and m.get("ref") in ways:
                ln = way_line(ways[m["ref"]])
                if ln is not None:
                    lines.append(ln)
        if not lines:
            return None, (rels[0].get("tags") or {})
        polys = list(polygonize(unary_union(lines)))
        tags = rels[0].get("tags") or {}
        if polys:
            return make_valid(unary_union(polys)), tags
        return linemerge(lines), tags
    if not ways:
        return None, {}
    way = next(iter(ways.values()))
    ln = way_line(way)
    tags = way.get("tags") or {}
    if ln is None:
        return None, tags
    coords = list(ln.coords)
    if coords[0] == coords[-1] and len(coords) >= 4:
        return make_valid(Polygon(coords)), tags
    return ln, tags


def fetch_osm(osm_id: int, prefer_poly: bool):
    trovati = []
    for kind in ("way", "relation"):
        try:
            data = osm_client.osm_full(kind, osm_id)
        except Exception as exc:
            print(f"  OSM {kind}/{osm_id}: {exc}")
            continue
        geom, tags = _geom_osm(data)
        if geom is None or geom.is_empty:
            continue
        nome = tags.get("name") or tags.get("waterway") or tags.get("highway") or kind
        print(f"  OSM {kind}/{osm_id}: {geom.geom_type} · {nome}")
        trovati.append((kind, geom, tags))
        if prefer_poly and "Polygon" in geom.geom_type:
            break
        if not prefer_poly and "Line" in geom.geom_type:
            break
    if not trovati:
        raise RuntimeError(f"OSM {osm_id} senza geometria")
    if prefer_poly:
        polys = [t for t in trovati if "Polygon" in t[1].geom_type]
        if polys:
            return polys[0]
    return trovati[0]


def _migliore(linee, *punti: Point) -> LineString:
    def costo(ln: LineString) -> float:
        return sum(geom_distance_m(ln, p) for p in punti)

    return min(linee, key=costo)


def _su_linea(ln: LineString, pt: Point) -> tuple[Point, float, float]:
    proj = ln.interpolate(ln.project(pt))
    return proj, locate_m(ln, proj), geom_distance_m(ln, pt)


def _tra(ln: LineString, a: float, b: float) -> LineString:
    return substring_m(ln, a, b)


def _meta_da_chiusa(ln: LineString, d_chiusa: float, d_ponte: float) -> LineString:
    """Il 50% del tratto, partendo dalla chiusa e andando verso il ponte."""
    span = abs(d_ponte - d_chiusa)
    half = span * 0.5
    if d_ponte >= d_chiusa:
        return _tra(ln, d_chiusa, d_chiusa + half)
    return _tra(ln, d_chiusa - half, d_chiusa)


def _offset_sud(ln: LineString, metri: float = 22.0) -> LineString:
    coords = list(ln.coords)
    if len(coords) < 2:
        return ln
    out = []
    for i, (x, y) in enumerate(coords):
        if i == 0:
            (ax, ay), (bx, by) = coords[0], coords[1]
        elif i == len(coords) - 1:
            (ax, ay), (bx, by) = coords[-2], coords[-1]
        else:
            (ax, ay), (bx, by) = coords[i - 1], coords[i + 1]
        lat = y
        dx = (bx - ax) * 111320.0 * math.cos(math.radians(lat))
        dy = (by - ay) * 110540.0
        length = math.hypot(dx, dy) or 1.0
        scelte = []
        for sign in (1.0, -1.0):
            ox = -dy / length * metri * sign
            oy = dx / length * metri * sign
            lon = x + ox / (111320.0 * math.cos(math.radians(lat)))
            lat2 = y + oy / 110540.0
            scelte.append((lat2, lon))
        lat2, lon = min(scelte, key=lambda t: t[0])
        out.append((lon, lat2))
    return LineString(out)


def _pin(lon, lat, props) -> dict:
    return feature(Point(lon, lat), props)


def _base(fc: dict) -> list[dict]:
    out = []
    for f in fc["features"]:
        p = dict(f["properties"])
        cid = p.get("corpo_id")
        if p.get("segmento_id") == "lago_lugano_canneto_lavena":
            p["kind"] = "stretto"
            p["note"] = "Riva italiana tra i due estremi confermati. Non è una corda sullo specchio."
        elif p.get("segmento_id"):
            p["kind"] = "restrizione_precedente"
            p["layer"] = "acque"
            p["note"] = "Cerchio da 50 m alla foce, confermato."
        elif cid == "tresa":
            p["kind"] = "fiume"
            p["layer"] = "acque"
            p["note"] = "Sponda svizzera esclusa. L'asse è il corso; si regola la sponda italiana."
            if p.get("bank") == "both":
                p["note"] += " bank both non è un permesso per la sponda svizzera."
        elif cid in ("lago_lugano", "lago_piano"):
            p["kind"] = "lago"
            p["layer"] = "acque"
        elif cid == "telo_osteno":
            p["kind"] = "telo"
            p["layer"] = "acque"
        elif cid == "lagadone":
            p["kind"] = "canale"
            p["layer"] = "acque"
            p["note"] = "Canale intero, dalle way OSM omonime. Non è citato nel grafo del prontuario."
        else:
            p["kind"] = "tributario"
            p["layer"] = "acque"
        p["stato"] = "base"
        out.append({"type": "Feature", "geometry": f["geometry"], "properties": p})
    return out


def _aggiorna_incerti() -> None:
    doc = json.loads(CERESIO_INCERTI.read_text(encoding="utf-8"))
    for s in doc["schede"]:
        if s["id"] in CAMPI_GARA:
            s["stato"] = "fuori_interesse"
            s["nota_operativa"] = "Campo gara: fuori perimetro operativo, non si cartografa."
    doc["schede"] = applica_indicazioni(doc["schede"])
    doc["da_validare"] = [s for s in doc["schede"] if s.get("stato") not in STATI_CHIUSI]
    doc["nota"] = (
        "Nessun pin è verificato. I campi gara non si sondano. "
        "Le indicazioni utente stanno in ceresio_capisaldi_indicati.json e restano da confermare "
        "sulla mappa di impalcatura. La foce del Tresa nel Verbano è rinviata al Lago Maggiore."
    )
    CERESIO_INCERTI.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Capisaldi ancora aperti: {len(doc['da_validare'])}")
    for s in doc["da_validare"]:
        print(f"  .. {s['id']}: {s.get('stato')}")


def main() -> None:
    indicati = json.loads(CERESIO_INDICATI.read_text(encoding="utf-8"))
    punti = indicati["punti"]
    raw = json.loads(CERESIO_RAW.read_text(encoding="utf-8"))
    acque = {f["properties"]["corpo_id"]: shape(f["geometry"]) for f in raw["features"]}
    tratti = json.loads(CERESIO_TRATTI.read_text(encoding="utf-8"))
    features = _base(tratti)
    misure = {}

    print("=== OSM ===")
    kind_p, ponte, tags_p = fetch_osm(int(punti["ponte_dogana"]["osm_id"]), prefer_poly=True)
    features.append(feature(ponte, {
        "id": "ponte_dogana",
        "kind": "ponte",
        "layer": "impalcatura",
        "nome": punti["ponte_dogana"]["nome"],
        "stato": "confermato",
        "precisione": "oggetto_osm",
        "note": f"OSM {kind_p}/{punti['ponte_dogana']['osm_id']} · {tags_p.get('name') or 'senza nome'}. Confermato.",
    }))
    telo_geom = acque.get("telo_osteno")
    misure["telo_m"] = round(sum(line_length_m(ln) for ln in _linee(telo_geom))) if telo_geom is not None else 0

    tresa = _linee(acque["tresa"])
    chiusa = Point(punti["chiusa_regolazione"]["lon"], punti["chiusa_regolazione"]["lat"])
    biv = Point(punti["ponte_biviglione"]["lon"], punti["ponte_biviglione"]["lat"])
    rif_ponte = ponte.centroid if "Polygon" in ponte.geom_type else ponte.interpolate(0.5, normalized=True)
    asta = _migliore(tresa, chiusa, rif_ponte)
    snap_ponte, d_ponte, dist_ponte = _su_linea(asta, rif_ponte)
    if "Polygon" in ponte.geom_type:
        inter = ponte.intersection(asta)
        pezzi = [g for g in _parts(inter) if not g.is_empty]
        if pezzi:
            centro = unary_union(pezzi).centroid
            snap_ponte, d_ponte, dist_ponte = _su_linea(asta, centro)
    snap_chiusa, d_chiusa, dist_chiusa = _su_linea(asta, chiusa)

    notturna = _tra(asta, d_ponte, d_chiusa)
    divieto = _offset_sud(_meta_da_chiusa(asta, d_chiusa, d_ponte))
    misure["dogana_chiusa_m"] = round(line_length_m(notturna))
    misure["divieto_lavena_m"] = round(line_length_m(divieto))
    misure["snap_chiusa_m"] = round(dist_chiusa)
    misure["snap_ponte_m"] = round(dist_ponte)
    print(f"  Dogana–chiusa: {misure['dogana_chiusa_m']} m (chiusa a {dist_chiusa:.0f} m dall'asse, ponte a {dist_ponte:.0f} m)")
    print(f"  Divieto piazze, 50% dalla chiusa in sponda sud: {misure['divieto_lavena_m']} m")

    features.append(feature(notturna, {
        "id": "tresa_notturna_dogana_chiusa",
        "kind": "notturna",
        "layer": "impalcatura",
        "nome": "Notturna Ponte della Dogana – chiusa",
        "stato": "confermato",
        "lunghezza_m": misure["dogana_chiusa_m"],
        "note": "Asse del tratto, confermato. La sponda svizzera è esclusa.",
    }))
    features.append(feature(divieto, {
        "id": "tresa_divieto_lavena",
        "kind": "divieto_sud",
        "layer": "impalcatura",
        "nome": "Divieto Piazza Europa e Piazza Mercato",
        "stato": "confermato",
        "bank": "sud",
        "lunghezza_m": misure["divieto_lavena_m"],
        "note": indicati["tratti"]["tresa_divieto_lavena"]["note"] + " Linea spostata di 22 m a sud dell'asse, per leggerla come sponda sud.",
    }))

    diga = punti["diga_creva"]
    diga_pt = Point(diga["lon"], diga["lat"])
    asta_bassa = _migliore(tresa, biv, diga_pt)
    snap_biv, d_biv, dist_biv = _su_linea(asta_bassa, biv)
    snap_diga, d_diga, dist_diga = _su_linea(asta_bassa, diga_pt)
    bottatrice = _tra(asta_bassa, d_biv, d_diga)
    misure["bottatrice_m"] = round(line_length_m(bottatrice))
    misure["snap_biviglione_m"] = round(dist_biv)
    misure["snap_diga_m"] = round(dist_diga)
    print(f"  Bottatrice Biviglione–diga di Creva: {misure['bottatrice_m']} m (ponte a {dist_biv:.0f} m, diga a {dist_diga:.0f} m)")
    features.append(feature(bottatrice, {
        "id": "tresa_notturna_bottatrice",
        "kind": "bottatrice",
        "layer": "impalcatura",
        "nome": "Notturna bottatrice, Biviglione – diga di Creva",
        "stato": "confermato",
        "lunghezza_m": misure["bottatrice_m"],
        "note": "Entrambi gli estremi sono confermati. La diga è il punto Nominatim accettato.",
    }))

    features.append(_pin(snap_ponte.x, snap_ponte.y, {
        "id": "ponte_dogana_punto",
        "kind": "pin",
        "layer": "impalcatura",
        "nome": "Ponte della Dogana, punto sull'asta",
        "stato": "confermato",
        "precisione": "proiezione",
        "note": f"Proiezione del poligono OSM sull'asse, a {dist_ponte:.0f} m dal centro del poligono. Confermato.",
    }))
    lago = acque["lago_lugano"]
    pt_rezzo = Point(punti["foce_rezzo"]["lon"], punti["foce_rezzo"]["lat"])
    pt_telo = Point(punti["foce_telo"]["lon"], punti["foce_telo"]["lat"])
    extra_note = {
        "foce_rezzo": (
            f" Confermato. Dista {geom_distance_m(lago, pt_rezzo):.0f} m dal poligono del lago "
            f"e {geom_distance_m(acque['rezzo'], pt_rezzo):.0f} m dall'asta."
        ),
        "foce_telo": (
            f" Confermato. Dista {geom_distance_m(acque['telo_osteno'], pt_telo):.0f} m dall'asta "
            f"e {geom_distance_m(lago, pt_telo):.0f} m dal poligono del lago."
        ),
    }
    for pid in ("chiusa_regolazione", "ponte_biviglione", "diga_creva", "vecchia_filanda", "grotto_bagat", "ponte_bigattini", "foce_rezzo", "foce_telo"):
        p = punti[pid]
        props = {
            "id": pid,
            "kind": "pin",
            "layer": "impalcatura",
            "nome": p["nome"],
            "stato": "confermato" if p.get("precisione") == "confermato" else "indicato_da_confermare",
            "precisione": p["precisione"],
            "note": p["note"] + extra_note.get(pid, ""),
        }
        if p.get("raggio_m"):
            props["raggio_m"] = p["raggio_m"]
        features.append(_pin(p["lon"], p["lat"], props))

    for feat in features:
        if feat["properties"].get("segmento_id") == "lago_lugano_canneto_lavena":
            misure["stretto_m"] = feat["properties"].get("lunghezza_m")

    trallo = _linee(acque["trallo"])
    ponte_tr = Point(punti["ponte_bigattini"]["lon"], punti["ponte_bigattini"]["lat"])
    foce_xy = (8.891842, 45.948623)
    asta_tr = _migliore(trallo, ponte_tr, Point(*foce_xy))
    snap_tr, d_tr, dist_tr = _su_linea(asta_tr, ponte_tr)
    _, d_foce, dist_foce = _su_linea(asta_tr, Point(*foce_xy))
    divieto_tr = _tra(asta_tr, d_tr, d_foce)
    misure["trallo_divieto_m"] = round(line_length_m(divieto_tr))
    misure["snap_bagattini_m"] = round(dist_tr)
    print(f"  Trallo ponte–foce: {misure['trallo_divieto_m']} m (ponte a {dist_tr:.0f} m dall'asse, foce geometrica a {dist_foce:.0f} m)")
    features.append(feature(divieto_tr, {
        "id": "trallo_divieto_foce",
        "kind": "divieto_trallo",
        "layer": "impalcatura",
        "nome": "Divieto Trallo, ponte di via Bagattini – foce",
        "stato": "confermato",
        "lunghezza_m": misure["trallo_divieto_m"],
        "note": (
            f"Dal punto confermato, proiettato sull'asta ({dist_tr:.0f} m di distanza), "
            f"fino allo sbocco. Lunghezza misurata {misure['trallo_divieto_m']} m; "
            "il prontuario dice circa 500 m."
        ),
    }))
    if dist_tr > 30:
        features.append(feature(LineString([(ponte_tr.x, ponte_tr.y), (snap_tr.x, snap_tr.y)]), {
            "id": "trallo_aggancio",
            "kind": "aggancio",
            "layer": "impalcatura",
            "nome": "Distanza del punto Bagattini dall'asta del Trallo",
            "stato": "indicato_da_confermare",
            "lunghezza_m": round(dist_tr),
            "note": "Il click non cade sull'asta OSM. Il segmento rosso parte dalla proiezione, non dal click.",
        }))

    fc_out = {
        "type": "FeatureCollection",
        "name": "ceresio_impalcatura",
        "meta": {
            "stato": "impalcatura",
            "aggiornato": "2026-09-28",
            "misure": misure,
            "aperti": [
                "Foce del Tresa nel Verbano: rinviata al Lago Maggiore.",
                "Foce del Cuccio: il raggio metà alveo + 50 m non è disegnato.",
                "Campi gara: fuori perimetro, non sono in mappa.",
            ],
        },
        "features": features,
    }
    CERESIO_IMPALCATURA.parent.mkdir(parents=True, exist_ok=True)
    CERESIO_IMPALCATURA.write_text(json.dumps(fc_out, ensure_ascii=False), encoding="utf-8")
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    CERESIO_IMPALCATURA_JS.write_text(
        "window.CERESIO_IMPALCATURA = " + json.dumps(fc_out, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    print(f"Impalcatura: {len(features)} geometrie")
    _aggiorna_incerti()


if __name__ == "__main__":
    main()
