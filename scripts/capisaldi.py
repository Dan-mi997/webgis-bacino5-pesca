"""Capisaldi del prontuario: pin verificati a mano, con fallback OSM se manca il pin."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point

from config import CAPISALDI_VERIFICATI
from geo_utils import line_length_m, point_at_m, project_info


@dataclass
class Caposaldo:
    id: str
    nome: str
    corso: str
    along_m: float
    lon: float
    lat: float
    fonte: str
    note: str = ""
    verificato: bool = False
    offset_m: float = 0.0


@dataclass
class Registro:
    capisaldi: dict = field(default_factory=dict)
    todo: list = field(default_factory=list)

    def add(self, cap: Caposaldo):
        self.capisaldi[cap.id] = cap
        mark = "OK" if cap.verificato else "??"
        print(f"  [{mark}] {cap.id}: along={cap.along_m:.0f} m  offset={cap.offset_m:.0f} m  {cap.fonte}")
        return cap

    def verify(self, key: str, label: str, motivo: str, approx=None):
        self.todo.append({
            "id": key, "label": label, "motivo": motivo,
            "status": "da_verificare", "coordinate_usate": approx,
        })
        print(f"  TODO [{key}] {motivo[:110]}")


def load_verified() -> dict:
    if not CAPISALDI_VERIFICATI.exists():
        return {}
    data = json.loads(CAPISALDI_VERIFICATI.read_text(encoding="utf-8"))
    return data.get("punti") or {}


VERIFIED = load_verified()


def pin_on(line: LineString, cap_id: str, *, corso: str, nome: str | None = None, note: str = "") -> Caposaldo:
    """Proietta un pin verificato sulla linea; il marker resta sulle coordinate confermate."""
    v = VERIFIED[cap_id]
    lon, lat = float(v["lon"]), float(v["lat"])
    _proj, along, off = project_info(line, lon, lat)
    return Caposaldo(
        id=cap_id,
        nome=nome or v.get("nome") or cap_id,
        corso=corso,
        along_m=along,
        lon=lon,
        lat=lat,
        fonte="verificato_manuale",
        note=note or v.get("note") or "",
        verificato=True,
        offset_m=off,
    )


def _cap_on(line: LineString, along: float, **kw) -> Caposaldo:
    p = point_at_m(line, along)
    return Caposaldo(along_m=along, lon=p.x, lat=p.y, offset_m=0.0, **kw)


def locate_stem(stem: LineString, _ghirla, _weirs, reg: Registro) -> dict:
    """Capisaldi sull'asta a valle di Ghirla. I pin verificati hanno priorità."""
    C = "margorabbia"
    total = line_length_m(stem)

    for cap_id, nome, extra_note in (
        ("outlet_ghirla", "Ponte sul Lago di Ghirla", "Inizio campo gara Ghirla"),
        ("chiusa_enel", "Chiusa Enel in località Ghetto", "Fine campo gara Ghirla"),
        ("ponte_grantola", "Ponte di Grantola", "Inizio No-Kill"),
        ("nk_end", "Briglia 150 m a monte di Passeri Concessionaria Opel (fine No-Kill)", "Fine No-Kill"),
        ("super_mesenzana", "Supermercato Mesenzana (Carrefour, sponda)", "Inizio campo gara Mesenzana"),
        ("ponte_cucco", "Ponte del Cucco", "Il campo gara termina 200 m più a valle"),
        ("foce_briglia", "Prima briglia a monte della confluenza (inizio divieto)", ""),
    ):
        if cap_id not in VERIFIED:
            raise KeyError(f"Manca il pin verificato «{cap_id}» in {CAPISALDI_VERIFICATI.name}")
        cap = pin_on(stem, cap_id, corso=C, nome=nome, note=extra_note)
        if cap.offset_m > 80:
            reg.verify(cap_id, nome, f"Pin verificato a {cap.offset_m:.0f} m dall'asta OSM: controllare la proiezione.", [cap.lon, cap.lat])
        reg.add(cap)

    cu = reg.capisaldi["ponte_cucco"].along_m
    reg.add(_cap_on(
        stem, min(total, cu + 200),
        id="fine_gara_cucco",
        nome="200 m a valle del Ponte del Cucco (fine campo gara)",
        corso=C, fonte="derivato_da_ponte_cucco", verificato=True,
        note="Derivato: +200 m lungo l'asta dal Ponte del Cucco confermato.",
    ))
    reg.add(_cap_on(
        stem, total,
        id="confluenza_tresa",
        nome="Confluenza Margorabbia–Tresa",
        corso=C, fonte="estremo_osm", verificato=True,
    ))

    nk = reg.capisaldi["nk_end"].along_m
    sup = reg.capisaldi["super_mesenzana"].along_m
    if nk > sup:
        print(f"  sovrapposizione No-Kill ∩ campo gara: {nk - sup:.0f} m (Carrefour → briglia Passeri)")
    return {k: v.along_m for k, v in reg.capisaldi.items() if v.corso == C}


def locate_boggione(line: LineString, reg: Registro) -> tuple[float, float] | None:
    C = "boggione"
    mon = pin_on(line, "monumento_ghirla", corso=C, nome="Monumento ai Caduti a Ghirla")
    mb = pin_on(line, "strada_marzio_boarezzo", corso=C, nome="Attraversamento strada Marzio–Boarezzo")
    reg.add(mon)
    reg.add(mb)
    a, b = sorted([mb.along_m, mon.along_m])
    return (a, b) if b - a > 10 else None


def locate_chiesone(line: LineString, reg: Registro) -> tuple[float, float] | None:
    C = "chiesone"
    sp = pin_on(line, "sp54_chiesone", corso=C, nome="Ponte S.S. 394 sul Chiesone (prontuario: S.P. 54)")
    pz = pin_on(line, "pianazzo_chiesone", corso=C, nome="Ponte di via Pianazzo (Chiesone)")
    reg.add(sp)
    reg.add(pz)
    a, b = sorted([sp.along_m, pz.along_m])
    print(f"  divieto Chiesone: {b - a:.0f} m (prontuario ~970 m)")
    return a, b
