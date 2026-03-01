# Project 69 — Story TTS

## What this project does
Generates spoken-word audio stories from a text prompt.

Pipeline:
1. User provides a story prompt
2. Grok API (xAI) writes a 300–500 word story with paralinguistic tags
3. `chatterbox-tts` (ChatterboxTurboTTS) converts the story to speech chunk by chunk
4. Audio chunks are concatenated and saved as `output.wav`

## Key files
- `story_tts.py` — main pipeline (story gen + TTS)
- `main.py` — placeholder entry point
- `.env` — API keys (not committed)

## Environment
- Python 3.12, managed with `uv`
- Virtual env at `.venv/`
- Run with: `uv run python story_tts.py "your prompt here"`

## Setup from scratch
1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Clone the repo
3. Create `.env` with `GROK_API_KEY=<your xAI key>` (get key from x.ai API console)
4. Run `uv run python story_tts.py "prompt"` — script auto-installs all deps on first run

## Dependencies (auto-installed by the script)
`pyproject.toml` has no declared deps. `story_tts.py` installs them itself at startup:
- `python-dotenv`
- `openai`
- `torch` + `torchaudio`
- `chatterbox-tts`

## Configuration (in story_tts.py)
- `GROK_API_KEY` — set in `.env`
- `GROK_MODEL` — `grok-3-mini` (or `grok-3`)
- `TTS_EXAGGERATION` — `0.7` (dramatic pacing)
- `TTS_CFG_WEIGHT` — `0.3`
- `SPEECH_RATE` — `0.80` (80% speed via resampling)
- `CHUNK_MAX_CHARS` — `280` (Chatterbox works best below ~300 chars)

## TTS model
Using `ChatterboxTTS` from `chatterbox.tts`. Note: `chatterbox.tts_turbo` / `ChatterboxTurboTTS` does NOT exist in the installed version of `chatterbox-tts` — do not use it.
Paralinguistic tags supported by the model: `[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]`

## Decisions made
- Switched back to `ChatterboxTTS` from `chatterbox.tts` (tts_turbo does not exist in installed version)
- Speech rate controlled via `torchaudio.functional.resample` (not a model param)
- Grok system prompt instructs the LLM to sprinkle in 2–5 expression tags naturally
- Chunker splits on sentence boundaries, hard-wraps sentences over 280 chars

## Voice quality gameplan (in progress)

### Step 1 — Add voice cloning support
Add `AUDIO_PROMPT_PATH` config var at the top of `story_tts.py`.
Pass it to every `model.generate()` call via `audio_prompt_path=`.
When `None`, falls back to default Chatterbox voice.

### Step 2 — Find a good voice sample
Source a ~15–30 second clean `.wav` clip (no music, no noise) of a narrator voice we like.
Good sources: LibriVox (librivox.org), self-recorded, royalty-free audiobook clips.
Save it to the project root as e.g. `voice.wav`.

### Step 3 — Tune parameters around the cloned voice
After locking in a voice sample, dial in these settings:
- `exaggeration` — start at `0.5` (default), nudge up for drama
- `cfg_weight` — try `0.5`–`0.7` (higher = tighter clone fidelity)
- `temperature` — try `0.9`–`1.0` for more natural delivery
- `repetition_penalty` — keep at `1.2`, raise if stuttering
- `SPEECH_RATE` — currently `0.80`, try `0.85`–`0.90` to see if pacing feels better

### Step 4 — Quick test loop (no full story needed)
Add a short test mode: pass a fixed 2-sentence test string directly to TTS,
skipping Grok entirely, so we can iterate on voice settings fast.
e.g. `python story_tts.py --test-voice`
