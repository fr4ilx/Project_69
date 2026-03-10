# Database Schema - Claude Code Ready

## Tables

### stories
- story_id (UUID, PK)
- template_id (FK)
- title (string)
- status (enum: pending, rendering, complete)
- created_at (timestamp)
- updated_at (timestamp)

### chunks
- chunk_id (UUID, PK)
- story_id (FK)
- chunk_index (int)
- text (text)
- voice_id (FK)
- status (enum: pending, rendering, complete, invalidated)
- audio_path (string, optional)
- created_at (timestamp)
- updated_at (timestamp)

### voices
- voice_id (UUID, PK)
- name (string)
- speaker_embedding (binary/blob)
- emotion_profile (JSON)
- pace (float)
- pitch (float)

### templates
- template_id (UUID, PK)
- name (string)
- type (enum: story, meditation)
- structure (JSON describing segments and placeholders)
- created_at (timestamp)
- updated_at (timestamp)