"""Reticolo OSM del bacino Margorabbia: asta, affluenti maggiori nominati e laghi.

Principio topologico: le way vengono fuse solo dove sono realmente contigue
(nodi condivisi, linemerge orientato) o separate da una lacuna di digitalizzazione
inferiore a MAX_JOIN_GAP_M. Nessuna corda viene tracciata attraverso laghi o versanti.
"""

from __future__ import annotations

import json

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import linemerge, polygonize, unary_union
from shapely.validation import make_valid

from config import BBOX, MAX_JOIN_GAP_M, MIN_ISOLATED_FRAGMENT_M, WATERWAYS_CACHE
from geo_utils import line_length_m, pt_dist_m


# --------------------------------------------------------------------------- download

def fetch_waterways(overpass_fn, force: bool = False) -> dict:
    if WATERWAYS_CACHE.exists() and not force:
        print(f"  cache waterways: {WATERWAYS_CACHE.relative_to(WATERWAYS_CACHE.parent.parent)}")
        return json.loads(WATERWAYS_CACHE.read_text(encoding="utf-8"))
    s, w, n, e = BBOX
    q = f"""[out:json][timeout:50];
(
  way["waterway"~"^(river|stream)$"]({s},{w},{n},{e});
);
(._;>;);
out;
"""
    data = overpass_fn(q)
    if not data:
        raise RuntimeError("Overpass non ha restituito le waterway del bacino")
    WATERWAYS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    WATERWAYS_CACHE.write_text(json.dumps(data), encoding="utf-8")
    print(f"  salvata cache {WATERWAYS_CACHE.name} ({len(data.get('elements', []))} elementi)")
    return data


def parse_ways(payload: dict) -> list[dict]:
    nodes = {el["id"]: el for el in payload.get("elements", []) if el["type"] == "node"}
    ways = []
    for el in payload.get("elements", []):
        if el["type"] != "way":
            continue
        tags = el.get("tags") or {}
        if tags.get("waterway") not in ("river", "stream"):
            continue
        coords = [[nodes[n]["lon"], nodes[n]["lat"]] for n in el.get("nodes", []) if n in nodes]
        if len(coords) < 2:
            continue
        ways.append({"id": el["id"], "name": tags.get("name") or "", "waterway": tags["waterway"], "geom": LineString(coords)})
    return ways


# --------------------------------------------------------------------------- linee

def select_named(ways: list[dict], names) -> list[dict]:
    wanted = {n.lower() for n in names}
    return [w for w in ways if w["name"].strip().lower() in wanted]


def _merge(ways: list[dict]) -> list[LineString]:
    geoms = [w["geom"] for w in ways if w["geom"].length > 0]
    if not geoms:
        return []
    merged = linemerge(geoms, directed=True)
    return [merged] if merged.geom_type == "LineString" else list(merged.geoms)


def _join_close(parts: list[LineString], max_gap_m: float) -> tuple[list[LineString], list[dict]]:
    """Unisce fine(A)->inizio(B) solo se distano meno di max_gap_m (lacune di digitalizzazione)."""
    parts = list(parts)
    joins = []
    changed = True
    while changed:
        changed = False
        for i, a in enumerate(parts):
            for j, b in enumerate(parts):
                if i == j:
                    continue
                gap = pt_dist_m(a.coords[-1], b.coords[0])
                if gap <= max_gap_m:
                    joins.append({"gap_m": round(gap, 1), "at": [round(c, 6) for c in a.coords[-1]]})
                    coords = list(a.coords) + list(b.coords)[(1 if gap == 0 else 0):]
                    parts = [p for k, p in enumerate(parts) if k not in (i, j)] + [LineString(coords)]
                    changed = True
                    break
            if changed:
                break
    return parts, joins


def _drop_fragments(parts: list[LineString], min_len_m: float) -> tuple[list[LineString], list[LineString]]:
    """Scarta monconi e frammenti corti (rami secondari, errori di digitalizzazione)."""
    keep, dropped = [], []
    for p in parts:
        (dropped if line_length_m(p) < min_len_m else keep).append(p)
    return keep, dropped


def build_watercourse(ways: list[dict], names, label: str) -> dict:
    """Parti continue (orientate secondo la corrente OSM) di un corso d'acqua nominato, dalla più lunga."""
    sel = select_named(ways, names)
    parts = _merge(sel)
    parts, joins = _join_close(parts, MAX_JOIN_GAP_M)
    parts, dropped = _drop_fragments(parts, MIN_ISOLATED_FRAGMENT_M)
    parts.sort(key=line_length_m, reverse=True)
    print(
        f"  {label}: {len(sel)} way -> {len(parts)} parti continue"
        + (f", {len(joins)} lacune <= {MAX_JOIN_GAP_M:.0f} m chiuse" if joins else "")
        + (f", {len(dropped)} frammenti < {MIN_ISOLATED_FRAGMENT_M:.0f} m scartati" if dropped else "")
    )
    return {"label": label, "way_ids": [w["id"] for w in sel], "parts": parts, "joins": joins, "dropped": dropped}


def downstream_stem(parts: list[LineString], receiver) -> LineString:
    """Parte d'asta che sfocia nel ricevente (quella su cui giacciono i capisaldi)."""
    return min(parts, key=lambda p: Point(p.coords[-1]).distance(receiver))


def local_reach(parts: list[LineString], at: Point, half_len_m: float) -> LineString | None:
    """Tratto di +/- half_len_m attorno al punto del corso più vicino ad `at`."""
    from geo_utils import locate_m, substring_m

    if not parts:
        return None
    line = min(parts, key=lambda p: p.distance(at))
    m = locate_m(line, at)
    return substring_m(line, m - half_len_m, m + half_len_m)


# --------------------------------------------------------------------------- laghi

def relation_polygon(payload: dict, osm_id: int):
    nodes = {el["id"]: el for el in payload["elements"] if el["type"] == "node"}
    ways = {el["id"]: el for el in payload["elements"] if el["type"] == "way"}
    rel = next(el for el in payload["elements"] if el["type"] == "relation" and el["id"] == osm_id)
    outer, inner = [], []
    for m in rel.get("members", []):
        if m["type"] != "way" or m["ref"] not in ways:
            continue
        c = [(nodes[n]["lon"], nodes[n]["lat"]) for n in ways[m["ref"]]["nodes"] if n in nodes]
        if len(c) >= 2:
            (inner if m.get("role") == "inner" else outer).append(LineString(c))
    if not outer:
        raise ValueError(f"nessun anello outer per relazione {osm_id}")
    polys_out = list(polygonize(unary_union(outer)))
    polys_in = list(polygonize(unary_union(inner))) if inner else []
    geom = unary_union(polys_out)
    if polys_in:
        geom = geom.difference(unary_union(polys_in))
    geom = make_valid(geom)
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))])
    if geom.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"relazione {osm_id}: geometria {geom.geom_type}")
    return geom
