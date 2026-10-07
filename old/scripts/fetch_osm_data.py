#!/usr/bin/env python3
"""Scarica per ID (way e relation) le acque del Ceresio e le scrive in GeoJSON.

Uso:  py -3 scripts/fetch_osm_data.py
Output: data/raw/ceresio_tresa_raw.geojson

Way e relation condividono lo spazio numerico: si tiene solo l'oggetto idrico.
Le relation multipolygon diventano poligoni (polygonize degli anelli).
"""

from __future__ import annotations

import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import LineString, MultiLineString, Point, mapping
from shapely.ops import linemerge, polygonize, unary_union
from shapely.validation import make_valid

import osm_client
from config import CERESIO_RAW, CERESIO_TRATTI, MAX_JOIN_GAP_M
from geo_utils import geom_distance_m, line_length_m, pt_dist_m

CORPI = [
    {"id": "lago_lugano", "osm_id": 1342576, "nome": "Lago di Lugano", "specie": "poligono"},
    {"id": "lago_piano", "osm_id": 176824, "nome": "Lago di Piano", "specie": "poligono"},
    {"id": "tresa", "osm_id": 2201762, "nome": "Fiume Tresa", "specie": "linea"},
    {"id": "cuccio", "osm_id": 3714983, "nome": "Torrente Cuccio", "specie": "linea"},
    {"id": "rezzo", "osm_id": 56676363, "nome": "Torrente Rezzo", "specie": "linea",
     "tratti": [56676363, 91803779, 1436650551, 1436650552]},
    {"id": "soldo", "osm_id": 56676160, "nome": "Torrente Soldo", "specie": "linea"},
    {"id": "trallo", "osm_id": 6485495, "nome": "Torrente Trallo", "specie": "linea"},
    {"id": "telo_osteno", "osm_id": 195989294, "nome": "Torrente Telo", "specie": "linea",
     "tratti": [195989294, 195989292]},
    {"id": "lagadone", "osm_id": 88471352, "nome": "Canale Lagadone", "specie": "linea",
     "tratti": [88471352, 1163685465, 1163685466, 1359706871, 1360190936,
                1360190937, 1360190938, 1360190939, 1360190942, 1360190943]},
    {"id": "lirone", "osm_id": 848395585, "nome": "Torrente Lirone", "specie": "linea",
     "tratti": [56676168, 848395585, 848395586]},
]


def overpass_query(ids: list[int]) -> str:
    body = "\n".join(f"  way({i});\n  relation({i});" for i in ids)
    return f"""[out:json][timeout:90];
(
{body}
);
out geom;
"""


def _coords(geom) -> list[tuple[float, float]]:
    return [(p["lon"], p["lat"]) for p in geom if "lon" in p and "lat" in p]


def is_water(tags: dict, nome_atteso: str) -> bool:
    if tags.get("highway") or tags.get("building") or tags.get("railway"):
        return False
    if tags.get("natural") == "water" or tags.get("water"):
        return True
    if tags.get("waterway") in ("river", "stream", "canal", "flowline", "drain"):
        return True
    if tags.get("type") in ("multipolygon", "waterway", "boundary") and (
        tags.get("natural") == "water" or tags.get("waterway") or tags.get("water")
    ):
        return True
    name = (tags.get("name") or "").lower()
    token = nome_atteso.split()[-1].lower()
    return token in name and tags.get("natural") != "coastline"


def _lines_from_members(el: dict) -> tuple[list[LineString], list[LineString]]:
    outer, inner = [], []
    for m in el.get("members") or []:
        coords = _coords(m.get("geometry") or [])
        if len(coords) < 2:
            continue
        line = LineString(coords)
        (inner if m.get("role") == "inner" else outer).append(line)
    return outer, inner


def _as_polygon(outer, inner):
    if not outer:
        return None
    polys = list(polygonize(unary_union(outer)))
    if not polys:
        return None
    geom = unary_union(polys)
    if inner:
        holes = list(polygonize(unary_union(inner)))
        if holes:
            geom = geom.difference(unary_union(holes))
    geom = make_valid(geom)
    if geom.geom_type == "GeometryCollection":
        keep = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        geom = unary_union(keep) if keep else None
    if geom is None or geom.is_empty or geom.geom_type not in ("Polygon", "MultiPolygon"):
        return None
    return geom


def _as_lines(lines: list[LineString]):
    if not lines:
        return None
    merged = linemerge(unary_union(lines))
    if merged.is_empty:
        return None
    if merged.geom_type == "LineString":
        parts = [merged]
    elif merged.geom_type == "MultiLineString":
        parts = list(merged.geoms)
    else:
        parts = [g for g in getattr(merged, "geoms", []) if g.geom_type == "LineString"]
    parts = [p for p in parts if p.length > 0]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiLineString(parts)


def element_geometry(el: dict, specie: str):
    if el["type"] == "way":
        coords = _coords(el.get("geometry") or [])
        if len(coords) < 2:
            return None
        line = LineString(coords)
        if specie == "poligono" and coords[0] == coords[-1] and len(coords) >= 4:
            return _as_polygon([line], [])
        return line
    outer, inner = _lines_from_members(el)
    if specie == "poligono":
        poly = _as_polygon(outer, inner)
        if poly is not None:
            return poly
    return _as_lines(outer)


def _way_line_from_api(osm_id: int) -> tuple[LineString | None, dict]:
    data = osm_client.osm_full("way", osm_id)
    nodes = {e["id"]: (e["lon"], e["lat"]) for e in data["elements"] if e["type"] == "node"}
    way = next(e for e in data["elements"] if e["type"] == "way")
    coords = [nodes[i] for i in way.get("nodes") or [] if i in nodes]
    if len(coords) < 2:
        return None, way.get("tags") or {}
    return LineString(coords), way.get("tags") or {}


def _unisci(lines: list[LineString], max_gap_m: float = MAX_JOIN_GAP_M) -> list[LineString]:
    """Unisce i pezzi dello stesso corso, anche se digitalizzati in versi opposti."""
    parts = [ln for ln in lines if ln is not None and line_length_m(ln) > 0]
    changed = True
    while changed and len(parts) > 1:
        changed = False
        best = None
        for i, a in enumerate(parts):
            for j in range(i + 1, len(parts)):
                b = parts[j]
                for ra in (False, True):
                    aa = LineString(list(a.coords)[::-1]) if ra else a
                    for rb in (False, True):
                        bb = LineString(list(b.coords)[::-1]) if rb else b
                        gap = pt_dist_m(aa.coords[-1], bb.coords[0])
                        if gap <= max_gap_m and (best is None or gap < best[0]):
                            best = (gap, i, j, ra, rb)
        if best is None:
            break
        gap, i, j, ra, rb = best
        a = LineString(list(parts[i].coords)[::-1]) if ra else parts[i]
        b = LineString(list(parts[j].coords)[::-1]) if rb else parts[j]
        coords = list(a.coords) + list(b.coords)[(1 if gap < 0.5 else 0):]
        parts = [p for k, p in enumerate(parts) if k not in (i, j)] + [LineString(coords)]
        changed = True
    return parts


def _come_geom(parts: list[LineString]):
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiLineString(parts)


def _tieni_collegate(meta: dict, lines: list[tuple[int, LineString]]) -> list[LineString]:
    """Per il Telo scarta il moncone che non tocca l'asta principale."""
    if meta["id"] != "telo_osteno":
        return [ln for _, ln in lines]
    principale = next(ln for i, ln in lines if i == meta["osm_id"])
    tenute = [principale]
    for i, ln in lines:
        if i == meta["osm_id"]:
            continue
        gap = min(
            geom_distance_m(principale, Point(ln.coords[0])),
            geom_distance_m(principale, Point(ln.coords[-1])),
        )
        if gap <= MAX_JOIN_GAP_M:
            tenute.append(ln)
            print(f"  telo {i}: agganciato ({gap:.0f} m)")
        else:
            print(f"  telo {i}: scartato, dista {gap:.0f} m dall'asta")
    return tenute


def completa_tratti_mancanti() -> None:
    """Aggiunge i pezzi di corso non compresi nell'ID principale e aggiorna il clip."""
    fc = json.loads(CERESIO_RAW.read_text(encoding="utf-8"))
    by_id = {f["properties"]["corpo_id"]: f for f in fc["features"]}
    for meta in CORPI:
        ids = meta.get("tratti")
        if not ids:
            continue
        scaricati = []
        for osm_id in ids:
            ln, tags = _way_line_from_api(osm_id)
            if ln is None:
                print(f"  senza geometria {meta['id']} {osm_id}")
                continue
            print(f"  {meta['id']} way/{osm_id} {tags.get('name') or ''} {line_length_m(ln):.0f} m")
            scaricati.append((osm_id, ln))
        tenute = _tieni_collegate(meta, scaricati)
        parts = _unisci(tenute)
        geom = _come_geom(parts)
        if geom is None:
            continue
        usate = [i for i, ln in scaricati if any(ln is t for t in tenute)]
        feat = by_id.get(meta["id"])
        if feat is None:
            feat = {"type": "Feature", "properties": {}, "geometry": None}
            fc["features"].append(feat)
            by_id[meta["id"]] = feat
        feat["geometry"] = mapping(geom)
        feat["properties"].update({
            "corpo_id": meta["id"],
            "nome": meta["nome"],
            "osm_type": "way",
            "osm_id": meta["osm_id"],
            "osm_ids": usate,
            "specie_attesa": "linea",
        })
        lung = round(sum(line_length_m(p) for p in parts))
        print(f"  -> {meta['nome']}: {len(parts)} parti, {lung} m, way {usate}")
    CERESIO_RAW.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    _allinea_tratti(fc)
    print(f"Aggiornato {CERESIO_RAW.name}")


def _allinea_tratti(raw_fc: dict) -> None:
    if not CERESIO_TRATTI.exists():
        return
    tratti = json.loads(CERESIO_TRATTI.read_text(encoding="utf-8"))
    nuovi = {"rezzo", "telo_osteno", "lagadone", "lirone"}
    tratti["features"] = [f for f in tratti["features"] if f["properties"].get("corpo_id") not in nuovi]
    for f in raw_fc["features"]:
        if f["properties"]["corpo_id"] not in nuovi:
            continue
        geom = f["geometry"]
        if geom["type"] == "LineString":
            geoms = [geom]
        elif geom["type"] == "MultiLineString":
            geoms = [{"type": "LineString", "coordinates": c} for c in geom["coordinates"]]
        else:
            continue
        for g in geoms:
            ln = LineString(g["coordinates"])
            tratti["features"].append({
                "type": "Feature",
                "geometry": g,
                "properties": {
                    "corpo_id": f["properties"]["corpo_id"],
                    "nome": f["properties"]["nome"],
                    "geometria": "linea",
                    "clip": "intero_in_italia",
                    "bank": "both",
                    "segmento_id": None,
                    "lunghezza_m": round(line_length_m(ln)),
                },
            })
    CERESIO_TRATTI.write_text(json.dumps(tratti, ensure_ascii=False), encoding="utf-8")
    print(f"Allineato {CERESIO_TRATTI.name}")


def fetch() -> dict:
    ids = [c["osm_id"] for c in CORPI]
    by_id = {c["osm_id"]: c for c in CORPI}
    payload = osm_client.overpass(overpass_query(ids))
    if not payload:
        raise RuntimeError("Overpass non ha risposto per gli ID del Ceresio")
    chosen: dict[int, dict] = {}
    for el in payload.get("elements") or []:
        meta = by_id.get(el.get("id"))
        if not meta:
            continue
        tags = el.get("tags") or {}
        if not is_water(tags, meta["nome"]):
            print(f"  scartato {el['type']}/{el['id']} ({tags.get('name') or tags.get('highway') or 'senza nome idrico'})")
            continue
        prev = chosen.get(el["id"])
        # A parità di ID tiene la relation se la way non è idrica (già filtrata) o se è un poligono.
        if prev is None or el["type"] == "relation":
            chosen[el["id"]] = el
    features = []
    for meta in CORPI:
        el = chosen.get(meta["osm_id"])
        if el is None:
            print(f"  MANCA {meta['nome']} ({meta['osm_id']})")
            continue
        geom = element_geometry(el, meta["specie"])
        if geom is None:
            print(f"  geometria vuota {meta['nome']}")
            continue
        tags = el.get("tags") or {}
        features.append({
            "type": "Feature",
            "geometry": mapping(geom),
            "properties": {
                "corpo_id": meta["id"],
                "nome": tags.get("name") or meta["nome"],
                "osm_type": el["type"],
                "osm_id": el["id"],
                "specie_attesa": meta["specie"],
            },
        })
    fc = {"type": "FeatureCollection", "name": "ceresio_tresa_raw", "features": features}
    CERESIO_RAW.parent.mkdir(parents=True, exist_ok=True)
    CERESIO_RAW.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    print(f"Scritte {len(features)} geometrie in {CERESIO_RAW.name}")
    for f in features:
        p = f["properties"]
        print(f"  {p['corpo_id']:14s} {p['osm_type']:10s} {p['osm_id']:<10} {f['geometry']['type']}")
    completa_tratti_mancanti()
    return fc


if __name__ == "__main__":
    if "--tratti-mancanti" in sys.argv:
        completa_tratti_mancanti()
    else:
        fetch()
