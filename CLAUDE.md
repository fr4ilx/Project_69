# Project 69 — Story TTS (Kinky Audio)

## What this project does
Generates spoken-word audio stories from a text prompt.

Pipeline:
1. User provides a story prompt via web UI or CLI
2. Grok API (xAI) writes a 300–500 word story with paralinguistic tags
3. `ChatterboxTurboTTS` converts the story to speech chunk by chunk
4. Audio chunks are concatenated and saved as `output.wav`

## Key files
- `story_tts.py` — main pipeline (story gen + TTS)
- `server.py` — FastAPI backend (SSE streaming, audio serving)
- `frontend/` — Vite + React web UI
- `params.md` — TTS parameter tuning file (edit this, not the script)
- `setup_voices.py` — one-time script to bake voice embeddings from `voices/*.wav`
- `voices/` — folder containing `<name>.wav` + `<name>_conds.pt` per voice
- `test_story.md` — story text for test runs (skips Grok)
- `voice-1.wav` — legacy voice clone sample (root, not committed)
- `.env` — API keys (not committed)

## Environment
- Python 3.12 (pinned `<3.13`), managed with `uv`
- Virtual env at `.venv/`
- Backend: `uv run python server.py` (port 8000)
- Frontend: `cd frontend && npm run dev` (port 5173)

## Setup from scratch
1. Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
2. Clone the repo and run `uv sync`
3. Create `.env` with:
   - `GROK_API_KEY=<your xAI key>`
   - `HF_TOKEN=<your HuggingFace token>` (required for turbo model download)
4. Log in to HuggingFace: `uv run huggingface-cli login`
5. Add voice samples to `voices/` (e.g. `voices/alyssa.wav`, 15–30 sec clean speech)
6. Run `uv run python setup_voices.py` to bake voice embeddings
7. Start backend: `uv run python server.py` (downloads turbo model on first run)
8. Start frontend: `cd frontend && npm run dev`

## Dependencies (pyproject.toml)
- `fastapi`, `uvicorn`, `sse-starlette`
- `openai` (Grok API client)
- `python-dotenv`
- `torch`, `torchaudio`
- `chatterbox-tts` (from GitHub: `resemble-ai/chatterbox`)
- `numpy>=1.26.0` (override — chatterbox pins older numpy incompatible with Python 3.12)

## Configuration (in story_tts.py)
- `GROK_API_KEY` — set in `.env`
- `GROK_MODEL` — `grok-3-mini` (or `grok-3`)
- `AUDIO_PROMPT_PATH` — fallback voice clone `.wav` if no baked voice found
- `VOICES_DIR` — `"voices"` folder with pre-baked `*_conds.pt` files
- `TEST_STORY_FILE` — set to `"test_story.md"` to skip Grok, `None` to use Grok
- `OUTPUT_FILE` — `"output.wav"`
- All TTS params loaded from `params.md` at startup

## TTS parameters (params.md)
Edit `params.md` to tune without touching the script:
- `temperature: 0.8` — naturalness/variation
- `repetition_penalty: 1.2` — prevents stuttering
- `top_p: 0.95` — nucleus sampling cutoff
- `top_k: 1000` — top-k sampling
- `speech_rate: 1.0` — post-processing speed via resampling
- `chunk_max_chars: 280` — max chars per TTS chunk

Note: `exaggeration`, `cfg_weight`, and `min_p` are NOT used by ChatterboxTurboTTS.

## TTS model
Using `ChatterboxTurboTTS` from `chatterbox.tts_turbo` (GitHub version).
Model weights: `ResembleAI/chatterbox-turbo` on HuggingFace (downloaded on first run).
Device: MPS (Apple Silicon) → CUDA → CPU, auto-detected.
Paralinguistic tags supported: `[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]`

## Voice system
- Pre-bake voices once with `setup_voices.py`: reads `voices/*.wav`, saves `voices/*_conds.pt`
- At server startup, all `*_conds.pt` files are loaded into `VOICES` dict in `story_tts.py`
- Web UI prompts user to pick a narrator before generating
- `model.conds` is set to the selected voice before each generation — no per-chunk cloning overhead
- `chatterbox/tts_turbo.py` is patched to add `builtin_voice_conds` (preserves default voice separately)
- Any `*_conds.pt` files baked with the old `ChatterboxTTS` are incompatible — re-run `setup_voices.py`

## Decisions made
- Switched from `ChatterboxTTS` to `ChatterboxTurboTTS` (faster, GitHub-only release)
- `chatterbox-tts` installed from GitHub (`resemble-ai/chatterbox`) not PyPI
- `numpy>=1.26.0` override required — PyPI chatterbox pins `<1.26` which can't build on Python 3.12
- Speech rate via `torchaudio.functional.resample` (not a model param)
- Grok system prompt instructs LLM to sprinkle in 2–5 expression tags naturally
- Chunker splits on sentence boundaries, hard-wraps sentences over 280 chars
- `params.md` loaded at startup via `_load_params()` — overrides script defaults
- `TEST_STORY_FILE` skips Grok entirely and reads from a `.md` file (saves tokens)
- Perth workaround: `_ensure_perth_watermarker()` in `story_tts.py` injects no-op if perth fails

## Voice quality gameplan
- [x] Step 1 — Voice cloning wired up
- [x] Step 2 — Voice sample in place
- [x] Step 3 — All params exposed in `params.md`
- [x] Step 4 — Test mode via `TEST_STORY_FILE`
- [x] Step 5 — Pre-baked voice embeddings (`setup_voices.py` + `voices/` folder)
- [x] Step 6 — Switched to ChatterboxTurboTTS
- [ ] Step 7 — Tune params and evaluate output quality
- [ ] Step 8 — Consider ElevenLabs backend if Chatterbox quality ceiling is hit
