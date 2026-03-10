# Task Breakdown - Claude Code Ready

## Objective
Build a self-hosted TTS API for long-form stories and meditation sessions using Orpheus or Chatterbox TTS. Must support:

- 30+ minute narration
- Multiple voices / speaker embeddings
- Chunked streaming playback
- Mid-generation editing
- Template-based story generation
- Cost-efficient GPU usage

## High-Level Tasks

1. Story Engine
   - Template management
   - Story generation (LLM integration)
   - Editable story pipeline

2. Chunk Manager
   - Split story into TTS-friendly chunks
   - Track chunk status (pending, rendering, complete, invalidated)

3. GPU Worker Pool
   - Load TTS models (Orpheus / Chatterbox)
   - Generate audio chunks
   - Manage speaker embeddings and emotion profiles
   - Batch processing for GPU efficiency

4. Audio Stitcher
   - Combine chunks
   - Add optional background ambience / music layers
   - Export to playable format

5. Streaming Server
   - Serve chunks progressively
   - Support WebSocket or HTTP streaming

6. Queue System
   - Redis-based job queue
   - Prioritize next playback chunks
   - Handle retries and invalidated chunks

7. API Endpoints
   - CRUD for stories, chunks, templates
   - Edit text mid-generation
   - Stream audio in real time

8. Metrics & Monitoring
   - Track GPU utilization, queue depth, chunk failures, generation latency
   - Logging for debugging and cost analysis