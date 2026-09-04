"""
TikTok -> Itinerary : the local workbench.

Run it, open the page, paste a link or drop a file.
Everything it grabs is saved in the `library` folder, one folder per post.
"""
import json, os, re, shutil, subprocess, threading, time, mimetypes
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import brain
import mapcheck
import trips

ROOT = Path(__file__).parent.resolve()
LIB = ROOT / "library"
BIN = ROOT / ".venv" / "bin"
LIB.mkdir(exist_ok=True)

YTDLP = str(BIN / "yt-dlp")
GALLERYDL = str(BIN / "gallery-dl")


def ffmpeg_path() -> str:
    """Our ffmpeg lives inside the project, not on the system path. yt-dlp needs
    to be told where it is - without it, it cannot join TikTok's separate video
    and audio streams and quietly hands back a silent video."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return ""

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".opus"}

app = FastAPI(title="TikTok Itinerary Workbench")

# Labelling runs in the background so the page never sits there frozen.
JOBS: Dict[str, Dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def set_job(item_id: str, **kw):
    with JOBS_LOCK:
        JOBS.setdefault(item_id, {}).update(kw)


def start_labelling(item_id: str):
    d = LIB / item_id
    set_job(item_id, state="working", step="Getting started", error="")

    def work():
        try:
            rec = json.loads((d / "record.json").read_text(encoding="utf-8"))
            rec["labels"] = brain.analyze(
                d, rec, on_step=lambda msg: set_job(item_id, step=msg))
            rec.pop("label_error", None)
            (d / "record.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
            set_job(item_id, state="done", step="", error="")
        except brain.BrainError as e:
            set_job(item_id, state="error", step="", error=str(e))
        except Exception as e:  # noqa: BLE001
            set_job(item_id, state="error", step="", error=f"Labelling hit a snag: {e}")

    threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------- helpers

def run(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 240):
    """Run a command, never explode. Return (ok, combined output)."""
    try:
        p = subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return False, "Timed out — the site took too long to answer."
    except Exception as e:  # noqa: BLE001
        return False, f"Could not run the downloader: {e}"


def new_item_dir() -> Path:
    d = LIB / f"{int(time.time() * 1000)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def classify(p: Path) -> Optional[str]:
    e = p.suffix.lower()
    if e in IMAGE_EXT:
        return "image"
    if e in VIDEO_EXT:
        return "video"
    if e in AUDIO_EXT:
        return "audio"
    return None


def collect_media(d: Path) -> List[Dict[str, Any]]:
    """Everything downloadable in the folder, sorted so slideshows stay in order."""
    out = []
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        kind = classify(p)
        if not kind:
            continue
        out.append({
            "kind": kind,
            "name": p.name,
            "url": "/files/" + str(p.relative_to(LIB)).replace(os.sep, "/"),
            "size": p.stat().st_size,
        })
    order = {"video": 0, "image": 1, "audio": 2}
    out.sort(key=lambda m: (order.get(m["kind"], 9), m["name"]))
    return out


def first(d: Dict[str, Any], keys: List[str], default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def read_sidecar_json(d: Path) -> Dict[str, Any]:
    """yt-dlp writes .info.json; gallery-dl writes <file>.json. Take the biggest."""
    best, best_size = {}, -1
    for p in d.rglob("*.json"):
        if p.name == "record.json":
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict) and len(data) > best_size:
            best, best_size = data, len(data)
    return best


def normalize(meta: Dict[str, Any], source_url: str, kind_hint: str) -> Dict[str, Any]:
    """Squash yt-dlp / gallery-dl metadata into one shape the page understands."""
    caption = first(meta, ["description", "desc", "title", "content"], "") or ""
    title = first(meta, ["title", "desc", "description"], "") or ""
    if title and len(title) > 120:
        title = title[:117] + "..."

    author = first(meta, ["uploader", "channel", "creator", "artist", "user"], "")
    if isinstance(author, dict):
        author = first(author, ["nickname", "unique_id", "name", "id"], "")
    handle = first(meta, ["uploader_id", "channel_id", "author"], "")
    if isinstance(handle, dict):
        handle = first(handle, ["unique_id", "id", "name"], "")

    date = first(meta, ["upload_date", "date", "create_time", "timestamp"], "")
    if isinstance(date, str) and re.fullmatch(r"\d{8}", date):
        date = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    elif isinstance(date, (int, float)):
        try:
            date = time.strftime("%Y-%m-%d", time.localtime(float(date)))
        except Exception:  # noqa: BLE001
            date = ""
    elif isinstance(date, str) and len(date) > 10:
        date = date[:10]

    hashtags = re.findall(r"#([A-Za-z0-9_]+)", caption)

    return {
        "kind": kind_hint,
        "source_url": source_url,
        "title": str(title),
        "caption": str(caption),
        "author": str(author or ""),
        "handle": str(handle or ""),
        "date": str(date or ""),
        "duration": first(meta, ["duration"], None),
        "views": first(meta, ["view_count", "play_count"], None),
        "likes": first(meta, ["like_count", "digg_count"], None),
        "comments": first(meta, ["comment_count"], None),
        "shares": first(meta, ["repost_count", "share_count"], None),
        "music": str(first(meta, ["track", "music", "album"], "") or ""),
        "hashtags": hashtags,
        "field_count": len(meta),
    }


# ---------------------------------------------------------------- the grab

def grab_link(url: str, d: Path) -> Dict[str, Any]:
    log = []
    is_photo = "/photo/" in url

    def try_gallerydl():
        ok, out = run([GALLERYDL, "-D", str(d), "--write-metadata", url])
        log.append(("gallery-dl (photos)", ok, out[-700:]))
        return ok and bool(collect_media(d))

    def try_ytdlp():
        cmd = [YTDLP, "-o", str(d / "%(id)s.%(ext)s"),
               "--write-info-json", "--write-thumbnail",
               "--no-warnings", "--no-playlist",
               # TikTok's h265 ("bytevc1") copies advertise audio but arrive
               # silent. The h264 ones really do carry sound, so ask for those
               # first and only fall back if none exist.
               "-f", ("b[vcodec^=h264]/b[vcodec^=avc]/"
                      "bv*[vcodec^=h264]+ba/bv*+ba/b"),
               "--merge-output-format", "mp4"]
        ff = ffmpeg_path()
        if ff:
            cmd += ["--ffmpeg-location", ff]
        ok, out = run(cmd + [url])
        log.append(("yt-dlp (video)", ok, out[-700:]))
        return ok and bool(collect_media(d))

    attempts = [try_gallerydl, try_ytdlp] if is_photo else [try_ytdlp, try_gallerydl]
    got = False
    for fn in attempts:
        if fn():
            got = True
            break

    media = collect_media(d)
    if not got and not media:
        why = "\n".join(f"[{n}] {o.strip()}" for n, _, o in log)
        raise HTTPException(status_code=422, detail=friendly_error(why))

    meta = read_sidecar_json(d)
    kind = "slideshow" if not any(m["kind"] == "video" for m in media) else "video"
    rec = normalize(meta, url, kind)
    rec["media"] = media
    return rec


def friendly_error(raw: str) -> str:
    r = raw.lower()
    if "ip address is blocked" in r or "blocked from accessing" in r:
        return ("TikTok wouldn't hand this one over right now. Either the post is "
                "private/deleted, or TikTok is temporarily saying no to this computer. "
                "Wait a minute and try again, or check the link is right.")
    if "unsupported url" in r or "no suitable extractor" in r:
        return "That doesn't look like a link this can open yet. TikTok links work today."
    if "video unavailable" in r or "404" in r or "not found" in r:
        return "That post seems to be gone, private, or the link has a typo."
    if "timed out" in r:
        return "It took too long to answer. Try again."
    return "Couldn't get this one. Details:\n\n" + raw[-600:]


def grab_upload(f: UploadFile, d: Path) -> Dict[str, Any]:
    name = os.path.basename(f.filename or "upload")
    name = re.sub(r"[^A-Za-z0-9._ -]", "_", name) or "upload"
    dest = d / name
    with dest.open("wb") as w:
        shutil.copyfileobj(f.file, w)
    if not classify(dest):
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422,
                            detail="That file isn't a video, photo, or sound file.")
    media = collect_media(d)
    kind = "video" if any(m["kind"] == "video" for m in media) else "slideshow"
    rec = normalize({}, "", kind)
    rec.update({"title": name, "author": "You uploaded this", "media": media,
                "date": time.strftime("%Y-%m-%d")})
    return rec


# ---------------------------------------------------------------- routes

@app.post("/api/add")
async def add(url: Optional[str] = Form(None), file: Optional[UploadFile] = File(None)):
    url = (url or "").strip()
    if not url and file is None:
        raise HTTPException(status_code=400, detail="Give me a link or a file.")
    d = new_item_dir()
    try:
        rec = grab_link(url, d) if url else grab_upload(file, d)
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Something broke: {e}")

    rec["id"] = d.name
    rec["added_at"] = time.strftime("%Y-%m-%d %H:%M")
    (d / "record.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")

    start_labelling(d.name)   # runs in the background; the page keeps moving
    rec["job"] = {"state": "working", "step": "Getting started"}
    return rec


@app.post("/api/analyze/{item_id}")
def analyze_one(item_id: str):
    if not re.fullmatch(r"\d+", item_id):
        raise HTTPException(status_code=400, detail="bad id")
    d = LIB / item_id
    rec_file = d / "record.json"
    if not rec_file.exists():
        raise HTTPException(status_code=404, detail="That item isn't here any more.")
    start_labelling(item_id)
    return {"ok": True, "job": {"state": "working", "step": "Getting started"}}


@app.post("/api/recheck-map")
def recheck_map():
    """Re-run the map check on everything already saved, without relabelling.
    Labelling is slow and varies run to run; the map check is neither."""
    checked = found = 0
    for d in sorted(LIB.iterdir()):
        f = d / "record.json"
        if not d.is_dir() or not f.exists():
            continue
        rec = json.loads(f.read_text(encoding="utf-8"))
        L = rec.get("labels") or {}
        if not L.get("spots"):
            continue
        place = L.get("place") or {}
        L["spots"] = mapcheck.verify_spots(L["spots"], str(place.get("city") or ""),
                                           str(place.get("country") or ""),
                                           str(place.get("area") or ""))
        L["on_map_count"] = sum(1 for x in L["spots"] if x.get("on_map"))
        checked += len(L["spots"])
        found += L["on_map_count"]
        f.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    return {"checked": checked, "found": found}


@app.get("/api/trips")
def get_trips():
    return trips.build(LIB)


@app.get("/api/key-status")
def key_status():
    try:
        brain.get_key()
        return {"ok": True}
    except brain.BrainError as e:
        return {"ok": False, "message": str(e)}


@app.get("/api/items")
def items():
    out = []
    for d in sorted(LIB.iterdir(), reverse=True):
        rec_file = d / "record.json"
        if d.is_dir() and rec_file.exists():
            try:
                rec = json.loads(rec_file.read_text(encoding="utf-8"))
                rec["media"] = collect_media(d)  # stay honest about what's on disk
                with JOBS_LOCK:
                    job = JOBS.get(rec.get("id", d.name))
                if job:
                    rec["job"] = dict(job)
                out.append(rec)
            except Exception:  # noqa: BLE001
                continue
    return out


@app.delete("/api/items/{item_id}")
def delete(item_id: str):
    if not re.fullmatch(r"\d+", item_id):
        raise HTTPException(status_code=400, detail="bad id")
    shutil.rmtree(LIB / item_id, ignore_errors=True)
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home():
    return (ROOT / "web" / "index.html").read_text(encoding="utf-8")


app.mount("/files", StaticFiles(directory=str(LIB)), name="files")
