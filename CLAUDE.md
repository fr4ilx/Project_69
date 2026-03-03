# Project 69 — Story TTS

## What this project does
Generates spoken-word audio stories from a text prompt.

Pipeline:
1. User provides a story prompt
2. Grok API (xAI) writes a 300–500 word story with paralinguistic tags
3. `chatterbox-tts` (ChatterboxTTS) converts the story to speech chunk by chunk
4. Audio chunks are concatenated and saved as `output.wav`

## Key files
- `story_tts.py` — main pipeline (story gen + TTS)
- `params.md` — TTS parameter tuning file (edit this, not the script)
- `test_story.md` — story text for test runs (skips Grok)
- `voice-1.wav` — voice clone sample (not committed)
- `main.py` — placeholder entry point
- `.env` — API keys (not committed)

## Environment
- Python 3.12, managed with `uv`
- Virtual env at `.venv/`
- Run with: `python3 story_tts.py`

## Setup from scratch
1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Clone the repo
3. Create `.env` with `GROK_API_KEY=<your xAI key>` (get key from x.ai API console)
4. Add `voice-1.wav` to project root (clean 15–30 sec narrator clip)
5. Run `python3 story_tts.py` — script auto-installs all deps on first run

## Dependencies (auto-installed by the script)
`pyproject.toml` has no declared deps. `story_tts.py` installs them itself at startup:
- `python-dotenv`
- `openai`
- `torch` + `torchaudio`
- `chatterbox-tts`

## Configuration (in story_tts.py)
- `GROK_API_KEY` — set in `.env`
- `GROK_MODEL` — `grok-3-mini` (or `grok-3`)
- `AUDIO_PROMPT_PATH` — voice clone `.wav` file, currently `"voice-1.wav"`
- `TEST_STORY_FILE` — set to `"test_story.md"` to skip Grok, `None` to use Grok
- `OUTPUT_FILE` — `"output.wav"`
- All TTS params are loaded from `params.md` at startup

## TTS parameters (params.md)
All at Chatterbox defaults — edit `params.md` to tune without touching the script:
- `exaggeration: 0.5` — emotional intensity (0=flat, 1+=very dramatic)
- `cfg_weight: 0.5` — clone fidelity (higher = tighter to voice sample)
- `temperature: 0.8` — naturalness/variation
- `repetition_penalty: 1.2` — prevents stuttering
- `min_p: 0.05` — minimum token probability threshold
- `top_p: 1.0` — nucleus sampling cutoff
- `speech_rate: 1.0` — post-processing speed via resampling
- `chunk_max_chars: 280` — max chars per TTS chunk

## TTS model
Using `ChatterboxTTS` from `chatterbox.tts`.
Note: `chatterbox.tts_turbo` / `ChatterboxTurboTTS` does NOT exist in the installed version — do not use it.
Paralinguistic tags supported: `[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]`

## Timing output
Each run prints per-chunk synthesis time, voice clone time (chunk 1), and total generation time.
Useful for benchmarking param changes.

## Decisions made
- `ChatterboxTTS` only — tts_turbo does not exist in installed version
- Speech rate via `torchaudio.functional.resample` (not a model param)
- Grok system prompt instructs LLM to sprinkle in 2–5 expression tags naturally
- Chunker splits on sentence boundaries, hard-wraps sentences over 280 chars
- `params.md` loaded at startup via `_load_params()` — overrides script defaults
- `TEST_STORY_FILE` skips Grok entirely and reads from a `.md` file (saves tokens)
- Prompt is skipped when `TEST_STORY_FILE` is set
- Voice cloning via `AUDIO_PROMPT_PATH` — first chunk includes clone overhead

## Voice quality gameplan (next steps)
- [x] Step 1 — Voice cloning wired up (`AUDIO_PROMPT_PATH`)
- [x] Step 2 — Voice sample in place (`voice-1.wav`)
- [x] Step 3 — All params exposed in `params.md` at defaults, ready to tune
- [x] Step 4 — Test mode via `TEST_STORY_FILE` (no Grok needed)
- [ ] Step 5 — Tune params around `voice-1.wav` and evaluate output quality
- [ ] Step 6 — Consider ElevenLabs backend if Chatterbox quality ceiling is hit
