#!/usr/bin/env python3
"""FastAPI backend for Story TTS chat UI.

Endpoints:
  POST /api/generate  — SSE stream: story text, per-chunk progress, done/error
  POST /api/edit      — SSE stream: rewrite from a chunk index, re-synthesise
  POST /api/abort     — cancel in-flight generation
  GET  /api/audio     — serve the generated output.wav
"""

import asyncio
import json
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# Import story_tts first — it auto-installs torch/torchaudio if missing.
import story_tts
import torch
import torchaudio as ta

# ---------------------------------------------------------------------------
# App lifecycle — load TTS model once at startup
# ---------------------------------------------------------------------------

_model: story_tts.ChatterboxTurboTTS | None = None
_lock = asyncio.Lock()
_abort = asyncio.Event()  # set to signal current generation should stop

CHUNKS_DIR = Path("output_chunks")

# ---------------------------------------------------------------------------
# In-memory story store
# ---------------------------------------------------------------------------
# story_id -> StoryRecord dict
# Kept in memory for the lifetime of the server process.
# A single record is overwritten per generation (single-user app).

def _new_story_record(
    story_id: str,
    story_text: str,
    chunks: list[str],
    voice: str,
) -> dict:
    return {
        "story_id": story_id,
        "story_text": story_text,
        "voice": voice,
        "status": "rendering",
        "chunks": [
            {
                "index": i,
                "text": text,
                "status": "pending",
                "audio_path": None,
            }
            for i, text in enumerate(chunks)
        ],
    }

_stories: dict[str, dict] = {}

# State persisted between generate and edit calls
_current_story: str = ""
_chunks: list[str] = []
_audio_parts: list[torch.Tensor] = []  # raw (pre-speed) per-chunk tensors


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    print("[Server] Loading TTS model…")
    _model = await asyncio.to_thread(story_tts.load_tts_model)
    print("[Server] TTS model ready.")
    yield


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# SSE generation stream
# ---------------------------------------------------------------------------

async def _sse_generator(time_str: str, fantasy: str, voice_name: str = "alyssa"):
    """Async generator yielding SSE events for the full pipeline."""
    prompt = f"{fantasy}\n\nWrite for a {time_str} listening experience."

    _abort.clear()

    async with _lock:
        try:
            # 1. Generate story via Grok
            story_id = uuid.uuid4().hex
            story = await asyncio.to_thread(story_tts.generate_story, prompt)

            if _abort.is_set():
                yield {"data": json.dumps({"type": "aborted"})}
                return

            yield {"data": json.dumps({"type": "story", "text": story, "story_id": story_id})}

            # 2. Chunk the story
            chunks = story_tts.chunk_text(story)
            n = len(chunks)

            # 3. Set voice
            if voice_name in story_tts.VOICES:
                _model.conds = story_tts.VOICES[voice_name]  # type: ignore[union-attr]

            # 4. Create a fresh chunk directory for this session
            chunk_dir = CHUNKS_DIR / story_id
            if CHUNKS_DIR.exists():
                shutil.rmtree(CHUNKS_DIR)  # drop previous session chunks
            chunk_dir.mkdir(parents=True)

            # 5. Register story in the store
            record = _new_story_record(story_id, story, chunks, voice_name)
            _stories[story_id] = record

            # 6. Synthesise chunk by chunk — save each, emit chunk events
            audio_parts: list[torch.Tensor] = []
            for i, chunk in enumerate(chunks, 1):
                # Check abort before each chunk
                if _abort.is_set():
                    record["status"] = "aborted"
                    yield {"data": json.dumps({"type": "aborted", "chunks_completed": i - 1})}
                    return

                record["chunks"][i - 1]["status"] = "rendering"
                yield {"data": json.dumps({
                    "type": "progress",
                    "text": f"Synthesising chunk {i}/{n}…",
                })}

                wav: torch.Tensor = await asyncio.to_thread(
                    _model.generate,  # type: ignore[union-attr]
                    chunk,
                    temperature=story_tts.TTS_TEMPERATURE,
                    repetition_penalty=story_tts.TTS_REP_PENALTY,
                    top_p=story_tts.TTS_TOP_P,
                    top_k=story_tts.TTS_TOP_K,
                )

                if wav.dim() == 1:
                    wav = wav.unsqueeze(0)

                # Apply speed per-chunk so streaming audio is correct rate
                if story_tts.SPEECH_RATE != 1.0:
                    wav = ta.functional.resample(
                        wav,
                        int(_model.sr * story_tts.SPEECH_RATE),  # type: ignore[union-attr]
                        _model.sr,  # type: ignore[union-attr]
                    )

                chunk_path = chunk_dir / f"chunk_{i:03d}.wav"
                ta.save(str(chunk_path), wav, _model.sr)  # type: ignore[union-attr]
                audio_parts.append(wav)

                record["chunks"][i - 1]["status"] = "complete"
                record["chunks"][i - 1]["audio_path"] = str(chunk_path)

                yield {"data": json.dumps({
                    "type": "chunk",
                    "index": i - 1,
                    "url": f"/api/chunks/{story_id}/chunk_{i:03d}.wav",
                })}

            # 7. Save combined output.wav (already speed-adjusted per chunk)
            combined = torch.cat(audio_parts, dim=-1)
            ta.save(story_tts.OUTPUT_FILE, combined, _model.sr)  # type: ignore[union-attr]

            record["status"] = "complete"
            yield {"data": json.dumps({"type": "done"})}

        except Exception as exc:  # noqa: BLE001
            yield {"data": json.dumps({"type": "error", "text": str(exc)})}


# ---------------------------------------------------------------------------
# SSE edit stream
# ---------------------------------------------------------------------------

async def _sse_editor(story_id: str, instruction: str, from_chunk_index: int | None = None):
    """Rewrite the story from a given chunk index and re-synthesise those chunks.

    If from_chunk_index is None, defaults to halfway through the story.
    Emits kept chunk URLs first so the frontend can replay the full story.
    """
    record = _stories.get(story_id)
    if not record:
        yield {"data": json.dumps({"type": "error", "text": "Story not found"})}
        return

    async with _lock:
        # Clear abort only AFTER acquiring the lock — otherwise we race with
        # the generator and wipe the flag before it can see it.
        _abort.clear()

        try:
            chunks: list[str] = [c["text"] for c in record["chunks"]]
            n = len(chunks)
            split = from_chunk_index if from_chunk_index is not None else n // 2
            split = max(0, min(split, n - 1))  # clamp to valid range

            before_text = " ".join(chunks[:split])
            old_segment_text = " ".join(chunks[split:])

            # 1. Rewrite segment via Grok
            yield {"data": json.dumps({"type": "progress", "text": "Rewriting story…"})}
            new_segment = await asyncio.to_thread(
                story_tts.rewrite_story_segment,
                before_text,
                old_segment_text,
                instruction,
            )

            if _abort.is_set():
                yield {"data": json.dumps({"type": "aborted"})}
                return

            # 2. Build new full story and assign a fresh story_id
            new_story = (before_text + "\n\n" + new_segment).strip() if before_text else new_segment
            new_story_id = uuid.uuid4().hex

            # 3. Chunk the new segment only (kept chunks stay on disk)
            new_chunks = story_tts.chunk_text(new_segment)
            new_n = len(new_chunks)

            # 4. Register updated story record
            kept = record["chunks"][:split]
            new_record = {
                "story_id": new_story_id,
                "story_text": new_story,
                "voice": record["voice"],
                "status": "rendering",
                "chunks": list(kept) + [
                    {"index": split + i, "text": t, "status": "pending", "audio_path": None}
                    for i, t in enumerate(new_chunks)
                ],
            }
            _stories[new_story_id] = new_record

            # 5. Emit updated story text so frontend can update the panel
            yield {"data": json.dumps({"type": "story", "text": new_story, "story_id": new_story_id})}

            # 6. Emit kept chunk URLs so frontend can replay them without re-synthesis
            old_story_id = record["story_id"]
            for kept_chunk in kept:
                if kept_chunk.get("audio_path"):
                    # Serve from original story's chunk dir
                    filename = Path(kept_chunk["audio_path"]).name
                    yield {"data": json.dumps({
                        "type": "chunk",
                        "index": kept_chunk["index"],
                        "url": f"/api/chunks/{old_story_id}/{filename}",
                        "kept": True,
                    })}

            # 7. Create chunk dir for new segments
            chunk_dir = CHUNKS_DIR / new_story_id
            chunk_dir.mkdir(parents=True, exist_ok=True)

            # 8. Set voice
            voice_name = record["voice"]
            if voice_name in story_tts.VOICES:
                _model.conds = story_tts.VOICES[voice_name]  # type: ignore[union-attr]

            # 9. Synthesise new chunks
            for i, chunk in enumerate(new_chunks, 1):
                if _abort.is_set():
                    new_record["status"] = "aborted"
                    yield {"data": json.dumps({"type": "aborted"})}
                    return

                chunk_idx = split + i  # global index in the full story
                new_record["chunks"][split + i - 1]["status"] = "rendering"
                yield {"data": json.dumps({
                    "type": "progress",
                    "text": f"Re-synthesising chunk {i}/{new_n}…",
                })}

                wav: torch.Tensor = await asyncio.to_thread(
                    _model.generate,  # type: ignore[union-attr]
                    chunk,
                    temperature=story_tts.TTS_TEMPERATURE,
                    repetition_penalty=story_tts.TTS_REP_PENALTY,
                    top_p=story_tts.TTS_TOP_P,
                    top_k=story_tts.TTS_TOP_K,
                )
                if wav.dim() == 1:
                    wav = wav.unsqueeze(0)
                if story_tts.SPEECH_RATE != 1.0:
                    wav = ta.functional.resample(
                        wav,
                        int(_model.sr * story_tts.SPEECH_RATE),  # type: ignore[union-attr]
                        _model.sr,  # type: ignore[union-attr]
                    )

                chunk_path = chunk_dir / f"chunk_{chunk_idx:03d}.wav"
                ta.save(str(chunk_path), wav, _model.sr)  # type: ignore[union-attr]

                new_record["chunks"][split + i - 1]["status"] = "complete"
                new_record["chunks"][split + i - 1]["audio_path"] = str(chunk_path)

                yield {"data": json.dumps({
                    "type": "chunk",
                    "index": split + i - 1,
                    "url": f"/api/chunks/{new_story_id}/chunk_{chunk_idx:03d}.wav",
                })}

            new_record["status"] = "complete"
            yield {"data": json.dumps({"type": "done"})}

        except Exception as exc:  # noqa: BLE001
            yield {"data": json.dumps({"type": "error", "text": str(exc)})}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    time: str
    fantasy: str
    voice: str = "alyssa"


class EditRequest(BaseModel):
    story_id: str
    instruction: str
    from_chunk_index: int | None = None


@app.get("/api/story/{story_id}")
async def story_status(story_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", story_id):
        raise HTTPException(status_code=400, detail="Invalid story_id")
    record = _stories.get(story_id)
    if not record:
        raise HTTPException(status_code=404, detail="Story not found")
    return record


@app.get("/api/voices")
async def voices():
    available = list(story_tts.VOICES.keys())
    return {"voices": available if available else ["alyssa"]}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    return EventSourceResponse(_sse_generator(req.time, req.fantasy, req.voice))


@app.post("/api/abort")
async def abort():
    """Signal the current generation/edit to stop after the current chunk."""
    _abort.set()
    return {"ok": True}


@app.post("/api/edit")
async def edit(req: EditRequest):
    if not re.fullmatch(r"[a-f0-9]{32}", req.story_id):
        raise HTTPException(status_code=400, detail="Invalid story_id")
    return EventSourceResponse(
        _sse_editor(req.story_id, req.instruction, req.from_chunk_index)
    )


@app.get("/api/audio")
async def audio():
    path = Path(story_tts.OUTPUT_FILE)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not yet generated")
    return FileResponse(str(path), media_type="audio/wav")


_CHUNK_FILENAME_RE = re.compile(r"^chunk_\d{3}\.wav$")

@app.get("/api/chunks/{story_id}/{filename}")
async def audio_chunk(story_id: str, filename: str):
    # Validate inputs to prevent path traversal
    if not re.fullmatch(r"[a-f0-9]{32}", story_id):
        raise HTTPException(status_code=400, detail="Invalid story_id")
    if not _CHUNK_FILENAME_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = CHUNKS_DIR / story_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Chunk not found")
    return FileResponse(str(path), media_type="audio/wav")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
