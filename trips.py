"""
Turn a pile of labelled posts into trips.

One city = one page. Inside it, places sorted into buckets. Advice that belongs
to that city sits underneath it; advice that works anywhere is pulled out once
into its own list, so you don't read it six times.
"""
import difflib, json, re

import brain
from pathlib import Path
from typing import Any, Dict, List

BUCKETS = ["sights", "eats", "activities", "drinks", "shopping", "stays"]
ALWAYS_SHOW = ["sights", "eats", "activities", "drinks"]   # Nathan's four
BUCKET_LABEL = {"sights": "Sights", "eats": "Eats", "activities": "Activities",
                "drinks": "Drinks", "shopping": "Shopping", "stays": "Stays"}

TOPIC_ORDER = ["local know-how", "getting around", "timing", "money", "etiquette",
               "packing", "safety", "other"]
TOPIC_LABEL = {"local know-how": "Local know-how", "getting around": "Getting around",
               "timing": "Timing & booking", "money": "Money",
               "etiquette": "Etiquette & language", "packing": "Packing",
               "safety": "Safety", "other": "Other"}

# same city, different spellings
CITY_ALIASES = {
    "roma": "Rome", "firenze": "Florence", "venezia": "Venice", "napoli": "Naples",
    "milano": "Milan", "torino": "Turin", "münchen": "Munich", "muenchen": "Munich",
    "köln": "Cologne", "wien": "Vienna", "praha": "Prague", "lisboa": "Lisbon",
    "sevilla": "Seville", "cdmx": "Mexico City", "mexico d.f.": "Mexico City",
    "nyc": "New York", "new york city": "New York", "la": "Los Angeles",
    "sf": "San Francisco", "hcmc": "Ho Chi Minh City", "saigon": "Ho Chi Minh City",
    "bkk": "Bangkok", "kbh": "Copenhagen", "københavn": "Copenhagen",
    "the hague": "The Hague", "den haag": "The Hague", "tokio": "Tokyo",
    "seoul si": "Seoul", "osaka shi": "Osaka", "istanbul": "Istanbul",
}

JUNK_CITY = {"", "unknown", "n/a", "none", "not stated", "unclear", "-", "various"}


def clean_city(raw: Any) -> str:
    c = str(raw or "").strip().strip(".,;:")
    low = c.lower()
    if low in JUNK_CITY:
        return ""
    low = re.sub(r"^(the city of|city of)\s+", "", low)
    if low in CITY_ALIASES:
        return CITY_ALIASES[low]
    return " ".join(w if w.isupper() and len(w) <= 3 else w.capitalize()
                    for w in re.split(r"\s+", c) if w)


def same_place(a: str, b: str) -> bool:
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return True
    if len(a) > 4 and len(b) > 4 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() > 0.86


def build(library: Path) -> Dict[str, Any]:
    records = []
    for d in sorted(library.iterdir()):
        f = d / "record.json"
        if not d.is_dir() or not f.exists():
            continue
        try:
            records.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            continue

    cities: Dict[str, Dict[str, Any]] = {}
    anywhere: List[Dict[str, Any]] = []
    unplaced: List[Dict[str, Any]] = []
    unlabelled = 0
    stale: List[Dict[str, Any]] = []

    for rec in records:
        L = rec.get("labels") or {}
        if not L:
            unlabelled += 1
            continue
        if "spots" not in L:
            # labelled by an older version - its places are stranded in the old shape
            stale.append({"video_id": rec.get("id"), "title": L.get("title"),
                          "author": rec.get("author"),
                          "stranded": len(L.get("mentioned_places") or [])})

        place = L.get("place") or {}
        city = clean_city(place.get("city"))
        country = str(place.get("country") or "").strip()
        if country.lower() in JUNK_CITY:
            country = ""

        src = {"video_id": rec.get("id"), "author": rec.get("author"),
               "title": L.get("title"), "url": rec.get("source_url")}

        # tips that work anywhere get lifted out once
        for t in L.get("tips") or []:
            if t.get("scope") == "anywhere":
                anywhere.append({**t, "from": src})

        if not city:
            unplaced.append({**src, "category": L.get("category"),
                             "why": L.get("purpose"), "kind": rec.get("kind"),
                             "spots": len(L.get("spots") or [])})
            continue

        c = cities.setdefault(city, {
            "city": city, "country": country, "videos": [],
            "buckets": {b: [] for b in BUCKETS}, "tips": [],
        })
        if country and not c["country"]:
            c["country"] = country
        c["videos"].append(src)

        for t in L.get("tips") or []:
            if t.get("scope") != "anywhere":
                c["tips"].append({**t, "from": src})

        for sp in L.get("spots") or []:
            b = sp.get("bucket")
            if b not in BUCKETS:                  # older entries, or the model forgot
                b = brain.bucket_for(sp)
            bucket = c["buckets"][b]
            hit = next((x for x in bucket if same_place(x["name"], sp["name"])), None)
            if hit:
                # same place from a second video - that's a stronger recommendation
                hit["seen_in"].append(src)
                rank = {"high": 3, "medium": 2, "low": 1}
                if rank.get(sp.get("sure"), 0) > rank.get(hit.get("sure"), 0):
                    hit["name"], hit["sure"], hit["source"] = (
                        sp["name"], sp.get("sure"), sp.get("source"))
                note = brain.clean_note(sp.get("note") or "", sp.get("name", ""))
                if note and not any(same_place(note, n) for n in hit["notes"]):
                    hit["notes"].append(note)
                hit["notes"].sort(key=len, reverse=True)   # fullest description first
                del hit["notes"][1:]                       # one is enough
            else:
                bucket.append({
                    "name": sp["name"], "kind": sp.get("kind", ""),
                    "sure": sp.get("sure", "medium"), "source": sp.get("source", ""),
                    "notes": [n for n in [brain.clean_note(sp.get("note") or "",
                                                            sp.get("name", ""))] if n],
                    "seen_in": [src],
                })

    # tidy each city for display
    out_cities = []
    for c in cities.values():
        shown = {}
        for b in BUCKETS:
            items = c["buckets"][b]
            items.sort(key=lambda x: (-len(x["seen_in"]), x["name"].lower()))
            if items or b in ALWAYS_SHOW:
                shown[b] = items
        c["buckets"] = shown
        c["tips"] = group_tips(c["tips"])
        c["place_count"] = sum(len(v) for v in shown.values())
        out_cities.append(c)

    out_cities.sort(key=lambda c: (-c["place_count"], c["city"]))

    return {
        "cities": out_cities,
        "anywhere": group_tips(dedupe_tips(anywhere)),
        "unplaced": unplaced,
        "unlabelled": unlabelled,
        "stale": stale,
        "bucket_label": BUCKET_LABEL,
        "topic_label": TOPIC_LABEL,
    }


def dedupe_tips(tips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for t in tips:
        if not any(same_place(t["tip"], o["tip"]) for o in out):
            out.append(t)
    return out


def group_tips(tips: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Into topic sections, in a sensible reading order."""
    by: Dict[str, List[Dict[str, Any]]] = {}
    for t in dedupe_tips(tips):
        by.setdefault(t.get("topic", "other"), []).append(t)
    return [{"topic": k, "label": TOPIC_LABEL.get(k, k.title()), "tips": by[k]}
            for k in TOPIC_ORDER if by.get(k)]
