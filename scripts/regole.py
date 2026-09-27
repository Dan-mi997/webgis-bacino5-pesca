"""Motore delle regole computabili (data/normativa/margorabbia_regole.json).

Uso da riga di comando:
    py -3 scripts/regole.py --elenco
    py -3 scripts/regole.py --zona margorabbia_no_kill_grantola_mesenzana --quando "2026-11-08 09:30"
    py -3 scripts/regole.py --zona affluenti_ordinario_B --corpo rancina --quando "2026-05-06 10:00"
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from datetime import date, datetime, timedelta, timezone

from config import REGOLE_JSON

WEEKDAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
DEFAULT_LATLON = (45.95, 8.78)


def deep_merge(base, over):
    """Gli oggetti si fondono ricorsivamente; liste e scalari vengono sostituiti."""
    if not isinstance(base, dict) or not isinstance(over, dict):
        return copy.deepcopy(over)
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = deep_merge(out[k], v) if isinstance(out.get(k), dict) and isinstance(v, dict) else copy.deepcopy(v)
    return out


# --------------------------------------------------------------------------- tempo

def movable_date(defn: dict, year: int) -> date:
    if defn["tipo"] != "ennesimo_giorno_settimana_del_mese":
        raise ValueError(defn["tipo"])
    wd = WEEKDAYS.index(defn["giorno_settimana"])
    month, n = defn["mese"], defn["ordinale"]
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(wd - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - timedelta(days=1)
    d -= timedelta(days=(d.weekday() - wd) % 7)
    return d + timedelta(weeks=n + 1)


def _rome_offset(dt_utc: datetime) -> timedelta:
    """CET/CEST senza dipendere da tzdata: ora legale dall'ultima domenica di marzo a quella di ottobre (01:00 UTC)."""
    y = dt_utc.year
    last_sun = lambda m: movable_date({"tipo": "ennesimo_giorno_settimana_del_mese", "mese": m, "giorno_settimana": "dom", "ordinale": -1}, y)
    start = datetime.combine(last_sun(3), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    end = datetime.combine(last_sun(10), datetime.min.time(), timezone.utc) + timedelta(hours=1)
    return timedelta(hours=2 if start <= dt_utc.replace(tzinfo=timezone.utc) < end else 1)


def sun_times(d: date, lat: float, lon: float) -> tuple[datetime, datetime]:
    """Alba e tramonto (ora locale di Roma, naive) — algoritmo dell'Almanac for Computers."""
    n = d.timetuple().tm_yday
    lng_hour = lon / 15.0
    out = []
    for rising in (True, False):
        t = n + ((6 if rising else 18) - lng_hour) / 24
        m = 0.9856 * t - 3.289
        l = (m + 1.916 * math.sin(math.radians(m)) + 0.020 * math.sin(math.radians(2 * m)) + 282.634) % 360
        ra = math.degrees(math.atan(0.91764 * math.tan(math.radians(l)))) % 360
        ra = (ra + (math.floor(l / 90) * 90 - math.floor(ra / 90) * 90)) / 15
        sin_dec = 0.39782 * math.sin(math.radians(l))
        cos_dec = math.cos(math.asin(sin_dec))
        cos_h = (math.cos(math.radians(90.833)) - sin_dec * math.sin(math.radians(lat))) / (cos_dec * math.cos(math.radians(lat)))
        h = (360 - math.degrees(math.acos(cos_h))) if rising else math.degrees(math.acos(cos_h))
        ut = (h / 15 + ra - 0.06571 * t - 6.622 - lng_hour) % 24
        dt_utc = datetime.combine(d, datetime.min.time()) + timedelta(hours=ut)
        out.append(dt_utc + _rome_offset(dt_utc))
    return out[0], out[1]


def _solar_instant(d: date, rif: str, offset_min: int, lat: float, lon: float) -> datetime:
    alba, tramonto = sun_times(d, lat, lon)
    return (alba if rif == "alba" else tramonto) + timedelta(minutes=offset_min)


# --------------------------------------------------------------------------- regole

class Regole:
    def __init__(self, path=REGOLE_JSON):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8"))
        self.zone = {z["id"]: z for z in self.data["zone"]}
        self.td = self.data["definizioni_temporali"]

    # ---- risoluzione -----------------------------------------------------
    def risolvi(self, zona_id: str, corpo_id: str | None = None) -> dict:
        d = self.data
        zona = self.zone[zona_id]
        corpo_id = corpo_id or zona.get("corpo_idrico")
        corpo = d["corpi_idrici"].get(corpo_id) if corpo_id else None
        eff = copy.deepcopy(d["profili"][zona["profilo"]])
        if corpo and eff.get("pesca_consentita"):
            eff = deep_merge(eff, corpo.get("override") or {})
        eff = deep_merge(eff, zona.get("override") or {})

        regime = d["vocabolari"]["regimi"][eff["regime"]]
        fonti = list(zona.get("fonti", [])) + list((corpo or {}).get("fonti", [])) + list(eff.pop("fonti", []))
        interpretazioni = list(eff.pop("interpretazioni", [])) + list(zona.get("interpretazioni", []))
        tipo = eff.get("tipo_acqua") or (corpo or {}).get("tipo_acqua")

        out = {
            "zona_id": zona_id,
            "zona_nome": zona["nome"],
            "corpo_idrico": corpo_id,
            "corpo_nome": (corpo or {}).get("nome"),
            "regime": eff["regime"],
            "regime_etichetta": regime["etichetta"],
            "regime_descrizione": regime["descrizione"],
            "tipo_acqua": tipo,
            "tipo_acqua_etichetta": d["vocabolari"]["tipi_acqua"].get(tipo, {}).get("etichetta") if tipo else None,
            "pesca_consentita": eff["pesca_consentita"],
            "priorita": zona.get("priorita", 0),
            "estensione": zona.get("estensione"),
            "calendario": self._calendario(eff.get("calendario")),
            "attrezzatura": eff.get("attrezzatura"),
            "esche": eff.get("esche"),
            "tecniche": eff.get("tecniche"),
            "prelievo": self._prelievo(eff.get("prelievo")),
            "permessi": self._permessi(eff.get("permessi")),
            "vincoli_speciali": eff.get("vincoli_speciali", []),
            "interpretazioni": interpretazioni,
            "fonti": fonti,
            "note_corpo": (corpo or {}).get("note"),
        }
        return out

    def _calendario(self, cal):
        if not cal:
            return None
        stag = lambda k: {"id": k, **self.td["stagioni"][k]}
        return {
            "stagione": stag(cal["stagione_ref"]),
            "giorni": {"id": cal["giorni_ref"], **self.td["calendari_giorni"][cal["giorni_ref"]]},
            "fascia_oraria": {"id": cal["fascia_oraria_ref"], **self.td["fasce_orarie"][cal["fascia_oraria_ref"]]},
            "periodi_speciali": [
                {**{k: v for k, v in p.items() if k != "stagione_ref"}, "stagione": stag(p["stagione_ref"])}
                for p in cal.get("periodi_speciali", [])
            ],
        }

    def _prelievo(self, pre):
        if not pre:
            return None
        sp = self.data["specie"]
        pre = dict(pre)
        if pre.get("tipo") == "nessuno":
            return pre
        misure = {k: v["valore"] for k, v in sp["misure_minime_cm"].items() if isinstance(v, dict) and "valore" in v}
        misure.update(pre.pop("misure_minime_override_cm", {}) or {})
        pre["misure_minime_cm"] = misure
        pre["specie_protette"] = sp["protette_sempre"]["elenco"] + pre.get("specie_sempre_protette_extra", [])
        if pre.get("limiti_ref"):
            pre["limiti"] = sp[pre["limiti_ref"]]
        return pre

    def _pacchetto(self, ref):
        pk = self.data["pacchetti_permessi"][ref]
        docs = [{"id": k, **self.data["documenti"][k]} for k in pk["documenti"]]
        costi = [x["costo_eur"] for x in docs]
        alt = pk.get("alternativa_non_tesserati")
        return {
            "id": ref,
            **{k: v for k, v in pk.items() if k not in ("documenti", "alternativa_non_tesserati")},
            "documenti": docs,
            "costo_totale_eur": sum(costi) if costi and None not in costi else None,
            "costo_noto_eur": sum(c for c in costi if c is not None),
            "alternativa_non_tesserati": [{"id": k, "etichetta": self.data["documenti"][k]["etichetta"]} for k in alt] if alt else None,
        }

    def _permessi(self, perm):
        if not perm:
            return None
        return {
            "pacchetto": self._pacchetto(perm["pacchetto_ref"]),
            "varianti": [{"condizione": v["condizione"], "pacchetto": self._pacchetto(v["pacchetto_ref"])} for v in perm.get("varianti", [])],
        }

    # ---- valutazione temporale ------------------------------------------
    def _bound(self, spec, year, lat, lon) -> datetime:
        d = movable_date(self.td["date_mobili"][spec["data_ref"]], year)
        return _solar_instant(d, spec["riferimento_solare"], spec["offset_minuti"], lat, lon)

    def in_stagione(self, stagione: dict, dt: datetime, lat: float, lon: float) -> bool | None:
        if stagione.get("rinvio_esterno"):
            return None
        if stagione["inizio"] is None:
            return True
        start = self._bound(stagione["inizio"], dt.year, lat, lon)
        end = self._bound(stagione["fine"], dt.year, lat, lon)
        return start <= dt <= end if start <= end else (dt >= start or dt <= end)

    def valuta(self, eff: dict, dt: datetime, lat: float = DEFAULT_LATLON[0], lon: float = DEFAULT_LATLON[1]) -> dict:
        alba, tramonto = sun_times(dt.date(), lat, lon)
        res = {"quando": dt.isoformat(timespec="minutes"), "alba": alba.strftime("%H:%M"), "tramonto": tramonto.strftime("%H:%M"),
               "consentita": True, "motivi": [], "vincoli_attivi": []}

        def no(msg):
            res["consentita"] = False
            res["motivi"].append(msg)

        if not eff["pesca_consentita"]:
            no(f"Zona di divieto: {eff['regime_etichetta']}")
            return res
        cal = eff["calendario"]
        st = self.in_stagione(cal["stagione"], dt, lat, lon)
        if st is None:
            res["consentita"] = None
            res["motivi"].append(f"Calendario rinviato a fonte esterna: {cal['stagione']['testo']}")
        elif not st:
            no(f"Fuori stagione ({cal['stagione']['testo']})")
        g = cal["giorni"]
        if WEEKDAYS[dt.weekday()] not in g["settimana"] and dt.strftime("%m-%d") not in g["festivi_aggiuntivi"]:
            no(f"Giorno non consentito ({g['testo']})")
        fo = cal["fascia_oraria"]
        if fo.get("da"):
            a = _solar_instant(dt.date(), fo["da"]["riferimento_solare"], fo["da"]["offset_minuti"], lat, lon)
            b = _solar_instant(dt.date(), fo["a"]["riferimento_solare"], fo["a"]["offset_minuti"], lat, lon)
            if not a <= dt <= b:
                no(f"Fuori orario ({a:%H:%M}–{b:%H:%M})")
        for p in cal["periodi_speciali"]:
            if self.in_stagione(p["stagione"], dt, lat, lon):
                res["vincoli_attivi"].append(p["testo"])
        res["vincoli_attivi"] += [v["testo"] for v in eff.get("vincoli_speciali", [])]
        return res


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--elenco", action="store_true", help="elenca le zone")
    ap.add_argument("--zona")
    ap.add_argument("--corpo")
    ap.add_argument("--quando", help="AAAA-MM-GG HH:MM (ora locale)")
    ap.add_argument("--json", action="store_true", help="stampa la zona risolta")
    args = ap.parse_args()
    r = Regole()
    if args.elenco or not args.zona:
        for z in r.data["zone"]:
            print(f"{z['id']:42s} {z['nome']}")
        return
    eff = r.risolvi(args.zona, args.corpo)
    if args.json:
        print(json.dumps(eff, ensure_ascii=False, indent=2))
    if args.quando:
        dt = datetime.strptime(args.quando, "%Y-%m-%d %H:%M")
        print(json.dumps(r.valuta(eff, dt), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
