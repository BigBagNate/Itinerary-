# The Itinerary Workbench — Full Reference

The complete record of what was built, what was tested, what broke, and what we
learned. Every measurement here was run on this machine, with the date it was
taken. If it isn't in here, we haven't proved it.

**Repo:** github.com/BigBagNate/Itinerary-
**Runs at:** `127.0.0.1:8000`
**Last updated:** 3 September 2026

---

## Contents

1. [What we're building](#1-what-were-building)
2. [What the tool does today](#2-what-the-tool-does-today)
3. [How it's put together](#3-how-its-put-together)
4. [The build, in order](#4-the-build-in-order)
5. [Every problem we hit, and the fix](#5-every-problem-we-hit-and-the-fix)
6. [Measurements](#6-measurements)
7. [Dead ends](#7-dead-ends)
8. [The map: what it can and can't do](#8-the-map-what-it-can-and-cant-do)
9. [Keys, limits and costs](#9-keys-limits-and-costs)
10. [How it does on real videos](#10-how-it-does-on-real-videos)
11. [What it still can't do](#11-what-it-still-cant-do)
12. [Running it](#12-running-it)
13. [Rules we hold to](#13-rules-we-hold-to)

---

## 1. What we're building

Recommendations are trapped inside videos. You save a TikTok about a great taco
place, and two weeks later you're standing in that city trying to remember which
video it was in. All the information already exists — it's just locked in a
format you can't use at the moment you need it.

**The promise: a video goes in, a day you can actually live comes out.**

Two ways in: paste a TikTok link, or hand it a video file directly. Both lead to
the same place. The person should never have to think about which one they used.

*(The full vision, including where this grows later, lives in `VISION.md`.)*

---

## 2. What the tool does today

You give it a TikTok. It gives you back an organised trip.

**What happens to a video:**

1. **Downloads it.** Videos and photo slideshows both — plus the caption, who
   posted it, the date, views, likes, comments, the song and the hashtags.
2. **Listens to it.** On your Mac. About 15 seconds for a two-minute video.
3. **Reads the screen.** Restaurant names, signs and captions burned into the
   picture.
4. **Works out what it is.** A readable title, what the video is for, why it's
   worth keeping, a category, where it is, the places it names, and practical tips.
5. **Checks every place against a real map.** Confirms it exists, fixes the
   spelling, gets a street address.
6. **Files it under its city**, sorted into Sights / Eats / Activities / Drinks,
   with Shopping and Stays appearing only when a city has some.

About 90 seconds end to end.

**What you see.** Two tabs: *Trips* and *Everything you've saved*.

Each city gets its own page. Every place shows what kind it is, a one-line
description, a street address, an "open in maps" link, and a button to watch the
video that recommended it — starting a few seconds before it's mentioned. A place
recommended in two videos says so.

Tips are split the way you chose: advice tied to a city sits under that city
("Good to know in Rome"); advice that works on any trip is lifted out once into
"Good to know anywhere". Topics are Local know-how, Getting around, Timing &
booking, Money, Etiquette & language, Packing, Safety.

---

## 3. How it's put together

| File | What it does |
|---|---|
| `app.py` | The web server. Downloads, saves, serves the page, runs labelling in the background. |
| `brain.py` | Listening, reading the screen, labelling, and cleaning up the result. |
| `mapcheck.py` | Checking places against a real map. |
| `trips.py` | Grouping everything into cities and buckets. |
| `web/index.html` | The whole page — no framework, no build step. |
| `start.command` | Double-click to run it. |

| Job | What does it | Why this one |
|---|---|---|
| Download videos | `yt-dlp` | Free, no account, 1800+ sites |
| Download slideshows | `gallery-dl` | The one that cracked TikTok photo posts |
| Cut audio and frames | `ffmpeg` (bundled) | No system install needed |
| Listen | `faster-whisper` **small**, local | Free, private, ~30× faster than sending audio away |
| Read the screen | a vision model at OpenRouter | Where the reliable names come from |
| Label it | `nemotron-3-super-120b-a12b` | Fastest good one we tested |
| Confirm places exist | OpenStreetMap **Nominatim** | Free, no key |
| Find places by location | OpenStreetMap **Overpass** | Free, no key — rescues mangled names |

Nothing here costs money or needs an account except the two API keys.

---

## 4. The build, in order

**Wrote the vision down first.** One file describing what's being built, not how.
It's been the reference point for every decision since.

**Proved we could get the goods out of a TikTok ourselves.** Checked the
open-source options and tested them rather than trusting write-ups. Videos, photo
slideshows, the audio behind a slideshow, and 54 fields of information about each
post — all free, all on this machine, no paid service.

**Built the local page.** Paste a link, drag a video in, or click to choose one.
All three tested working.

**Added the thinking.** Listening to the video, reading the text burned onto the
screen, and turning both into the labels you asked for: a readable title, what
the video is for, why it's worth keeping, a category, and where it is.

**Moved the listening onto this Mac.** It had been going to NVIDIA and taking 150
seconds. Locally it takes 4.5 and transcribes *more*.

**Made the page stop freezing.** The download returns in about two seconds and
labelling continues in the background with a live progress line, so you can keep
using the page.

**Switched providers to OpenRouter** after racing them on the same video — 47
seconds against 264, with identical answers.

**Cleaned up the places list**, which was producing four spellings of one
restaurant and words like "HOTEL" that aren't places at all.

**Grouped everything into cities and buckets**, and split tips into city-specific
and applies-anywhere.

**Put it on GitHub**, with the keys and every downloaded video deliberately left
out.

**Made the writing read like a guidebook**, not like a machine describing its own
workings.

**Started checking every place against a real map** — the change that turned names
into addresses.

**Found and fixed the silent-video bug**, which had been feeding whole videos
through the pipeline deaf.

**Added automatic failover** between providers when one runs out of free requests.

**Added neighbourhood proximity** to map matching, and a way to trace any place
back to the video that recommended it.

**Built location-first search**, which recovers a real place from a badly
transcribed name.

---

## 5. Every problem we hit, and the fix

Kept because each one cost real time to find, and would cost it again.

### The page froze for minutes
Labelling is slow and it was blocking the request. **Fix:** download returns
immediately, labelling runs in the background, the page polls and shows a live
progress line.

### Raw errors thrown at the user
A red wall of JSON saying "ResourceExhausted: Worker local total request limit
reached (16/16)". **Fix:** plain-English messages, automatic retries with a
growing wait, and failover to the other provider.

### One restaurant appearing four times
"Il Gabbriello", "Gabbriendo", "Gabbriele", "Odigabriele" — one place, four
mishearings. Plus "HOTEL" and "RISTORANTE" listed as venues. **Fix:** a bigger
local listening model, an instruction to leave out anything too garbled to
identify, and a cleanup pass that merges near-identical names, drops generic
words and fixes SHOUTING CAPS.

### The model reasoning instead of answering
Adding stricter rules made it think out loud in prose and run out of room before
writing its answer. **Fix:** told to reply with the answer only, given four times
the room, strict-JSON mode where supported, and a salvage step that keeps the
fields that did arrive when an answer is cut off mid-sentence.

### Places stranded by an older version
Records labelled before buckets existed kept their places in the old field, so
London showed as an empty city even though it had correctly read "The Mayfair
Chippy" off the screen. **Fix:** stale records are detected and surfaced with a
one-click refresh, instead of failing silently.

### The machine describing itself to the user
"Shown on screen as LA TERRA", "name heard as 'Gora Armando'", and a badge on
every place saying where we'd read it. **Fix:** guidebook prose about the place
only, a cleanup pass that strips the rest, and no badge unless a name is genuinely
unclear.

### Videos processed completely deaf
A reported video transcribed to nothing. The download worked and the file played —
but had no audio track. **Fix:** ask for the h264 copy. Transcript went from 0
characters to 2,811. *(See §6.)*

### A confident wrong address
"Fortunato" was confirmed at a pastry shop 5 km from the Pantheon the video
described. **Fix:** rank map results by the neighbourhood the video mentioned, and
refuse a short name that only matches somewhere else.

### A wrong match vouching for itself
On re-check we passed the place's *own* area — which, after a bad match, held the
wrong neighbourhood. So re-checking confirmed the error rather than catching it.
**Fix:** the video's stated neighbourhood always wins.

### A venue called "aT"
Matching by substring meant a two-letter name matched inside *fortun**at**o* and
*m**at**ricanella*. **Fix:** whole-word matching only, with a minimum length.

---

## 6. Measurements

### TikTok serves silent videos — 3 Sep 2026
TikTok offers each video in h264 and h265 (`bytevc1`). Both advertise having
sound. **The h265 ones arrive with no audio track at all.** yt-dlp picks the
highest resolution, which was h265.

Counted audio streams directly: `bytevc1_540p` → **0**, `h264_540p` → **1**.

| | Before | After |
|---|---|---|
| Transcript on the reported video | 0 chars | **2,811 chars** |

### Listening locally beats sending it away — 2 Sep 2026
Same 104-second video:

| | Time | Transcribed |
|---|---|---|
| NVIDIA omni model | 150 s | 886 chars |
| faster-whisper **small**, local | **4.5 s** | **1,299 chars** |

33× faster, more complete, free, private, and it can't be rate-limited.

### OpenRouter against NVIDIA — 2 Sep 2026
Same video, same labelling model, same answers — same title, same category, same
city.

| | Total |
|---|---|
| OpenRouter | **47 s** |
| NVIDIA | 264 s |

The model wasn't the difference. The queue was.

### Listening model sizes — 3 Sep 2026
Tested on Italian restaurant names inside English speech:

| Model | Time | "Armando al Pantheon" heard as | "Matricianella" heard as |
|---|---|---|---|
| `small` | 15 s | Gora Armando | the Matricanella |
| `medium` | 46 s | **Armando again** | **Amatricianella** |
| `large-v3` | 58 s | *dropped half the video* | *dropped half the video* |

`large-v3` returned **700 characters where `small` returned 1,276**, with no
punctuation or capitals. On this machine it is a downgrade. `medium` is a real
improvement at about +29 seconds a video.

---

## 7. Dead ends

Don't spend time here again.

**Seeding the transcriber with context does nothing.** Tried the caption, the
on-screen text, and both together. Identical results to feeding it nothing — 5 of
6 names either way. *An earlier version of this test appeared to work, but it had
the actual restaurant names sitting in the prompt, so it was only reading back the
answer.*

**NVIDIA's speech-to-text models can't be reached with our key.** Their catalogue
lists nine — Parakeet, Canary — and they'd be better than what we use. Five
different addresses tested; all refused. They're for people running their own GPU.

**Three models are listed but dead on our NVIDIA account.**
`llama-3.1-nemotron-70b-instruct` and `nemotron-nano-3-30b-a3b` return Not Found;
`deepseek-v4-flash-0731` never answers. Being in a catalogue does not mean it
works — test before trusting.

**On build.nvidia.com, use the "Free Endpoint" filter.** Only 39 of the 98 models
are callable with a free key; the rest are downloads for people with their own
hardware.

---

## 8. The map: what it can and can't do

> **The principle.** The video decides *which* place is meant. The map decides
> *how it's spelled and where it is*. Neither is enough on its own.

### Searching by name is exact, not fuzzy
- "Matricanella" — one letter wrong — returns **nothing at all**.
- "Armando" — real, but too short — returns a butcher, a bridge and a farm.
- It speaks the local language: *Roma* and *Italia*, not Rome and Italy. An early
  version compared these strictly and rejected every correct result.

### Searching by location rescues a mangled name
Ask what's actually near the landmark the video mentioned, then find our name in
that list.

| What we heard | What was really there |
|---|---|
| Gora Armando | **Armando al Pantheon** — 31 Salita de' Crescenzi |
| Matricanella | **La Matricianella** — 4 Via del Leone |
| Fortunato | **Da Fortunato** — 55 Via del Pantheon |
| La Pietra | *correctly rejected — not a real place* |

### Six guards, each added after a real failure
1. **Reject non-venues.** "La Terra" first matched a footpath and a bus stop.
2. **Speak local.** Roma / Italia versus Rome / Italy.
3. **Match the name.** "La Terra" then matched "ESA Centre for Earth Observation".
4. **Rank by neighbourhood.** "Fortunato" was confirmed 5 km from the Pantheon.
5. **Whole words only.** A venue named "aT" matched inside *fortun**at**o*.
6. **Judge extra words against the landmark.** "Armando al Pantheon" adds
   *Pantheon* — the landmark we searched near, so it corroborates. "Antics Osteria
   Di Pietra" adds *Antics*, which corroborates nothing.

Rate limit is one request a second. Every lookup is cached to disk.

---

## 9. Keys, limits and costs

Both keys live in `.env`, which is **never** committed to GitHub. Neither the keys
nor any downloaded video has ever been pushed — checked directly against GitHub's
own records, not assumed.

### OpenRouter — the default
- **50 free requests a day.** Each video costs 2, so about **25 videos a day**.
- $10 of credit raises it to 1,000 a day — roughly 500 videos. The $10 isn't spent
  on requests; it unlocks the higher free tier.
- Resets daily at 5 PM.

### NVIDIA — the automatic backup
Used on its own when OpenRouter runs dry, and it says so on screen when it
switches. **It is the weaker labeller.** On the same video it produced the title
and tips but found no places at all, where OpenRouter found four. It keeps you
working — not working equally well.

### Models that work
**Labelling, in order:** `nemotron-3-super-120b-a12b` → `gpt-oss-120b` →
`nemotron-3.5-lightning-30b-a3b`.
**Reading the screen:** `google/gemma-4-31b-it:free`, `gemma-4-26b-a4b-it:free`,
`minimax/minimax-m3:free`, `thinkingmachines/inkling:free`.

---

## 10. How it does on real videos

| City | Places confirmed on the map |
|---|---|
| San Francisco | **8 of 8** |
| London | **5 of 6** |
| Rome | **2 of 6** — 4 of 6 once location-first search is applied |

**Why San Francisco does best:** clear English audio, names spoken plainly, and a
long caption.

**Why Rome does worst:** Italian restaurant names spoken by a native speaker
inside English sentences. The names arrive mangled and everything downstream
inherits that. This is the single biggest quality problem in the tool.

---

## 11. What it still can't do

- **Only on this Mac.** Not on a phone — which is where it would actually be used,
  and the test the vision file sets for itself.
- **Lists, not days.** No ordering, no "these three are on the same street". The
  promise is a day you can live; we deliver a sorted list.
- **You can't edit anything.** No fixing a name, deleting a wrong place, adding
  your own, or crossing things off.
- **Cities, not trips.** Rome and Florence in one Italy trip aren't connected.
- **TikTok only.** Not Instagram, YouTube, or a link a friend texts you.
- **No backup.** Saved trips live in one folder on one machine. The code is on
  GitHub; your library is not.
- **Slideshows can't be watched in the app** — they link out to TikTok instead.
- **Timestamps only on new videos.** Anything labelled before 3 Sep 2026 jumps to
  the start rather than the moment a place is named.
- **Untested at size.** Seven videos, three cities. Nobody knows what fifty looks
  like.

**Pending right now:** the location-first search is built and proven but hasn't
been applied across the saved library, so Rome still shows 2 of 6 on screen.

---

## 12. Running it

Double-click **`start.command`**. A black window opens — leave it alone. The site
opens by itself at **127.0.0.1:8000**. Close that window to stop it.

Your saved videos live in the **`library`** folder, one folder per post, as
ordinary files you can open in Finder.

**Two useful buttons.** *Label it* redoes a single video. The map re-check re-runs
only the map step across everything saved — about 13 seconds, where relabelling
everything takes minutes.

**Saving your work to GitHub:**

```
cd "/Users/nathancao/Itenirary " && git add -A && git commit -m "what you changed" && git push
```

**Never put a key directly in a code file.** They belong in `.env`, which git
ignores. That's the only reason publishing has been safe.

---

## 13. Rules we hold to

1. **Nothing invented.** If the evidence didn't say it, it doesn't go in. A place
   the map can't confirm is shown dimmed and marked — never quietly dropped, never
   given a made-up address.
2. **Say when we don't know.** "Not on the map" and "check spelling" are honest
   answers. A confident wrong address is worse than no address at all.
3. **Never show our workings.** Descriptions describe the place, not where we read
   about it.
4. **Zero setup.** Paste, and the tool does the rest.
5. **Test it, don't trust it.** Nearly every finding in this document contradicted
   something that looked true on paper — the catalogue that listed dead models, the
   format that advertised audio it didn't have, the bigger model that turned out
   worse.

---

## Related files

- **`VISION.md`** — what we're building and why. The north star.
- **`RESEARCH-can-we-download-tiktoks.md`** — the original proof it was possible.
- **`HOW-TO-START.md`** — the short version of §12.
- **`MODELS-what-works.md`** — superseded; points here.

A browsable version of this reference is published at
`claude.ai/code/artifact/7f6ac39d-ce5a-4555-8a7a-1218a1a4f24b`.
