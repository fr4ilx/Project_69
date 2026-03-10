# Queue & Worker Design - Claude Code Ready

## Queue System
- Redis-based
- Stores chunk generation jobs
- Fields per job:
  - chunk_id
  - story_id
  - priority
  - status

## Worker Design
- Pull chunk jobs from Redis queue
- Check status (skip invalidated chunks)
- Load voice embedding & TTS model
- Generate audio chunk
- Save to storage (disk or object store)
- Update chunk status to complete
- Push next chunk to playback queue

## Worker Scaling
- Horizontal scaling by adding more GPU workers
- Workers can batch multiple chunks for efficiency
- Example: batch of 4 chunks per GPU for Orpheus TTS