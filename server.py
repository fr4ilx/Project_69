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
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# Import story_tts first — it auto-installs torch/torchaudio if missing.
import story_tts
import db
import torch
import torchaudio as ta

# ---------------------------------------------------------------------------
# App lifecycle — load TTS model once at startup
# ---------------------------------------------------------------------------

_generation_models: list[story_tts.ChatterboxTurboTTS] = []
_edit_lock = asyncio.Lock()
_edit_abort = asyncio.Event()  # edit stream cancel signal
_primary_model_lock = asyncio.Lock()  # serialize shared model-0 use with edit

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
@dataclass
class GenerationJob:
    time_str: str
    fantasy: str
    voice_name: str
    stream: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    abort: asyncio.Event = field(default_factory=asyncio.Event)
    event_hint: str | None = None
    redirect: str | None = None
    story_id: str | None = None
    queued_at_monotonic: float = 0.0


_MAX_CONCURRENT_JOBS = max(1, int(os.environ.get("MAX_CONCURRENT_JOBS", "1")))
_job_queue: asyncio.Queue[GenerationJob | None] = asyncio.Queue()
_worker_tasks: list[asyncio.Task] = []
_active_jobs: dict[str, GenerationJob] = {}  # story_id -> job
_worker_stats: list[dict[str, Any]] = []
_jobs_enqueued_total = 0
_jobs_completed_total = 0
_jobs_failed_total = 0
_jobs_aborted_total = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _generation_models, _worker_stats
    db.init_db()
    print(f"[Server] Loading {_MAX_CONCURRENT_JOBS} TTS model instance(s)…")
    _generation_models = []
    for i in range(_MAX_CONCURRENT_JOBS):
        print(f"[Server] Loading TTS model {i + 1}/{_MAX_CONCURRENT_JOBS}…")
        model = await asyncio.to_thread(story_tts.load_tts_model)
        _generation_models.append(model)
    print("[Server] TTS model pool ready.")
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    _worker_stats = [
        {
            "worker_index": i,
            "jobs_started": 0,
            "jobs_completed": 0,
            "jobs_failed": 0,
            "jobs_aborted": 0,
            "chunks_synthesized": 0,
            "last_job_duration_ms": None,
            "last_queue_wait_ms": None,
            "last_error": None,
            "active_story_id": None,
        }
        for i in range(_MAX_CONCURRENT_JOBS)
    ]

    for i, model in enumerate(_generation_models):
        _worker_tasks.append(asyncio.create_task(_generation_worker(i, model)))
    print(f"[Server] Generation worker pool ready (size={_MAX_CONCURRENT_JOBS}).")

    try:
        yield
    finally:
        for _ in _worker_tasks:
            await _job_queue.put(None)
        await asyncio.gather(*_worker_tasks, return_exceptions=True)
        _worker_tasks.clear()


app = FastAPI(lifespan=lifespan)


# ---------------------------------------------------------------------------
# SSE generation stream
# ---------------------------------------------------------------------------

_TIME_TO_WORDS: dict[str, int] = {
    "5 minutes":  950,
    "15 minutes": 2800,
    "30 minutes": 5500,
    "an hour":    11000,
}
_LONG_STORY_THRESHOLD = 2500  # words; above this use multi-segment generation


_WORDS_PER_GROK_CHUNK = 100  # target words per Grok paragraph


async def _run_generation_job(job: GenerationJob, model: story_tts.ChatterboxTurboTTS, worker_index: int) -> None:
    """Run one generation job and stream events to its queue.

    Each job owns its abort/event/redirect state so concurrent users do not interfere.
    """
    target_words = _TIME_TO_WORDS.get(job.time_str.lower(), 950)
    prompt = job.fantasy
    n_paragraphs = max(3, target_words // _WORDS_PER_GROK_CHUNK)

    worker_stat = _worker_stats[worker_index]
    started_at = time.monotonic()
    worker_stat["jobs_started"] += 1
    worker_stat["active_story_id"] = "pending_session"
    if job.queued_at_monotonic > 0:
        worker_stat["last_queue_wait_ms"] = int((started_at - job.queued_at_monotonic) * 1000)

    try:
        story_id = uuid.uuid4().hex
        job.story_id = story_id
        worker_stat["active_story_id"] = story_id

        # Voice conditionals are worker-local (one model per worker).
        voice_conds = story_tts.VOICES.get(job.voice_name)
        if voice_conds is not None:
            model.conds = voice_conds

        # 2. Create session chunk directory and register session
        chunk_dir = CHUNKS_DIR / story_id
        chunk_dir.mkdir(parents=True, exist_ok=True)

        db.create_session(story_id, prompt, job.voice_name)
        _stories[story_id] = {
            "story_id": story_id,
            "story_text": "",
            "voice": job.voice_name,
            "status": "rendering",
            "chunks": [],
        }
        _active_jobs[story_id] = job
        record = _stories[story_id]

        await job.stream.put({"data": json.dumps({"type": "session", "story_id": story_id})})

        # 3. Generate paragraph by paragraph
        audio_parts: list[torch.Tensor] = []
        tts_index = 0

        for para_i in range(n_paragraphs):
            if job.abort.is_set():
                record["status"] = "aborted"
                await job.stream.put({"data": json.dumps({"type": "aborted", "chunks_completed": tts_index})})
                return

            is_first = para_i == 0
            is_last = para_i == n_paragraphs - 1

            arc_phase = story_tts.compute_arc_phase(para_i, n_paragraphs)
            db.set_arc_phase(story_id, arc_phase)

            await job.stream.put({"data": json.dumps({
                "type": "progress",
                "text": f"Writing paragraph {para_i + 1}/{n_paragraphs}…",
            })})

            # One-shot event hint + persistent redirect, both scoped to this job.
            hint = job.event_hint
            job.event_hint = None
            combined_hint = " ".join(filter(None, [job.redirect, hint]))

            story_so_far = db.get_story_so_far(story_id)
            paragraph = await asyncio.to_thread(
                story_tts.generate_next_chunk,
                prompt,
                story_so_far,
                arc_phase,
                is_first,
                is_last,
                _WORDS_PER_GROK_CHUNK,
                combined_hint or None,
            )

            if job.abort.is_set():
                record["status"] = "aborted"
                await job.stream.put({"data": json.dumps({"type": "aborted", "chunks_completed": tts_index})})
                return

            record["story_text"] = (record["story_text"] + "\n\n" + paragraph).strip()
            await job.stream.put({"data": json.dumps({"type": "story", "text": record["story_text"], "story_id": story_id})})

            tts_chunks = story_tts.chunk_text(paragraph)
            for tts_chunk in tts_chunks:
                if job.abort.is_set():
                    record["status"] = "aborted"
                    await job.stream.put({"data": json.dumps({"type": "aborted", "chunks_completed": tts_index})})
                    return

                await job.stream.put({"data": json.dumps({
                    "type": "progress",
                    "text": f"Synthesising chunk {tts_index + 1}…",
                })})

                if worker_index == 0:
                    async with _primary_model_lock:
                        wav: torch.Tensor = await asyncio.to_thread(
                            model.generate,
                            tts_chunk,
                            temperature=story_tts.TTS_TEMPERATURE,
                            repetition_penalty=story_tts.TTS_REP_PENALTY,
                            top_p=story_tts.TTS_TOP_P,
                            top_k=story_tts.TTS_TOP_K,
                        )
                else:
                    wav = await asyncio.to_thread(
                        model.generate,
                        tts_chunk,
                        temperature=story_tts.TTS_TEMPERATURE,
                        repetition_penalty=story_tts.TTS_REP_PENALTY,
                        top_p=story_tts.TTS_TOP_P,
                        top_k=story_tts.TTS_TOP_K,
                    )

                if job.abort.is_set():
                    record["status"] = "aborted"
                    await job.stream.put({"data": json.dumps({"type": "aborted", "chunks_completed": tts_index})})
                    return

                if wav.dim() == 1:
                    wav = wav.unsqueeze(0)
                if story_tts.SPEECH_RATE != 1.0:
                    wav = ta.functional.resample(
                        wav,
                        int(model.sr * story_tts.SPEECH_RATE),
                        model.sr,
                    )

                chunk_path = chunk_dir / f"chunk_{tts_index:03d}.wav"
                ta.save(str(chunk_path), wav, model.sr)
                audio_parts.append(wav)

                record["chunks"].append({
                    "index": tts_index,
                    "text": tts_chunk,
                    "status": "complete",
                    "audio_path": str(chunk_path),
                })
                db.save_chunk(story_id, tts_index, tts_chunk, str(chunk_path))

                await job.stream.put({"data": json.dumps({
                    "type": "chunk",
                    "index": tts_index,
                    "url": f"/api/chunks/{story_id}/chunk_{tts_index:03d}.wav",
                })})
                worker_stat["chunks_synthesized"] += 1
                tts_index += 1

        if audio_parts:
            combined = torch.cat(audio_parts, dim=-1)
            ta.save(story_tts.OUTPUT_FILE, combined, model.sr)

        record["status"] = "complete"
        worker_stat["jobs_completed"] += 1
        global _jobs_completed_total
        _jobs_completed_total += 1
        await job.stream.put({"data": json.dumps({"type": "done"})})

    except Exception as exc:  # noqa: BLE001
        worker_stat["jobs_failed"] += 1
        worker_stat["last_error"] = str(exc)
        global _jobs_failed_total
        _jobs_failed_total += 1
        await job.stream.put({"data": json.dumps({"type": "error", "text": str(exc)})})
    finally:
        elapsed_ms = int((time.monotonic() - started_at) * 1000)
        worker_stat["last_job_duration_ms"] = elapsed_ms
        worker_stat["active_story_id"] = None
        if job.story_id:
            record = _stories.get(job.story_id)
            if record and record.get("status") == "aborted":
                worker_stat["jobs_aborted"] += 1
                global _jobs_aborted_total
                _jobs_aborted_total += 1
            _active_jobs.pop(job.story_id, None)
        await job.stream.put(None)


async def _generation_worker(worker_index: int, model: story_tts.ChatterboxTurboTTS) -> None:
    while True:
        job = await _job_queue.get()
        if job is None:
            _job_queue.task_done()
            return
        try:
            await _run_generation_job(job, model, worker_index)
        finally:
            _job_queue.task_done()


async def _stream_job(job: GenerationJob):
    """SSE stream wrapper around queued generation jobs."""
    global _jobs_enqueued_total
    job.queued_at_monotonic = time.monotonic()
    _jobs_enqueued_total += 1
    await job.stream.put({"data": json.dumps({"type": "progress", "text": "Queued for generation…"})})
    await _job_queue.put(job)
    while True:
        event = await job.stream.get()
        if event is None:
            return
        yield event


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

    async with _edit_lock:
        # Clear abort only AFTER acquiring the lock — otherwise we race with
        # the generator and wipe the flag before it can see it.
        _edit_abort.clear()

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

            if _edit_abort.is_set():
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

            voice_name = record["voice"]
            voice_conds = story_tts.VOICES.get(voice_name)
            primary_model = _generation_models[0]

            # 9. Synthesise new chunks
            for i, chunk in enumerate(new_chunks, 1):
                if _edit_abort.is_set():
                    new_record["status"] = "aborted"
                    yield {"data": json.dumps({"type": "aborted"})}
                    return

                chunk_idx = split + i  # global index in the full story
                new_record["chunks"][split + i - 1]["status"] = "rendering"
                yield {"data": json.dumps({
                    "type": "progress",
                    "text": f"Re-synthesising chunk {i}/{new_n}…",
                })}

                async with _primary_model_lock:
                    if voice_conds is not None:
                        primary_model.conds = voice_conds
                    wav: torch.Tensor = await asyncio.to_thread(
                        primary_model.generate,
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
                        int(primary_model.sr * story_tts.SPEECH_RATE),
                        primary_model.sr,
                    )

                chunk_path = chunk_dir / f"chunk_{chunk_idx:03d}.wav"
                ta.save(str(chunk_path), wav, primary_model.sr)

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


class InjectRequest(BaseModel):
    event: str
    story_id: str | None = None


class AbortRequest(BaseModel):
    story_id: str | None = None


def _resolve_target_job(story_id: str | None) -> GenerationJob | None:
    if story_id:
        return _active_jobs.get(story_id)
    if not _active_jobs:
        return None
    # Fallback for legacy clients that do not send story_id.
    return next(reversed(_active_jobs.values()))


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


@app.get("/api/metrics")
async def metrics():
    active_jobs: list[dict[str, Any]] = []
    for sid, job in _active_jobs.items():
        active_jobs.append(
            {
                "story_id": sid,
                "voice": job.voice_name,
                "queued_for_ms": int((time.monotonic() - job.queued_at_monotonic) * 1000)
                if job.queued_at_monotonic > 0
                else None,
                "has_redirect": bool(job.redirect),
                "has_event_hint": bool(job.event_hint),
            }
        )
    return {
        "config": {
            "max_concurrent_jobs": _MAX_CONCURRENT_JOBS,
            "loaded_models": len(_generation_models),
        },
        "queue": {
            "depth": _job_queue.qsize(),
            "active_jobs": len(_active_jobs),
        },
        "totals": {
            "jobs_enqueued": _jobs_enqueued_total,
            "jobs_completed": _jobs_completed_total,
            "jobs_failed": _jobs_failed_total,
            "jobs_aborted": _jobs_aborted_total,
        },
        "workers": _worker_stats,
        "active": active_jobs,
    }


@app.post("/api/generate")
async def generate(req: GenerateRequest):
    return EventSourceResponse(_stream_job(GenerationJob(req.time, req.fantasy, req.voice)))


@app.post("/api/abort")
async def abort(req: AbortRequest | None = None):
    """Signal one generation/edit stream to stop after the current chunk."""
    story_id = req.story_id if req else None
    job = _resolve_target_job(story_id)
    if job:
        job.abort.set()
        return {"ok": True, "story_id": job.story_id}
    _edit_abort.set()
    return {"ok": True}


@app.post("/api/inject")
async def inject(req: InjectRequest):
    """Queue an event hint for the next generated paragraph."""
    job = _resolve_target_job(req.story_id)
    if not job:
        raise HTTPException(status_code=404, detail="No active generation for story_id")
    job.event_hint = req.event.strip() or None
    return {"ok": True, "event": job.event_hint, "story_id": job.story_id}


@app.post("/api/redirect")
async def redirect(req: InjectRequest):
    """Set a persistent course change for all remaining paragraphs."""
    job = _resolve_target_job(req.story_id)
    if not job:
        raise HTTPException(status_code=404, detail="No active generation for story_id")
    job.redirect = req.event.strip() or None
    return {"ok": True, "redirect": job.redirect, "story_id": job.story_id}


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
# Serve built frontend (SPA) — must be mounted last so /api/* routes take priority
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host=host, port=port)
