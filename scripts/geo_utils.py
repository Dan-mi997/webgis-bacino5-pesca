"""Utility geometriche in coordinate geografiche (lon, lat)."""

from __future__ import annotations

import math

from shapely.geometry import LineString, Point, mapping
from shapely.ops import substring


def haversine_m(lon1, lat1, lon2, lat2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def pt_dist_m(a, b) -> float:
    return haversine_m(a[0], a[1], b[0], b[1])


def line_length_m(line: LineString) -> float:
    coords = list(line.coords)
    return sum(pt_dist_m(a, b) for a, b in zip(coords, coords[1:]))


def max_segment_m(line: LineString) -> float:
    coords = list(line.coords)
    return max((pt_dist_m(a, b) for a, b in zip(coords, coords[1:])), default=0.0)


def geom_distance_m(geom, pt: Point) -> float:
    """Distanza metrica approssimata punto-geometria (via punto più vicino)."""
    from shapely.ops import nearest_points

    near = nearest_points(geom, pt)[0]
    return haversine_m(pt.x, pt.y, near.x, near.y)


def locate_m(line: LineString, pt: Point) -> float:
    return line.project(pt, normalized=True) * line_length_m(line)


def point_at_m(line: LineString, dist_m: float) -> Point:
    total = line_length_m(line)
    if total == 0:
        return Point(line.coords[0])
    return line.interpolate(max(0.0, min(1.0, dist_m / total)), normalized=True)


def substring_m(line: LineString, start_m: float, end_m: float) -> LineString:
    total = line_length_m(line)
    if total == 0:
        return line
    a = max(0.0, min(total, min(start_m, end_m)))
    b = max(0.0, min(total, max(start_m, end_m)))
    if b - a < 1.0:
        b = min(total, a + 1.0)
    g = substring(line, a / total, b / total, normalized=True)
    if g.is_empty or g.geom_type == "Point":
        return LineString([point_at_m(line, a).coords[0], point_at_m(line, a + 0.5).coords[0]])
    return g


def project_info(line: LineString, lon: float, lat: float) -> tuple[Point, float, float]:
    """(punto proiettato, progressiva in m lungo la linea, distanza in m dalla linea)."""
    pt = Point(lon, lat)
    proj = line.interpolate(line.project(pt))
    return proj, locate_m(line, proj), haversine_m(lon, lat, proj.x, proj.y)


def feature(geom, props: dict) -> dict:
    return {"type": "Feature", "geometry": mapping(geom), "properties": props}


def point_feature(lon: float, lat: float, props: dict) -> dict:
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}
