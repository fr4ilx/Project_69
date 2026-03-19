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
- `server.py` — FastAPI backend (SSE streaming, audio serving, chunk file serving)
- `db.py` — SQLite persistence (sessions + chunks, `story.db`)
- `output_chunks/` — per-session WAV chunk files (`{story_id}/chunk_NNN.wav`); no global wipe per generation
- `frontend/` — Vite + React web UI
  - `src/App.tsx` — top-level state, split-screen layout
  - `src/components/ChatWindow.tsx` — left panel chat feed
  - `src/components/VoicePoweredOrb.tsx` — WebGL orb (right panel)
  - `src/components/ChunkPlayer.tsx` — invisible Web Audio engine for chunk streaming
  - `src/components/AudioPlayer.tsx` — `<audio>` element, kept for post-edit replay only
  - `src/components/Message.tsx` — chat bubble renderer
  - `src/index.css` — all styles (no Tailwind — plain CSS)
- `params.md` — TTS parameter tuning file (edit this, not the script)
- `setup_voices.py` — one-time script to bake voice embeddings from `voices/*.wav`
- `voices/` — folder containing `<name>.wav` + `<name>_conds.pt` per voice
- `test_story.md` — story text for test runs (skips Grok)
- `voice-1.wav` — legacy voice clone sample (root, not committed)
- `.env` — API keys (not committed)
- `Dockerfile` — backend image for RunPod / generic container
- `docs/DEPLOY_RUNPOD.md` — deploy backend to RunPod (GPU or CPU)

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
- Server: `HOST` and `PORT` env (default `0.0.0.0`, `8000`) for RunPod/containers
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

## Frontend UI layout
Split-screen after landing:
- **Left panel** (`.app-left`) — chat conversation: bot/user bubbles, quick-reply chips, fantasy input, voice selector, edit input
- **Right panel** (`.app-right`) — two zones stacked:
  - **Orb zone** (`.orb-zone`, `flex: 1`) — WebGL orb always visible and vertically centered; dims at 35% opacity until audio is ready
  - **Bottom zone** (`.orb-bottom`, max 40% height) — audio player + story text (scrollable)
- Message types in chat: `bot-text`, `user-text`, `bot-progress` — story text and audio live in right panel, not in the chat feed

## Chunk streaming pipeline (implemented 2026-03-07)

### How it works
Previously the server waited for all TTS chunks before sending any audio. Now:
1. Each chunk is synthesised, saved to `output_chunks/{story_id}/chunk_NNN.wav`, and immediately served
2. Server emits a `chunk` SSE event (`{type, index, url}`) after each chunk
3. Frontend `ChunkPlayer` fetches and schedules each chunk as it arrives — playback starts after chunk 1 (~8-10s instead of ~60s)
4. Combined `output.wav` is still saved at the end for post-edit replay

### Server changes (`server.py`)
- `CHUNKS_DIR = Path("output_chunks")` — root dir for per-session chunks
- Generator creates a `story_id` (UUID hex), writes `output_chunks/{story_id}/chunk_NNN.wav`, emits `chunk` SSE event per chunk
- `SPEECH_RATE` applied per-chunk (before saving) instead of on combined file
- No global `output_chunks/` wipe on each generation (multi-user safe)
- New endpoint: `GET /api/chunks/{story_id}/{filename}` with path-traversal validation (story_id must be 32-char hex, filename must match `chunk_NNN.wav`)

### ChunkPlayer (`frontend/src/components/ChunkPlayer.tsx`)
- Invisible React component (renders `null`) — pure audio engine
- `AudioContext` + `AnalyserNode` created lazily on first `addChunk()` call to avoid autoplay policy blocks
- Chunks fetched, decoded via `decodeAudioData`, scheduled with `AudioBufferSourceNode` for gapless playback
- `nextStartTime` tracks the scheduled end of the last chunk; each new chunk starts where the previous ends
- Exposes imperative handle: `addChunk(url)`, `getAnalyser()`, `reset()`
- `reset()` stops all sources, closes `AudioContext`, clears queue — called at start of each generation

### VoicePoweredOrb
- File: `frontend/src/components/VoicePoweredOrb.tsx`
- Dependency: `ogl` npm package (WebGL)
- **No Tailwind, no shadcn** — uses inline styles
- Now accepts `analyserNode?: AnalyserNode | null` (replaces old `audioElement` prop)
- No longer owns an `AudioContext` — reads from the `AnalyserNode` provided by `ChunkPlayer`
- `analyserNodeRef` keeps a stable ref so the RAF loop always reads the latest analyser without re-running the WebGL effect
- Colors: hot pink `#f472b6`, light pink `#f9a8d4`, deep rose `#831843` — matches app accent
- Orb dims (`orb-container--idle`) until `isPlaying` flips true on first chunk event

### App.tsx wiring
- `chunkPlayerRef` → `ChunkPlayer` imperative handle
- `analyserNode` state → set from `chunkPlayerRef.current.getAnalyser()` on first chunk, passed to `VoicePoweredOrb`
- `isPlaying` state + `isPlayingRef` ref → controls orb idle/active CSS class; ref avoids stale closure in async SSE loops
- `audioSrc` state kept only for post-edit `AudioPlayer` replay
- `chunk` SSE events → `chunkPlayerRef.current.addChunk(event.url)`
- `generatingRef` tracks whether the generate SSE stream is active (used by edit to know if abort is needed)

## Arc pacing system (implemented 2026-03-11)

### Problem solved
Stories were stuck in "setup" mode — 8 paragraphs of atmosphere, 1 rushed climax. Root cause: `arc_phase` was read from DB but never updated, so every paragraph ran as `phase=setup`.

### How it works
- `compute_arc_phase(para_index, n_paragraphs)` in `story_tts.py` auto-calculates phase from paragraph position
- Split: ~1/3 setup, 1 transitional "build" paragraph, ~1/2 peak (climax), ~1/6 finish
- 4 arc directives in `_ARC_DIRECTIVES`: `setup`, `build`, `peak`, `finish`
- Server calls `compute_arc_phase()` each iteration and updates DB via `db.set_arc_phase()`
- System prompt also includes pacing instructions as a guardrail

### Example for 10 paragraphs (5-min story)
- Paragraphs 0–2: setup (3)
- Paragraph 3: build (1)
- Paragraphs 4–7: peak (4)
- Paragraphs 8–9: finish (2)

## Mid-session controls (implemented 2026-03-11)

### 4 action buttons (replace old single edit input)
During `generating` or `done` stages, user sees 4 buttons:

1. **New fantasy** — abort current generation, prompt for new fantasy, restart from scratch
   - Calls `POST /api/abort`, waits for lock release (up to 30s), then `POST /api/generate`
   - Uses `resetForEdit()` (not `reset()`) to keep AudioContext alive after `prime()`
2. **Add event** — one-shot hint for the next paragraph only
   - Calls `POST /api/inject` with event text
   - Server stores in `_event_hint`, consumed by next `generate_next_chunk()` call
   - Does NOT interrupt playback — story continues, next paragraph weaves in the event
3. **Change course** — persistent redirect for all remaining paragraphs
   - Calls `POST /api/redirect` with redirect text
   - Server stores in `_redirect`, applied to every remaining paragraph (not consumed)
   - Cleared when a new generation starts
4. **I'm done** — abort generation cleanly
   - Calls `POST /api/abort`

### Server endpoints
- `POST /api/inject` — sets one-shot event hint for target story/job
- `POST /api/redirect` — sets persistent redirect for target story/job
- Both hints are combined and passed as `event_hint` to `generate_next_chunk()`

### story_tts.py changes
- `generate_next_chunk()` accepts `event_hint: str | None` parameter
- Hint injected into Grok user message: "the listener has requested this happen…"

## Mid-session editing (implemented 2026-03-09)

### How it works
User can type a redirect instruction during generation OR after story completes. The system:
1. Aborts in-flight generation (if still running) via `POST /api/abort`
2. Calls `POST /api/edit` with the instruction and `from_chunk_index` (current playback position)
3. Server keeps chunks before the split point, rewrites the rest via Grok, re-synthesises only new chunks
4. Kept chunk URLs are re-emitted so frontend can replay the full story (kept + new) seamlessly

### Server changes (`server.py`)
- `POST /api/abort` can target a specific story/job (`story_id`)
- Generation abort is now per-job; editor has separate abort signal
- `_sse_editor` accepts optional `from_chunk_index` (defaults to `n // 2`); emits kept chunk URLs before synthesising new chunks
- `EditRequest` model has `from_chunk_index: int | None = None`

### ChunkPlayer updates (`ChunkPlayer.tsx`)
- Tracks `currentChunkIndex` via `onended` callbacks and scheduled start times
- `getCurrentChunkIndex()` — returns 0-based index of chunk currently playing
- `resetFromIndex(fromIndex)` — stops sources from index onward, keeps earlier ones playing
- `chunkStartTimesRef` tracks scheduled start times for accurate playback position

### App.tsx edit flow
- Edit input visible during both `"generating"` and `"done"` stages
- `handleEdit` calls `abortGeneration()` first if `generatingRef.current` is true, then polls until SSE stream closes
- `prime()` called synchronously in click handler before any awaits (browser autoplay policy)
- `fromChunkIndex` derived from `getCurrentChunkIndex() + 1` (edit from where user is listening)
- `ChunkPlayer.reset()` before edit; kept chunks re-streamed by server for gapless replay

### API changes (`api.ts`)
- `SSEEvent.type` includes `"session"` and `"aborted"`; fields: `story_id`, `kept`, `chunks_completed`
- `streamEdit()` accepts optional `fromChunkIndex` parameter
- `abortGeneration(storyId?)` — `POST /api/abort`
- `injectEvent(event, storyId?)` — `POST /api/inject`
- `redirectStory(event, storyId?)` — `POST /api/redirect`

## Multi-user queue + worker pool (implemented 2026-03-19)

### Problem solved
Single global lock and shared mutable generation state blocked true multi-user usage and caused control collisions between sessions.

### How it works now
- Generation requests are enqueued as `GenerationJob` objects (`time`, `fantasy`, `voice`, per-job state/events)
- SSE `POST /api/generate` now streams from a per-job queue
- Worker pool size is configured by `MAX_CONCURRENT_JOBS` (default `1`)
- Server preloads one `ChatterboxTurboTTS` model instance per worker
- Each worker synthesises with its own model instance (parallel generation path)
- Story controls are story-scoped: inject/redirect/abort target the active `story_id`
- No global chunk-dir wipe; each story writes only to `output_chunks/{story_id}/`

### Endpoints and events
- `POST /api/generate` — returns SSE with early `session` event (`{type:"session", story_id}`)
- `POST /api/abort` — optional `story_id` to abort one active story
- `POST /api/inject` — optional `story_id`, one-shot next-paragraph hint
- `POST /api/redirect` — optional `story_id`, persistent redirect for remaining paragraphs
- `GET /api/metrics` — queue/worker runtime stats for tuning saturation

### Metrics payload (`GET /api/metrics`)
- `config`: `max_concurrent_jobs`, `loaded_models`
- `queue`: queue depth and active job count
- `totals`: jobs enqueued/completed/failed/aborted
- `workers[]`: per-worker counters, last queue wait/job duration/error, active story
- `active[]`: currently active stories and lightweight state

### Tuning notes
- Start with `MAX_CONCURRENT_JOBS=2` on 4090, then test `3`
- Watch queue wait, worker job duration, and failures/OOM before increasing further

## Audio download (implemented 2026-03-11)

- `AudioPlayer` + download button shown in right panel bottom zone after generation completes
- `audioSrc` set to `/api/audio?t={timestamp}` on "done" event (cache-busted)
- Download link: `<a href="/api/audio" download="story.wav">`

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
- No Tailwind or shadcn in frontend — plain CSS in `index.css`; keep it that way unless explicitly migrating

## Docker / RunPod deployment
- **Dockerfile** uses `python:3.12-slim`; deps from **pyproject.toml** only (`pip install -e .`). No custom base image or `--no-deps` hacks.
- **docker-entrypoint.sh** copies `/data/.env` and `/data/voice-1.wav` (and `/data/voices/`) into `/app` at container start when present. Mount a volume at `/data` on RunPod and put secrets/voice there.
- **Build:** `docker build -t YOUR_DOCKERHUB_USER/story-tts:latest .` then `docker push ...`
- **RunPod:** Create Pod with that image, expose HTTP port 8000, set `GROK_API_KEY` and `HF_TOKEN` in env. Full steps: [docs/DEPLOY_RUNPOD.md](docs/DEPLOY_RUNPOD.md).

## Claude Code tips
- Token usage is not visible in Claude Code directly
- Watch for the auto-compression notice when context gets full
- API usage visible at console.anthropic.com
- Start a fresh conversation if context runs out — `CLAUDE.md` and `MEMORY.md` restore context instantly

## Voice quality gameplan
- [x] Step 1 — Voice cloning wired up
- [x] Step 2 — Voice sample in place
- [x] Step 3 — All params exposed in `params.md`
- [x] Step 4 — Test mode via `TEST_STORY_FILE`
- [x] Step 5 — Pre-baked voice embeddings (`setup_voices.py` + `voices/` folder)
- [x] Step 6 — Switched to ChatterboxTurboTTS
- [ ] Step 7 — Tune params and evaluate output quality
- [ ] Step 8 — Consider ElevenLabs backend if Chatterbox quality ceiling is hit
