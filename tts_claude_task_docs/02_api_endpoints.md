# API Endpoints - Claude Code Ready

## Create Story
POST /story
Body:
{
 "template_id": "fantasy_adventure",
 "voice_id": "narrator_male",
 "length_minutes": 30
}

Response:
{
 "story_id": "uuid",
 "status": "pending"
}

## Get Story Status
GET /story/{story_id}
Response:
{
 "story_id": "uuid",
 "status": "rendering|complete",
 "chunks_completed": 12,
 "total_chunks": 24,
 "audio_url": "url_if_complete"
}

## Edit Future Chunks
PATCH /story/{story_id}/segments
Body:
{
 "segment_ids": ["chunk_10", "chunk_11"],
 "new_text": ["New text for chunk 10", "New text for chunk 11"]
}

Response:
{
 "updated_chunks": ["chunk_10", "chunk_11"],
 "status": "pending"
}

## Stream Audio
GET /story/{story_id}/stream
- Streams chunks as they complete
- Supports WebSocket or chunked HTTP streaming

## Manage Templates
CRUD endpoints for story and meditation templates