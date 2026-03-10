# Plan: Mid-Session Story Editing

**Goal:** Let the user redirect the story after it’s generated (e.g. change a name, adjust tone). The system re-prompts the LLM for the next 2–3 paragraphs, regenerates only that segment’s audio, and splices it into the existing file.

---

## 1. Current state

- **Flow:** Generate full story (Grok) → chunk with `chunk_text()` → synthesize all chunks (Turbo) → concatenate → save `output.wav` → done.
- **Server:** No persistence of story text, chunk list, or per-chunk audio boundaries. Only the final `output.wav` exists.
- **Frontend:** After “done”, user sees the full story (expandable) and the audio player. No way to send a follow-up instruction.

To support editing we need: (1) **segment identity** (which part to replace), (2) **backend state** (current story, chunks, and where each chunk sits in the wav), (3) **LLM re-prompt** (rewrite only that segment), (4) **TTS for the new segment only**, (5) **audio splice** (replace that span in the wav), (6) **UI** to send the instruction and refresh story + audio.

---

## 2. Scope and user flow

**When:** Editing is available in the **“done”** stage (story + audio already generated).

**User flow:**

1. User has listened to some or all of the story and wants a change (e.g. “change his name to Mark”, “make the next part darker”).
2. User types the instruction in the chat (or in a dedicated “Redirect story” input).
3. Frontend sends the instruction to the backend (e.g. “replace the **next** 2–3 paragraphs” with a rewrite that follows the instruction).
4. Backend:
   - Determines which segment to replace (see below).
   - Calls Grok to rewrite only that segment (with context + instruction).
   - Chunks the new text, synthesizes those chunks, splices them into the existing wav.
   - Updates stored story and chunk metadata.
5. Frontend receives success (and optionally the new full story text); refreshes the story view and the audio player (re-fetch `GET /api/audio`).

**Out of scope for this plan:** Editing *while* the first generation is still running (interrupt mid-stream). That would require a different pipeline (e.g. stream story paragraph-by-paragraph and allow “replace from here”).

---

## 3. Segment definition: “next 2–3 paragraphs”

We need a stable way to map “the next 2–3 paragraphs” to a span of the **chunk list** (and thus to a span of the wav).

**Option A — By chunk index (recommended for MVP)**  
- We already have a list of **chunks** from `chunk_text(story)`.  
- “Next 2–3 paragraphs” ≈ “next 2–3 **chunks**” (chunks are sentence-bound and ~280 chars; 2–3 chunks is a reasonable “segment”).  
- Backend (or frontend) sends a **segment start index** `K` (0-based). We replace chunks `K` through `K+2` (3 chunks) or `K` through `K+1` (2 chunks).  
- **Who chooses K?**  
  - **Simplest:** Always replace from chunk index **1** (skip the first chunk so we don’t rewrite the very opening). Or always replace **2–3 chunks starting at index 0** for the first edit.  
  - **Richer later:** Frontend sends “replace starting at chunk index K” (e.g. user selected a position in the story, or we derive K from “current playback position” if we have it).

**Option B — By paragraph (double-newline split)**  
- Split story by `\n\n` into paragraphs; “next 2–3 paragraphs” = paragraphs `[K, K+1, K+2]`.  
- We must then map paragraph span → character span in story → which chunks overlap that span. Doable but more bookkeeping; Option A is simpler.

**Recommendation:** Start with **Option A**, and fix the segment to “replace chunks 1, 2, 3” (indices 1, 2, 3) for the first version. Later we can add a parameter “start chunk index” so the user can choose “change the beginning” vs “change the middle” (e.g. from a “position” in the story or from playback time).

---

## 4. Backend state and persistence

We need the server to remember, for the **current session**, after the first generation:

- `current_story: str` — full story text (updated after each edit).
- `chunks: list[str]` — current chunk list (updated after each edit).
- `chunk_sample_ranges: list[tuple[int, int]]` — for each chunk, `(start_sample, end_sample)` in the current wav (so we can splice).

**Persistence:**  
- **Single-user / single-story MVP:** In-memory globals (e.g. `_current_story`, `_chunks`, `_chunk_sample_ranges`) updated at the end of `_sse_generator` and in the new edit endpoint. When a new full generation runs, we overwrite them.  
- **Multi-user later:** Session ID or user ID; store state in a dict keyed by session, or in a small file/DB per session.

**When we build the first wav:** In `_sse_generator` we already have `audio_parts` (list of tensors). Before `torch.cat`, compute per-chunk sample counts and cumulative start/end:

- `chunk_sample_ranges = []`  
- `offset = 0`  
- For each part in `audio_parts`: `n = part.shape[-1]`, append `(offset, offset + n)`, then `offset += n`.  
- After saving `output.wav`, set `_chunk_sample_ranges = chunk_sample_ranges`, `_chunks = chunks`, `_current_story = story`.

---

## 5. Backend: edit endpoint and LLM re-prompt

**New endpoint (e.g.):**  
`POST /api/edit`  
Body: `{ "instruction": "change his name to Mark", "start_chunk_index": 1 }`  
(For MVP, `start_chunk_index` can be optional and default to 1.)

**Steps:**

1. **Validate:** We have `_current_story`, `_chunks`, `_chunk_sample_ranges` and `start_chunk_index` is in range. Number of chunks to replace: e.g. 2 or 3 (e.g. `num_chunks = min(3, len(_chunks) - start_chunk_index)`).
2. **Segment to replace:**  
   - `old_segment_chunks = _chunks[start_chunk_index : start_chunk_index + num_chunks]`  
   - `old_segment_text = " ".join(old_segment_chunks)`  
   - `story_before = " ".join(_chunks[:start_chunk_index])`
3. **LLM:** New function in `story_tts.py`, e.g. `rewrite_story_segment(story_before, old_segment_text, user_instruction, num_paragraphs=3)`.  
   - Prompt: “You are continuing an erotic/sensual short story. Here is the story so far: <story_before>. The following segment is to be REPLACED: <old_segment_text>. The user wants: <user_instruction>. Write ONLY the replacement for that segment (2–3 paragraphs), same style and paralinguistic tags. Do not repeat the story so far; output only the new segment.”
   - Return the new segment text (plain string).
4. **Chunk and synthesize:**  
   - `new_chunks = chunk_text(new_segment_text)`  
   - Synthesize only `new_chunks` (same voice/model as initial generation; use existing `_model` and voice conds).  
   - Collect tensors into `new_audio` (1D or 2D, same as now).
5. **Splice:**  
   - `start_sample, end_sample = _chunk_sample_ranges[start_chunk_index][0], _chunk_sample_ranges[start_chunk_index + num_chunks - 1][1]`  
   - Load current wav from `output.wav` (or keep it in memory if we prefer).  
   - `new_wav = concat( wav[:, :start_sample], new_audio, wav[:, end_sample:] )`  
   - Apply `SPEECH_RATE` if needed (same as initial generation).  
   - Save to `output.wav`.
6. **Update state:**  
   - New full story: replace the old segment with `new_segment_text` in `_current_story` (by string replace or by rebuilding from chunks).  
   - New chunks: `_chunks = _chunks[:start_chunk_index] + new_chunks + _chunks[start_chunk_index + num_chunks:]`  
   - New sample ranges: recompute from the updated chunk list and the new wav (we have the new wav; we need per-chunk lengths for the *new* chunks only, and we already have ranges for the unchanged chunks before and after). So:  
   - Ranges before `start_chunk_index`: unchanged.  
   - Ranges for the new chunks: from the lengths of the new tensors we just synthesized.  
   - Ranges after: shift by `(new_total_segment_samples - old_segment_samples)`.  
   - Update `_chunk_sample_ranges` accordingly.
7. **Response:** Return e.g. `{ "ok": true, "story": _current_story }` so the frontend can update the story view; audio is already at `GET /api/audio`.

**Edge cases:**  
- If `new_segment_text` produces more or fewer chunks than 2–3, that’s fine: we still have one contiguous “new” audio blob and we splice it in once.  
- If the user has never generated (no state), return 400 with “Generate a story first.”

---

## 6. story_tts.py: new function and prompt

- **`rewrite_story_segment(story_before: str, old_segment_text: str, user_instruction: str, num_paragraphs: int = 3) -> str`**  
  - Uses same Grok client and env (GROK_API_KEY, etc.).  
  - System prompt: same tone as main story (erotic, immersive, paralinguistic tags).  
  - User prompt: story so far + segment to replace + instruction; ask for ONLY the replacement 2–3 paragraphs.  
  - Return the raw string (no title, no meta).

- **Optional:** A helper that splits the current story into “paragraphs” (e.g. by `\n\n`) if we later want to expose “paragraph index” in the UI. Not required for chunk-index-based MVP.

---

## 7. Frontend

- **Done stage:** In addition to the story and audio player, show a way to send a redirect instruction:
  - **Option A:** A text input + “Redirect story” (or “Change next part”) that sends `POST /api/edit` with `{ instruction, start_chunk_index?: 1 }`.
  - **Option B:** A chat-style message from the bot: “Want to change something? Type your request below.” and the next user message is treated as the instruction (with a “Apply to story” or “Regenerate part” button).
- **While edit is in progress:** Disable the input and show “Updating story…” (or reuse the progress-style message).
- **On success:**  
  - Replace the content of the **bot-story** message with the new `story` from the response (or append an “Edited” story message).  
  - Re-fetch audio: set the audio player’s `src` to `/api/audio?t=<timestamp>` or re-mount the player so it reloads the wav (browser may cache; cache-bust if needed).
- **On error:** Show the error in the chat (e.g. “Couldn’t update: …”).

**API client:** Add e.g. `editStory(instruction: string, startChunkIndex?: number)` that POSTs to `/api/edit` and returns the JSON.

---

## 8. Implementation order

1. **Backend state:** In `server.py`, add globals `_current_story`, `_chunks`, `_chunk_sample_ranges`. At the end of `_sse_generator`, after building `audio_parts`, compute and store chunk sample ranges and story/chunks.
2. **story_tts.py:** Implement `rewrite_story_segment(...)` and a small test (optional) that it returns only the segment.
3. **Backend edit endpoint:** Implement `POST /api/edit` with the steps above (replace chunks 1–3 by default), including splice and state update.
4. **Frontend:** Add input + “Redirect” in done stage, call `editStory`, update story message and audio on success.
5. **Polish:** Error handling, loading state, and (optional) cache-bust for `GET /api/audio` after edit.

---

## 9. Open questions / later improvements

- **Segment choice:** Let the user pick “which part” (e.g. “from here” based on playback position, or a paragraph index). For MVP, fixed “chunks 1–3” or “start_chunk_index: 1” is enough.
- **Multiple edits:** Each edit updates the same in-memory state; multiple edits in a row are fine as long as we keep recomputing `_chunks` and `_chunk_sample_ranges` correctly.
- **Voice:** Edit uses the same voice as the initial generation (already in `_model.conds`); no change needed unless we add voice switching mid-session later.

---

*Plan for Project 69 — mid-session story editing (redirect + LLM rewrite + TTS splice).*
