#!/usr/bin/env python3
"""FastAPI backend for Story TTS chat UI.

Endpoints:
  POST /api/generate  — SSE stream: story text, per-chunk progress, done/error
  GET  /api/audio     — serve the generated output.wav
"""

import asyncio
import json
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

    async with _lock:
        try:
            # 1. Generate story via Grok
            story = await asyncio.to_thread(story_tts.generate_story, prompt)
            yield {"data": json.dumps({"type": "story", "text": story})}

            # 2. Chunk the story
            chunks = story_tts.chunk_text(story)
            n = len(chunks)

            # 3. Set voice (pre-baked conds if available, else model uses its default)
            if voice_name in story_tts.VOICES:
                _model.conds = story_tts.VOICES[voice_name]  # type: ignore[union-attr]

            # 4. Synthesise chunk by chunk, yielding progress events
            audio_parts: list[torch.Tensor] = []
            for i, chunk in enumerate(chunks, 1):
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
                audio_parts.append(wav)

            # 4. Combine, apply speed, save
            combined = torch.cat(audio_parts, dim=-1)
            if story_tts.SPEECH_RATE != 1.0:
                combined = ta.functional.resample(
                    combined,
                    int(_model.sr * story_tts.SPEECH_RATE),  # type: ignore[union-attr]
                    _model.sr,  # type: ignore[union-attr]
                )
            ta.save(story_tts.OUTPUT_FILE, combined, _model.sr)  # type: ignore[union-attr]

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


@app.get("/api/voices")
async def voices():
    available = list(story_tts.VOICES.keys())
    return {"voices": available if available else ["alyssa"]}


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    return EventSourceResponse(_sse_generator(req.time, req.fantasy, req.voice))


@app.get("/api/audio")
async def audio():
    path = Path(story_tts.OUTPUT_FILE)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio not yet generated")
    return FileResponse(str(path), media_type="audio/wav")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
