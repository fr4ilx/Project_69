# GPU Batching & Chunk Streaming - Claude Code Ready

## Chunking Strategy
- Split story into 60–90 second segments
- Maintain story index and segment order

## GPU Batching
- Batch multiple chunks per forward pass if GPU memory allows
- Use speaker embedding cache to reduce computation
- Stream chunks as soon as generated

## Streaming Playback
- Start playback after first chunk is ready (~5–10s)
- Append subsequent chunks in order
- Optional crossfade between chunks for smooth audio

## Example Pseudocode
```python
while True:
    chunk = redis_queue.pop()
    if chunk.status != "invalidated":
        audio = tts_model.synthesize(chunk.text, voice_embedding=chunk.voice_embedding)
        save_audio(chunk.chunk_id, audio)
        chunk.status = "complete"
        update_db(chunk)
        stream_to_client(chunk.chunk_id, audio)
```