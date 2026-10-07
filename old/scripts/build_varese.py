#!/usr/bin/env python3
"""Scarica i corpi indicati e scrive l'impalcatura di Varese, Comabbio e Monate.

Non pubblica e non marca verificato. I divieti restano nel grafo, non sulla geometria,
finché i capisaldi non sono confermati.

Uso:  py -3 scripts/build_geo_data.py --area varese
"""

from __future__ import annotations

import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import Point, shape

import fetch_osm_data as fosm
import osm_client
from config import VARESE_IMPALCATURA_JS, VARESE_INCERTI, VARESE_RAW
from geo_utils import geom_distance_m, line_length_m, point_feature

CORPI = [
    {"id": "lago_varese", "osm_id": 38372, "nome": "Lago di Varese", "specie": "poligono", "kind": "lago"},
    {"id": "lago_comabbio", "osm_id": 1314305, "nome": "Lago di Comabbio", "specie": "poligono", "kind": "lago"},
    {"id": "lago_monate", "osm_id": 1309665, "nome": "Lago di Monate", "specie": "poligono", "kind": "lago"},
    {"id": "bardello", "osm_id": 3574688, "nome": "Fiume Bardello", "specie": "linea", "kind": "emissario"},
    {"id": "canale_brabbia", "osm_id": 88824168, "nome": "Canale Brabbia", "specie": "linea", "kind": "canale"},
    {"id": "acquanegra", "osm_id": 3594006, "nome": "Torrente Acquanegra", "specie": "linea", "kind": "emissario"},
    {
        "id": "tinella",
        "osm_id": 3714984,
        "nome": "Torrente Tinella",
        "specie": "linea",
        "kind": "immissario",
        "codice_proposto": True,
    },
]

RICERCHE = [
    ("schiranna", "Canottieri Schiranna, Varese", "Torretta di arrivo della Società Canottieri, inizio dei 250 m verso nord."),
    ("oltrona", "Oltrona, Gavirate", "Località della foce del Tinella. Il divieto si misura dalla foce, non dal centro abitato."),
    ("ponte_xxiii", "via Giovanni XXIII, Travedona-Monate", "Estremo del divieto sull'Acquanegra. Serve il ponte, non la via intera."),
    ("ponte_trevisani", "via Trevisani, Monate", "Estremo del divieto sull'Acquanegra, a Monate."),
    ("roverplast", "Roverplast, Gavirate", "La cascatella è subito a valle dello stabilimento, non lo stabilimento stesso."),
]


def _lunghezza(geom) -> int:
    if geom.geom_type == "LineString":
        return round(line_length_m(geom))
    if geom.geom_type == "MultiLineString":
        return round(sum(line_length_m(g) for g in geom.geoms))
    return 0


def _estremi(geom) -> list[Point]:
    lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
    punti = []
    for ln in lines:
        punti.append(Point(ln.coords[0]))
        punti.append(Point(ln.coords[-1]))
    return punti


def _piu_vicino(punti: list[Point], poly) -> Point:
    return min(punti, key=lambda p: geom_distance_m(poly, p))


def scarica() -> dict:
    ids = [c["osm_id"] for c in CORPI]
    by_id = {c["osm_id"]: c for c in CORPI}
    payload = osm_client.overpass(fosm.overpass_query(ids))
    if not payload:
        raise RuntimeError("Overpass non ha risposto")
    chosen: dict[int, dict] = {}
    for el in payload.get("elements") or []:
        meta = by_id.get(el.get("id"))
        if not meta:
            continue
        tags = el.get("tags") or {}
        if not fosm.is_water(tags, meta["nome"]):
            print(f"  scartato {el['type']}/{el['id']}")
            continue
        if el["id"] not in chosen or el["type"] == "relation":
            chosen[el["id"]] = el
    features = []
    for meta in CORPI:
        el = chosen.get(meta["osm_id"])
        if el is None:
            print(f"  MANCA {meta['nome']} ({meta['osm_id']})")
            continue
        geom = fosm.element_geometry(el, meta["specie"])
        if geom is None:
            print(f"  geometria vuota {meta['nome']}")
            continue
        tags = el.get("tags") or {}
        features.append({
            "type": "Feature",
            "geometry": fosm.mapping(geom),
            "properties": {
                "corpo_id": meta["id"],
                "nome": tags.get("name") or meta["nome"],
                "osm_type": el["type"],
                "osm_id": el["id"],
                "specie_attesa": meta["specie"],
                "kind": meta["kind"],
                "codice_proposto": bool(meta.get("codice_proposto")),
                "bank": "both" if meta["specie"] == "linea" else None,
            },
        })
    fc = {"type": "FeatureCollection", "name": "varese_comabbio_monate_raw", "features": features}
    VARESE_RAW.parent.mkdir(parents=True, exist_ok=True)
    VARESE_RAW.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"Scritte {len(features)} geometrie in {VARESE_RAW.name}")
    for f in features:
        p = f["properties"]
        geom = shape(f["geometry"])
        extra = f"{_lunghezza(geom)} m" if p["specie_attesa"] == "linea" else geom.geom_type
        segno = " proposto" if p["codice_proposto"] else ""
        print(f"  {p['corpo_id']:16} {p['osm_type']:10} {p['osm_id']:<10} {extra}{segno}")
    return fc


def _candidati_nominatim() -> list[dict]:
    out = []
    for cid, query, motivo in RICERCHE:
        hits = osm_client.nominatim_search(query, limit=3)
        voci = []
        for h in hits:
            voci.append({
                "nome": h.get("display_name"),
                "lon": float(h["lon"]),
                "lat": float(h["lat"]),
                "classe": h.get("class"),
                "tipo": h.get("type"),
            })
        out.append({"id": cid, "query": query, "motivo": motivo, "hits": voci})
        print(f"  {cid}: {len(voci)} hit")
    return out


def _sbocco(fc: dict, corso_id: str, lago_id: str, pin_id: str, nome: str) -> dict | None:
    by_id = {f["properties"]["corpo_id"]: f for f in fc["features"]}
    corso = by_id.get(corso_id)
    lago = by_id.get(lago_id)
    if not corso or not lago:
        return None
    linea = shape(corso["geometry"])
    poly = shape(lago["geometry"])
    if linea.geom_type not in ("LineString", "MultiLineString"):
        return None
    pt = _piu_vicino(_estremi(linea), poly)
    dist = round(geom_distance_m(poly, pt))
    return {
        "id": pin_id,
        "nome": nome,
        "lon": pt.x,
        "lat": pt.y,
        "distanza_lago_m": dist,
        "nota": "Estremo OSM più vicino allo specchio. Non è un caposaldo confermato.",
    }


def impalcatura(fc: dict) -> None:
    print("=== Candidati ===")
    ricerche = _candidati_nominatim()
    sbocchi = [
        _sbocco(fc, "bardello", "lago_varese", "sbocco_bardello", "Bardello — estremo verso il Lago di Varese"),
        _sbocco(fc, "acquanegra", "lago_monate", "sbocco_acquanegra", "Acquanegra — estremo verso il Lago di Monate"),
        _sbocco(fc, "tinella", "lago_varese", "foce_tinella", "Tinella — estremo verso il Lago di Varese"),
    ]
    features = []
    for f in fc["features"]:
        p = dict(f["properties"])
        geom = shape(f["geometry"])
        p.update({
            "layer": "acque",
            "stato": "proposto" if p.get("codice_proposto") else "grezzo",
            "id": p["corpo_id"],
        })
        if p["specie_attesa"] == "linea":
            p["lunghezza_m"] = _lunghezza(geom)
        features.append({"type": "Feature", "geometry": f["geometry"], "properties": p})
    for ric in ricerche:
        for i, h in enumerate(ric["hits"], start=1):
            features.append(point_feature(h["lon"], h["lat"], {
                "id": f"{ric['id']}_{i}",
                "nome": h["nome"],
                "kind": "candidato",
                "layer": "candidati",
                "stato": "non_confermato",
                "gruppo": ric["id"],
                "precisione": "nominatim",
                "note": ric["motivo"],
            }))
    for s in sbocchi:
        if not s:
            continue
        features.append(point_feature(s["lon"], s["lat"], {
            "id": s["id"],
            "nome": s["nome"],
            "kind": "sbocco",
            "layer": "candidati",
            "stato": "derivato_osm",
            "precisione": f"{s['distanza_lago_m']} m dallo specchio",
            "note": s["nota"],
        }))
    aperti = [
        "Schiranna: manca la torretta di arrivo. I 250 m × 50 m non sono disegnati.",
        "Oltrona: la fascia in lago alla foce del Tinella non è disegnata.",
        "Acquanegra: i due ponti non sono confermati, il tratto in divieto non è tagliato.",
        "Tinella: relation 3714984 proposta, non indicata. Il tratto da 1.000 m non è tagliato.",
        "Barona: nessun oggetto OSM. Il divieto resta solo nel testo dell'Acquanegra.",
        "Campi gara del Varese: fuori, non sono in mappa.",
    ]
    payload = {
        "type": "FeatureCollection",
        "name": "varese_comabbio_monate_impalcatura",
        "meta": {"stato": "impalcatura", "aggiornato": "2026-09-29", "aperti": aperti},
        "features": features,
    }
    VARESE_IMPALCATURA_JS.parent.mkdir(parents=True, exist_ok=True)
    VARESE_IMPALCATURA_JS.write_text(
        "window.VARESE_IMPALCATURA = " + json.dumps(payload, ensure_ascii=False) + ";\n",
        encoding="utf-8",
    )
    incerti = {
        "stato": "nessun punto verificato",
        "ricerche": ricerche,
        "sbocchi": [s for s in sbocchi if s],
        "aperti": aperti,
    }
    VARESE_INCERTI.write_text(json.dumps(incerti, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Impalcatura: {VARESE_IMPALCATURA_JS.name}")
    print(f"Incerti: {VARESE_INCERTI.name}")


def main() -> None:
    fc = scarica()
    impalcatura(fc)


if __name__ == "__main__":
    main()
