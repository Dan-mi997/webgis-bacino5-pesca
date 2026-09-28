#!/usr/bin/env python3
"""Clip del Ceresio sul confine di Stato e capisaldi non univoci (STEP 3).

Non pubblica la mappa e non marca alcun pin come verificato.
Scrive data/geojson/ceresio_tratti.geojson e ceresio_capisaldi_incerti.json.
"""

from __future__ import annotations

import json
import math
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.affinity import scale
from shapely.geometry import LineString, MultiLineString, Point, box, shape
from shapely.ops import linemerge, polygonize, unary_union
from shapely.validation import make_valid

import osm_client
from config import CERESIO_INCERTI, CERESIO_INDICATI, CERESIO_RAW, CERESIO_TRATTI
from geo_utils import feature, geom_distance_m, line_length_m, point_at_m, substring_m

# Punti di controllo a terra, non sull'acqua. Servono a etichettare i pezzi del riquadro.
PUNTI_IT = {
    "porto_ceresio": (8.901, 45.968),
    "porlezza": (9.130, 46.038),
    "campione": (8.971, 45.970),
    "lavena": (8.857, 45.967),
    "brusimpiano": (8.890, 45.945),
    "luino": (8.747, 46.002),
}
PUNTI_CH = {
    "lugano": (8.951, 46.003),
    "morcote": (8.917, 45.928),
    "melide": (8.949, 45.955),
    "capolago": (8.981, 45.905),
}
SOGLIA_M = 80.0

# Capisaldi da sondare. I campi gara non si cercano: dal 2026-09-28 sono fuori perimetro.
# La foce del Tresa nel Verbano si affronta con il Lago Maggiore, non qui.
SONDE = [
    {"id": "ponte_dogana", "corpi": ["tresa", "lago_lugano"], "q": "Ponte della Dogana, Lavena Ponte Tresa", "nomi": ["dogana"], "uso": "Pesca notturna Tresa (inizio) e divieto sulle piattaforme doganali"},
    {"id": "chiusa_regolazione", "corpi": ["tresa"], "q": "chiusa regolazione acque, Lavena Ponte Tresa", "nomi": ["chiusa"], "uso": "Pesca notturna Tresa (fine tratto Dogana–chiusa)"},
    {"id": "diga_creva", "corpi": ["tresa"], "q": "diga di Creva, Luino", "nomi": ["creva"], "uso": "Pesca notturna della bottatrice a monte della diga"},
    {"id": "ponte_biviglione", "corpi": ["tresa"], "q": "ponte di ferro Biviglione", "nomi": ["biviglione"], "uso": "Fine del tratto notturno bottatrice"},
    {"id": "piazza_europa", "corpi": ["tresa"], "q": "Piazza Europa, Lavena Ponte Tresa", "nomi": ["europa"], "uso": "Divieto Lungo Argine / Piazza Europa / Piazza Mercato"},
    {"id": "piazza_mercato", "corpi": ["tresa"], "q": "Piazza Mercato, Lavena Ponte Tresa", "nomi": ["mercato"], "uso": "Divieto Lungo Argine / Piazza Europa / Piazza Mercato"},
    {"id": "vecchia_filanda", "corpi": ["lago_lugano"], "q": "Vecchia Filanda, Lavena Ponte Tresa", "nomi": ["filanda"], "uso": "Inizio canneto dello stretto di Lavena"},
    {"id": "grotto_bagat", "corpi": ["lago_lugano"], "q": "Grotto del Bagat, Lavena Ponte Tresa", "nomi": ["bagat"], "uso": "Fine canneto dello stretto di Lavena"},
    {"id": "ponte_bigattini", "corpi": ["trallo"], "q": "via Bigattini, Brusimpiano", "nomi": ["bigattini", "bagattini"], "uso": "Inizio divieto Trallo (ponte–foce, circa 500 m)"},
]


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


def _member_lines(el: dict) -> list[LineString]:
    lines = []
    for m in el.get("members") or []:
        geom = m.get("geometry") or []
        coords = [(p["lon"], p["lat"]) for p in geom if "lon" in p]
        if len(coords) >= 2:
            lines.append(LineString(coords))
    return lines


def _poly_from_relation(el: dict):
    lines = _member_lines(el)
    if not lines:
        return None
    polys = list(polygonize(unary_union(lines)))
    if not polys:
        return None
    return make_valid(unary_union(polys))


def _way_lines(payload) -> tuple[list[LineString], list[dict]]:
    lines, tags = [], []
    for el in (payload or {}).get("elements") or []:
        if el.get("type") not in (None, "way"):
            continue
        coords = [(p["lon"], p["lat"]) for p in (el.get("geometry") or []) if "lon" in p]
        if len(coords) >= 2:
            lines.append(LineString(coords))
            tags.append(el.get("tags") or {})
    return lines, tags


def _lato_sinistro(pt: Point, ln: LineString) -> bool:
    i = min(range(len(ln.coords) - 1), key=lambda k: LineString([ln.coords[k], ln.coords[k + 1]]).distance(pt))
    ax, ay = ln.coords[i]
    bx, by = ln.coords[i + 1]
    return (bx - ax) * (pt.y - ay) - (by - ay) * (pt.x - ax) > 0


def _e_italia(pt: Point, lines, tags) -> bool | None:
    if not lines:
        return None
    j = min(range(len(lines)), key=lambda k: lines[k].distance(pt))
    left = tags[j].get("region:left") or ""
    sinistra = _lato_sinistro(pt, lines[j])
    if "Lombardia" in left or left.startswith("Italia"):
        return sinistra
    if "Ticino" in left or "Svizzera" in left or "Schweiz" in left:
        return not sinistra
    return None


def _prolunga_a_riva(lines, lago) -> list[LineString]:
    """Il confine OSM nel lago ha buchi di centinaia di metri: si prolunga l'ultimo lato fino a riva."""
    ring = lago.boundary
    extra = []
    for ln in lines:
        if not ln.intersects(lago.buffer(-0.00015)) or len(ln.coords) < 2:
            continue
        for end in (0, -1):
            if end == 0:
                apt, bpt = ln.coords[1], ln.coords[0]
            else:
                apt, bpt = ln.coords[-2], ln.coords[-1]
            shore = ring.interpolate(ring.project(Point(bpt)))
            if geom_distance_m(Point(bpt), shore) < 40:
                continue
            lat = bpt[1]
            dx = (bpt[0] - apt[0]) * 111320 * math.cos(math.radians(lat))
            dy = (bpt[1] - apt[1]) * 110540
            length = math.hypot(dx, dy) or 1.0
            metri = 6000.0
            far = (
                bpt[0] + dx / length * metri / (111320 * math.cos(math.radians(lat))),
                bpt[1] + dy / length * metri / 110540,
            )
            hit = LineString([bpt, far]).intersection(ring)
            dest = None
            if hit.geom_type == "Point":
                dest = hit
            elif hit.geom_type == "MultiPoint":
                dest = min(hit.geoms, key=lambda p: geom_distance_m(Point(bpt), p))
            elif hit.geom_type == "LineString" and len(hit.coords):
                dest = Point(hit.coords[0])
            if dest is not None:
                extra.append(LineString([bpt, (dest.x, dest.y)]))
    return extra


def confine_italiano(frame, lago):
    """Terre italiane nel riquadro e parte italiana del lago.

    Nel lago il confine OSM non è continuo. I pezzi già chiusi (Porlezza, sponda di
    Lavena-Brusimpiano, Campione) si tengono interi. Il bacino centrale si spezza
    prolungando il confine fino a riva e tenendo il lato Lombardia.
    """
    s, w, n, e = frame.bounds[1], frame.bounds[0], frame.bounds[3], frame.bounds[2]
    q = f"""[out:json][timeout:80];
way["boundary"="administrative"]["admin_level"="2"]({s},{w},{n},{e});
out geom;
"""
    lines, tags = _way_lines(osm_client.overpass(q))
    campione = None
    rel = osm_client.overpass("""[out:json][timeout:60];
relation["name"="Campione d'Italia"]["boundary"="administrative"];
out geom;
""")
    if rel:
        for el in rel.get("elements") or []:
            if el.get("type") == "relation":
                campione = _poly_from_relation(el)
                if campione is not None:
                    break
    if not lines:
        raise RuntimeError("Overpass non ha restituito il confine di Stato nel riquadro del Ceresio")
    seed = unary_union(lines + [frame.boundary])
    pezzi = [p for p in polygonize(seed) if p.area > 1e-8]
    italia, svizzera = [], []
    for p in pezzi:
        hit_it = [k for k, (lon, lat) in PUNTI_IT.items() if p.covers(Point(lon, lat))]
        hit_ch = [k for k, (lon, lat) in PUNTI_CH.items() if p.covers(Point(lon, lat))]
        if hit_it and not hit_ch:
            italia.append(p)
        elif hit_ch and not hit_it:
            svizzera.append(p)
    if not italia:
        raise RuntimeError("Il confine non isola nessun pezzo di territorio italiano")
    terra = make_valid(unary_union(italia))
    if campione is not None:
        terra = make_valid(unary_union([terra, campione]))
    print(f"  confine: {len(lines)} way, pezzi IT {len(italia)}, pezzi CH {len(svizzera)}, Campione={'sì' if campione is not None else 'no'}")

    extra = _prolunga_a_riva(lines, lago)
    facce = [
        p for p in polygonize(unary_union(lines + extra + [lago.boundary]))
        if (not p.is_empty) and p.representative_point().within(lago) and p.area > 1e-7
    ]
    terre_it = make_valid(unary_union(italia))
    tenute = []
    for g in facce:
        rep = g.representative_point()
        lato = _e_italia(rep, lines, tags)
        host_it = terre_it.covers(rep)
        if host_it or lato is True:
            tenute.append(g)
    if campione is not None:
        tenute.append(make_valid(lago.intersection(campione)))
    lago_it = make_valid(unary_union([g for g in tenute if g is not None and not g.is_empty]))
    # Se un punto di controllo svizzero cade ancora nel lago tenuto, si scarta quella faccia.
    for nome, (lon, lat) in PUNTI_CH.items():
        p = Point(lon, lat)
        if not (lago.covers(p) and lago_it.covers(p)):
            continue
        lago_it = make_valid(unary_union([g for g in _parts(lago_it) if not g.covers(p)]))
        print(f"  scartata la faccia che conteneva {nome}")
    print(f"  lago italiano: {lago_it.area / lago.area:.0%} della superficie OSM")
    sv = make_valid(unary_union(svizzera)) if svizzera else box(0, 0, 0, 0)
    return terra, sv, lago_it


def buffer_m(pt: Point, metri: float):
    lat = pt.y
    kx = 111320.0 * math.cos(math.radians(lat))
    ky = 110540.0
    scaled = scale(pt, xfact=kx, yfact=ky, origin=(0, 0))
    return scale(scaled.buffer(metri), xfact=1 / kx, yfact=1 / ky, origin=(0, 0))


def _in_italy(pt: Point, italia) -> bool:
    return italia.covers(pt)


def lato_punto(a, b, metri: float, sinistra: bool) -> Point:
    lat = (a[1] + b[1]) / 2
    dx = (b[0] - a[0]) * 111320.0 * math.cos(math.radians(lat))
    dy = (b[1] - a[1]) * 110540.0
    length = math.hypot(dx, dy) or 1.0
    # Sinistra rispetto al verso della linea: (-dy, dx).
    sign = 1.0 if sinistra else -1.0
    ox, oy = -dy / length * metri * sign, dx / length * metri * sign
    return Point(a[0] + (b[0] - a[0]) * 0.5 + ox / (111320.0 * math.cos(math.radians(lat))),
                 a[1] + (b[1] - a[1]) * 0.5 + oy / 110540.0)


def orienta_verso_valle(line: LineString, valle: Point) -> LineString:
    if Point(line.coords[0]).distance(valle) < Point(line.coords[-1]).distance(valle):
        return LineString(list(line.coords)[::-1])
    return line


def classifica_tresa(line: LineString, italia) -> list[tuple[LineString, str]]:
    """Tiene l'asse se almeno una sponda è in Italia. bank è left/right/both guardando verso valle."""
    coords = list(line.coords)
    if len(coords) < 2:
        return []
    # Campioni ogni ~40 m, poi si ricompongono i tratti omogenei.
    totale = line_length_m(line)
    step = 40.0
    n = max(2, int(totale / step))
    classi = []
    for i in range(n):
        d0 = totale * i / n
        d1 = totale * (i + 1) / n
        mid = point_at_m(line, (d0 + d1) / 2)
        a = point_at_m(line, d0)
        b = point_at_m(line, min(totale, d1))
        left = lato_punto((a.x, a.y), (b.x, b.y), 30.0, True)
        right = lato_punto((a.x, a.y), (b.x, b.y), 30.0, False)
        # Se il campione cade in mezzo al fiume, conta la sponda.
        it_l, it_r = _in_italy(left, italia), _in_italy(right, italia)
        if it_l and it_r:
            bank = "both"
        elif it_l:
            bank = "left"
        elif it_r:
            bank = "right"
        elif _in_italy(mid, italia):
            bank = "both"
        else:
            bank = None
        classi.append((d0, d1, bank))
    pezzi = []
    cur = None
    for d0, d1, bank in classi:
        if bank is None:
            if cur:
                pezzi.append(cur)
                cur = None
            continue
        if cur and cur[2] == bank:
            cur = (cur[0], d1, bank)
        else:
            if cur:
                pezzi.append(cur)
            cur = (d0, d1, bank)
    if cur:
        pezzi.append(cur)
    out = []
    for d0, d1, bank in pezzi:
        if d1 - d0 < 30:
            continue
        out.append((substring_m(line, d0, d1), bank))
    return out


STATI_CHIUSI = {"univoco", "fuori_interesse", "rinviato_verbano", "confermato"}


def applica_indicazioni(schede: list[dict]) -> list[dict]:
    """Le coordinate dell'utente non diventano pin verificati: restano da confermare in mappa."""
    punti = {}
    tratti = {}
    if CERESIO_INDICATI.exists():
        doc = json.loads(CERESIO_INDICATI.read_text(encoding="utf-8"))
        punti = doc.get("punti") or {}
        tratti = doc.get("tratti") or {}
    for s in schede:
        if s["id"] == "foce_tresa_verbano":
            s["stato"] = "rinviato_verbano"
            s["nota_operativa"] = "Foce nel Lago Maggiore. Si affronta con il Verbano, non su questa mappa."
        if s["id"] == "diga_creva" and not punti.get("diga_creva"):
            s["stato"] = "candidato_da_confermare"
            s["nota_operativa"] = "Un solo riscontro Nominatim. Non è confermato dall'utente."
        ind = punti.get(s["id"])
        if ind:
            confermato = ind.get("precisione") == "confermato"
            s["stato"] = "confermato" if confermato else "indicato_da_confermare"
            s["verificato"] = confermato
            s["indicazione_utente"] = {
                k: ind[k] for k in ("lat", "lon", "nome", "note", "precisione", "osm_id", "osm_type") if k in ind
            }
        if s["id"] in ("piazza_europa", "piazza_mercato") and tratti.get("tresa_divieto_lavena", {}).get("confermato"):
            s["stato"] = "confermato"
            s["verificato"] = True
            s["indicazione_utente"] = tratti["tresa_divieto_lavena"]
    return schede


def load_raw() -> dict[str, object]:
    fc = json.loads(CERESIO_RAW.read_text(encoding="utf-8"))
    out = {}
    for f in fc["features"]:
        out[f["properties"]["corpo_id"]] = shape(f["geometry"])
    return out


def foce_su_lago(corso, lago) -> Point | None:
    shore = lago.boundary
    inter = corso.intersection(shore)
    pts = [g for g in _parts(inter) if g.geom_type == "Point"]
    if inter.geom_type == "Point":
        pts = [inter]
    # Un solo sbocco, oppure un grappolo di pochi metri.
    if not pts:
        return None
    if len(pts) == 1:
        return pts[0]
    cluster = unary_union(pts).convex_hull
    if geom_distance_m(pts[0], Point(cluster.centroid.x, cluster.centroid.y)) < 40 and len(pts) <= 4:
        return cluster.centroid
    return None


def nomi_overpass(frame) -> list[dict]:
    s, w, n, e = frame.bounds[1], frame.bounds[0], frame.bounds[3], frame.bounds[2]
    q = f"""[out:json][timeout:40];
(
  node["name"]({s},{w},{n},{e});
  way["name"]({s},{w},{n},{e});
);
out tags center;
"""
    # Troppo largo: si chiedono solo i toponimi dei capisaldi.
    q = f"""[out:json][timeout:40];
(
  nwr["name"~"Dogana|Bigattini|Bagattini|Biviglione|Creva|Bagat|Filanda",i]({s},{w},{n},{e});
);
out tags center;
"""
    payload = osm_client.overpass(q) or {}
    hits = []
    for el in payload.get("elements") or []:
        tags = el.get("tags") or {}
        lon = el.get("lon") or (el.get("center") or {}).get("lon")
        lat = el.get("lat") or (el.get("center") or {}).get("lat")
        if lon is None or not tags.get("name"):
            continue
        hits.append({"nome": tags["name"], "lon": lon, "lat": lat, "osm": f"{el['type']}/{el['id']}"})
    print(f"  toponimi OSM nel riquadro: {len(hits)}")
    return hits


def sonda(spec, acque, toponimi) -> dict:
    geoms = [acque[c] for c in spec["corpi"] if c in acque and acque[c] is not None]
    target = unary_union(geoms) if geoms else None
    candidati = []
    for h in osm_client.nominatim_search(spec["q"], limit=5):
        lon, lat = float(h["lon"]), float(h["lat"])
        dist = round(geom_distance_m(target, Point(lon, lat)), 1) if target is not None else None
        candidati.append({
            "fonte": "nominatim",
            "nome": h.get("display_name"),
            "lon": lon,
            "lat": lat,
            "dist_m": dist,
        })
    for h in toponimi:
        if not any(tok in h["nome"].lower() for tok in spec["nomi"]):
            continue
        dist = round(geom_distance_m(target, Point(h["lon"], h["lat"])), 1) if target is not None else None
        candidati.append({"fonte": "overpass", **h, "dist_m": dist})
    vicini = [c for c in candidati if c["dist_m"] is not None and c["dist_m"] <= SOGLIA_M]
    # Stesso luogo da due fonti non conta come due luoghi.
    luoghi = []
    for c in vicini:
        if any(abs(c["lon"] - u["lon"]) < 0.0004 and abs(c["lat"] - u["lat"]) < 0.0004 for u in luoghi):
            continue
        luoghi.append(c)
    if len(luoghi) == 1:
        stato = "univoco"
    elif not candidati:
        stato = "nessun_riscontro"
    elif not vicini:
        stato = "lontano"
    else:
        stato = "piu_candidati"
    return {
        "id": spec["id"],
        "uso": spec["uso"],
        "corpi": spec["corpi"],
        "query": spec["q"],
        "stato": stato,
        "verificato": False,
        "soglia_m": SOGLIA_M,
        "luoghi_entro_soglia": [
            {"fonte": c["fonte"], "nome": c["nome"], "lon": round(c["lon"], 6), "lat": round(c["lat"], 6), "dist_m": c["dist_m"]}
            for c in luoghi
        ],
        "candidati": [
            {"fonte": c["fonte"], "nome": c["nome"], "lon": round(c["lon"], 6), "lat": round(c["lat"], 6), "dist_m": c["dist_m"]}
            for c in sorted(candidati, key=lambda x: (x["dist_m"] is None, x["dist_m"] or 1e9))[:6]
        ],
    }


def main():
    if not CERESIO_RAW.exists():
        raise SystemExit("Manca data/raw/ceresio_tresa_raw.geojson: eseguire prima fetch_osm_data.py")
    acque = load_raw()
    lago = make_valid(acque["lago_lugano"])
    frame = box(*unary_union([lago, acque["tresa"]]).buffer(0.03).bounds)
    print("=== Confine di Stato ===")
    italia, _svizzera, lago_it = confine_italiano(frame, lago)

    features = []
    features.append(feature(lago_it, {
        "corpo_id": "lago_lugano",
        "nome": "Lago di Lugano",
        "geometria": "poligono",
        "clip": "confine_stato",
        "bank": None,
        "segmento_id": None,
    }))
    piano = make_valid(acque["lago_piano"])
    if piano.intersects(italia) or not piano.intersects(_svizzera):
        piano_it = piano
    else:
        piano_it = make_valid(piano.intersection(italia))
    features.append(feature(piano_it, {
        "corpo_id": "lago_piano",
        "nome": "Lago di Piano",
        "geometria": "poligono",
        "clip": "intero_in_italia",
        "bank": None,
        "segmento_id": None,
    }))

    tresa = acque["tresa"]
    parti = [g for g in _parts(tresa) if g.geom_type == "LineString"]
    if tresa.geom_type == "MultiLineString":
        merged = linemerge(tresa)
        parti = [g for g in _parts(merged) if g.geom_type == "LineString"]
    valle = Point(8.73, 46.00)
    banks = []
    for parte in sorted(parti, key=line_length_m, reverse=True):
        parte = orienta_verso_valle(parte, valle)
        for tratto, bank in classifica_tresa(parte, italia):
            banks.append(bank)
            features.append(feature(tratto, {
                "corpo_id": "tresa",
                "nome": "Fiume Tresa",
                "geometria": "linea",
                "clip": "sponda_italiana",
                "bank": bank,
                "segmento_id": None,
                "lunghezza_m": round(line_length_m(tratto)),
            }))
    print(f"  Tresa: bank sui tratti tenuti = {sorted(set(banks)) or 'nessuno'}")

    for cid, nome in (
        ("cuccio", "Torrente Cuccio"),
        ("rezzo", "Torrente Rezzo"),
        ("soldo", "Torrente Soldo"),
        ("trallo", "Torrente Trallo"),
        ("telo_osteno", "Torrente Telo di Osteno"),
        ("lagadone", "Canale Lagadone"),
        ("lirone", "Torrente Lirone"),
    ):
        if cid not in acque:
            continue
        geom = acque[cid]
        if geom.intersects(_svizzera):
            tenuto = make_valid(geom.intersection(italia))
            clip = "confine_stato"
        else:
            tenuto = geom
            clip = "intero_in_italia"
        for parte in _parts(tenuto):
            if parte.geom_type != "LineString":
                continue
            features.append(feature(parte, {
                "corpo_id": cid,
                "nome": nome,
                "geometria": "linea",
                "clip": clip,
                "bank": "both",
                "segmento_id": None,
                "lunghezza_m": round(line_length_m(parte)),
            }))

    # Foci geometriche: il raggio «metà alveo + 50 m» del Cuccio non si taglia.
    # I 50 m fissi di Rezzo e Soldo si tagliano solo se lo sbocco è un solo punto.
    foci = {}
    for cid in ("cuccio", "rezzo", "soldo", "trallo"):
        foci[cid] = foce_su_lago(acque[cid], lago_it)
        if foci[cid] is not None:
            print(f"  foce {cid}: {foci[cid].x:.5f}, {foci[cid].y:.5f}")
        else:
            print(f"  foce {cid}: non univoca")
    for cid, seg_id in (("rezzo", "lago_lugano_restrizione_rezzo"), ("soldo", "lago_lugano_restrizione_soldo")):
        pt = foci[cid]
        if pt is None:
            continue
        zona = make_valid(lago_it.intersection(buffer_m(pt, 50)))
        if not zona.is_empty:
            features.append(feature(zona, {
                "corpo_id": "lago_lugano",
                "nome": f"Restrizione foce {cid} (50 m, solo riva, 1 canna, 3 ami)",
                "geometria": "poligono",
                "clip": "foce_geometrica",
                "bank": None,
                "segmento_id": seg_id,
            }))

    print("=== Capisaldi ===")
    toponimi = nomi_overpass(frame)
    schede = [sonda(s, acque, toponimi) for s in SONDE]
    for cid, pt in foci.items():
        schede.append({
            "id": f"foce_{cid}",
            "uso": "Sbocco geometrico nel lago (intersezione delle geometrie OSM)",
            "corpi": [cid, "lago_lugano"],
            "stato": "univoco" if pt is not None else "non_univoca",
            "verificato": False,
            "luoghi_entro_soglia": [] if pt is None else [{"fonte": "intersezione", "lon": round(pt.x, 6), "lat": round(pt.y, 6), "dist_m": 0}],
            "candidati": [],
        })
    # Telo: way OSM 195989294. Il punto di foce, se c'è, arriva dalle indicazioni utente.
    schede.append({
        "id": "foce_telo",
        "uso": "Restrizione 50 m alla foce del Telo di Osteno. Asta OSM way 195989294.",
        "corpi": ["telo_osteno", "lago_lugano"],
        "stato": "senza_geometria",
        "verificato": False,
        "luoghi_entro_soglia": [],
        "candidati": [],
    })
    schede = applica_indicazioni(schede)

    incerti = [s for s in schede if s["stato"] not in STATI_CHIUSI]
    CERESIO_TRATTI.parent.mkdir(parents=True, exist_ok=True)
    CERESIO_TRATTI.write_text(json.dumps({
        "type": "FeatureCollection",
        "name": "ceresio_tratti",
        "features": features,
    }, ensure_ascii=False), encoding="utf-8")
    CERESIO_INCERTI.write_text(json.dumps({
        "soglia_m": SOGLIA_M,
        "nota": "Nessun pin è verificato. I campi gara non si sondano. Le indicazioni utente stanno in ceresio_capisaldi_indicati.json e restano da confermare sulla mappa di impalcatura. La foce del Tresa nel Verbano è rinviata al Lago Maggiore.",
        "schede": schede,
        "da_validare": incerti,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Tratti: {len(features)} -> {CERESIO_TRATTI.name}")
    print(f"Capisaldi da validare: {len(incerti)} -> {CERESIO_INCERTI.name}")
    for s in incerti:
        print(f"  ?? {s['id']}: {s['stato']}")


if __name__ == "__main__":
    main()
