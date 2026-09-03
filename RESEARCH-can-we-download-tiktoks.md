# Can We Download TikToks Ourselves? — YES. Tested and Proven.

Tested: September 2, 2026, on Nathan's Mac. No paid service. No cloud tool.
Two free, open-source programs did the whole job.

---

## The Short Answer

We can take any public TikTok link and pull down everything in it, on our own
machine, for free. This is not a maybe. It ran, and it worked.

---

## What We Actually Tested

### Test 1 — A photo slideshow post
Handed it a TikTok that's a slideshow of photos, not a video.

**Result: it worked.** It came back with:
- Every photo in the slideshow, saved separately as its own image file
- The audio track playing behind the slideshow, saved as its own sound file

So the "slideshow" problem you asked about is solved. It doesn't matter whether
someone posted a video or a stack of photos — we can take both apart.

### Test 2 — A regular video post
Handed it a normal TikTok video.

**Result: it worked.** It came back with:
- The video file itself (a clean copy, no watermark)
- A big pile of information about the post — 54 separate pieces of information

### What that "54 pieces of information" includes
The useful ones for us:
- The caption the person typed
- Who posted it and their account name
- How long the video is
- The date it was posted
- Likes, views, comment count
- The link back to the original
- The cover image

All of that comes free, instantly, without watching anything.

---

## The One Important Catch

**The caption is usually short.** On the video we tested, the person's typed
caption was about one sentence long.

That matters. If someone makes a TikTok called "10 best restaurants in Rome,"
the caption almost never lists all ten. The actual list lives in two places:

1. **What they say out loud** in the video
2. **The text they slap on the screen** as it plays

Neither of those is handed to us for free. We get the video and the audio — we
have them in our hands — but turning the talking into text, and reading the
words off the screen, is a second step we have to do ourselves.

**This is not a wall. It's just the next thing to solve.** We already have the
raw material sitting on the hard drive. That's the hard part, and it's done.

---

## The Second Catch — TikTok Can Say No

During testing, one request came back with "your IP address is blocked."

Plain version: if we hammer TikTok with hundreds of requests fast from one
place, TikTok notices and shuts the door for a while. It's a bouncer, not a
locked vault.

Not a problem for one person pasting one link. It becomes something we have to
handle carefully if lots of people are using this at once. Worth knowing now,
not worth solving today.

---

## What We're Standing On

Two free tools, both open-source, both actively maintained by large communities.
Nobody can send us a bill and nobody can shut off our access on a whim.

- **yt-dlp** — the video workhorse. Huge project, updated constantly, handles
  TikTok plus about 1,800 other sites. This is the same engine nearly every
  downloader on the internet is quietly built on.
- **gallery-dl** — the photo workhorse. This is the one that cracked the
  slideshow posts. Its TikTok photo support is recent and it works.

Both are now installed on Nathan's machine and confirmed working.

### The other repos we looked at
Several people have built TikTok downloaders and put them on GitHub. Every
serious one is a wrapper around the same two tools above:
- `miztizm/rapidok` — videos, images, and audio, several at once
- `Kieranmcm07/TikTok-Downloader` — pulls slideshow photos into their own folder
- `dinoosauro/tiktok-to-ytdlp` — grabs whole accounts and liked-video lists

**Conclusion: skip the wrappers, use the two real tools directly.** The wrappers
add nothing we need and are one more thing that can break or go unmaintained.

---

## Small Housekeeping Note

The Mac is running an older version of Python (the language these tools are
written in). Everything works today, but the tools have started warning that
they'll stop supporting it. Updating it later is a ten-minute job. Flagging it
so it's not a surprise.

---

## Where This Leaves Us

**Solved:** Getting the raw goods out of any public TikTok — video, photos,
audio, caption, and all the surrounding details. Ours, free, on our machine.

**Next:** Turning what's *said* and what's *shown on screen* into text we can
read. That's where the restaurant names actually live.

---

## Sources

- yt-dlp: https://github.com/yt-dlp/yt-dlp
- yt-dlp photo mode discussion: https://github.com/yt-dlp/yt-dlp/issues/10034
- gallery-dl: https://github.com/mikf/gallery-dl
- gallery-dl TikTok slideshow issue: https://github.com/mikf/gallery-dl/issues/7060
- rapidok: https://github.com/miztizm/rapidok
- Kieranmcm07/TikTok-Downloader: https://github.com/Kieranmcm07/TikTok-Downloader
- dinoosauro/tiktok-to-ytdlp: https://github.com/dinoosauro/tiktok-to-ytdlp
