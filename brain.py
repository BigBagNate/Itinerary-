"""
The brain: turn a downloaded post into a labelled, readable entry.

Two passes, both on NVIDIA's free developer models:
  1. LISTEN + READ  - an omni model hears the talking and reads the words
                      burned onto the screen. This is where the real content is.
  2. LABEL          - a text model turns that raw evidence into the fields
                      Nathan asked for: title, why, purpose, category, place.
"""
import base64, json, os, re, subprocess, tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

import mapcheck

# Two places we can send work. Whichever has a key wins; OpenRouter first if both.
PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter",
        "base": "https://openrouter.ai/api/v1/chat/completions",
        "env": "OPENROUTER_API_KEY",
        "key_prefix": "sk-or-",
        # reads words off the screen - all free, checked live in the catalogue
        "vision": [
            "google/gemma-4-31b-it:free",
            "google/gemma-4-26b-a4b-it:free",
            "minimax/minimax-m3:free",
            "thinkingmachines/inkling:free",
        ],
        # turns the evidence into the labels
        "label_models": [
            "nvidia/nemotron-3-super-120b-a12b:free",
            "z-ai/glm-5.2:free",
            "minimax/minimax-m2.7:free",
            "nvidia/nemotron-3-ultra-550b-a55b:free",
        ],
    },
    "nvidia": {
        "label": "NVIDIA",
        "base": "https://integrate.api.nvidia.com/v1/chat/completions",
        "env": "NVIDIA_API_KEY",
        "key_prefix": "nvapi-",
        "vision": ["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"],
        "label_models": [
            "nvidia/nemotron-3-super-120b-a12b",
            "openai/gpt-oss-120b",
            "nvidia/nemotron-3.5-lightning-30b-a3b",
        ],
    },
}

# Set PROVIDER=nvidia or PROVIDER=openrouter in .env to force one.
PREFERENCE = ["openrouter", "nvidia"]

CATEGORIES = ["food", "drinks", "sights", "activities", "shopping", "stay", "mixed", "other"]

MAX_AUDIO_SECONDS = 240      # keep the upload sane
MAX_FRAMES = 5               # stills we send along
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".aac", ".opus"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class BrainError(Exception):
    pass


# ------------------------------------------------------------------ key

def read_env() -> Dict[str, str]:
    out = dict(os.environ)
    envf = Path(__file__).parent / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return out


def pick_provider() -> Dict[str, Any]:
    """Whichever provider has a key. If both, whatever PROVIDER says, else OpenRouter."""
    env = read_env()
    forced = (env.get("PROVIDER") or "").strip().lower()
    order = [forced] if forced in PROVIDERS else PREFERENCE
    for name in order:
        cfg = PROVIDERS[name]
        key = (env.get(cfg["env"]) or "").strip()
        if key:
            return {"name": name, "key": key, **cfg}
    raise BrainError(
        "No key found. Put one in the .env file in this folder, on its own line:\n\n"
        "OPENROUTER_API_KEY=sk-or-your-key-here\n"
        "  or\n"
        "NVIDIA_API_KEY=nvapi-your-key-here"
    )


def providers_in_order() -> List[Dict[str, Any]]:
    """Every provider we have a key for, best first. Used to fail over when one
    runs out of free requests for the day."""
    env = read_env()
    forced = (env.get("PROVIDER") or "").strip().lower()
    order = ([forced] + [n for n in PREFERENCE if n != forced]) if forced in PROVIDERS \
        else list(PREFERENCE)
    out = []
    for name in order:
        cfg = PROVIDERS[name]
        key = (env.get(cfg["env"]) or "").strip()
        if key:
            out.append({"name": name, "key": key, **cfg})
    if not out:
        raise BrainError(
            "No key found. Put one in the .env file in this folder, on its own line:\n\n"
            "OPENROUTER_API_KEY=sk-or-your-key-here\n"
            "  or\n"
            "NVIDIA_API_KEY=nvapi-your-key-here"
        )
    return out


def out_of_requests(e: Exception) -> bool:
    """Is this 'you have used your free allowance', rather than a real fault?"""
    m = str(e).lower()
    return any(x in m for x in (
        "rate limit", "rate-limited", "free tier is busy", "per-day", "per day",
        "quota", "too many requests", "429", "resourceexhausted", "busy"))


def get_key() -> str:          # kept so the key-status check still works
    return providers_in_order()[0]["key"]


# ------------------------------------------------------------------ ffmpeg

def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _run(cmd: List[str], timeout: int = 180) -> bool:
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def prepare_audio(d: Path, tmp: Path) -> Optional[Path]:
    """One small mono mp3, whether the post was a video or a slideshow."""
    src = None
    for p in sorted(d.rglob("*")):
        if p.is_file() and p.suffix.lower() in VIDEO_EXT:
            src = p
            break
    if src is None:
        for p in sorted(d.rglob("*")):
            if p.is_file() and p.suffix.lower() in AUDIO_EXT:
                src = p
                break
    if src is None:
        return None
    out = tmp / "audio.mp3"
    ok = _run([ffmpeg_exe(), "-y", "-i", str(src), "-vn",
               "-t", str(MAX_AUDIO_SECONDS), "-ac", "1", "-ar", "16000",
               "-b:a", "48k", str(out)])
    return out if ok and out.exists() and out.stat().st_size > 0 else None


def prepare_frames(d: Path, tmp: Path) -> List[Path]:
    """Stills to read on-screen text from: slideshow photos, or frames from a video."""
    photos = [p for p in sorted(d.rglob("*"))
              if p.is_file() and p.suffix.lower() in IMAGE_EXT and p.stat().st_size > 20_000]
    out: List[Path] = []
    if photos:
        for i, p in enumerate(photos[:MAX_FRAMES]):
            dst = tmp / f"f{i:02d}.jpg"
            if _run([ffmpeg_exe(), "-y", "-i", str(p),
                     "-vf", "scale='min(1024,iw)':-2", "-q:v", "4", str(dst)]):
                out.append(dst)
        return out

    vid = next((p for p in sorted(d.rglob("*"))
                if p.is_file() and p.suffix.lower() in VIDEO_EXT), None)
    if vid is None:
        return []
    # one frame every few seconds, capped
    if _run([ffmpeg_exe(), "-y", "-i", str(vid),
             "-vf", "fps=1/3,scale='min(1024,iw)':-2", "-frames:v", str(MAX_FRAMES),
             "-q:v", "4", str(tmp / "f%02d.jpg")]):
        out = sorted(tmp.glob("f*.jpg"))
    return out[:MAX_FRAMES]


def data_uri(p: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode("ascii")


# ------------------------------------------------------------------ api

def call(model: str, messages: List[Dict[str, Any]], prov: Dict[str, Any],
         max_tokens: int = 2048, temperature: float = 0.2, timeout: int = 300,
         tries: int = 4, json_only: bool = False) -> str:
    """The free tier fills up and briefly refuses. Wait and ask again."""
    import time as _t
    wait, last = 6, None
    for attempt in range(tries):
        try:
            return _call_once(model, messages, prov, max_tokens, temperature, timeout, json_only)
        except BrainError as e:
            last = e
            msg = str(e)
            fatal = ("isn't valid" in msg or "Not Found" in msg or "404" in msg
                     or "no endpoints" in msg.lower())
            if fatal or attempt == tries - 1:
                raise
            _t.sleep(wait)
            wait = min(wait * 2, 45)
        except requests.exceptions.RequestException as e:
            last = BrainError(f"Lost the connection to {prov['label']}: {e}")
            if attempt == tries - 1:
                raise last
            _t.sleep(wait)
            wait = min(wait * 2, 45)
    raise last or BrainError(f"Gave up talking to {prov['label']}.")


def _call_once(model: str, messages: List[Dict[str, Any]], prov: Dict[str, Any],
               max_tokens: int, temperature: float, timeout: int,
               json_only: bool = False) -> str:
    headers = {"Authorization": f"Bearer {prov['key']}", "Content-Type": "application/json",
               "Accept": "application/json"}
    if prov["name"] == "openrouter":
        headers["HTTP-Referer"] = "http://127.0.0.1:8000"
        headers["X-Title"] = "Itinerary Workbench"
    r = requests.post(
        prov["base"],
        headers=headers,
        json=_body(model, messages, max_tokens, temperature, json_only),
        timeout=timeout,
    )
    if r.status_code in (401, 403):
        raise BrainError(f"{prov['label']} says that key isn't valid. "
                         "Check it was copied in full.")
    if r.status_code in (429, 503):
        raise BrainError(f"{prov['label']}'s free tier is busy or rate-limited right now.")
    if r.status_code == 400 and json_only and "response_format" in r.text:
        return _call_once(model, messages, prov, max_tokens, temperature, timeout, False)
    if r.status_code >= 400:
        raise BrainError(f"{prov['label']} refused ({r.status_code}): {r.text[:300]}")
    body = r.json()
    try:
        return body["choices"][0]["message"]["content"] or ""
    except Exception:  # noqa: BLE001
        raise BrainError(f"Unexpected answer shape: {json.dumps(body)[:300]}")


def _body(model, messages, max_tokens, temperature, json_only):
    b = {"model": model, "messages": messages, "max_tokens": max_tokens,
         "temperature": temperature, "stream": False}
    if json_only:
        b["response_format"] = {"type": "json_object"}
    return b


def strip_think(s: str) -> str:
    s = re.sub(r"<think>.*?</think>", "", s, flags=re.S | re.I)
    return re.sub(r"</?think>", "", s, flags=re.I).strip()


def _repair(s: str) -> Optional[Dict[str, Any]]:
    """Salvage an answer that got cut off mid-thought.

    Models sometimes stop partway through the JSON, or open with a stray brace.
    Rather than throw the whole answer away, close what is still open and keep
    the fields that did arrive."""
    start = s.find("{")
    if start < 0:
        return None
    s = s[start:]
    while s.startswith("{") and s[1:].lstrip().startswith("{"):
        s = s[1:].lstrip()                     # a doubled opening brace

    depth, in_str, esc, stack, last_good = 0, False, False, [], None
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if stack:
                stack.pop()
            if not stack:
                last_good = i               # a complete object ended here
    if last_good is not None:
        try:
            return json.loads(s[:last_good + 1])
        except Exception:  # noqa: BLE001
            pass
    if not stack:
        return None

    # cut back to the last thing that finished cleanly, then close what is open
    body = s
    if in_str:
        body = body[:body.rfind('"')]
        body = body[:body.rfind('"')] if body.count('"') % 2 else body
    cut = max(body.rfind("}"), body.rfind("]"), body.rfind('"'))
    if cut > 0:
        body = body[:cut + 1]
    for closer in reversed(stack):
        body += closer
    for attempt in (body, re.sub(r",\s*([}\]])", r"\1", body)):
        try:
            return json.loads(attempt)
        except Exception:  # noqa: BLE001
            continue
    return None


def parse_json(s: str) -> Dict[str, Any]:
    s = strip_think(s)
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    try:
        return json.loads(s)
    except Exception:  # noqa: BLE001
        pass
    found, depth, start = [], 0, -1
    for i, ch in enumerate(s):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    found.append(json.loads(s[start:i + 1]))
                except Exception:  # noqa: BLE001
                    pass
                start = -1
    if found:   # the real answer is the richest object, not a stray fragment
        return max(found, key=len)
    salvaged = _repair(s)
    if salvaged:
        return salvaged
    raise BrainError("The model didn't answer in a readable form. Try again.")


# ------------------------------------------------------------------ pass 1

# ------------------------------------------------------------------ ears (local)

_WHISPER = None


def whisper():
    """Loaded once, then reused. Runs on this Mac - free, private, ~30x faster
    than sending the audio away."""
    global _WHISPER
    if _WHISPER is None:
        from faster_whisper import WhisperModel
        _WHISPER = WhisperModel("small", device="cpu", compute_type="int8")
    return _WHISPER


def transcribe_locally(audio: Path) -> str:
    segs, _info = whisper().transcribe(str(audio), beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segs).strip()


LISTEN_PROMPT = """You are given a short social video post (audio and/or still frames from it).

Do exactly two things and nothing else:

1. TRANSCRIPT - write out everything spoken, word for word. If there is no speech,
   write exactly: (no speech)
2. ON-SCREEN TEXT - write out every word visible in the frames: captions burned into
   the video, titles, signs, restaurant names, prices, addresses. One item per line,
   in the order they appear. If there is none, write exactly: (no on-screen text)

Copy what is actually there. Do not summarise, translate, correct, or invent anything.

Answer in exactly this shape:

TRANSCRIPT:
<the words>

ON-SCREEN TEXT:
<the words>"""


SCREEN_PROMPT = """These are frames from a short travel/food video.

Write out every word visible in them: captions burned into the video, titles,
restaurant and bar names, street signs, prices, addresses, menu items.

One item per line, in the order they appear. Copy exactly what is written - do not
translate, correct, summarise or invent. If there is no readable text at all, reply
with exactly: (no on-screen text)"""


def listen_and_read(d: Path, prov: Dict[str, Any]) -> Dict[str, Any]:
    """Ears run here on the Mac. Eyes run on NVIDIA. Either can fail without
    sinking the whole thing - we label with whatever evidence we got."""
    transcript, on_screen, notes, used = "", "", [], {}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        audio = prepare_audio(d, tmp)
        frames = prepare_frames(d, tmp)

        if audio:
            try:
                transcript = transcribe_locally(audio)
            except Exception as e:  # noqa: BLE001
                notes.append(f"Could not listen to the audio: {e}")
        else:
            notes.append("This video came without an audio track, so there was "
                         "nothing to listen to - the labels come from the caption "
                         "and the text on screen.")

        if frames:
            content: List[Dict[str, Any]] = [{"type": "text", "text": SCREEN_PROMPT}]
            for f in frames:
                content.append({"type": "image_url",
                                "image_url": {"url": data_uri(f, "image/jpeg")}})
            last_err = None
            for vm in prov["vision"]:      # try each until one answers
                try:
                    raw = strip_think(call(vm, [{"role": "user", "content": content}],
                                           prov, max_tokens=1200, temperature=0.0,
                                           timeout=180, tries=2))
                    if raw.strip().lower() not in ("(no on-screen text)", "(none)", ""):
                        on_screen = raw.strip()
                    used["vision"] = vm
                    last_err = None
                    break
                except BrainError as e:
                    last_err = e
            if last_err:
                notes.append(f"Could not read the screen text: {last_err}")

    return {"transcript": transcript, "on_screen": on_screen,
            "audio_used": bool(transcript), "frames_used": len(frames),
            "notes": notes, "used": used}


# ------------------------------------------------------------------ pass 2

LABEL_PROMPT = """Output a single JSON object and NOTHING else. No explanation, no reasoning, no
working-out, no markdown fence. Exactly one opening brace at the very start and
one closing brace at the very end. Keep every field short - long answers get cut
off before you finish.

You are labelling a saved social-media post so a traveller can scan it later.

Use ONLY the evidence below. If the evidence does not say something, leave that field
empty or use "unknown". Never invent a place, a city, or a detail.

Answer with ONE JSON object and nothing else:

{{
  "title": "a short readable title, max 9 words, what this post actually is",
  "purpose": "one sentence: what this video sets out to do for the viewer",
  "why_saved": "one sentence: what someone gets out of keeping this",
  "category": "exactly one of: {cats}",
  "category_reason": "a few words on why that category",
  "other_categories": ["any others that also apply, from the same list"],
  "place": {{
    "city": "city if stated or clearly implied, else unknown",
    "area": "neighbourhood or region if stated, else empty",
    "country": "country if stated or clearly implied, else unknown",
    "how_we_know": "the exact words in the evidence that told you, or 'not stated'"
  }},
  "spots": [
    {{
      "name": "the venue's actual name, spelled as well as the evidence allows",
      "kind": "restaurant / bar / cafe / museum / park / shop / hotel / landmark / other",
      "bucket": "exactly one of: sights, eats, activities, drinks, shopping, stays",
      "note": "a few words describing the place itself - what it is known for, what to
               order, where it is. Write it for a traveller reading a guidebook.
               NEVER describe where you found the information: no 'mentioned as',
               no 'shown on screen', no 'heard as', no 'the video says'. If you have
               nothing to say about the place itself, leave this empty.",
      "source": "on-screen if the name was written on screen, spoken if only said out loud, caption if only in the caption",
      "sure": "high if the name was written on screen or spelled clearly, medium if heard clearly, low if you are guessing at the spelling"
    }}
  ],
  "tips": [
    {{
      "tip": "one piece of practical advice, in one short sentence",
      "topic": "exactly one of: getting around, timing, money, local know-how, etiquette, packing, safety, other",
      "scope": "city if it only makes sense in this city, anywhere if it is true for any trip"
    }}
  ],
  "confidence": "high, medium or low - how sure you are overall"
}}

Which bucket a spot goes in:
- sights     : landmarks, viewpoints, churches, museums, monuments, squares - you go and LOOK
- eats       : restaurants, trattorias, cafes, bakeries, street food, markets you eat at
- drinks     : bars, wine bars, cocktail places, pubs, clubs, coffee-as-the-point
- activities : things you go and DO - tours, hikes, classes, boats, shows, day trips
- shopping   : shops, boutiques, vintage, markets you buy things at
- stays      : hotels, hostels, apartments - where you sleep

Rules for "tips":
- A tip is useful advice that is NOT a place: which train from the airport, what to book
  ahead, how much to tip, what to pack, when to avoid crowds, how to dress.
- Only include advice the video actually gives. If it gives none, return an empty list.
- "scope" decides whether the tip is safe to repeat on a different trip:
  - "city" if it depends on this place at all - a named train or pass, a local custom,
    a rule about how things are done here, anything a local would say about THIS city.
    A custom is city-specific even when it sounds like general advice: "you can refuse
    to pay for bad food" is a local norm, not a universal right.
  - "anywhere" ONLY if it would be true and safe in any country - bring a charger,
    wear comfortable shoes, tell your bank before you travel, book popular things early.
  - When you are unsure, choose "city". Wrongly promising a local custom works
    everywhere is worse than filing a general tip under one city.

Pick the tip's topic from this list. Read the definitions - do not guess:
- getting around  : trains, metro, buses, taxis, airport transfers, walking, driving,
                    passes and tickets for transport
- timing          : when to go, what to book ahead and how far, opening hours, best time
                    of day, how to avoid crowds and queues
- money           : what things cost, cash vs card, ATMs, tipping amounts, avoiding
                    overcharging, tourist-trap pricing
- local know-how  : how to find the good places and avoid the bad ones - who to ask,
                    what a tourist trap looks like, which streets to skip, how locals
                    actually do it. Most "insider tip" advice belongs here.
- etiquette       : customs and manners - how to greet, how to dress, what is rude,
                    ordering conventions, useful phrases, language
- packing         : what to bring or wear - shoes, adapters, chargers, clothing
- safety          : scams, pickpockets, areas to avoid, health
- other           : LAST RESORT ONLY. If a tip fits any topic above even loosely, use
                    that one instead. Do not use "other" just because it is convenient.

Write every "note" as if it were printed in a guidebook. "Family-run trattoria near
the Pantheon, known for carbonara" is right. "Shown on screen as RISTORANTE AL 34" is
wrong - that describes your own reading process, not the restaurant.

Rules for "spots" - these matter most:
- A spot must be a NAMED place someone could look up. "Armando al Pantheon" is a spot.
  "a restaurant", "the hotel", "RISTORANTE" on its own are NOT spots - leave them out.
- If the same place appears more than once with different spellings, include it ONCE,
  using the best spelling. Names written on screen are more reliable than names heard
  out loud - prefer the written spelling.
- Speech-to-text mangles foreign names. If a name sounds garbled and you cannot tell
  what it is, LEAVE IT OUT. A short honest list beats a long wrong one.
- If the evidence names no specific places at all, return an empty list. That is fine.

Category guide:
- food      : restaurants, cafes, bakeries, street food, anything mainly about eating
- drinks    : bars, cocktails, coffee-as-the-point, wine, nightlife drinking
- sights    : landmarks, views, museums, architecture, things you go and look at
- activities: things you go and DO - hikes, tours, classes, surfing, day trips
- shopping  : markets, boutiques, vintage, souvenirs
- stay      : hotels, hostels, airbnbs, where to sleep
- mixed     : genuinely several of the above with no clear winner
- other     : none of the above

EVIDENCE
--------
Posted by: {author}
Caption: {caption}
Hashtags: {hashtags}
Sound/track: {music}
Post type: {kind}

What is spoken in the video:
{transcript}

Text shown on screen:
{on_screen}
--------

Reply with the JSON object only, starting immediately."""


GENERIC = {
    "restaurant", "restaurants", "ristorante", "ristoranti", "trattoria", "osteria",
    "pizzeria", "gelateria", "enoteca", "hotel", "hostel", "bar", "bars", "cafe",
    "caffe", "coffee", "pub", "club", "museum", "market", "shop", "store", "beach",
    "park", "church", "the hotel", "the bar", "the restaurant", "food", "lunch",
    "dinner", "breakfast", "brunch", "spot", "spots", "place", "places", "here",
    "there", "this place", "unknown", "n/a", "none",
}


BUCKETS = ["sights", "eats", "activities", "drinks", "shopping", "stays"]
TOPICS = ["getting around", "timing", "money", "local know-how", "etiquette",
          "packing", "safety", "other"]

# if the model forgets the bucket, work it out from the kind of place
KIND_TO_BUCKET = {
    "restaurant": "eats", "trattoria": "eats", "osteria": "eats", "pizzeria": "eats",
    "cafe": "eats", "bakery": "eats", "gelateria": "eats", "food": "eats",
    "street food": "eats", "deli": "eats", "food market": "eats",
    "bar": "drinks", "pub": "drinks", "club": "drinks", "wine bar": "drinks",
    "cocktail bar": "drinks", "brewery": "drinks", "winery": "drinks",
    "museum": "sights", "landmark": "sights", "church": "sights", "cathedral": "sights",
    "monument": "sights", "viewpoint": "sights", "square": "sights", "gallery": "sights",
    "park": "sights", "garden": "sights", "castle": "sights", "ruins": "sights",
    "tour": "activities", "hike": "activities", "class": "activities",
    "beach": "activities", "experience": "activities", "activity": "activities",
    "shop": "shopping", "boutique": "shopping", "market": "shopping",
    "store": "shopping", "vintage": "shopping",
    "hotel": "stays", "hostel": "stays", "apartment": "stays", "airbnb": "stays",
}


def bucket_for(spot: Dict[str, str]) -> str:
    b = str(spot.get("bucket") or "").strip().lower()
    if b in BUCKETS:
        return b
    kind = str(spot.get("kind") or "").strip().lower()
    if kind in KIND_TO_BUCKET:
        return KIND_TO_BUCKET[kind]
    for k, v in KIND_TO_BUCKET.items():        # "seafood restaurant" -> eats
        if k in kind:
            return v
    return "sights"


def tidy_tips(raw: Any) -> List[Dict[str, str]]:
    out, seen = [], set()
    if not isinstance(raw, list):
        return out
    for item in raw:
        if isinstance(item, str):
            item = {"tip": item}
        if not isinstance(item, dict):
            continue
        text = str(item.get("tip") or "").strip()
        if len(text) < 8:
            continue
        fp = re.sub(r"[^a-z0-9]+", "", text.lower())[:70]
        if fp in seen:
            continue
        seen.add(fp)
        topic = str(item.get("topic") or "other").strip().lower()
        scope = str(item.get("scope") or "city").strip().lower()
        out.append({
            "tip": text,
            "topic": topic if topic in TOPICS else "other",
            "scope": "anywhere" if scope.startswith("any") else "city",
        })
    return out


PLUMBING = re.compile(
    r"^\s*(?:it\s+is\s+|its\s+)?"
    r"(?:also\s+|only\s+|just\s+)?"
    r"(?:shown|seen|written|displayed|mentioned|named|referenced|listed|heard|said|"
    r"stated|appears?|appeared|noted|described|spelled|spelt)\b"
    r"[^,;.]*?"
    r"(?:\bon\s+screen\b|\bon-screen\b|\bin\s+the\s+(?:video|caption|transcript)\b|"
    r"\bas\b|\bby\s+the\s+(?:speaker|creator)\b)?"
    r"\s*(?:as|:)?\s*",
    re.I)

SOURCE_TALK = re.compile(
    r"\b(?:on[- ]screen|in the video|the video says?|the caption|transcript|"
    r"name heard as|heard as|shown as|spelled as|per the video)\b", re.I)


# a note that only says "we don't know" is worse than no note at all
FILLER = re.compile(
    r"\b(?:not\s+(?:specified|stated|given|mentioned|available|provided|clear|known)"
    r"|no\s+(?:details?|info(?:rmation)?|description)"
    r"|details?\s+unknown|unspecified|unknown|n/?a)\b", re.I)


def is_filler(n: str) -> bool:
    """True when what's left says nothing about the place."""
    if FILLER.search(n):
        # keep it only if there's real content besides the hedge
        rest = FILLER.sub("", n).strip(" .,;:-")
        return len(rest) < 12
    return n.strip(" .,;:-").lower() in {"none", "n/a", "na", "-", "unknown"}


def clean_note(note: str, name: str) -> str:
    """Strip the machine talking about itself. A note should describe the place."""
    n = (note or "").strip()
    if not n:
        return ""
    n = PLUMBING.sub("", n).strip(" ,;:-")
    # drop whole clauses that are only about where we read it
    keep = [c.strip() for c in re.split(r"[;,]\s*", n)
            if c.strip() and not SOURCE_TALK.search(c)]
    n = ", ".join(keep).strip(" ,;:-")
    # "LA TERRA" restated as its own description says nothing
    if not n or n.lower().strip() == name.lower().strip():
        return ""
    if len(n) < 4 or is_filler(n):
        return ""
    return n[0].upper() + n[1:]


def tidy_spots(raw: Any) -> List[Dict[str, str]]:
    """Drop generic words, drop fragments, merge near-duplicates, fix SHOUTING."""
    import difflib

    if not isinstance(raw, list):
        return []
    out: List[Dict[str, str]] = []
    for item in raw:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip(" \t\n\r\"'.,;:-|")
        if not name:
            continue
        low = name.lower().strip()
        if low in GENERIC or len(name) < 3:
            continue
        if not re.search(r"[A-Za-z]{3}", name):        # needs real letters
            continue
        words = [w for w in re.split(r"\s+", low) if w]
        if all(w in GENERIC for w in words):           # every word generic -> not a place
            continue
        if name.isupper() and len(name) > 4:           # RISTORANTE AL 34 -> Ristorante Al 34
            name = name.title()

        # already have something close enough? keep the better-evidenced one.
        dup = None
        for kept in out:
            a, b = name.lower(), kept["name"].lower()
            if a == b or a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() > 0.82:
                dup = kept
                break
        rank = {"high": 3, "medium": 2, "low": 1}
        entry = {
            "name": name,
            "bucket": bucket_for(item),
            "kind": str(item.get("kind") or "").strip().lower(),
            "note": clean_note(str(item.get("note") or ""), name),
            "source": str(item.get("source") or "").strip().lower(),
            "sure": str(item.get("sure") or "medium").strip().lower(),
        }
        if dup is None:
            out.append(entry)
        elif rank.get(entry["sure"], 0) > rank.get(dup["sure"], 0):
            dup.update(entry)                          # better spelling wins
    return out


def label(meta: Dict[str, Any], heard: Dict[str, str], prov: Dict[str, Any]) -> Dict[str, Any]:
    prompt = LABEL_PROMPT.format(
        cats=", ".join(CATEGORIES),
        author=meta.get("author") or "unknown",
        caption=(meta.get("caption") or "(none)")[:6000],
        hashtags=", ".join(meta.get("hashtags") or []) or "(none)",
        music=meta.get("music") or "(none)",
        kind=meta.get("kind") or "unknown",
        transcript=(heard.get("transcript") or "(nothing spoken, or not available)")[:6000],
        on_screen=(heard.get("on_screen") or "(nothing on screen, or not available)")[:4000],
    )
    last = None
    for model in prov["label_models"]:
        try:
            out = call(model, [{"role": "user", "content": prompt}], prov,
                       max_tokens=7000, temperature=0.1, timeout=240, tries=2,
                       json_only=True)
            res = parse_json(out)
            res["labelled_by"] = model
            return res
        except BrainError as e:
            last = e
            if "isn't valid" in str(e):
                raise
    raise last or BrainError("No labelling model would answer.")


# ------------------------------------------------------------------ front door

def analyze(item_dir: Path, meta: Dict[str, Any], on_step=None) -> Dict[str, Any]:
    provs = providers_in_order()
    last = None
    for i, prov in enumerate(provs):
        try:
            return _analyze_with(item_dir, meta, prov, on_step)
        except BrainError as e:
            last = e
            if not out_of_requests(e) or i == len(provs) - 1:
                raise
            nxt = provs[i + 1]["label"]
            if on_step:
                on_step(f"{prov['label']} is out of free requests - switching to {nxt}")
    raise last or BrainError("Could not label this one.")


def _analyze_with(item_dir: Path, meta: Dict[str, Any], prov: Dict[str, Any],
                  on_step=None) -> Dict[str, Any]:
    if on_step:
        on_step(f"Listening to the video and reading the screen ({prov['label']})")
    heard = listen_and_read(item_dir, prov)
    if on_step:
        on_step(f"Working out what it is and where ({prov['label']})")
    result = label(meta, heard, prov)

    cat = str(result.get("category", "other")).lower().strip()
    result["category"] = cat if cat in CATEGORIES else "other"

    raw_spots = result.get("spots") or result.get("mentioned_places") or []
    result["spots"] = tidy_spots(raw_spots)
    result["spots_dropped"] = max(0, len(raw_spots) - len(result["spots"]))
    result.pop("mentioned_places", None)
    result["tips"] = tidy_tips(result.get("tips"))
    result["transcript"] = heard.get("transcript", "")
    result["on_screen"] = heard.get("on_screen", "")
    result["heard_audio"] = heard.get("audio_used", False)
    result["saw_frames"] = heard.get("frames_used", 0)
    place = result.get("place") or {}
    if result["spots"]:
        if on_step:
            on_step("Checking each place against the map")
        try:
            result["spots"] = mapcheck.verify_spots(
                result["spots"], str(place.get("city") or ""),
                str(place.get("country") or ""))
        except Exception as e:  # noqa: BLE001
            result.setdefault("notes", []).append(f"Map check skipped: {e}")
    result["on_map_count"] = sum(1 for x in result["spots"] if x.get("on_map"))

    result["provider"] = prov["label"]
    result["read_by"] = "whisper on this Mac + " + (heard.get("used", {}).get("vision") or "no screen reader")
    result["notes"] = heard.get("notes", [])
    return result
