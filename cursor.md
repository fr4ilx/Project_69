# Cursor context — what we're up to

This file gives Claude and other Cursor AI assistants quick context on the project and recent work. Full project spec and rules are in [CLAUDE.md](CLAUDE.md).

## Project in one line

Story TTS: prompt → Grok → ChatterboxTTS → output.wav; optional web UI (FastAPI + Vite/React).

## Stack and entry points

- **CLI:** `python3 story_tts.py` — [story_tts.py](story_tts.py)
- **Backend:** `uv run python server.py` — [server.py](server.py) (port 8000)
- **Frontend:** `npm run dev` in [frontend/](frontend/) — Vite proxies `/api` to port 8000

## Recent context

- **Perth workaround:** In [story_tts.py](story_tts.py), `_ensure_perth_watermarker()` runs before importing Chatterbox. If `resemble-perth`'s `PerthImplicitWatermarker` is missing or broken (e.g. inner import fails), a no-op watermarker is injected into `sys.modules["perth"]` so TTS still runs. Do not remove this without verifying real perth works.
- **Grok API:** No module-level Grok constants. `generate_story()` in [story_tts.py](story_tts.py) reads `GROK_API_KEY`, `GROK_BASE_URL`, and `GROK_MODEL` from the environment at call time (e.g. from `.env` via python-dotenv).
- **TTS device:** `load_tts_model()` in [story_tts.py](story_tts.py) chooses device automatically: CUDA → MPS → CPU. There is no config/params.md option yet to force GPU; that was discussed but not implemented.

## Where to look

- Story pipeline and Grok: [story_tts.py](story_tts.py)
- API and SSE: [server.py](server.py)
- UI flow and API client: [frontend/src/App.tsx](frontend/src/App.tsx), [frontend/src/api.ts](frontend/src/api.ts)
- TTS tuning: [params.md](params.md)
