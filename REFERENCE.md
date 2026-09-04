# The Itinerary Workbench — Everything We Know

The single place to look things up. Every claim here was tested on this machine,
with the date it was checked. If something isn't in here, we haven't proved it.

Last updated: 3 September 2026

---

## 1. What the tool does today

You give it a TikTok — paste a link, drop a video file, or pick one from your
computer. It gives you back an organised trip.

**Step by step, what happens to a video:**

1. **Downloads it.** Videos and photo slideshows both. Also grabs the caption,
   who posted it, the date, views, likes, comments, the song and the hashtags.
2. **Listens to it.** On your Mac. About 15 seconds for a 2-minute video.
3. **Reads the screen.** Restaurant names, signs and captions burned into the
   video, using a vision model.
4. **Works out what it is.** A readable title, what the video is for, why it's
   worth keeping, a category, where it is, the places it names, and practical tips.
5. **Checks every place against a real map.** Confirms it exists, fixes the
   spelling, and gets a street address.
6. **Files it under its city**, sorted into Sights / Eats / Activities / Drinks,
   with Shopping and Stays appearing only when a city has some.

Roughly 90 seconds a video end to end.

**What you see:** each city on its own page. Every place shows what kind it is,
a one-line description, a street address, an "open in maps" link, and a button
to watch the video that recommended it — starting a few seconds before it's
mentioned. A place recommended in two videos says so.

---

## 2. What it can't do yet

- **Only on this Mac.** Not on a phone, which is where it would actually be used.
- **Lists, not days.** No ordering, no "these three are on the same street".
- **You can't edit anything.** No fixing a name, deleting a wrong place, adding
  your own, or crossing things off.
- **TikTok only.** Not Instagram, YouTube, or a link a friend texts you.
- **No backup.** Your saved trips live in one folder on one machine.
- **Slideshows can't be watched in the app** — they link out to TikTok instead.
- **Timestamps only on new videos.** Anything labelled before 3 Sep 2026 jumps
  to the start of the video rather than the moment a place is mentioned.

---

## 3. The pieces, and why each one

| Job | What does it | Why this one |
|---|---|---|
| Download videos | yt-dlp | Free, no account, handles 1800+ sites |
| Download slideshows | gallery-dl | The one that cracked TikTok photo posts |
| Cut audio and frames | ffmpeg (bundled) | No system install needed |
| Listen | faster-whisper, `small`, on this Mac | Free, private, ~30x faster than sending audio away |
| Read the screen | a vision model at OpenRouter | Where the reliable names come from |
| Label it | `nemotron-3-super-120b-a12b` at OpenRouter | Fastest good one we tested |
| Check places exist | OpenStreetMap Nominatim | Free, no key |
| Find places by location | OpenStreetMap Overpass | Free, no key, rescues mangled names |

Nothing here costs money or needs an account except the two API keys.

---

## 4. Things we tested and proved

### TikTok serves silent videos
**Checked 3 Sep 2026.** TikTok offers each video in h264 and in h265
("bytevc1"). Both advertise having sound. **The h265 ones arrive with no audio
track at all.** yt-dlp picks the highest resolution, which was h265, so videos
were going through the whole pipeline mute and being labelled from the caption
alone.

Counted audio streams directly: `bytevc1_540p` → 0, `h264_540p` → 1.

Fix: ask for h264 first. On the video that reported the bug, the transcript went
from **0 characters to 2,811**.

### Listening locally beats sending it away
**Checked 2 Sep 2026.** Same 104-second video:
- NVIDIA's omni model: **150 seconds**, 886 characters
- faster-whisper `small` on this Mac: **4.5 seconds**, 1,299 characters

33x faster, more complete, free, private, and it can't be rate-limited.

### OpenRouter is much faster than NVIDIA for the same work
**Checked 2 Sep 2026.** Identical video, identical labelling model:
- OpenRouter: **47 seconds**
- NVIDIA: **264 seconds**

Same answers — same title, same category, same city. The model wasn't the
difference; the queue was.

### Bigger listening models: medium helps, large is worse
**Checked 3 Sep 2026**, on the Rome video's Italian names:

| Model | Time | "Armando al Pantheon" heard as | "Matricianella" heard as |
|---|---|---|---|
| `small` | 15s | "Gora Armando" | "the Matricanella" |
| `medium` | 46s | "Armando again" | "Amatricianella" |
| `large-v3` | 58s | *dropped half the video* | *dropped half the video* |

`large-v3` returned **700 characters where `small` returned 1,276**, with no
punctuation or capitals. On this machine it is a downgrade, not an upgrade.

`medium` is a genuine improvement at about +29 seconds a video.

---

## 5. Dead ends — don't spend time here again

**Seeding the transcriber with context does nothing.** Tried feeding it the
caption, the on-screen text, and both. Identical results to feeding it nothing.
*(An earlier version of this test appeared to work — but it had the actual
restaurant names in the prompt, so it was just reading back the answer.)*

**NVIDIA's speech-to-text models can't be reached with our key.** Their catalogue
lists 9 of them (Parakeet, Canary) and they would be better than what we use.
Tested five different addresses — all refused. They're for people running their
own GPU.

**These models are listed but dead on our NVIDIA account:**
- `nvidia/llama-3.1-nemotron-70b-instruct` — Not Found
- `nvidia/nemotron-nano-3-30b-a3b` — Not Found
- `deepseek-ai/deepseek-v4-flash-0731` — never answers

Being in a catalogue does not mean it works. Test before trusting.

**On build.nvidia.com, use the "Free Endpoint" filter.** Only 39 of the 98
models are callable with a free key; the rest are downloads for people with
their own hardware.

---

## 6. The map: what it can and can't do

**Nominatim (search by name) does exact text matching, not fuzzy.**
- "Matricanella" (one letter wrong) → **nothing at all**
- "Armando" (a real name, too short) → a butcher, a bridge, and a farm

**It speaks the local language.** It says *Roma* and *Italia*, not Rome and
Italy. An early version compared these strictly and rejected every correct
result.

**Overpass (search by location) is what rescues a mangled name.** Ask what is
actually near the landmark the video mentioned, then find our name in that list:

| We heard | It found |
|---|---|
| "Gora Armando" | Armando al Pantheon, 31 Salita de' Crescenzi |
| "Matricanella" | La Matricianella, 4 Via del Leone |
| "Fortunato" | Da Fortunato, 55 Via del Pantheon |
| "La Pietra" | *correctly rejected — not a real place* |

**The principle:** the video decides *which* place is meant. The map decides
*how it's spelled and where it is*. Neither is enough alone.

**Six guards had to be added, each after a real failure:**
1. Reject non-venues — "La Terra" first matched a footpath and a bus stop
2. Speak local — Roma/Italia vs Rome/Italy
3. Match the name — "La Terra" then matched "ESA Centre for Earth Observation"
4. Rank by neighbourhood — "Fortunato" was confirmed 5km from the Pantheon
5. Whole words only — "aT" matched inside "fortun**at**o" and "m**at**ricanella"
6. Judge extra words against the landmark — "Armando al Pantheon" adds
   *Pantheon*, which is the landmark we searched near, so it corroborates.
   "Antics Osteria Di Pietra" adds *Antics*, which corroborates nothing.

Rate limit: one request a second. Every lookup is cached to disk.

---

## 7. Keys, limits and what they cost

Both keys live in `.env`, which is never committed to GitHub.

**OpenRouter (what it uses by default)**
- **50 free requests a day.** Each video costs 2 → about **25 videos a day**.
- Adding $10 of credit raises it to 1,000 a day → about 500 videos.
- Resets daily at 5 PM.

**NVIDIA (the automatic backup)**
- Used on its own when OpenRouter runs dry. It says so on screen when it switches.
- **It is the weaker labeller.** On the same video it produced the title and
  tips but found no places, where OpenRouter found four. It keeps you working,
  not working equally well.

**Models that work, checked 2–3 Sep 2026**
- Labelling: `nemotron-3-super-120b-a12b`, then `gpt-oss-120b`, then
  `nemotron-3.5-lightning-30b-a3b`
- Reading the screen: `google/gemma-4-31b-it:free`, `gemma-4-26b-a4b-it:free`,
  `minimax/minimax-m3:free`, `thinkingmachines/inkling:free`

---

## 8. How it does on real videos

| City | Places confirmed on the map |
|---|---|
| San Francisco | 8 of 8 |
| London | 5 of 6 |
| Rome | 2 of 6 *(4 of 6 recoverable with the location-first search)* |

**Why San Francisco does best:** clear English audio, names spoken plainly, and
a long caption. **Why Rome does worst:** Italian restaurant names spoken by a
native speaker inside English sentences. The names arrive mangled, and
everything downstream inherits that.

---

## 9. Running it

Double-click **start.command**. A black window opens — leave it alone. The site
opens by itself at `127.0.0.1:8000`. Close the window to stop it.

Your saved videos live in the **library** folder, one folder per post, as normal
files you can open in Finder.

**Useful buttons:** *Label it* redoes a single video. There is also a re-check
that re-runs only the map step over everything saved — that takes about 13
seconds, where relabelling everything takes minutes.

---

## 10. Rules we hold to

1. **Nothing invented.** If the evidence didn't say it, it doesn't go in. A place
   the map can't confirm is shown dimmed and marked, never quietly dropped and
   never given a made-up address.
2. **Say when we don't know.** "Not on the map" and "check spelling" are honest
   answers. A confident wrong address is worse than no address.
3. **Never show our workings to the user.** Descriptions describe the place, not
   where we read about it.
4. **Zero setup.** Paste, and it does the rest.
