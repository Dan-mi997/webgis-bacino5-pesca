#!/usr/bin/env python3
"""Pipeline legacy del pilota Margorabbia (OpenStreetMap).

Dal 2026-10-06 le aree nuove non passano di qui: la geometria è il reticolo
regionale e la segmentazione è scripts/segmenta_rete.py. Questo script resta
solo per rigenerare il pilota già pubblicato, finché non viene rimpiazzato
da uno STEP 4 sul reticolo ufficiale.

Pipeline:
  1. laghi (poligoni OSM) e reticolo filtrato (asta + affluenti maggiori nominati);
  2. capisaldi del prontuario georiferiti sull'asta e sugli affluenti;
  3. tagli restrittivi letti da struttura_dati_regole.json (No-Kill, divieti);
  4. overlay temporanei (campi gara, deroga invernale) come layer a parte, senza spezzare la base;
  5. ogni geometria riceve le regole risolte in cascata (matrice → eccezione → taglio).

Uso:  py -3 scripts/build_geo_data.py [--refresh]
"""

from __future__ import annotations

import argparse
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union
from shapely.validation import make_valid

import capisaldi as cp
import config as cfg
import osm_basin
import osm_client
from geo_utils import feature, line_length_m, max_segment_m, point_feature, substring_m
from regole import Matrice, verifica_matrice

MAX_STRAIGHT_SEGMENT_M = 600.0  # oltre: sospetta corda artificiale
RESIDUO = "residuo"
LOCATORS = {"boggione": cp.locate_boggione, "chiesone": cp.locate_chiesone}


def _misura(props: dict, geom) -> None:
    if geom.geom_type in ("LineString", "MultiLineString"):
        parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        props["lunghezza_m"] = round(sum(line_length_m(p) for p in parts))
    else:
        props["area_ha"] = round(geom.area * (111_320 * 0.6947) * 110_540 / 10_000, 1)


def overlaps(a0: float, a1: float, b0: float, b1: float, tol: float = 1.0) -> bool:
    lo = max(min(a0, a1), min(b0, b1))
    hi = min(max(a0, a1), max(b0, b1))
    return hi - lo > tol


class Builder:
    def __init__(self):
        self.matrice = Matrice()
        self.features: list[dict] = []
        self.overlays: list[dict] = []

    def add(self, geom, *, corpo_id: str, nome_tratto: str, ruolo: str, segmento_id: str | None = None,
            extra: dict | None = None, overlay_links: list | None = None):
        poly = geom.geom_type in ("Polygon", "MultiPolygon")
        r = self.matrice.risolvi(corpo_id, segmento_id, "sponda")
        corpo = self.matrice.corpi[corpo_id]
        n = sum(1 for f in self.features if f["properties"]["corpo_idrico"] == corpo_id) + 1
        props = {
            "id": f"{corpo_id}_{n:02d}",
            "nome_tratto": nome_tratto,
            "corpo_idrico": corpo_id,
            "corpo_nome": corpo["nome"],
            "ruolo": ruolo,
            "layer": "base",
            "segmento_id": segmento_id,
            "zona_id": r["zona_id"],
            "regime": r["regime"],
            "regime_etichetta": r["regime_etichetta"],
            "tipo_acqua": r["tipo_acqua"],
            "pesca_consentita": r["pesca_consentita"],
            "geometria": geom.geom_type,
            "matrice": r["matrice"],
            "overlay_coperti": overlay_links or [],
        }
        _misura(props, geom)
        props.update(extra or {})
        props["regole"] = r
        if poly:
            props["regole_natante"] = self.matrice.risolvi(corpo_id, segmento_id, "natante")
        self.features.append(feature(geom, props))

    def add_overlay(self, geom, *, corpo_id: str, overlay: dict, segmento_id: str | None, parte: int):
        r_base = self.matrice.risolvi(corpo_id, segmento_id, "sponda")
        r_on = self.matrice.risolvi(corpo_id, segmento_id, "sponda", overlay_id=overlay["id"])
        props = {
            "id": f"{overlay['id']}_{parte:02d}",
            "layer": "overlay",
            "overlay_id": overlay["id"],
            "tipo_overlay": overlay["tipo"],
            "nome_tratto": overlay["nome"],
            "sintesi": overlay.get("sintesi"),
            "attivazione": overlay["attivazione"],
            "non_taglia_geometria_base": True,
            "corpo_idrico": corpo_id,
            "corpo_nome": self.matrice.corpi[corpo_id]["nome"],
            "segmento_sottostante": segmento_id,
            "regime": r_base["regime"],
            "regime_sottostante": r_base["regime"],
            "regime_etichetta": r_base["regime_etichetta"],
            "tipo_acqua": r_base["tipo_acqua"],
            "pesca_consentita": r_on["pesca_consentita"],
            "geometria": geom.geom_type,
            "matrice": r_base["matrice"],
            "regole": r_base,
            "regole_se_attivo": r_on,
        }
        _misura(props, geom)
        self.overlays.append(feature(geom, props))


def segment_line(line: LineString, cuts: dict, intervals: list[tuple[str, str, str]], default_zone: str, priority):
    """Spezza la linea sui capisaldi e assegna a ogni pezzo la zona di priorità massima che lo copre.

    cuts: {caposaldo_id: progressiva_m}; intervals: (zona_id, caposaldo_a, caposaldo_b).
    """
    total = line_length_m(line)
    points = sorted({0.0, total, *(min(max(v, 0.0), total) for v in cuts.values())})
    merged = []
    for c in points:
        if not merged or c - merged[-1] > 15:
            merged.append(c)
    merged[-1] = total

    def zone_at(m):
        best = (default_zone, -1, None)
        for zid, ka, kb in intervals:
            if ka not in cuts or kb not in cuts:
                continue
            a, b = sorted((cuts[ka], cuts[kb]))
            pr = priority(zid)
            if a - 1 <= m <= b + 1 and pr > best[1]:
                best = (zid, pr, (ka, kb) if cuts[ka] <= cuts[kb] else (kb, ka))
        return best

    out = []
    for a, b in zip(merged, merged[1:]):
        zid, _, caps = zone_at((a + b) / 2)
        if out and out[-1][0] == zid:
            out[-1] = (zid, out[-1][1], b, caps)
        else:
            out.append((zid, a, b, caps))
    return [(zid, substring_m(line, a, b), caps, a, b) for zid, a, b, caps in out]


def overlay_links(matrice: Matrice, corpo_id: str, cuts: dict, sa: float, sb: float) -> list[dict]:
    links = []
    for ov in matrice.overlays(corpo_id):
        if ov["monte"] not in cuts or ov["valle"] not in cuts:
            continue
        a, b = sorted((cuts[ov["monte"]], cuts[ov["valle"]]))
        if not overlaps(sa, sb, a, b):
            continue
        totale = a <= sa + 1 and sb <= b + 1
        links.append({
            "id": ov["id"],
            "nome": ov["nome"],
            "tipo": ov["tipo"],
            "copertura": "totale" if totale else "parziale",
            "attivazione": ov["attivazione"],
            "sintesi": ov.get("sintesi"),
            "vincoli": [v.get("testo") for v in (ov.get("override") or {}).get("vincoli_speciali") or [] if v.get("testo")],
        })
    return links


def bind_line(b: Builder, line: LineString, corpo_id: str, ruolo: str, cuts: dict, extra: dict, nomi: dict):
    """Spezza la linea solo sui tagli e appoggia gli overlay come geometrie sorelle."""
    tagli = [(s["id"], s["monte"], s["valle"]) for s in b.matrice.tagli(corpo_id)]
    pri = lambda z: b.matrice.segmenti[z]["priorita"]
    pieces = segment_line(line, cuts, tagli, RESIDUO, pri)
    for zid, seg, cc, sa, sb in pieces:
        segmento_id = None if zid == RESIDUO else zid
        if segmento_id:
            nome = b.matrice.segmenti[segmento_id]["nome"]
        else:
            nome = b.matrice.risolvi(corpo_id)["zona_nome"]
        e = dict(extra)
        if cc:
            e["capisaldi"] = {"monte": nomi[cc[0]].nome, "valle": nomi[cc[1]].nome}
        b.add(seg, corpo_id=corpo_id, nome_tratto=nome, ruolo=ruolo, segmento_id=segmento_id,
              extra=e, overlay_links=overlay_links(b.matrice, corpo_id, cuts, sa, sb))
    parte: dict[str, int] = {}
    for ov in b.matrice.overlays(corpo_id):
        if ov["monte"] not in cuts or ov["valle"] not in cuts:
            print(f"  overlay {ov['id']}: caposaldo mancante, geometria non emessa")
            continue
        a, b_m = sorted((cuts[ov["monte"]], cuts[ov["valle"]]))
        for zid, _seg, _cc, sa, sb in pieces:
            if not overlaps(sa, sb, a, b_m):
                continue
            parte[ov["id"]] = parte.get(ov["id"], 0) + 1
            segmento_id = None if zid == RESIDUO else zid
            b.add_overlay(substring_m(line, max(sa, a), min(sb, b_m)), corpo_id=corpo_id, overlay=ov,
                          segmento_id=segmento_id, parte=parte[ov["id"]])


def validate(features: list[dict]) -> list[str]:
    problems = []
    for f in features:
        g = f["geometry"]
        p = f["properties"]
        if g["type"] in ("LineString", "MultiLineString"):
            geom = shape(g)
            parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
            worst = max(max_segment_m(x) for x in parts)
            p["segmento_max_m"] = round(worst)
            if worst > MAX_STRAIGHT_SEGMENT_M:
                problems.append(f"{p['id']}: segmento rettilineo di {worst:.0f} m")
        elif g["type"] in ("Polygon", "MultiPolygon"):
            rings = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
            for poly in rings:
                for ring in poly:
                    if ring[0] != ring[-1]:
                        problems.append(f"{p['id']}: anello non chiuso")
    return problems


def corpo_extra(corpo: dict, **more) -> dict:
    extra = dict(more)
    extra["citato_in_prontuario"] = corpo.get("citato_in_prontuario")
    if corpo.get("identita_incerta"):
        extra["identita_incerta"] = True
    if corpo.get("note"):
        extra["note_corpo"] = corpo["note"]
    return extra


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="ignora la cache e riscarica da OSM")
    ap.add_argument("--area", default="margorabbia", choices=("margorabbia", "ceresio", "varese"), help="area da costruire")
    args = ap.parse_args()
    print("Pipeline legacy OSM: solo il pilota già pubblicato. Le aree nuove usano scripts/segmenta_rete.py.")
    if args.area == "ceresio":
        import build_ceresio
        build_ceresio.main()
        return
    if args.area == "varese":
        import build_varese
        build_varese.main()
        return
    osm_client.REFRESH = args.refresh
    print("=== Cascata normativa ===")
    verifica_matrice()
    b = Builder()
    reg = cp.Registro()

    print("=== Laghi ===")
    lakes = {}
    for key, meta in cfg.OSM_LAKES.items():
        lakes[key] = osm_basin.relation_polygon(osm_client.osm_full(meta["osm_type"], meta["osm_id"]), meta["osm_id"])
        print(f"  {meta['name']}: {lakes[key].geom_type}, valido={lakes[key].is_valid}")

    print("=== Reticolo (asta + affluenti maggiori nominati) ===")
    ways = osm_basin.parse_ways(osm_basin.fetch_waterways(osm_client.overpass, force=args.refresh))
    n_named = sum(1 for w in ways if w["name"])
    print(f"  way river/stream nel bbox: {len(ways)} ({len(ways) - n_named} senza nome, scartate)")
    stem_wc = osm_basin.build_watercourse(ways, cfg.STEM_OSM_NAMES, "margorabbia")
    tribs = {k: osm_basin.build_watercourse(ways, names, k) for k, names in cfg.MAJOR_TRIBUTARIES.items()}
    tresa_wc = osm_basin.build_watercourse(ways, cfg.RECEIVER_OSM_NAMES, "tresa")

    receiver = unary_union(tresa_wc["parts"]) if tresa_wc["parts"] else Point(8.73, 45.995)
    stem = osm_basin.downstream_stem(stem_wc["parts"], receiver)
    mouth = Point(stem.coords[-1])
    tresa = osm_basin.local_reach(tresa_wc["parts"], mouth, cfg.RECEIVER_HALF_REACH_M)
    print(f"  asta a valle di Ghirla: {line_length_m(stem):.0f} m")

    print("=== Capisaldi (pin verificati) ===")
    cuts = cp.locate_stem(stem, lakes["lago_ghirla"], [], reg)

    print("=== Segmentazione (tagli) e overlay ===")
    bind_line(b, stem, "margorabbia", "asta", cuts,
              {"stato_geometria": "asta_osm_continua", "osm_way_ids": stem_wc["way_ids"]}, reg.capisaldi)
    for part in stem_wc["parts"]:
        if part is stem:
            continue
        b.add(part, corpo_id="margorabbia", nome_tratto="Margorabbia — Regime Ordinario B (tronco a monte di Ghirla)",
              ruolo="asta", extra={"stato_geometria": "tronco_osm_separato_dai_laghi"})

    for key in ("lago_ganna", "lago_ghirla"):
        corpo = b.matrice.corpi[key]
        interi = b.matrice.tagli(key, intero=True)
        segmento_id = max(interi, key=lambda s: s["priorita"])["id"] if interi else None
        nome = b.matrice.segmenti[segmento_id]["nome"] if segmento_id else b.matrice.risolvi(key)["zona_nome"]
        b.add(lakes[key], corpo_id=key, nome_tratto=nome, ruolo=corpo["ruolo"], segmento_id=segmento_id,
              extra=corpo_extra(corpo, osm_relation=cfg.OSM_LAKES[key]["osm_id"]))

    for key, wc in tribs.items():
        corpo = b.matrice.corpi[key]
        ruolo = corpo["ruolo"]
        extra = corpo_extra(corpo, osm_way_ids=wc["way_ids"], nomi_osm=list(cfg.MAJOR_TRIBUTARIES[key]))
        if not wc["parts"]:
            reg.verify(f"{key}_geom", corpo["nome"], "Nessuna way OSM con questo nome nel bacino.")
            continue
        main_line, *others = wc["parts"]
        taglio_ok = LOCATORS[key](main_line, reg) is not None if key in LOCATORS else True
        tcuts = {cid: c.along_m for cid, c in reg.capisaldi.items() if c.corso == key}
        if taglio_ok and tcuts and b.matrice.tagli(key):
            bind_line(b, main_line, key, ruolo, tcuts, extra, reg.capisaldi)
        else:
            b.add(main_line, corpo_id=key, nome_tratto=b.matrice.risolvi(key)["zona_nome"], ruolo=ruolo, extra=extra)
        for part in others:
            b.add(part, corpo_id=key, nome_tratto=b.matrice.risolvi(key)["zona_nome"], ruolo=ruolo, extra=extra)

    non_mappati = []
    lis = b.matrice.corpi["lisascora"]
    if not lis.get("mappato", True):
        non_mappati.append({
            "id": "lisascora",
            "nome": lis["nome"],
            "regime": "divieto",
            "motivo": lis.get("note") or "Corso non cartografato.",
        })
        print("  Lisascora: non mappato (divieto solo normativo)")

    if tresa and not cfg.CERESIO_TRATTI.exists():
        b.add(tresa, corpo_id="tresa", nome_tratto="Fiume Tresa — tratto presso la confluenza (Italo-Svizzera + Cat. C)",
              ruolo="ricevente", extra={"tratto_parziale_osm": True, "osm_way_ids": tresa_wc["way_ids"]})

    print("=== Ceresio ===")
    ingest_ceresio(b)

    print("=== Validazione ===")
    problems = validate(b.features + b.overlays)
    for p in problems:
        print(f"  ATTENZIONE {p}")
    for f in b.features:
        p = f["properties"]
        misura = f"{p['lunghezza_m']:>6} m " if "lunghezza_m" in p else f"{p['area_ha']:>6} ha"
        assi = p["matrice"]
        print(f"  {p['id']:22s} {p['geometria']:10s} {p['regime']:14s} {assi['regime_amministrativo']:16s} cat.{assi['classificazione_biologica']} {misura}  {p['nome_tratto']}")
    for f in b.overlays:
        p = f["properties"]
        print(f"  {p['id']:22s} {'overlay':10s} {p['tipo_overlay']:14s} sotto {p['regime_sottostante']:14s} {p['lunghezza_m']:>6} m  {p['nome_tratto']}")
    print(f"  {len(b.features)} geometrie base, {len(b.overlays)} overlay, {len(problems)} anomalie topologiche")

    write_outputs(b, reg, problems, non_mappati)


CERESIO_CORSI = {
    "ponte_dogana": "tresa",
    "chiusa_regolazione": "tresa",
    "ponte_biviglione": "tresa",
    "diga_creva": "tresa",
    "vecchia_filanda": "lago_lugano",
    "grotto_bagat": "lago_lugano",
    "ponte_bigattini": "trallo",
    "foce_rezzo": "rezzo",
    "foce_telo": "lirone",
}


def ingest_ceresio(b: Builder) -> None:
    """Aggiunge il Ceresio già tagliato. I cerchi di foce restano solo la parte di specchio."""
    if not cfg.CERESIO_TRATTI.exists():
        print("  manca ceresio_tratti.geojson")
        return
    fc = json.loads(cfg.CERESIO_TRATTI.read_text(encoding="utf-8"))
    laghi, buchi, altri = [], [], []
    for feat in fc["features"]:
        p = feat["properties"]
        if p.get("corpo_id") not in b.matrice.corpi:
            print(f"  salto {p.get('corpo_id')}: non è nel grafo")
            continue
        geom = shape(feat["geometry"])
        if geom.is_empty:
            continue
        interno = geom.geom_type in ("Polygon", "MultiPolygon") and p.get("segmento_id") and p.get("corpo_id") in ("lago_lugano", "lago_piano")
        base_lago = geom.geom_type in ("Polygon", "MultiPolygon") and not p.get("segmento_id") and p.get("corpo_id") in ("lago_lugano", "lago_piano")
        if interno:
            buchi.append(feat)
        elif base_lago:
            laghi.append(feat)
        else:
            altri.append(feat)
    for feat in laghi:
        p = feat["properties"]
        geom = shape(feat["geometry"])
        tagli = [shape(h["geometry"]) for h in buchi if h["properties"]["corpo_id"] == p["corpo_id"]]
        if tagli:
            geom = make_valid(geom.difference(unary_union(tagli)))
        _aggiungi_ceresio(b, geom, p)
    for feat in buchi + altri:
        _aggiungi_ceresio(b, shape(feat["geometry"]), feat["properties"])
    print(f"  Ceresio: {len(laghi)} specchi, {len(buchi)} zone interne, {len(altri)} linee")


def _aggiungi_ceresio(b: Builder, geom, props: dict) -> None:
    if geom.is_empty:
        return
    cid = props["corpo_id"]
    corpo = b.matrice.corpi[cid]
    seg = props.get("segmento_id")
    if seg and seg not in b.matrice.segmenti:
        seg = None
    if seg:
        nome = b.matrice.segmenti[seg]["nome"]
    else:
        nome = b.matrice.risolvi(cid)["zona_nome"]
    extra = {"area": "ceresio", "clip": props.get("clip")}
    if props.get("bank") in ("left", "right", "both"):
        extra["bank"] = props["bank"]
    if props.get("spazio"):
        extra["spazio"] = props["spazio"]
    elif geom.geom_type in ("Polygon", "MultiPolygon"):
        extra["spazio"] = "interno"
    else:
        extra["spazio"] = "sponda"
    if geom.geom_type == "GeometryCollection":
        parti = [g for g in geom.geoms if not g.is_empty and g.geom_type in ("Polygon", "LineString")]
    elif geom.geom_type in ("MultiPolygon", "MultiLineString"):
        parti = list(geom.geoms)
    else:
        parti = [geom]
    for parte in parti:
        if parte.is_empty:
            continue
        b.add(parte, corpo_id=cid, nome_tratto=nome, ruolo=corpo["ruolo"], segmento_id=seg,
              extra=corpo_extra(corpo, **extra))


def write_outputs(b: Builder, reg: cp.Registro, problems: list[str], non_mappati: list[dict] | None = None):
    fc = {"type": "FeatureCollection", "name": "margorabbia_tratti", "features": b.features}
    fc_ov = {"type": "FeatureCollection", "name": "margorabbia_overlay", "features": b.overlays}
    fc_cap = {"type": "FeatureCollection", "name": "capisaldi", "features": [
        point_feature(c.lon, c.lat, {"id": c.id, "nome": c.nome, "corso": c.corso, "progressiva_m": round(c.along_m),
                                     "fonte": c.fonte, "note": c.note, "verificato": c.verificato})
        for c in reg.capisaldi.values()
    ]}
    if cfg.CAPISALDI_VERIFICATI.exists():
        presenti = {f["properties"]["id"] for f in fc_cap["features"]}
        extra = json.loads(cfg.CAPISALDI_VERIFICATI.read_text(encoding="utf-8"))["punti"]
        for cid, p in extra.items():
            if cid in presenti or cid not in CERESIO_CORSI:
                continue
            fc_cap["features"].append(point_feature(p["lon"], p["lat"], {
                "id": cid, "nome": p["nome"], "corso": CERESIO_CORSI[cid], "progressiva_m": None,
                "fonte": "verificato_manuale", "note": p.get("note"), "verificato": True,
            }))
    fc_todo = {"type": "FeatureCollection", "name": "punti_da_verificare", "features": [
        point_feature(t["coordinate_usate"][0], t["coordinate_usate"][1], {k: v for k, v in t.items() if k != "coordinate_usate"})
        for t in reg.todo if t.get("coordinate_usate")
    ]}
    report = {
        "n_geometrie": len(b.features),
        "n_overlay": len(b.overlays),
        "per_regime": {},
        "per_corpo_idrico": {},
        "anomalie_topologiche": problems,
        "punti_da_verificare": reg.todo,
        "non_mappati": non_mappati or [],
    }
    for f in b.features:
        p = f["properties"]
        report["per_regime"][p["regime"]] = report["per_regime"].get(p["regime"], 0) + 1
        report["per_corpo_idrico"][p["corpo_idrico"]] = report["per_corpo_idrico"].get(p["corpo_idrico"], 0) + p.get("lunghezza_m", 0)

    cfg.GEOJSON_DIR.mkdir(parents=True, exist_ok=True)
    dump = lambda obj, path: path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    dump(fc, cfg.OUT_TRATTI)
    dump(fc_ov, cfg.OUT_OVERLAY)
    dump(fc_cap, cfg.OUT_CAPISALDI)
    dump(fc_todo, cfg.OUT_TODO_GEOJSON)
    dump(report, cfg.OUT_REPORT)

    d = b.matrice.base.data
    regole_web = {k: d[k] for k in ("meta", "schema", "vocabolari", "definizioni_temporali")}
    regole_web["struttura"] = {
        "schema": b.matrice.spec["schema"],
        "esempi": b.matrice.spec["esempi"],
    }
    js = "".join(
        f"window.{name} = {json.dumps(obj, ensure_ascii=False)};\n"
        for name, obj in (("MARGORABBIA_TRATTI", fc), ("MARGORABBIA_OVERLAY", fc_ov),
                          ("MARGORABBIA_CAPISALDI", fc_cap),
                          ("MARGORABBIA_TODO", fc_todo), ("MARGORABBIA_REGOLE", regole_web))
    )
    cfg.OUT_WEB_JS.write_text(js, encoding="utf-8")
    print(f"Scritti {len(b.features)} tratti, {len(b.overlays)} overlay, {len(fc_cap['features'])} capisaldi, {len(reg.todo)} punti da verificare.")
    for path in (cfg.OUT_TRATTI, cfg.OUT_OVERLAY, cfg.OUT_CAPISALDI, cfg.OUT_TODO_GEOJSON, cfg.OUT_REPORT, cfg.OUT_WEB_JS):
        print(f"  {path.relative_to(cfg.ROOT)}")


if __name__ == "__main__":
    main()
