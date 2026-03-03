# Kinky Audio

Generate spoken-word audio stories from a text prompt. The app (Kinky Audio) uses the Grok API to write a short story, then [Chatterbox TTS](https://github.com/resemble-ai/chatterbox) to turn it into speech. You can use the **web UI** or the **CLI**.

## What you need

- **Python 3.12+** (recommended: [uv](https://docs.astral.sh/uv/) for installs)
- **Node.js 18+** and npm (for the frontend)
- **Grok API key** from [x.ai](https://x.ai/) (for story generation)
- **Voice sample** — a clean 15–30 second `.wav` file for TTS voice cloning (see below)

## Quick start (after cloning)

### 1. Backend (Python)

From the **project root**:

```bash
# Install uv if you don't have it: https://docs.astral.sh/uv/getting-started/installation/
uv sync
```

This installs all Python dependencies (including PyTorch and Chatterbox TTS) into `.venv/`.

**Environment and voice file:**

- Create a `.env` file in the project root with:
  ```bash
  GROK_API_KEY=your_xai_api_key_here
  ```
  Optional: `GROK_BASE_URL`, `GROK_MODEL` (defaults: x.ai endpoint, `grok-3-mini`).

- Add a voice clone sample: place a 15–30 second `.wav` file in the project root and name it **`voice-1.wav`** (or set `AUDIO_PROMPT_PATH` in `story_tts.py` to your filename). The TTS model uses this for the narrator voice. Without it, the app may error when generating audio.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

The dev server runs at `http://localhost:5173` (or the next free port). It proxies `/api` to the backend.

### 3. Run the backend

From the **project root** (in a separate terminal):

```bash
uv run python server.py
```

Backend runs at `http://localhost:8000`. The first run will download the TTS model; give it a minute.

### 4. Use the app

Open the frontend URL in your browser. Use the landing page, pick a time and describe your fantasy; the app will generate a story and then audio.

## Project layout

| Path | Purpose |
|------|--------|
| `story_tts.py` | Core pipeline: Grok → story text → chunking → Chatterbox TTS → `output.wav` |
| `server.py` | FastAPI backend: SSE for generation, serves `output.wav` at `/api/audio` |
| `frontend/` | Vite + React UI (landing, chat flow, audio player) |
| `params.md` | TTS tuning (exaggeration, temperature, etc.); edit here, not in code |
| `.env` | API keys (not in git) |
| `voice-1.wav` | Voice clone sample (not in git; you add it) |

## CLI only (no frontend)

From the project root, with `.env` and `voice-1.wav` in place:

```bash
uv run python story_tts.py "a short story about a rainy night"
```

Or run `uv run python story_tts.py` and enter the prompt when asked. Audio is written to `output.wav`.

To test TTS without calling Grok, set `TEST_STORY_FILE = "test_story.md"` in `story_tts.py` and put your story text in `test_story.md`.

## If something breaks

- **“GROK_API_KEY environment variable is not set”** — Add `GROK_API_KEY=...` to `.env` in the project root.
- **Backend errors about voice / audio prompt** — Add `voice-1.wav` (15–30 s, clean speech) to the project root, or point `AUDIO_PROMPT_PATH` in `story_tts.py` to your file.
- **Frontend can’t reach the API** — Start the backend with `uv run python server.py` and keep it running; the frontend proxies `/api` to port 8000.
- **Python deps out of sync** — From project root run `uv sync` again. All backend deps (including `torch`, `torchaudio`, `chatterbox-tts`) are in `pyproject.toml`.
- **First backend run is slow** — The TTS model is downloaded on first use; later runs are faster.

## License and assets

- **Breath Demo** font (landing page) — demo use; check 1001fonts / author for licensing.
- **Voice sample** (`voice-1.wav`) — you supply your own; not included in the repo.
- **Chatterbox TTS** — see [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) for their terms and PerTh watermarking.
