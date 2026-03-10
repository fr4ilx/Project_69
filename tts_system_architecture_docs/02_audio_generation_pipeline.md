# Audio Generation Pipeline

## Overview

The pipeline converts story text into long-form audio while maintaining responsiveness.

Pipeline stages:

1. Story generation
2. Segment creation
3. Chunk scheduling
4. TTS synthesis
5. Audio assembly
6. Streaming delivery

## Step 1 — Story Generation

Input:

- user prompt
- template
- desired length

Output:

Story segments:

intro
scene
dialogue
transition
ending

Segments remain editable until synthesized.

## Step 2 — Chunk Creation

Segments are split into TTS chunks.

Typical sizes:

30–60 seconds (dialogue)
60–90 seconds (story narration)
90–120 seconds (meditation)

Chunk structure:

chunk_id
story_id
text
voice_profile
status

Statuses:

pending
rendering
complete
invalidated

## Step 3 — Queue Scheduling

Chunks are pushed into Redis queue.

Priority order:

1. next playback chunk
2. upcoming chunk
3. future chunks

This ensures playback never pauses.

## Step 4 — TTS Worker Processing

Workers pull from queue.

Worker workflow:

load voice embedding
run TTS model
save audio file
update chunk status

Workers should batch multiple chunks when possible.

## Step 5 — Audio Assembly

Chunks are concatenated using FFmpeg.

Optional enhancements:

crossfades
background ambience
music layers

## Step 6 — Streaming

Once first chunk is complete:

stream begins

Subsequent chunks appended to playback stream.