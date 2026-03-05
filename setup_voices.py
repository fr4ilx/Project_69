#!/usr/bin/env python3
"""setup_voices.py — Pre-compute voice embeddings from voices/*.wav and save as *_conds.pt.

Run once after adding or updating voice .wav files:
  uv run python setup_voices.py

For each voices/<name>.wav, outputs voices/<name>_conds.pt.
Existing .pt files are overwritten.
"""

from pathlib import Path

import story_tts
from chatterbox.tts import Conditionals  # noqa: F401


VOICES_DIR = Path(story_tts.VOICES_DIR)


def main():
    if not VOICES_DIR.exists():
        print(f"[Setup] Creating '{VOICES_DIR}/' …")
        VOICES_DIR.mkdir()

    wavs = sorted(VOICES_DIR.glob("*.wav"))
    if not wavs:
        print(f"[Setup] No .wav files found in '{VOICES_DIR}/'. Add a .wav and re-run.")
        return

    print("[Setup] Loading TTS model…")
    model = story_tts.load_tts_model()

    for wav_path in wavs:
        name = wav_path.stem
        out_path = VOICES_DIR / f"{name}_conds.pt"
        print(f"[Setup] Processing '{wav_path.name}' → '{out_path.name}' …")
        model.prepare_conditionals(str(wav_path), exaggeration=story_tts.TTS_EXAGGERATION)
        model.conds.save(out_path)
        print(f"[Setup]   Saved '{out_path}'.")

    print(f"\n[Setup] Done. {len(wavs)} voice(s) baked.")


if __name__ == "__main__":
    main()
