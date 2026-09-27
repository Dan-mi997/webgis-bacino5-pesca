"""Accesso a OSM API, Nominatim e Overpass con cache su disco (cache/http)."""

from __future__ import annotations

import hashlib
import json
import time

import requests

from config import HTTP_CACHE_DIR, USER_AGENT

OSM_API = "https://api.openstreetmap.org/api/0.6"
NOMINATIM = "https://nominatim.openstreetmap.org"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

REFRESH = False  # True = ignora la cache e riscarica


def _cache_path(kind: str, key: str):
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return HTTP_CACHE_DIR / f"{kind}_{digest}.json"


def _cached(kind: str, key: str, fetch):
    path = _cache_path(kind, key)
    if path.exists() and not REFRESH:
        return json.loads(path.read_text(encoding="utf-8"))
    data = fetch()
    if data is not None:
        HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def osm_full(osm_type: str, osm_id: int) -> dict:
    url = f"{OSM_API}/{osm_type}/{osm_id}/full.json"

    def fetch():
        print(f"  OSM {osm_type}/{osm_id} ...")
        r = SESSION.get(url, timeout=90)
        r.raise_for_status()
        return r.json()

    return _cached("osm", url, fetch)


def nominatim_search(q: str, limit: int = 5) -> list[dict]:
    params = {"q": q, "format": "json", "limit": limit, "countrycodes": "it", "addressdetails": 1}

    def fetch():
        time.sleep(1.1)
        r = SESSION.get(f"{NOMINATIM}/search", params=params, timeout=40)
        r.raise_for_status()
        data = r.json()
        print(f"  Nominatim [{q}] -> {len(data)} hit")
        return data

    return _cached("nominatim", json.dumps(params, sort_keys=True), fetch) or []


def overpass(query: str) -> dict | None:
    def fetch():
        for url in OVERPASS_URLS:
            try:
                print(f"  Overpass {url.split('/')[2]} ...")
                r = SESSION.post(url, data=query.encode("utf-8"), timeout=60)
                if r.status_code == 200:
                    return r.json()
                print(f"    status {r.status_code}")
            except Exception as exc:
                print(f"    errore: {exc}")
        return None

    return _cached("overpass", query, fetch)
