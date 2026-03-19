# Parallelization + Queieing Architecture

This is a quick technical walkthrough of how the backend now handles multi-user generation safely and how parallel synthesis is achieved on GPU.

## 1) Queueing model

Generation requests no longer run inline in the request handler.  
Each `POST /api/generate` call creates a `GenerationJob` and enqueues it.

Each job carries:

- `time_str`, `fantasy`, `voice_name`
- per-job controls: `abort`, `event_hint` (one-shot), `redirect` (persistent)
- per-job event stream queue used for SSE responses

This isolates user state per story and prevents cross-user collisions.

## 2) SSE flow

`/api/generate` returns an `EventSourceResponse` over `_stream_job(job)`.

Flow:

1. emit a queued/progress event immediately
2. put the job into `_job_queue`
3. worker consumes job and pushes events (`session`, `progress`, `story`, `chunk`, `done`, `error`, `aborted`) into that job's stream queue
4. SSE endpoint forwards those events to the requesting client only

The frontend reads `session.story_id` and uses it for targeted control actions.

## 3) Bounded worker pool

Worker count is controlled by:

- `MAX_CONCURRENT_JOBS` (default: `1`)

At startup, the app preloads one TTS model per worker and starts one async worker task per model.

This gives bounded admission and avoids unbounded concurrency under load.

## 4) Parallelization strategy (current implementation)

Stage 1 introduced queue safety; Stage 2 introduced true worker parallelism:

- one `ChatterboxTurboTTS` model instance per worker
- each worker synthesizes with its own model
- jobs can run in parallel across workers (subject to GPU memory/throughput limits)

Edit flow currently uses the primary model safely under a lock for consistency.

## 5) Story-scoped controls

Control endpoints now support targeting a specific active story:

- `POST /api/abort` (optional `story_id`)
- `POST /api/inject` (optional `story_id`)
- `POST /api/redirect` (optional `story_id`)

If `story_id` is provided, action is scoped to that job.

## 6) Chunk storage safety

No global chunk-directory wipe on each new request.

- each story writes to `output_chunks/{story_id}/chunk_NNN.wav`

This prevents one user from deleting another user's chunks.

## 7) Runtime metrics for tuning

`GET /api/metrics` provides:

- queue depth and active jobs
- total enqueued/completed/failed/aborted counts
- per-worker counters and latest queue wait/job duration/error
- active story metadata

Use this to tune `MAX_CONCURRENT_JOBS` (recommended: start with 2 on 4090, then test 3 if stable).

## 8) Practical tuning notes

- Start with `MAX_CONCURRENT_JOBS=2`
- Watch:
  - queue wait time
  - worker job duration
  - failure/OOM rate
  - first-chunk latency
- Increase to `3` only if VRAM and latency remain healthy under concurrent load.
