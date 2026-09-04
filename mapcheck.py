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
OVERPASS = "https://overpass-api.de/api/interpreter"
NEARBY_CACHE = Path(__file__).parent / ".nearbycache.json"
NEARBY_RADIUS = 900          # metres. 400 missed a place 600m from the landmark.
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


def _name_score(asked: str, found: str) -> int:
    """How well the map's name matches the one we heard.
    3 = certain, 2 = very close, 1 = plausible but needs corroborating, 0 = no."""
    import difflib
    a, f = asked.strip().lower(), (found or "").strip().lower()
    if not a or not f:
        return 0
    if a == f or a in f or f in a:
        return 3
    ratio = difflib.SequenceMatcher(None, a, f).ratio()
    if ratio >= 0.75:
        return 3
    aw = {w for w in re.findall(r"[a-z0-9']{3,}", NOISE_WORDS.sub(" ", a))}
    fw = {w for w in re.findall(r"[a-z0-9']{3,}", NOISE_WORDS.sub(" ", f))}
    if aw and fw:
        share = len(aw & fw) / len(aw)
        if share >= 0.6:
            return 3
        if share > 0:
            return 2
    if ratio >= 0.62:
        return 2
    if ratio >= 0.48:
        return 1          # "Matricanella" vs "Matricianella" - only with support
    return 0


def _adds_new_word(asked: str, found: str) -> bool:
    """Did the map turn our name into a different, longer one?
    'La Pietra' -> 'La Pietra Scheggiata' is the map choosing a place for us."""
    aw = {w for w in re.findall(r"[a-z0-9']{4,}", NOISE_WORDS.sub(" ", asked.lower()))}
    fw = {w for w in re.findall(r"[a-z0-9']{4,}", NOISE_WORDS.sub(" ", (found or "").lower()))}
    return bool(fw - aw) and aw.issubset(fw)


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


def look_up(name: str, city: str = "", country: str = "", area: str = "",
            near: str = "") -> Optional[Dict[str, Any]]:
    """Return map details for a real venue, or None if it isn't one.

    The video says which place is meant; the map says how it is spelled and where
    it is. A name we half-heard is accepted only when the map's answer also sits
    where the video said the place was."""
    key = f"{name}|{city}|{country}|{area}|{near}".lower()
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

    # Score every candidate on two independent things: does the name match, and
    # does it sit where the video said it was. Either alone can mislead; together
    # they pin the place down.
    ranked = []
    for h in hits:
        cls = h.get("class", "")
        if cls in BAD_CLASSES or cls not in GOOD_CLASSES:
            continue                               # a road or a bus stop is not the place
        if not _in_right_place(h.get("address", {}), city, country):
            continue                               # right name, wrong country
        nscore = _name_score(name, h.get("name") or "")
        if nscore == 0:
            continue                               # wrong place wearing a right address
        near_hit = _area_score(h, near)             # what the video said about THIS place
        area_hit = _area_score(h, area)             # what it said about the city
        ranked.append({"h": h, "name": nscore, "near": near_hit, "area": area_hit,
                       "total": nscore + near_hit + (area_hit and 1)})

    ranked.sort(key=lambda r: (-r["near"], -r["total"], -r["name"]))

    best = None
    for r in ranked:
        h, corroborated = r["h"], bool(r["near"] or r["area"])
        found_name = h.get("name") or name
        # a shaky name needs the video to back up where it is
        if r["name"] <= 1 and not corroborated:
            continue
        # a risky short name needs it too
        if _is_risky_name(name) and (area or near) and not corroborated:
            continue
        # and the map must not swap our place for a longer-named different one
        if _adds_new_word(name, found_name) and not corroborated:
            continue
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
            "agrees_with_video": corroborated,
            "why_matched": ("the video's own directions for this place" if r["near"]
                            else "the area the video described" if r["area"]
                            else "an exact name match"),
        }
        break

    result = best or {"found": False,
                      "why": "nothing on the map matches both the name and where "
                             "the video said it was"}
    cache[key] = result
    _save(cache)
    return result


# ---------------------------------------------------------------- location first
#
# Searching the map by name fails when the name is wrong: "Matricanella" returns
# nothing, "Armando" returns a butcher and a bridge. So when that happens, work
# the other way round - ask what is actually AT the place the video described,
# then find our name in that list.

def _nearby_cache() -> Dict[str, Any]:
    if NEARBY_CACHE.exists():
        try:
            return json.loads(NEARBY_CACHE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {}


def landmark_point(clue: str, city: str, country: str):
    """Turn 'near the Pantheon' into a point on the map."""
    words = " ".join(w for w in re.split(r"\s+", clue or "")
                     if w.lower() not in {"near", "the", "in", "at", "on", "by",
                                          "around", "close", "to", "area", "next"})
    if not words.strip():
        return None
    try:
        hits = _ask(", ".join(x for x in [words.strip(), city, country] if x))
    except Exception:  # noqa: BLE001
        return None
    if not hits:
        return None
    return float(hits[0]["lat"]), float(hits[0]["lon"])


def venues_around(lat: float, lon: float) -> List[Dict[str, Any]]:
    """Everything named and visitable within walking distance of a point."""
    key = f"{lat:.4f},{lon:.4f},{NEARBY_RADIUS}"
    cache = _nearby_cache()
    if key in cache:
        return cache[key]
    kinds = "restaurant|cafe|bar|fast_food|pub|ice_cream|bakery|marketplace|nightclub"
    q = (f'[out:json][timeout:50];('
         f'node["name"]["amenity"~"{kinds}"](around:{NEARBY_RADIUS},{lat},{lon});'
         f'way["name"]["amenity"~"{kinds}"](around:{NEARBY_RADIUS},{lat},{lon});'
         f'node["name"]["shop"](around:{NEARBY_RADIUS},{lat},{lon});'
         f'node["name"]["tourism"](around:{NEARBY_RADIUS},{lat},{lon});'
         f');out center tags;')
    with _lock:
        gap = time.time() - _last_call[0]
        if gap < MIN_GAP:
            time.sleep(MIN_GAP - gap)
        _last_call[0] = time.time()
    try:
        r = requests.get(OVERPASS, params={"data": q},
                         headers={"User-Agent": UA}, timeout=90)
        if r.status_code != 200:
            return []
        out = []
        for e in r.json().get("elements", []):
            t = e.get("tags", {})
            if not t.get("name"):
                continue
            centre = e.get("center") or {}
            out.append({
                "name": t["name"],
                "kind": (t.get("amenity") or t.get("shop") or t.get("tourism") or ""),
                "street": " ".join(x for x in [t.get("addr:housenumber"),
                                               t.get("addr:street")] if x),
                "lat": e.get("lat") or centre.get("lat"),
                "lon": e.get("lon") or centre.get("lon"),
            })
    except Exception:  # noqa: BLE001
        return []
    cache[key] = out
    try:
        NEARBY_CACHE.write_text(json.dumps(cache), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return out


def find_near(name: str, clue: str, city: str, country: str) -> Optional[Dict[str, Any]]:
    """Our name, matched against what is really there."""
    import difflib
    pt = landmark_point(clue, city, country)
    if not pt:
        return None
    places = venues_around(*pt)
    if not places:
        return None
    low = name.lower().strip()
    core = max(re.findall(r"[A-Za-z']{3,}", name) or [name], key=len).lower()

    def whole_word(needle: str, hay: str) -> bool:
        """"at" must not match inside "fortunato"."""
        if len(needle) < 4:
            return False
        return re.search(r"(?<![a-z])" + re.escape(needle) + r"(?![a-z])", hay) is not None

    best, best_score = None, 0.0
    for v in places:
        vl = v["name"].lower()
        if whole_word(low, vl) or whole_word(vl, low):
            score = 1.0
        elif whole_word(core, vl):
            # sharing one word is not enough if the map's name is a different,
            # much longer one: "La Pietra" is not "Antics Osteria Di Pietra"
            ours = set(re.findall(r"[a-z']{4,}", NOISE_WORDS.sub(" ", low)))
            clue_words = set(re.findall(r"[a-z']{4,}", (clue or "").lower()))
            # "Armando al Pantheon" adds "Pantheon" - but that is the very landmark
            # we searched near, so it corroborates. "Antics" corroborates nothing.
            extra = [w for w in re.findall(r"[a-z']{4,}", NOISE_WORDS.sub(" ", vl))
                     if w not in ours and w not in clue_words]
            if extra:
                continue
            score = 0.9                       # "Armando" inside "Armando al Pantheon"
        else:
            score = difflib.SequenceMatcher(None, low, vl).ratio()
            if score < 0.78 or min(len(low), len(vl)) < 5:
                continue
        if score > best_score:
            best, best_score = v, score
    if not best:
        return None
    return {
        "found": True, "name": best["name"],
        "address": best["street"] or "", "area": "",
        "city": city, "lat": best["lat"], "lon": best["lon"],
        "osm_kind": (best["kind"] or "").replace("_", " "),
        "bucket": OSM_TO_BUCKET.get(best["kind"]),
        "map_url": f"https://www.google.com/maps/search/?api=1&query={best['lat']},{best['lon']}",
        "agrees_with_video": True,
        "why_matched": f"found near {clue.strip()}, where the video said it was",
    }


def verify_spots(spots: List[Dict[str, Any]], city: str = "", country: str = "",
                 area: str = "") -> List[Dict[str, Any]]:
    """Look each place up and fold what the map says back into it."""
    for sp in spots:
        # Always judge against the neighbourhood the VIDEO described. Using the
        # spot's own area lets a previous wrong match vouch for itself.
        clue = sp.get("near") or area or sp.get("area") or ""
        hit = look_up(sp.get("name", ""), city, country,
                      area or sp.get("area") or "", sp.get("near") or "")
        if (not hit or not hit.get("found")) and clue:
            # the name search failed - ask what is actually there instead
            hit = find_near(sp.get("name", ""), clue, city, country) or hit
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
        sp["agrees_with_video"] = hit.get("agrees_with_video", False)
        sp["why_matched"] = hit.get("why_matched", "")
    return spots
