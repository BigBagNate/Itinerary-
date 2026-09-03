# Which NVIDIA Models To Use — Tested With Our Own Key

Tested live on September 2, 2026. Every line below is a real call, not a guess.

## Use these two

| Job | Model | Speed | Status |
|---|---|---|---|
| Listen to the video + read on-screen text | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | slow — about 1.5x the video's length | WORKS |
| Turn that into title / category / place | `nvidia/nemotron-3-super-120b-a12b` | ~2 seconds | WORKS |

Backups for the labelling job, both tested working:
`openai/gpt-oss-120b`, then `nvidia/nemotron-3.5-lightning-30b-a3b`.

## Do NOT use these — they are listed but dead on our account

- `nvidia/llama-3.1-nemotron-70b-instruct` — returns "Not Found"
- `nvidia/nemotron-nano-3-30b-a3b` — returns "Not Found"
- `deepseek-ai/deepseek-v4-flash-0731` — never answered, timed out

Being in the catalogue does not mean it works. Always test before trusting one.

## About the 9 "Speech-to-Text" models in the catalogue

These are Parakeet and Canary. They would be much faster than our omni model.
**But we cannot use them with our key.** Tested five different addresses, all
refused. NVIDIA offers them to run on your own graphics hardware via Docker, or
through a separate system — not as a simple call like the others.

So the omni model stays our ears for now.

## Two things that will bite us

1. **Speed.** The omni model runs at about 1.5x the video length. A 2-minute
   TikTok means roughly a 3-minute wait.
2. **The free tier fills up.** We hit "worker limit reached (16/16)" once. It
   cleared on its own. We need to retry rather than fail.

## The likely fix for speed

Run the listening part on Nathan's own Mac instead of sending it to NVIDIA.
Whisper-style transcription runs locally, free, private, and much faster than
1.5x. NVIDIA would then only do the labelling — which already takes 2 seconds.

Not yet tested on this machine. Next thing to try.
