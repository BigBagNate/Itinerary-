"""
Check every place against a real map.

Uses OpenStreetMap's Nominatim: free, no key, no account. In return their policy
asks for a real User-Agent and at most one request a second, so we rate-limit and
cache every lookup to disk. A place looked up once is never looked up again.

What this buys us:
  - proof the place exists at all
  - the correct spelling, straight from the map
  - a street address, which is what "enough to find it" actually means
  - a sanity check on the bucket (a pub filed under Sights gets corrected)
"""
import json, re, threading, time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

ENDPOINT = "https://nominatim.openstreetmap.org/search"
UA = "ItineraryWorkbench/0.1 (personal trip planner; https://github.com/BigBagNate/Itinerary-)"
CACHE_FILE = Path(__file__).parent / ".mapcache.json"

MIN_GAP = 1.2          # seconds between requests - their policy is 1/sec
_last_call = [0.0]
_lock = threading.Lock()

# things that are a venue you can visit
GOOD_CLASSES = {"amenity", "shop", "tourism", "leisure", "historic", "craft"}
# things that are emphatically not
BAD_CLASSES = {"highway", "boundary", "waterway", "railway", "landuse", "natural",
               "place", "admin", "barrier", "man_made", "route"}

OSM_TO_BUCKET = {
    "restaurant": "eats", "fast_food": "eats", "cafe": "eats", "bakery": "eats",
    "food_court": "eats", "ice_cream": "eats", "deli": "eats",
    "bar": "drinks", "pub": "drinks", "biergarten": "drinks", "nightclub": "drinks",
    "wine_bar": "drinks", "winery": "drinks", "brewery": "drinks",
    "museum": "sights", "attraction": "sights", "artwork": "sights", "gallery": "sights",
    "viewpoint": "sights", "monument": "sights", "memorial": "sights", "castle": "sights",
    "ruins": "sights", "church": "sights", "cathedral": "sights", "place_of_worship": "sights",
    "park": "sights", "garden": "sights",
    "hotel": "stays", "hostel": "stays", "guest_house": "stays", "apartment": "stays",
    "theatre": "activities", "cinema": "activities", "zoo": "activities",
    "theme_park": "activities", "beach": "activities", "swimming_pool": "activities",
    "marketplace": "shopping", "mall": "shopping", "department_store": "shopping",
}


def _cache() -> Dict[str, Any]:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def _save(c: Dict[str, Any]):
    try:
        CACHE_FILE.write_text(json.dumps(c, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _ask(query: str) -> List[Dict[str, Any]]:
    with _lock:                                    # one at a time, politely spaced
        gap = time.time() - _last_call[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last_call[0] = time.time()
    r = requests.get(ENDPOINT, headers={"User-Agent": UA}, timeout=30,
                     params={"q": query, "format": "json", "limit": 5,
                             "addressdetails": 1})
    if r.status_code != 200:
        raise RuntimeError(f"map lookup failed ({r.status_code})")
    return r.json()


def _address(a: Dict[str, Any]) -> str:
    street = " ".join(x for x in [a.get("house_number"), a.get("road")] if x)
    bits = [street, a.get("suburb") or a.get("neighbourhood") or a.get("quarter")]
    return ", ".join(b for b in bits if b)


def _city_of(a: Dict[str, Any]) -> str:
    return str(a.get("city") or a.get("town") or a.get("village")
               or a.get("municipality") or a.get("county") or "")


def _close(a: str, b: str) -> bool:
    """Loose match. Maps speak local: Roma/Rome, Italia/Italy, Munchen/Munich."""
    import difflib
    a, b = (a or "").strip().lower(), (b or "").strip().lower()
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.6


def _in_right_place(addr: Dict[str, Any], city: str, country: str) -> bool:
    """Guard against the right name in the wrong country - but stay permissive,
    because the map labels places in their own language."""
    if not city and not country:
        return True
    if country and _close(addr.get("country", ""), country):
        return True
    for field in ("city", "town", "village", "municipality", "county", "state"):
        if _close(str(addr.get(field) or ""), city):
            return True
    return False


NOISE_WORDS = re.compile(
    r"\b(?:the|la|le|il|lo|el|los|las|los|de|di|del|della|da|do|du|a|al|au|aux|"
    r"restaurant|ristorante|trattoria|osteria|pizzeria|cafe|caff[eè]|bar|hotel)\b",
    re.I)


def _name_matches(asked: str, found: str) -> bool:
    """Guard against the map confidently returning something else entirely.
    'La Terra' must not match 'ESA Centre for Earth Observation'."""
    import difflib
    a, f = asked.strip().lower(), (found or "").strip().lower()
    if not a or not f:
        return False
    if a in f or f in a:
        return True
    if difflib.SequenceMatcher(None, a, f).ratio() >= 0.62:
        return True
    # compare the words that actually carry the name
    aw = {w for w in re.findall(r"[a-z0-9']{3,}", NOISE_WORDS.sub(" ", a))}
    fw = {w for w in re.findall(r"[a-z0-9']{3,}", NOISE_WORDS.sub(" ", f))}
    return bool(aw and fw and len(aw & fw) / len(aw) >= 0.6)


def _area_words(text: str) -> set:
    """Neighbourhood words worth matching on, minus the filler."""
    stop = {"area", "district", "neighbourhood", "neighborhood", "near", "the", "and",
            "quarter", "side", "street", "st", "road", "rd", "via", "avenue", "ave"}
    return {w for w in re.findall(r"[a-z']{3,}", (text or "").lower()) if w not in stop}


def _area_score(hit: Dict[str, Any], area: str) -> int:
    """How well does this result sit in the neighbourhood the video described?"""
    if not area:
        return 0
    want = _area_words(area)
    if not want:
        return 0
    a = hit.get("address", {})
    have = _area_words(" ".join(str(a.get(k) or "") for k in
                                ("suburb", "neighbourhood", "quarter", "city_district",
                                 "road", "hamlet", "borough")))
    have |= _area_words(hit.get("display_name", ""))
    return 2 if want & have else 0


def _is_risky_name(name: str) -> bool:
    """Some names match half a city. 'Fortunato' and 'Beam' are common words that
    will find *a* business almost anywhere. 'Matricianella' is distinctive enough
    to trust on its own, and any multi-word name is safer still.

    Risky means: one short word. Those we only accept in the right neighbourhood."""
    words = [w for w in re.findall(r"[A-Za-z0-9']{2,}", name) if w.lower() not in
             {"the", "la", "le", "il", "lo", "el", "de", "di", "da", "al", "au"}]
    if len(words) >= 2:
        return False
    return not words or len(words[0]) < 12


def look_up(name: str, city: str = "", country: str = "",
            area: str = "") -> Optional[Dict[str, Any]]:
    """Return map details for a real venue, or None if it isn't one."""
    key = f"{name}|{city}|{country}|{area}".lower()
    cache = _cache()
    if key in cache:
        return cache[key]

    # The neighbourhood ranks the results; it must not narrow the search itself,
    # or an over-specified query comes back empty.
    query = ", ".join(x for x in [name, city, country] if x)
    try:
        hits = _ask(query)
    except Exception:  # noqa: BLE001
        return None                                # network trouble: don't punish the place

    ranked = []
    for h in hits:
        cls, typ = h.get("class", ""), h.get("type", "")
        if cls in BAD_CLASSES or cls not in GOOD_CLASSES:
            continue                               # a road or a bus stop is not the place
        if not _in_right_place(h.get("address", {}), city, country):
            continue                               # right name, wrong country
        if not _name_matches(name, h.get("name") or ""):
            continue                               # wrong place wearing a right address
        ranked.append((_area_score(h, area), h))

    # the one in the neighbourhood the video described wins
    ranked.sort(key=lambda r: -r[0])

    # A short name in the wrong neighbourhood is almost certainly a different
    # business with a similar name. Better to say "not found" than to send
    # someone across the city.
    if ranked and area and _is_risky_name(name) and ranked[0][0] == 0:
        result = {"found": False, "why": "no match in the area the video described"}
        cache[key] = result
        _save(cache)
        return result

    best = None
    for _score, h in ranked[:1]:
        typ = h.get("type", "")
        best = {
            "found": True,
            "name": h.get("name") or name,
            "address": _address(h.get("address", {})),
            "area": h.get("address", {}).get("suburb")
                    or h.get("address", {}).get("neighbourhood") or "",
            "city": _city_of(h.get("address", {})),
            "lat": h.get("lat"), "lon": h.get("lon"),
            "osm_kind": typ.replace("_", " "),
            "bucket": OSM_TO_BUCKET.get(typ),
            "map_url": f"https://www.google.com/maps/search/?api=1&query={h.get('lat')},{h.get('lon')}",
        }
        break

    if best and ranked:
        best["in_described_area"] = bool(ranked[0][0])
    result = best or {"found": False}
    cache[key] = result
    _save(cache)
    return result


def verify_spots(spots: List[Dict[str, Any]], city: str = "", country: str = "",
                 area: str = "") -> List[Dict[str, Any]]:
    """Look each place up and fold what the map says back into it."""
    for sp in spots:
        # Always judge against the neighbourhood the VIDEO described. Using the
        # spot's own area lets a previous wrong match vouch for itself.
        hit = look_up(sp.get("name", ""), city, country, area or sp.get("area") or "")
        if not hit or not hit.get("found"):
            sp["on_map"] = False
            if hit and hit.get("why"):
                sp["map_note"] = hit["why"]
            continue
        sp["on_map"] = True
        sp["name"] = hit["name"]                   # the map spells it correctly
        sp["address"] = hit["address"]
        sp["map_url"] = hit["map_url"]
        sp["lat"], sp["lon"] = hit["lat"], hit["lon"]
        if hit.get("area"):
            sp["area"] = hit["area"]
        if hit.get("osm_kind"):
            sp["kind"] = hit["osm_kind"]
        if hit.get("bucket"):
            sp["bucket"] = hit["bucket"]           # the map knows better than we do
        sp["sure"] = "high"                        # confirmed by a real map
    return spots
