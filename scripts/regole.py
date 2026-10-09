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

from config import REGOLE_JSON, STRUTTURA_JSON

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
    if defn["tipo"] == "data_fissa":
        return date(year, defn["mese"], defn["giorno"])
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
    if rif == "inizio_giorno":
        return datetime.combine(d, datetime.min.time()) + timedelta(minutes=offset_min)
    if rif == "fine_giorno":
        return datetime.combine(d, datetime.max.time()) + timedelta(minutes=offset_min)
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
        pre["periodi_divieto"] = self._periodi_divieto()
        nota = (sp.get("periodi_divieto_fonte") or {}).get("estratto")
        if nota:
            pre["periodi_divieto_nota"] = nota
        return pre

    def _periodi_divieto(self) -> list[dict]:
        mesi = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]

        def giorno(mmdd: str) -> str:
            mese, g = mmdd.split("-")
            return f"{int(g)} {mesi[int(mese) - 1]}"

        out = []
        for p in self.data["specie"].get("periodi_divieto") or []:
            if p.get("dal_ref"):
                dal = self.td["date_mobili"][p["dal_ref"]]["etichetta"]
                al = self.td["date_mobili"][p["al_ref"]]["etichetta"]
            else:
                dal, al = giorno(p["dal"]), giorno(p["al"])
            if dal[:1].isalpha():
                ponte = "all'" if al[:1].lower() in "aeiou" else "alla "
                testo = f"dalla {dal} {ponte}{al}"
            else:
                testo = f"dal {dal} al {al}"
            voce = {"specie": p["specie"], "dal": dal, "al": al, "testo": testo}
            if p.get("ambito"):
                voce["ambito"] = p["ambito"]
            out.append(voce)
        return out

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
        if not perm.get("pacchetto_ref"):
            return {
                "pacchetto": {
                    "id": None,
                    "etichetta": perm.get("etichetta") or "Scheda permessi non ancora ingerita",
                    "documenti": [],
                    "note": perm.get("nota") or "Il regime amministrativo non ha ancora un pacchetto compilato per questa classe.",
                    "richiede_contributo_extra": None,
                    "richiede_tesserino": None,
                    "costo_totale_eur": None,
                    "costo_noto_eur": 0,
                    "alternativa_non_tesserati": None,
                },
                "varianti": [
                    {"condizione": v["condizione"], "pacchetto": self._pacchetto(v["pacchetto_ref"])}
                    for v in perm.get("varianti", [])
                ],
            }
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
            res["motivi"].append(f"Calendario non computabile: {cal['stagione']['testo']}")
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
                if p.get("vietata"):
                    no(p["testo"])
                else:
                    res["vincoli_attivi"].append(p["testo"])
        res["vincoli_attivi"] += [v["testo"] for v in eff.get("vincoli_speciali", [])]
        return res


# --------------------------------------------------------------------------- matrice (struttura_dati_regole.json)

_APPEND = ("vincoli_speciali", "fonti", "interpretazioni")
_STRUTTURALI = ("per_modalita", "fonti", "interpretazioni", "ambito_geometrico")
_ROSA = {
    "cispp_tresa",
    "fipsas_verbano_riva",
    "fipsas_verbano_barca",
    "fipsas_ceresio_riva_va",
    "fipsas_ceresio_barca_va",
    "fipsas_ceresio_riva_co",
    "fipsas_ceresio_barca_co",
}
_RIDOTTO = {"fipsas_varese_ridotto", "fipsas_lago_riva"}
_INTERO = {"fipsas_acque_B", "fipsas_lago_belly_boat", "fipsas_co_lc_barca", "fipsas_tipo_c_corrente"}


def livello_permesso(amm_id: str | None, pacchetto_id: str | None, bio_id: str | None) -> str:
    """Cinque layer di permesso, mutuamente esclusivi sul disegno."""
    if amm_id == "diritti_esclusivi":
        return "esclusivi"
    if bio_id == "CISPP" or pacchetto_id in _ROSA:
        return "fipsas_tesserino_maggiore"
    if pacchetto_id in _RIDOTTO:
        return "fipsas_contributo_ridotto"
    if pacchetto_id in _INTERO:
        return "fipsas_contributo_intero"
    return "fipsas_base"


def applica_delta(eff: dict, delta: dict | None) -> dict:
    """Come deep_merge, ma vincoli, fonti e interpretazioni si accodano."""
    if not delta:
        return eff
    delta = copy.deepcopy(delta)
    extra = {k: delta.pop(k) for k in _APPEND if k in delta}
    out = deep_merge(eff, delta)
    for k, v in extra.items():
        out[k] = list(out.get(k) or []) + list(v)
    return out


class Matrice:
    """Risolve la cascata a cinque livelli su struttura_dati_regole.json.

    I blocchi operativi (profili, calendari, documenti, specie) restano nel
    file dizionario letto da Regole.
    """

    def __init__(self, path=STRUTTURA_JSON, definizioni=REGOLE_JSON):
        self.path = path
        self.spec = json.loads(path.read_text(encoding="utf-8"))
        self.base = Regole(definizioni)
        self.corpi = self.spec["corpi_idrici"]
        self.eccezioni = self.spec.get("eccezioni_locali") or {}
        self.segmenti = {s["id"]: s for s in self.spec["segmenti"]}
        self.overlay = {o["id"]: o for o in self.spec["overlay_temporanei"]}
        self.rb = self.spec["regole_base"]

    def tagli(self, corpo_id: str, *, intero: bool = False) -> list[dict]:
        out = []
        for s in self.spec["segmenti"]:
            if s["corpo_idrico"] != corpo_id or s.get("effetto") != "taglio":
                continue
            if bool(s.get("intero_corpo")) == intero:
                out.append(s)
        return out

    def overlays(self, corpo_id: str) -> list[dict]:
        return [o for o in self.spec["overlay_temporanei"] if o["corpo_idrico"] == corpo_id]

    def _entita(self, corpo: dict, modalita: str) -> dict:
        return ((corpo.get("entita") or {}).get(modalita) or {})

    def risolvi(self, corpo_id: str, segmento_id: str | None = None, modalita: str = "sponda", overlay_id: str | None = None) -> dict:
        corpo = self.corpi[corpo_id]
        if corpo.get("stato") == "predisposto" or not corpo.get("classificazione_biologica"):
            raise ValueError(f"{corpo_id}: corpo predisposto, senza classe né regime")
        bio_id = corpo["classificazione_biologica"]
        entita = self._entita(corpo, modalita)
        amm_id = entita.get("regime_amministrativo") or corpo["regime_amministrativo"]
        bio = self.rb["classificazione_biologica"][bio_id]
        amm = self.rb["regime_amministrativo"][amm_id]
        profili = self.base.data["profili"]
        trace = []

        blocco_id = bio["blocco_ref"]
        if corpo.get("geometria") == "linea" and bio.get("blocco_ref_linea"):
            blocco_id = bio["blocco_ref_linea"]
        eff = copy.deepcopy(profili[blocco_id])
        eff["tipo_acqua"] = bio_id
        cella = (amm.get("permessi_per_classe") or {}).get(bio_id)
        if cella is not None:
            eff["permessi"] = copy.deepcopy(cella)
        if amm_id == "diritti_esclusivi":
            eff["regime"] = "diritti_esclusivi"
        trace.append({"livello": 1, "asse": "classificazione_biologica", "id": bio_id, "blocco": blocco_id, "fonte": bio.get("fonte")})
        trace.append({"livello": 1, "asse": "regime_amministrativo", "id": amm_id, "entita": modalita if corpo.get("entita_separate") else None})

        if bio.get("completo") is False and bio.get("nota"):
            eff.setdefault("interpretazioni", [])
            eff["interpretazioni"] = list(eff.get("interpretazioni") or []) + [
                {"campo": "classificazione", "nota": bio["nota"]}
            ]

        mod = self.rb["modalita_pesca"][modalita]
        if corpo["geometria"] == "linea" and modalita == "natante":
            raise ValueError(f"{corpo_id}: la modalità natante non si applica a una linea")
        eff = applica_delta(eff, mod.get("regole"))
        trace.append({"livello": 2, "asse": "entita", "id": modalita, "geometria": entita.get("geometria") or corpo.get("geometria")})

        exc = copy.deepcopy(self.eccezioni.get(corpo_id) or {})
        per_mod = exc.pop("per_modalita", {}) or {}
        exc.pop("ambito_geometrico", None)
        chiavi_exc = [k for k in exc if k not in _STRUTTURALI]
        eff = applica_delta(eff, exc)
        ramo = per_mod.get(modalita) or {}
        if ramo:
            chiavi_exc += [f"{modalita}.{k}" for k in ramo if k not in ("fonti", "interpretazioni")]
            eff = applica_delta(eff, ramo)
        if chiavi_exc:
            trace.append({"livello": 3, "asse": "eccezione_locale", "id": corpo_id, "chiavi": chiavi_exc, "ambito": "geometria_esatta"})

        if bio_id == "A" and eff.get("regime") == "ordinario_C_lago":
            eff["regime"] = "ordinario_A"
            eff["interpretazioni"] = [
                i for i in (eff.get("interpretazioni") or [])
                if "tipo C" not in (i.get("nota") or "")
            ]
        elif bio_id == "C" and corpo.get("geometria") == "linea" and eff.get("regime") == "ordinario_C_lago":
            eff["regime"] = "ordinario_C"
        if amm_id == "diritti_esclusivi":
            eff["regime"] = "diritti_esclusivi"

        for k in ("fonti", "interpretazioni"):
            if corpo.get(k):
                eff[k] = list(eff.get(k) or []) + list(corpo[k])

        segmento = self.segmenti.get(segmento_id) if segmento_id else None
        if segmento:
            if segmento.get("sostituisci_con_blocco"):
                tipo = eff.get("tipo_acqua")
                eff = copy.deepcopy(profili[segmento["sostituisci_con_blocco"]])
                if segmento.get("mantieni_classe") and tipo:
                    eff["tipo_acqua"] = tipo
            if segmento.get("regime_amministrativo"):
                amm_id = segmento["regime_amministrativo"]
                amm = self.rb["regime_amministrativo"][amm_id]
                if amm_id == "diritti_esclusivi":
                    eff["regime"] = "diritti_esclusivi"
                if segmento.get("pacchetto_ref"):
                    eff["permessi"] = {"pacchetto_ref": segmento["pacchetto_ref"], "varianti": []}
            delta = copy.deepcopy(segmento.get("override") or {})
            for k in ("fonti", "interpretazioni"):
                if segmento.get(k):
                    delta[k] = list(delta.get(k) or []) + list(segmento[k])
            eff = applica_delta(eff, delta)
            trace.append({
                "livello": 4,
                "asse": "segmento",
                "id": segmento_id,
                "effetto": segmento.get("effetto") or "taglio",
                "geometria_vincolo": (segmento.get("geometria_vincolo") or {}).get("tipo"),
            })

        overlay = self.overlay.get(overlay_id) if overlay_id else None
        if overlay:
            delta = copy.deepcopy(overlay.get("override") or {})
            eff = applica_delta(eff, delta)
            trace.append({"livello": 5, "asse": "overlay", "id": overlay_id, "non_taglia_geometria_base": True})

        if segmento and overlay:
            zona_id, zona_nome = f"{segmento_id}__{overlay_id}", f"{segmento['nome']} + {overlay['nome']}"
            estensione, priorita = segmento.get("estensione"), segmento.get("priorita", 0)
        elif segmento:
            zona_id, zona_nome = segmento_id, segmento["nome"]
            estensione = segmento.get("estensione") or {
                "tipo": (segmento.get("geometria_vincolo") or {}).get("tipo") or "segmento",
                "descrizione": segmento["nome"],
            }
            priorita = segmento.get("priorita", 0)
        elif overlay:
            zona_id, zona_nome = f"{corpo_id}_residuo__{overlay_id}", overlay["nome"]
            estensione, priorita = {"tipo": "overlay", "descrizione": overlay.get("sintesi")}, 0
        else:
            zona_id = f"{corpo_id}_residuo"
            zona_nome = f"{corpo['nome']} — {self.base.data['vocabolari']['regimi'][eff['regime']]['etichetta']}"
            estensione = {"tipo": "residuale", "descrizione": "Fuori dai tagli restrittivi (No-Kill, divieto, riserva)."}
            priorita = 10

        pacchetto_id = (eff.get("permessi") or {}).get("pacchetto_ref")
        out = self._espandi(eff, zona_id=zona_id, zona_nome=zona_nome, corpo=corpo, corpo_id=corpo_id, priorita=priorita, estensione=estensione)
        out["matrice"] = {
            "regime_amministrativo": amm_id,
            "regime_amministrativo_etichetta": amm["etichetta"],
            "classificazione_biologica": bio_id,
            "classificazione_etichetta": bio["etichetta"],
            "livello_permesso": livello_permesso(amm_id, pacchetto_id, bio_id),
            "modalita": modalita,
            "entita": modalita,
            "geometria_entita": entita.get("geometria") or ("linea" if corpo.get("geometria") == "linea" else corpo.get("geometria")),
            "tipo_geometria_normativa": corpo["geometria"],
            "eredita": trace,
        }
        return out

    def _espandi(self, eff, *, zona_id, zona_nome, corpo, corpo_id, priorita, estensione) -> dict:
        d = self.base.data
        extra_docs = None
        if eff.get("permessi"):
            extra_docs = eff["permessi"].pop("documenti_extra", None)
        regime = d["vocabolari"]["regimi"][eff["regime"]]
        fonti = list(eff.pop("fonti", []) or [])
        interpretazioni = list(eff.pop("interpretazioni", []) or [])
        tipo = eff.get("tipo_acqua")
        out = {
            "zona_id": zona_id,
            "zona_nome": zona_nome,
            "corpo_idrico": corpo_id,
            "corpo_nome": corpo.get("nome"),
            "regime": eff["regime"],
            "regime_etichetta": regime["etichetta"],
            "regime_descrizione": regime["descrizione"],
            "tipo_acqua": tipo,
            "tipo_acqua_etichetta": d["vocabolari"]["tipi_acqua"].get(tipo, {}).get("etichetta") if tipo else None,
            "pesca_consentita": eff["pesca_consentita"],
            "priorita": priorita,
            "estensione": estensione,
            "calendario": self.base._calendario(eff.get("calendario")),
            "attrezzatura": eff.get("attrezzatura"),
            "esche": eff.get("esche"),
            "tecniche": eff.get("tecniche"),
            "prelievo": self._prelievo_contestuale(self.base._prelievo(eff.get("prelievo")), tipo, eff["regime"]),
            "permessi": self.base._permessi(eff.get("permessi")),
            "vincoli_speciali": eff.get("vincoli_speciali", []),
            "interpretazioni": interpretazioni,
            "fonti": fonti,
            "note_corpo": corpo.get("note"),
        }
        if extra_docs and out.get("permessi"):
            out["permessi"]["pacchetto"]["documenti"].extend(extra_docs)
        return out

    def _prelievo_contestuale(self, pre: dict | None, tipo: str | None, regime: str) -> dict | None:
        if not pre or not pre.get("periodi_divieto"):
            return pre
        if regime == "cispp" or tipo == "CISPP":
            pre["periodi_divieto"] = []
            pre["periodi_divieto_nota"] = "I periodi di divieto per specie del Capitolo 5 non sono ancora nella scheda."
            return pre
        if tipo == "A":
            pre["periodi_divieto"] = [p for p in pre["periodi_divieto"] if "altre acque" not in (p.get("ambito") or "")]
        return pre


def verifica_matrice(m: Matrice | None = None) -> None:
    """Controlli della cascata sugli esempi del file di struttura."""
    m = m or Matrice()
    tresa = m.risolvi("tresa")
    assert tresa["regime"] == "cispp" and tresa["tipo_acqua"] == "CISPP", tresa["regime"]
    assert tresa["matrice"]["regime_amministrativo"] == "fipsas"
    assert tresa["matrice"]["classificazione_biologica"] == "CISPP"
    assert tresa["matrice"]["livello_permesso"] == "fipsas_tesserino_maggiore"
    assert "cispp.org" not in json.dumps(m.spec)
    assert "fuori_cap4" not in json.dumps(m.spec)
    assert "italo_svizzera" not in json.dumps(m.spec)
    assert "rinvio_esterno" not in json.dumps(m.base.data)
    for seg in m.spec["segmenti"]:
        assert seg.get("geometria_vincolo"), seg["id"]
    assert m.corpi["lago_brinzio"].get("stato") != "predisposto"
    assert m.corpi["rio_briviola"].get("stato") != "predisposto"

    asta = m.risolvi("margorabbia")
    assert asta["calendario"]["giorni"]["id"] == "tutti_i_giorni_deroga_tresa"
    assert "temolo" in asta["prelievo"]["specie_sempre_protette_extra"]
    periodi_asta = {p["specie"]: p["testo"] for p in asta["prelievo"]["periodi_divieto"]}
    assert periodi_asta["trota_fario"] == "dalla prima domenica di ottobre all'ultima domenica di febbraio"
    assert periodi_asta["luccio"] == "dal 1 febbraio al 15 aprile"
    assert periodi_asta["barbo"] == "dal 1 maggio al 30 giugno"
    piano_pre = m.risolvi("lago_piano")["prelievo"]["periodi_divieto"]
    assert all(p["specie"] != "trota_fario" for p in piano_pre)
    assert any(p["specie"] == "luccio" for p in piano_pre)
    assert m.risolvi("verbano")["prelievo"]["periodi_divieto"] == []
    ranco_pre = m.risolvi("verbano", "verbano_ranco_angera")["prelievo"]
    assert ranco_pre["periodi_divieto"] == []
    assert "Capitolo 5" in ranco_pre["periodi_divieto_nota"]
    assert m.risolvi("rancina")["calendario"]["giorni"]["id"] == "giorni_tipo_B"

    nk = "margorabbia_no_kill_grantola_mesenzana"
    base_nk = m.risolvi("margorabbia", nk)
    assert base_nk["regime"] == "no_kill" and base_nk["prelievo"]["rilascio_obbligatorio"] is True
    gara_su_nk = m.risolvi("margorabbia", nk, overlay_id="margorabbia_campo_gara_mesenzana")
    assert gara_su_nk["prelievo"]["rilascio_obbligatorio"] is True
    assert gara_su_nk["attrezzatura"]["ardiglione"] == "ammesso"
    assert gara_su_nk["prelievo"]["misure_minime_cm"]["trota_fario"] == 22
    assert gara_su_nk["regime"] == "no_kill"

    gara = m.risolvi("margorabbia", overlay_id="margorabbia_campo_gara_ghirla")
    assert gara["regime"] == "ordinario_B" and gara["prelievo"]["rilascio_obbligatorio"] is False
    assert gara["prelievo"]["misure_minime_cm"]["trota_fario"] == 22

    inverno = m.risolvi("margorabbia", nk, overlay_id="margorabbia_pesca_invernale_nokill")
    assert "guado" in inverno["tecniche"]["vietate"] and inverno["prelievo"]["rilascio_obbligatorio"] is True

    sponda = m.risolvi("lago_ghirla", modalita="sponda")
    natante = m.risolvi("lago_ghirla", modalita="natante")
    assert sponda["prelievo"]["misure_minime_cm"]["persico_reale"] == 18
    assert sponda["permessi"]["pacchetto"]["id"] == "fipsas_lago_riva"
    assert natante["permessi"]["pacchetto"]["id"] == "fipsas_lago_belly_boat"
    assert natante["prelievo"]["misure_minime_cm"]["salmerino_alpino"] == 30

    ganna = m.risolvi("lago_ganna", "lago_ganna_divieto")
    assert ganna["pesca_consentita"] is False and ganna["tipo_acqua"] == "C"

    varese = m.risolvi("lago_varese")
    assert varese["prelievo"]["misure_minime_cm"]["persico_reale"] == 18
    assert varese["matrice"]["classificazione_biologica"] == "A"
    assert m.risolvi("lago_varese", modalita="sponda")["permessi"]["pacchetto"]["id"] == "fipsas_varese_ridotto"
    assert m.risolvi("lago_varese", modalita="sponda")["matrice"]["regime_amministrativo"] == "fipsas"
    assert m.risolvi("lago_varese", modalita="natante")["matrice"]["regime_amministrativo"] == "diritti_esclusivi"
    assert m.risolvi("lago_varese", modalita="natante")["matrice"]["livello_permesso"] == "esclusivi"
    assert m.risolvi("lago_varese", "lago_varese_natante_esclusivi", modalita="natante")["permessi"]["pacchetto"]["id"] is None
    assert m.risolvi("lago_comabbio", modalita="natante")["pesca_consentita"] is False
    assert m.risolvi("lago_monate")["prelievo"]["misure_minime_cm"]["persico_reale"] == 18
    assert m.risolvi("bardello")["permessi"]["pacchetto"]["id"] == "fipsas_varese_ridotto"
    assert m.risolvi("tinella")["calendario"]["giorni"]["id"] == "tutti_i_giorni_deroga_varese"
    assert m.risolvi("acquanegra", "acquanegra_divieto")["pesca_consentita"] is False

    piano = m.risolvi("lago_piano")
    ids = [d["id"] for d in piano["permessi"]["pacchetto"]["documenti"]]
    assert "libretto_lago_piano" in ids
    assert piano["tipo_acqua"] == "A"
    assert piano["attrezzatura"]["ardiglione"] == "vietato"
    assert m.risolvi("lago_piano", modalita="sponda")["permessi"]["pacchetto"]["id"] == "fipsas_co_lc_riva"
    assert m.risolvi("lago_piano", modalita="sponda")["matrice"]["livello_permesso"] == "fipsas_base"
    barca_piano = m.risolvi("lago_piano", modalita="natante")
    assert barca_piano["permessi"]["pacchetto"]["id"] == "fipsas_co_lc_barca"
    assert barca_piano["matrice"]["livello_permesso"] == "fipsas_contributo_intero"
    assert "libretto_lago_piano" in [d["id"] for d in barca_piano["permessi"]["pacchetto"]["documenti"]]
    brinzio = m.risolvi("lago_brinzio", modalita="sponda")
    assert brinzio["tipo_acqua"] == "C"
    assert brinzio["matrice"]["regime_amministrativo"] == "diritti_esclusivi"
    assert brinzio["matrice"]["livello_permesso"] == "esclusivi"
    assert brinzio["permessi"]["pacchetto"]["id"] == "diritti_brinzio"
    assert m.risolvi("lago_brinzio", modalita="natante")["pesca_consentita"] is False
    assert m.risolvi("rio_briviola")["tipo_acqua"] == "B"
    assert m.risolvi("rio_briviola")["matrice"]["livello_permesso"] == "esclusivi"
    assert m.risolvi("rio_briviola", "rio_brivola_divieto")["pesca_consentita"] is False

    lugano = m.risolvi("lago_lugano")
    assert lugano["regime"] == "cispp"
    assert lugano["attrezzatura"]["canne_max"] == 2
    assert lugano["matrice"]["classificazione_biologica"] == "CISPP"
    assert lugano["matrice"]["livello_permesso"] == "fipsas_tesserino_maggiore"
    assert lugano["permessi"]["pacchetto"]["id"] == "fipsas_ceresio_riva_va"
    nat = m.risolvi("lago_lugano", modalita="natante")
    assert any("tramonto" in v["testo"] for v in nat["vincoli_speciali"])
    assert nat["permessi"]["pacchetto"]["id"] == "fipsas_ceresio_barca_va"
    for cid in ("lago_lugano_nord", "lago_lugano_campione"):
        riva = m.risolvi(cid, modalita="sponda")
        barca = m.risolvi(cid, modalita="natante")
        assert riva["matrice"]["classificazione_biologica"] != "CISPP", cid
        assert riva["permessi"]["pacchetto"]["id"] == "fipsas_co_lc_riva", cid
        assert barca["permessi"]["pacchetto"]["id"] == "fipsas_co_lc_barca", cid
        assert riva["matrice"]["livello_permesso"] == "fipsas_base", cid
        assert barca["matrice"]["livello_permesso"] == "fipsas_contributo_intero", cid
    assert m.segmenti["lago_lugano_restrizione_rezzo"]["corpo_idrico"] == "lago_lugano_nord"
    est = m.risolvi("annone", "annone_est_diritti_esclusivi", modalita="sponda")
    assert est["matrice"]["livello_permesso"] == "esclusivi"
    assert est["permessi"]["pacchetto"]["id"] == "diritti_citterio"
    porto = m.risolvi("lario", "lario_ormeggio_lecco_canottieri", modalita="natante")
    assert porto["pesca_consentita"] is True
    assert m.base.valuta(porto, datetime(2026, 1, 15, 12, 0))["consentita"] is False
    assert m.base.valuta(porto, datetime(2026, 4, 30, 12, 0))["consentita"] is False
    assert m.base.valuta(porto, datetime(2026, 6, 15, 12, 0))["consentita"] is not False
    assert sum(1 for s in m.spec["segmenti"] if s["id"].startswith("lario_ormeggio_")) == 57
    assert m.risolvi("trallo")["calendario"]["giorni"]["id"] == "tutti_i_giorni_deroga_ceresio_va"
    assert m.risolvi("cuccio")["calendario"]["giorni"]["id"] == "giorni_tipo_B"

    pusiano = m.risolvi("pusiano")
    assert pusiano["matrice"]["regime_amministrativo"] == "diritti_esclusivi"
    assert pusiano["regime"] == "diritti_esclusivi"
    assert pusiano["tipo_acqua"] == "A"
    assert pusiano["permessi"]["pacchetto"]["id"] == "diritti_pusiano"
    assert pusiano["prelievo"]["rilascio_obbligatorio"] is True
    assert m.risolvi("lario", modalita="natante")["permessi"]["pacchetto"]["id"] == "fipsas_co_lc_barca"
    assert m.risolvi("olona")["calendario"]["giorni"]["id"] == "tutti_i_giorni_deroga_olona"
    assert m.risolvi("lambro")["tipo_acqua"] == "C"
    assert m.risolvi("verbano")["regime"] == "cispp"
    assert m.risolvi("verbano")["matrice"]["classificazione_biologica"] == "CISPP"
    ranco = m.risolvi("verbano", "verbano_ranco_angera")
    assert ranco["regime"] == "diritti_esclusivi"
    assert ranco["matrice"]["livello_permesso"] == "esclusivi"
    assert ranco["permessi"]["pacchetto"]["id"] == "diritti_ranco_angera"
    sud = m.risolvi("annone", "annone_sud_diritti_esclusivi", modalita="natante")
    assert sud["matrice"]["regime_amministrativo"] == "diritti_esclusivi"
    assert sud["permessi"]["pacchetto"]["id"] == "diritti_citterio"
    assert m.risolvi("annone", modalita="sponda")["matrice"]["regime_amministrativo"] == "fipsas"
    for cid in ("pusiano", "segrino", "montorfano", "lago_monate", "lago_comabbio"):
        for modalita in ("sponda", "natante"):
            risolto = m.risolvi(cid, modalita=modalita)
            assert risolto["matrice"]["regime_amministrativo"] == "diritti_esclusivi", (cid, modalita)
            assert risolto["matrice"]["entita"] == modalita


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--elenco", action="store_true", help="elenca le zone")
    ap.add_argument("--zona")
    ap.add_argument("--corpo")
    ap.add_argument("--quando", help="AAAA-MM-GG HH:MM (ora locale)")
    ap.add_argument("--json", action="store_true", help="stampa la zona risolta")
    ap.add_argument("--matrice", action="store_true", help="risolve la cascata di struttura_dati_regole.json")
    ap.add_argument("--segmento", help="id di un taglio (con --matrice)")
    ap.add_argument("--overlay", help="id di un overlay temporaneo (con --matrice)")
    ap.add_argument("--modalita", default="sponda", choices=("sponda", "natante"))
    ap.add_argument("--verifica", action="store_true", help="controlla gli esempi della cascata")
    args = ap.parse_args()
    if args.verifica or args.matrice:
        m = Matrice()
        if args.verifica:
            verifica_matrice(m)
            print("Cascata ok.")
            if not args.corpo:
                return
        if not args.corpo:
            for cid, c in m.corpi.items():
                print(f"{cid:16s} {c['regime_amministrativo']:18s} cat.{c['classificazione_biologica']}  {c['geometria']:8s}  {c['nome']}")
            return
        eff = m.risolvi(args.corpo, args.segmento, args.modalita, args.overlay)
        if args.json or not args.quando:
            print(json.dumps(eff, ensure_ascii=False, indent=2))
        if args.quando:
            dt = datetime.strptime(args.quando, "%Y-%m-%d %H:%M")
            print(json.dumps(m.base.valuta(eff, dt), ensure_ascii=False, indent=2))
        return
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
