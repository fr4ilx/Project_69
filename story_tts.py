#!/usr/bin/env python3
"""
story_tts.py — Generate a spoken-word story from a text prompt.

Pipeline:
  1. User provides a story prompt.
  2. Grok API (OpenAI-compatible) writes the story.
  3. chatterbox-tts converts the story to speech, chunk by chunk.
  4. All audio chunks are concatenated and saved as output.wav.

Usage:
  python story_tts.py "a scary story about a haunted lighthouse"
  python story_tts.py  # will prompt interactively
"""

import subprocess
import sys
import os
import re
import textwrap

# ---------------------------------------------------------------------------
# 1. Ensure dependencies are available
# ---------------------------------------------------------------------------

def pip_install(package: str) -> None:
    """Install one or more pip packages into the current interpreter if missing."""
    packages = package.split()
    subprocess.check_call([sys.executable, "-m", "pip", "install"] + packages,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


try:
    from dotenv import load_dotenv
except ImportError:
    print("Installing python-dotenv …")
    pip_install("python-dotenv")
    from dotenv import load_dotenv

load_dotenv()

try:
    from openai import OpenAI
except ImportError:
    print("Installing openai …")
    pip_install("openai")
    from openai import OpenAI

try:
    import torch
    import torchaudio as ta
except ImportError:
    print("Installing torch / torchaudio …")
    pip_install("torch torchaudio")
    import torch
    import torchaudio as ta

try:
    from chatterbox.tts import ChatterboxTTS
except ImportError:
    print("Installing chatterbox-tts …")
    pip_install("chatterbox-tts")
    from chatterbox.tts import ChatterboxTTS


# ---------------------------------------------------------------------------
# 2. Configuration
# ---------------------------------------------------------------------------

GROK_API_KEY  = os.environ.get("GROK_API_KEY", "")   # set in your shell
GROK_BASE_URL = "https://api.x.ai/v1"                 # Grok's OpenAI-compat endpoint
GROK_MODEL    = "grok-3-mini"                          # or "grok-3" for the full model

# TTS generation settings — tuned for dramatic pacing
TTS_EXAGGERATION = 0.7
TTS_CFG_WEIGHT   = 0.3

# Speech rate: 1.0 = normal, < 1.0 = slower, > 1.0 = faster
# Good starting points: 0.85 (slow), 0.90 (slightly slow), 1.0 (default)
SPEECH_RATE = 0.80

# Maximum characters per TTS chunk (Chatterbox works best below ~300 chars)
CHUNK_MAX_CHARS = 280

OUTPUT_FILE = "output.wav"


# ---------------------------------------------------------------------------
# 3. Story generation via Grok
# ---------------------------------------------------------------------------

def generate_story(prompt: str) -> str:
    """Call the Grok API and return the generated story as a string."""
    if not GROK_API_KEY:
        raise ValueError(
            "GROK_API_KEY environment variable is not set. "
            "Export it before running:\n  export GROK_API_KEY='your-key-here'"
        )

    client = OpenAI(api_key=GROK_API_KEY, base_url=GROK_BASE_URL)

    system_msg = (
        "You are a master storyteller specialising in atmospheric, dramatic short fiction. "
        "Write vivid, evocative prose. Keep the story between 300 and 500 words. "
        "Do not include a title or any meta-commentary — only the story itself.\n\n"
        "The story will be read aloud by a text-to-speech narrator. "
        "Sprinkle in paralinguistic expression tags where they feel natural and enhance the drama. "
        "Use them sparingly (2–5 times per story). "
        "Supported tags (use exactly as written, including brackets): "
        "[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]\n"
        "Example: 'She opened the door. [gasp] The room was empty.'"
    )

    print(f"\n[Grok] Generating story for prompt: '{prompt}' …")
    response = client.chat.completions.create(
        model=GROK_MODEL,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.9,
    )

    story = response.choices[0].message.content.strip()
    print(f"[Grok] Story received ({len(story)} chars).\n")
    return story


# ---------------------------------------------------------------------------
# 4. Text chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, max_chars: int = CHUNK_MAX_CHARS) -> list[str]:
    """
    Split *text* into chunks that respect sentence boundaries where possible,
    keeping each chunk under *max_chars* characters.
    """
    # Split into sentences (naively on punctuation followed by whitespace)
    sentence_pattern = re.compile(r'(?<=[.!?…])\s+')
    sentences = sentence_pattern.split(text.strip())

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If a single sentence exceeds max_chars, hard-wrap it
        if len(sentence) > max_chars:
            for line in textwrap.wrap(sentence, width=max_chars):
                chunks.append(line)
            current = ""
            continue

        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = (current + " " + sentence).strip() if current else sentence

    if current:
        chunks.append(current)

    return chunks


# ---------------------------------------------------------------------------
# 5. Text-to-speech via Chatterbox
# ---------------------------------------------------------------------------

def load_tts_model() -> ChatterboxTTS:
    """Load ChatterboxTTS, preferring CUDA > MPS > CPU."""
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"[TTS] Loading ChatterboxTTS on device='{device}' …")
    model = ChatterboxTTS.from_pretrained(device=device)
    print("[TTS] Model loaded.\n")
    return model


def generate_audio(model: ChatterboxTTS, chunks: list[str]) -> torch.Tensor:
    """
    Generate audio for every text chunk and concatenate them into one tensor.
    Returns a 2-D tensor shaped (channels, samples).
    """
    audio_parts: list[torch.Tensor] = []

    for i, chunk in enumerate(chunks, 1):
        print(f"[TTS] Synthesising chunk {i}/{len(chunks)}: '{chunk[:60]}…'")
        wav = model.generate(
            chunk,
            exaggeration=TTS_EXAGGERATION,
            cfg_weight=TTS_CFG_WEIGHT,
        )
        # model.generate may return (1, T) or (T,); normalise to (1, T)
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)
        audio_parts.append(wav)

    # Concatenate along the time axis
    combined = torch.cat(audio_parts, dim=-1)
    return combined


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main() -> None:
    # --- Get prompt --------------------------------------------------------
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = input("Enter your story prompt: ").strip()
        if not prompt:
            print("No prompt provided. Exiting.")
            sys.exit(1)

    # --- Generate story ----------------------------------------------------
    story = generate_story(prompt)
    print("=" * 60)
    print(story)
    print("=" * 60 + "\n")

    # --- Chunk text --------------------------------------------------------
    chunks = chunk_text(story)
    print(f"[Chunker] Split story into {len(chunks)} chunk(s).\n")

    # --- Load TTS model ----------------------------------------------------
    model = load_tts_model()

    # --- Synthesise audio --------------------------------------------------
    wav = generate_audio(model, chunks)

    # --- Adjust speed ------------------------------------------------------
    if SPEECH_RATE != 1.0:
        wav = ta.functional.resample(wav, int(model.sr * SPEECH_RATE), model.sr)
        print(f"[Speed] Applied rate {SPEECH_RATE}x.")

    # --- Save output -------------------------------------------------------
    ta.save(OUTPUT_FILE, wav, model.sr)
    print(f"\n[Done] Audio saved to '{OUTPUT_FILE}'  "
          f"({wav.shape[-1] / model.sr:.1f} seconds @ {model.sr} Hz)")


if __name__ == "__main__":
    main()
