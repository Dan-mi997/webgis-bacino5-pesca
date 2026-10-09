"""Tagli con confine esatto su laghi e aste.

I vertici in normativa sono [lat, lon]. Le geometrie Shapely restano (lon, lat).
"""

from __future__ import annotations

from shapely.affinity import scale
from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.ops import linemerge, nearest_points, polygonize, split, substring, unary_union

from geo_utils import geom_distance_m, line_length_m, project_info, substring_m

TIPI_SPAZIALI = ("semipiano", "poligono_costa_e_confine", "poligono_due_punti_costa")
_AREA_MIN = 1e-9


def latlon(pair) -> Point:
    lat, lon = pair
    return Point(float(lon), float(lat))


def pulisci(geom):
    if geom is None or geom.is_empty:
        return geom
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def pezzi_poligono(geom) -> list:
    geom = pulisci(geom)
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom] if geom.area > _AREA_MIN else []
    if geom.geom_type == "MultiPolygon":
        return [g for g in geom.geoms if g.area > _AREA_MIN]
    if geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(pezzi_poligono(g))
        return out
    return []


def unisci(geoms):
    vivi = [g for g in geoms if g is not None and not g.is_empty]
    if not vivi:
        return Polygon()
    return pulisci(unary_union(vivi))


def costa_di(geom) -> LineString | MultiLineString:
    """Anelli esterni: la costa, senza i tagli artificiali interni."""
    geom = pulisci(geom)
    anelli = []
    if geom.geom_type == "Polygon":
        anelli = [geom.exterior]
    elif geom.geom_type == "MultiPolygon":
        anelli = [p.exterior for p in geom.geoms]
    linee = [LineString(r.coords) for r in anelli if len(r.coords) >= 2]
    if not linee:
        return LineString()
    if len(linee) == 1:
        return linee[0]
    return MultiLineString(linee)


def costa_sul_pezzo(pezzo, costa_originale):
    """Solo il bordo che coincide con la costa originaria, non il taglio in acqua."""
    if costa_originale is None or costa_originale.is_empty:
        return LineString()
    bordo = pezzo.boundary
    fascia = costa_originale.buffer(0.00025)
    tratto = bordo.intersection(fascia)
    if tratto.is_empty:
        return LineString()
    if tratto.geom_type == "GeometryCollection":
        linee = [g for g in tratto.geoms if g.geom_type in ("LineString", "MultiLineString", "LinearRing")]
        tratto = unisci(linee)
    if tratto.geom_type == "LinearRing":
        return LineString(tratto.coords)
    return tratto


def _estendi(line: LineString, fattore: float = 4.0) -> LineString:
    (x1, y1), (x2, y2) = line.coords[0], line.coords[-1]
    return LineString([(x1 - (x2 - x1) * fattore, y1 - (y2 - y1) * fattore),
                       (x2 + (x2 - x1) * fattore, y2 + (y2 - y1) * fattore)])


def _a_nord(poly, linea: LineString) -> bool:
    c = poly.representative_point()
    (x1, y1), (x2, y2) = linea.coords[0], linea.coords[-1]
    if abs(x2 - x1) < 1e-12:
        return c.y >= (y1 + y2) / 2
    t = (c.x - x1) / (x2 - x1)
    return c.y >= y1 + t * (y2 - y1)


def split_semipiano(lago, linea_latlon: list) -> tuple[list, list]:
    """Ritorna (pezzi a nord della linea, pezzi a sud)."""
    cruda = LineString([latlon(linea_latlon[0]).coords[0], latlon(linea_latlon[1]).coords[0]])
    taglio = _estendi(cruda)
    lago = pulisci(lago)
    try:
        parti = pezzi_poligono(split(lago, taglio))
    except Exception:
        parti = []
    if len(parti) < 2:
        (x1, y1), (x2, y2) = taglio.coords
        dx, dy = x2 - x1, y2 - y1
        span = 2.0
        nord = Polygon([(x1, y1), (x2, y2), (x2, y2 + span), (x1, y1 + span)])
        sud = Polygon([(x1, y1), (x2, y2), (x2, y2 - span), (x1, y1 - span)])
        parti = pezzi_poligono(lago.intersection(nord)) + pezzi_poligono(lago.intersection(sud))
    a_nord, a_sud = [], []
    for p in parti:
        (a_nord if _a_nord(p, cruda) else a_sud).append(p)
    return a_nord, a_sud


def _arco(ring: LineString, a: Point, b: Point, scegli) -> LineString:
    """Uno dei due archi del ring chiuso fra a e b. `scegli` riceve i due archi."""
    if ring.is_empty:
        return LineString([a.coords[0], b.coords[0]])
    ra = ring.project(a, normalized=True)
    rb = ring.project(b, normalized=True)
    lo, hi = min(ra, rb), max(ra, rb)
    diretto = substring(ring, lo, hi, normalized=True)
    coda = substring(ring, hi, 1.0, normalized=True)
    testa = substring(ring, 0.0, lo, normalized=True)

    def _unibile(g) -> bool:
        return g is not None and not g.is_empty and g.geom_type == "LineString" and len(list(g.coords)) >= 2

    parti = [g for g in (coda, testa) if _unibile(g)]
    if len(parti) == 2:
        altro = linemerge(parti)
    elif len(parti) == 1:
        altro = parti[0]
    else:
        altro = LineString()
    if altro.geom_type == "MultiLineString":
        altro = max(altro.geoms, key=lambda g: g.length)
    candidati = [g for g in (diretto, altro) if _unibile(g)]
    if not candidati:
        return LineString([a.coords[0], b.coords[0]])
    if len(candidati) == 1:
        return candidati[0]
    return scegli(candidati[0], candidati[1])


def _poligono_arco_corda(arco: LineString) -> Polygon | None:
    coords = list(arco.coords)
    if len(coords) < 2:
        return None
    if coords[0] != coords[-1]:
        coords = coords + [coords[0]]
    if len(coords) < 4:
        return None
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = poly.buffer(0)
    pezzi = pezzi_poligono(poly)
    if not pezzi:
        return None
    return max(pezzi, key=lambda g: g.area)


def poligono_due_punti_costa(lago, punti_latlon: list):
    """Poligono chiuso dalla corda fra i due punti e dall'arco di costa interno al lago."""
    lago = pulisci(lago)
    anello = costa_di(lago)
    if anello.geom_type != "LineString":
        anello = max(anello.geoms, key=line_length_m)
    a = nearest_points(anello, latlon(punti_latlon[0]))[0]
    b = nearest_points(anello, latlon(punti_latlon[1]))[0]

    def scegli(u, v):
        pu, pv = _poligono_arco_corda(u), _poligono_arco_corda(v)
        dentro = []
        for arco, poly in ((u, pu), (v, pv)):
            if poly is None:
                continue
            comune = poly.intersection(lago).area
            if poly.area > 0 and comune / poly.area > 0.6:
                dentro.append((arco, poly))
        if dentro:
            return min(dentro, key=lambda t: t[1].area)[0]
        return u if line_length_m(u) <= line_length_m(v) else v

    arco = _arco(anello, a, b, scegli)
    poly = _poligono_arco_corda(arco)
    if poly is None:
        return []
    return pezzi_poligono(poly.intersection(lago))


def _classe_vertice(pt: Point, lago, costa, confine_nel_lago) -> str:
    """Terra se il vertice sta sulla costa; acqua se sta sul confine regionale.

    Il clip regionale lascia i vertici d'acqua appena fuori dal poligono del lago.
    Quei punti non vanno trattati come terraferma: sono sul confine, dentro il lago.
    """
    d_costa = geom_distance_m(costa, pt)
    d_confine = geom_distance_m(confine_nel_lago, pt) if not confine_nel_lago.is_empty else 1e9
    if d_confine + 80 < d_costa:
        return "acqua"
    if not lago.covers(pt) or d_costa + 30 < d_confine:
        return "terra"
    return "acqua"


def _snap(geom, pt: Point) -> Point:
    if geom is None or geom.is_empty:
        return pt
    return nearest_points(geom, pt)[0]


def poligono_costa_e_confine(lago, confine_regionale, vertici_latlon: list, costa=None):
    """Vertici in terra agganciati alla costa; vertici in acqua al confine regionale nel lago.

    Il lato terra-terra segue la costa. Il lato acqua-acqua segue il confine regionale.
    I lati misti sono il raccordo fra i due.
    """
    lago = pulisci(lago)
    confine = pulisci(confine_regionale)
    if costa is None:
        costa = costa_di(lago)
    if costa.geom_type == "MultiLineString":
        costa_line = max(costa.geoms, key=line_length_m)
    else:
        costa_line = costa
    bordo = confine.boundary.intersection(lago.buffer(0.0004))
    if bordo.is_empty:
        bordo = costa_line
    grezzi = [latlon(v) for v in vertici_latlon]
    classi = [_classe_vertice(p, lago, costa, bordo) for p in grezzi]
    agganci = [_snap(costa if c == "terra" else bordo, p) for p, c in zip(grezzi, classi)]

    def linea_lato(i: int):
        a, b = agganci[i], agganci[(i + 1) % len(agganci)]
        ca, cb = classi[i], classi[(i + 1) % len(classi)]
        if ca == cb == "terra":
            return _arco(costa_line, a, b, lambda u, v: u if line_length_m(u) <= line_length_m(v) else v)
        if ca == cb == "acqua":
            supporto = bordo if bordo.geom_type == "LineString" else linemerge(bordo)
            if supporto.geom_type != "LineString":
                return LineString([a.coords[0], b.coords[0]])
            return _arco(supporto, a, b, lambda u, v: u if line_length_m(u) <= line_length_m(v) else v)
        return LineString([a.coords[0], b.coords[0]])

    lati = [linea_lato(i) for i in range(len(agganci))]
    polys = [p for p in polygonize(unary_union(lati)) if p.area > _AREA_MIN]
    if not polys:
        hull = Polygon([(p.x, p.y) for p in agganci])
        return pezzi_poligono(hull.intersection(lago)), classi
    # Il poligono cercato sta nel lago e contiene (o sfiora) i quattro agganci.
    def punteggio(poly: Polygon) -> float:
        dentro = poly.intersection(lago).area
        if poly.area <= 0:
            return -1
        copre = sum(1 for p in agganci if poly.buffer(0.001).covers(p))
        return copre * 10 + dentro / poly.area
    scelto = max(polys, key=punteggio)
    return pezzi_poligono(scelto.intersection(lago)), classi


def tratto_fino_al_lago(linee: list[LineString], origine_latlon, lago) -> list[LineString]:
    """Dal punto, verso valle, fino a toccare il lago. Le linee sono centerline del corpo."""
    if not linee or lago is None or lago.is_empty:
        return []
    origine = latlon(origine_latlon)
    ranked = []
    for i, line in enumerate(linee):
        _proj, _m, dist = project_info(line, origine.x, origine.y)
        ranked.append((dist, i))
    ranked.sort()
    dist, idx = ranked[0]
    if dist > 800:
        return []
    line = linee[idx]
    proj, metri, _dist = project_info(line, origine.x, origine.y)
    totale = line_length_m(line)
    monte = substring_m(line, 0, metri)
    valle = substring_m(line, metri, totale)

    def verso_lago(piece: LineString) -> bool:
        if piece.is_empty or len(piece.coords) < 2:
            return False
        inizio, fine = Point(piece.coords[0]), Point(piece.coords[-1])
        return geom_distance_m(lago, fine) <= geom_distance_m(lago, inizio)

    pezzo = valle if verso_lago(valle) or not verso_lago(monte) else monte
    # Se la centerline entra nel lago, tieni solo il tratto ancora fuori, fino al bordo.
    if pezzo.intersects(lago):
        fuori = pezzo.difference(lago.buffer(1e-5))
        candidati = []
        if fuori.geom_type == "LineString":
            candidati = [fuori]
        elif fuori.geom_type == "MultiLineString":
            candidati = list(fuori.geoms)
        elif fuori.geom_type == "GeometryCollection":
            candidati = [g for g in fuori.geoms if g.geom_type == "LineString"]
        if candidati:
            pezzo = min(candidati, key=lambda g: geom_distance_m(g, proj))
    if pezzo.is_empty or line_length_m(pezzo) < 20:
        return []
    return [pezzo]


def buffer_m(pt: Point, metri: float) -> Polygon:
    """Cerchio metrico approssimato in gradi (raggio nord-sud e est-ovest)."""
    import math
    dy = metri / 111320.0
    dx = metri / (111320.0 * max(0.2, math.cos(math.radians(pt.y))))
    return scale(pt.buffer(1.0, resolution=24), dx, dy, origin=pt)


def fascia_lungo_costa(lago, origine: Point, lunghezza_m: float, distanza_m: float, verso: str | None = None):
    """Striscia dalla costa verso l'interno, lunga `lunghezza_m` a partire dal punto."""
    lago = pulisci(lago)
    anello = costa_di(lago)
    if anello.geom_type == "MultiLineString":
        anello = max(anello.geoms, key=line_length_m)
    snap = nearest_points(anello, origine)[0]
    metri = line_length_m(anello) * anello.project(snap, normalized=True)
    avanti = substring_m(anello, metri, metri + lunghezza_m)
    indietro = substring_m(anello, metri - lunghezza_m, metri)

    def quota(line: LineString) -> float:
        coords = list(line.coords) if line is not None and not line.is_empty else []
        if len(coords) < 2:
            return -999.0
        return Point(coords[-1]).y

    if verso == "nord":
        arco = avanti if quota(avanti) >= quota(indietro) else indietro
    elif verso == "sud":
        arco = avanti if quota(avanti) <= quota(indietro) else indietro
    else:
        arco = avanti
    if arco.is_empty:
        return []
    gradi = distanza_m / 111320.0
    return pezzi_poligono(lago.intersection(arco.buffer(gradi)))


def arco_fra_punti(costa, punto_a: dict, punto_b: dict) -> LineString:
    """Arco di costa più corto fra due capisaldi con lat/lon."""
    if costa is None or costa.is_empty:
        return LineString()
    ring = costa if costa.geom_type == "LineString" else max(costa.geoms, key=line_length_m)
    a = nearest_points(ring, Point(float(punto_a["lon"]), float(punto_a["lat"])))[0]
    b = nearest_points(ring, Point(float(punto_b["lon"]), float(punto_b["lat"])))[0]
    return _arco(ring, a, b, lambda u, v: u if line_length_m(u) <= line_length_m(v) else v)


def self_test() -> None:
    lago = Polygon([(9.30, 45.80), (9.36, 45.80), (9.36, 45.84), (9.30, 45.84)])
    nord, sud = split_semipiano(lago, [[45.82, 9.37], [45.82, 9.29]])
    assert nord and sud, (nord, sud)
    assert all(p.representative_point().y >= 45.82 for p in nord)
    assert all(p.representative_point().y < 45.82 for p in sud)
    zona = poligono_due_punti_costa(lago, [[45.84, 9.31], [45.84, 9.35]])
    assert zona and zona[0].area < lago.area
    print("tagli_geometrici self-test ok")


if __name__ == "__main__":
    self_test()
