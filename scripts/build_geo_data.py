#!/usr/bin/env python3
"""Genera la mappa regolamentare del reticolo Margorabbia.

Pipeline:
  1. laghi (poligoni OSM) e reticolo filtrato (asta + affluenti maggiori nominati);
  2. capisaldi del prontuario georiferiti sull'asta e sugli affluenti;
  3. segmentazione per zona normativa (margorabbia_regole.json, vince la priorità più alta);
  4. arricchimento di ogni geometria con le regole risolte, validazione topologica, scrittura.

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

import capisaldi as cp
import config as cfg
import osm_basin
import osm_client
from geo_utils import feature, line_length_m, max_segment_m, point_feature, substring_m
from regole import Regole

MAX_STRAIGHT_SEGMENT_M = 600.0  # oltre: sospetta corda artificiale


class Builder:
    def __init__(self):
        self.regole = Regole(cfg.REGOLE_JSON)
        self.features: list[dict] = []
        self._resolved: dict = {}

    def zona(self, zona_id: str, corpo_id: str | None) -> dict:
        key = (zona_id, corpo_id)
        if key not in self._resolved:
            self._resolved[key] = self.regole.risolvi(zona_id, corpo_id)
        return self._resolved[key]

    def add(self, geom, *, zona_id: str, corpo_id: str, nome_tratto: str, ruolo: str, extra: dict | None = None):
        r = self.zona(zona_id, corpo_id)
        props = {
            "id": f"{corpo_id}_{sum(1 for f in self.features if f['properties']['corpo_idrico'] == corpo_id) + 1:02d}",
            "nome_tratto": nome_tratto,
            "corpo_idrico": corpo_id,
            "corpo_nome": self.regole.data["corpi_idrici"][corpo_id]["nome"],
            "ruolo": ruolo,
            "zona_id": zona_id,
            "regime": r["regime"],
            "regime_etichetta": r["regime_etichetta"],
            "tipo_acqua": r["tipo_acqua"],
            "pesca_consentita": r["pesca_consentita"],
            "geometria": geom.geom_type,
        }
        if geom.geom_type in ("LineString", "MultiLineString"):
            parts = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
            props["lunghezza_m"] = round(sum(line_length_m(p) for p in parts))
        else:
            props["area_ha"] = round(geom.area * (111_320 * 0.6947) * 110_540 / 10_000, 1)
        props.update(extra or {})
        props["regole"] = r
        self.features.append(feature(geom, props))


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
    return [(zid, substring_m(line, a, b), caps) for zid, a, b, caps in out]


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


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="ignora la cache e riscarica da OSM")
    args = ap.parse_args()
    osm_client.REFRESH = args.refresh
    b = Builder()
    reg = cp.Registro()
    priority = lambda zid: b.regole.zone[zid].get("priorita", 0)

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

    print("=== Segmentazione normativa ===")
    stem_intervals = [
        ("margorabbia_campo_gara_ghirla", "outlet_ghirla", "chiusa_enel"),
        ("margorabbia_no_kill_grantola_mesenzana", "ponte_grantola", "nk_end"),
        ("margorabbia_campo_gara_mesenzana_cucco", "super_mesenzana", "fine_gara_cucco"),
        ("margorabbia_sovrapposizione_nokill_gara", "super_mesenzana", "nk_end"),
        ("margorabbia_divieto_foce", "foce_briglia", "confluenza_tresa"),
    ]
    caps = reg.capisaldi
    for zid, seg, cc in segment_line(stem, cuts, stem_intervals, "margorabbia_ordinario", priority):
        extra = {"stato_geometria": "asta_osm_continua", "osm_way_ids": stem_wc["way_ids"]}
        if cc:
            extra["capisaldi"] = {"monte": caps[cc[0]].nome, "valle": caps[cc[1]].nome}
        b.add(seg, zona_id=zid, corpo_id="margorabbia", nome_tratto=b.regole.zone[zid]["nome"], ruolo="asta", extra=extra)
    for part in stem_wc["parts"]:
        if part is stem:
            continue
        b.add(part, zona_id="margorabbia_ordinario", corpo_id="margorabbia",
              nome_tratto="Margorabbia — Regime Ordinario B (tronco a monte di Ghirla)", ruolo="asta",
              extra={"stato_geometria": "tronco_osm_separato_dai_laghi"})

    for key in ("lago_ganna", "lago_ghirla"):
        corpo = b.regole.data["corpi_idrici"][key]
        b.add(lakes[key], zona_id=corpo["zona_default"], corpo_id=key, nome_tratto=b.regole.zone[corpo["zona_default"]]["nome"],
              ruolo="lago", extra={"osm_relation": cfg.OSM_LAKES[key]["osm_id"]})

    special = {"boggione": (cp.locate_boggione, "boggione_divieto"), "chiesone": (cp.locate_chiesone, "chiesone_divieto")}
    for key, wc in tribs.items():
        corpo = b.regole.data["corpi_idrici"][key]
        ruolo = corpo["ruolo"]
        extra = {"osm_way_ids": wc["way_ids"], "citato_in_prontuario": corpo["citato_in_prontuario"], "nomi_osm": list(cfg.MAJOR_TRIBUTARIES[key])}
        if corpo.get("identita_incerta"):
            extra["identita_incerta"] = True
        if corpo.get("note"):
            extra["note_corpo"] = corpo["note"]
        if not wc["parts"]:
            reg.verify(f"{key}_geom", corpo["nome"], "Nessuna way OSM con questo nome nel bacino.")
            continue
        main_line, *others = wc["parts"]
        rng = special[key][0](main_line, reg) if key in special else None
        if rng:
            ka, kb = {"boggione": ("strada_marzio_boarezzo", "monumento_ghirla"), "chiesone": ("sp54_chiesone", "pianazzo_chiesone")}[key]
            tcuts = {"_a": rng[0], "_b": rng[1]}
            for zid, seg, cc in segment_line(main_line, tcuts, [(special[key][1], "_a", "_b")], "affluenti_ordinario_B", priority):
                e = dict(extra)
                if zid != "affluenti_ordinario_B":
                    e["capisaldi"] = {"monte": caps[ka].nome, "valle": caps[kb].nome}
                nome = b.regole.zone[zid]["nome"] if zid != "affluenti_ordinario_B" else f"{corpo['nome']} — Regime Ordinario B"
                b.add(seg, zona_id=zid, corpo_id=key, nome_tratto=nome, ruolo=ruolo, extra=e)
        else:
            b.add(main_line, zona_id="affluenti_ordinario_B", corpo_id=key, nome_tratto=f"{corpo['nome']} — Regime Ordinario B", ruolo=ruolo, extra=extra)
        for part in others:
            b.add(part, zona_id="affluenti_ordinario_B", corpo_id=key, nome_tratto=f"{corpo['nome']} — Regime Ordinario B", ruolo=ruolo, extra=extra)

    non_mappati = []
    lis = b.regole.data["corpi_idrici"]["lisascora"]
    if lis.get("non_mappato"):
        non_mappati.append({
            "id": "lisascora",
            "nome": lis["nome"],
            "regime": "divieto",
            "motivo": lis.get("note") or "Corso non cartografato.",
        })
        print("  Lisascora: non mappato (divieto solo normativo)")

    if tresa:
        b.add(tresa, zona_id="tresa_cispp", corpo_id="tresa", nome_tratto="Fiume Tresa — tratto presso la confluenza (Regime CISPP)",
              ruolo="ricevente", extra={"tratto_parziale_osm": True, "osm_way_ids": tresa_wc["way_ids"]})

    print("=== Validazione ===")
    problems = validate(b.features)
    for p in problems:
        print(f"  ATTENZIONE {p}")
    for f in b.features:
        p = f["properties"]
        misura = f"{p['lunghezza_m']:>6} m " if "lunghezza_m" in p else f"{p['area_ha']:>6} ha"
        print(f"  {p['id']:15s} {p['geometria']:10s} {p['regime']:17s} {misura} seg.max {p.get('segmento_max_m', '-'):>4}  {p['nome_tratto']}")
    print(f"  {len(b.features)} geometrie, {len(problems)} anomalie topologiche")

    write_outputs(b, reg, problems, non_mappati)


def write_outputs(b: Builder, reg: cp.Registro, problems: list[str], non_mappati: list[dict] | None = None):
    fc = {"type": "FeatureCollection", "name": "margorabbia_tratti", "features": b.features}
    fc_cap = {"type": "FeatureCollection", "name": "capisaldi", "features": [
        point_feature(c.lon, c.lat, {"id": c.id, "nome": c.nome, "corso": c.corso, "progressiva_m": round(c.along_m),
                                     "fonte": c.fonte, "note": c.note, "verificato": c.verificato})
        for c in reg.capisaldi.values()
    ]}
    fc_todo = {"type": "FeatureCollection", "name": "punti_da_verificare", "features": [
        point_feature(t["coordinate_usate"][0], t["coordinate_usate"][1], {k: v for k, v in t.items() if k != "coordinate_usate"})
        for t in reg.todo if t.get("coordinate_usate")
    ]}
    report = {
        "n_geometrie": len(b.features),
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
    dump(fc_cap, cfg.OUT_CAPISALDI)
    dump(fc_todo, cfg.OUT_TODO_GEOJSON)
    dump(report, cfg.OUT_REPORT)

    d = b.regole.data
    regole_web = {k: d[k] for k in ("meta", "schema", "vocabolari", "definizioni_temporali")}
    js = "".join(
        f"window.{name} = {json.dumps(obj, ensure_ascii=False)};\n"
        for name, obj in (("MARGORABBIA_TRATTI", fc), ("MARGORABBIA_CAPISALDI", fc_cap),
                          ("MARGORABBIA_TODO", fc_todo), ("MARGORABBIA_REGOLE", regole_web))
    )
    cfg.OUT_WEB_JS.write_text(js, encoding="utf-8")
    print(f"Scritti {len(b.features)} tratti, {len(fc_cap['features'])} capisaldi, {len(reg.todo)} punti da verificare.")
    for path in (cfg.OUT_TRATTI, cfg.OUT_CAPISALDI, cfg.OUT_TODO_GEOJSON, cfg.OUT_REPORT, cfg.OUT_WEB_JS):
        print(f"  {path.relative_to(cfg.ROOT)}")


if __name__ == "__main__":
    main()
