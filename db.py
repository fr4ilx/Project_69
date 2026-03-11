"""db.py — SQLite persistence for story sessions and chunks.

Tables:
  sessions — one row per generation session (story_id, prompt, voice, arc_phase)
  chunks   — one row per TTS chunk (text, audio_path, status)
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path("story.db")

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    story_id   TEXT PRIMARY KEY,
    prompt     TEXT NOT NULL,
    voice      TEXT NOT NULL,
    arc_phase  TEXT NOT NULL DEFAULT 'setup',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    story_id    TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    audio_path  TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    FOREIGN KEY (story_id) REFERENCES sessions(story_id)
);
"""


def init_db() -> None:
    """Create tables if they don't exist. Call once at server startup."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
    print(f"[DB] Initialised at '{DB_PATH}'.")


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------

@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def create_session(story_id: str, prompt: str, voice: str) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO sessions (story_id, prompt, voice, arc_phase) VALUES (?, ?, ?, 'setup')",
            (story_id, prompt, voice),
        )


def get_session(story_id: str) -> sqlite3.Row | None:
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM sessions WHERE story_id = ?", (story_id,)
        ).fetchone()


def set_arc_phase(story_id: str, phase: str) -> None:
    """Update the arc phase for a session. Valid phases: setup, build, peak."""
    assert phase in ("setup", "build", "peak", "finish"), f"Invalid arc phase: {phase}"
    with _connect() as conn:
        conn.execute(
            "UPDATE sessions SET arc_phase = ? WHERE story_id = ?",
            (phase, story_id),
        )


# ---------------------------------------------------------------------------
# Chunk CRUD
# ---------------------------------------------------------------------------

def save_chunk(story_id: str, chunk_index: int, text: str, audio_path: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO chunks (story_id, chunk_index, text, audio_path, status)
            VALUES (?, ?, ?, ?, 'complete')
            ON CONFLICT DO NOTHING
            """,
            (story_id, chunk_index, text, audio_path),
        )


def get_chunks(story_id: str) -> list[sqlite3.Row]:
    """Return all chunks for a session, ordered by chunk_index."""
    with _connect() as conn:
        return conn.execute(
            "SELECT * FROM chunks WHERE story_id = ? ORDER BY chunk_index ASC",
            (story_id,),
        ).fetchall()


def get_story_so_far(story_id: str) -> str:
    """Return the full story text built from all saved chunks, in order."""
    rows = get_chunks(story_id)
    return " ".join(row["text"] for row in rows)
