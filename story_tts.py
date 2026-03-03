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
import time

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

# ---------------------------------------------------------------------------
# Workaround: resemble-perth can set PerthImplicitWatermarker = None on
# import failure (e.g. missing native deps). Chatterbox requires it in __init__.
# Inject a no-op watermarker so TTS works without the real perth.
# See: https://github.com/resemble-ai/chatterbox
# ---------------------------------------------------------------------------
def _ensure_perth_watermarker() -> None:
    import sys
    try:
        import perth
        if perth.PerthImplicitWatermarker is not None and callable(perth.PerthImplicitWatermarker):
            return  # real perth is available
    except Exception:
        pass
    # No-op watermarker: apply_watermark(signal, sample_rate) -> signal
    class _NoOpWatermarker:
        def apply_watermark(self, signal, sample_rate, **_kwargs):
            return signal

    fake = type(sys)("perth")
    fake.PerthImplicitWatermarker = _NoOpWatermarker
    sys.modules["perth"] = fake
    print("[TTS] Using no-op watermarker (resemble-perth failed to load).")


_ensure_perth_watermarker()

try:
    from chatterbox.tts import ChatterboxTTS
except ImportError:
    print("Installing chatterbox-tts …")
    pip_install("chatterbox-tts")
    from chatterbox.tts import ChatterboxTTS


# ---------------------------------------------------------------------------
# 2. Configuration
# ---------------------------------------------------------------------------

# TTS generation settings — defaults (overridden by params.md if present)
TTS_EXAGGERATION   = 0.5
TTS_CFG_WEIGHT     = 0.5
TTS_TEMPERATURE    = 0.8
TTS_REP_PENALTY    = 1.2
TTS_MIN_P          = 0.05
TTS_TOP_P          = 1.0
SPEECH_RATE        = 1.0
CHUNK_MAX_CHARS    = 280

# Voice clone: path to a clean 15–30 sec .wav file, or None for default voice
AUDIO_PROMPT_PATH = "voice-1.wav"

# Test mode: set to a .md file path to skip Grok and read story from file instead
# e.g. "test_story.md" — set to None to use Grok normally
TEST_STORY_FILE = "test_story.md"

OUTPUT_FILE = "output.wav"

# ---------------------------------------------------------------------------
# 2b. Load params from params.md (if present)
# ---------------------------------------------------------------------------

def _load_params(path: str = "params.md") -> None:
    """Override config globals from a simple key: value .md file."""
    if not os.path.exists(path):
        return
    _map = {
        "exaggeration":      ("TTS_EXAGGERATION", float),
        "cfg_weight":        ("TTS_CFG_WEIGHT",   float),
        "temperature":       ("TTS_TEMPERATURE",  float),
        "repetition_penalty":("TTS_REP_PENALTY",  float),
        "min_p":             ("TTS_MIN_P",          float),
        "top_p":             ("TTS_TOP_P",          float),
        "speech_rate":       ("SPEECH_RATE",       float),
        "chunk_max_chars":   ("CHUNK_MAX_CHARS",   int),
    }
    g = globals()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip().lower()
            if key in _map:
                var, cast = _map[key]
                g[var] = cast(val.strip())
    print(f"[Params] Loaded settings from '{path}'.")

_load_params()


# ---------------------------------------------------------------------------
# 3. Story generation via Grok
# ---------------------------------------------------------------------------

def generate_story(prompt: str) -> str:
    """Call the Grok API and return the generated story as a string."""
    api_key = os.environ.get("GROK_API_KEY", "")
    base_url = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
    model = os.environ.get("GROK_MODEL", "grok-3-mini")

    if not api_key:
        raise ValueError(
            "GROK_API_KEY environment variable is not set. "
            "Export it before running:\n  export GROK_API_KEY='your-key-here'"
        )

    client = OpenAI(api_key=api_key, base_url=base_url)

    system_msg = (
        "You are a master storyteller specialising in erotic, sensual short fiction. "
        "Write explicit, immersive prose — do not sanitise or soften the content. "
        "Honour exactly what is asked for, with full intensity and heat. "
        "Keep the story between 300 and 500 words. "
        "Do not include a title or any meta-commentary — only the story itself.\n\n"
        "The story will be read aloud by a text-to-speech narrator. "
        "Sprinkle in paralinguistic expression tags where they feel natural and heighten the moment. "
        "Use them sparingly (2–5 times per story). "
        "Supported tags (use exactly as written, including brackets): "
        "[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]\n"
        "Example: 'She pulled him closer. [gasp] He didn\\'t resist.'"
    )

    print(f"\n[Grok] Generating story for prompt: '{prompt}' …")
    response = client.chat.completions.create(
        model=model,
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
    chunk_times: list[float] = []
    clone_time: float = 0.0

    for i, chunk in enumerate(chunks, 1):
        print(f"[TTS] Synthesising chunk {i}/{len(chunks)}: '{chunk[:60]}…'")
        t0 = time.time()
        wav = model.generate(
            chunk,
            audio_prompt_path=AUDIO_PROMPT_PATH,
            exaggeration=TTS_EXAGGERATION,
            cfg_weight=TTS_CFG_WEIGHT,
            temperature=TTS_TEMPERATURE,
            repetition_penalty=TTS_REP_PENALTY,
            min_p=TTS_MIN_P,
            top_p=TTS_TOP_P,
        )
        elapsed = time.time() - t0
        # First chunk includes voice cloning; track it separately
        if i == 1 and AUDIO_PROMPT_PATH:
            clone_time = elapsed
            print(f"         └─ clone + synthesis: {elapsed:.1f}s")
        else:
            chunk_times.append(elapsed)
            print(f"         └─ synthesis: {elapsed:.1f}s")
        # model.generate may return (1, T) or (T,); normalise to (1, T)
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)
        audio_parts.append(wav)

    # Concatenate along the time axis
    combined = torch.cat(audio_parts, dim=-1)

    # --- Timing summary ----------------------------------------------------
    print("\n[Timing]")
    if AUDIO_PROMPT_PATH:
        print(f"  Voice cloning (chunk 1): {clone_time:.1f}s")
    for i, t in enumerate(chunk_times, 2):
        print(f"  Chunk {i}: {t:.1f}s")
    total = clone_time + sum(chunk_times)
    print(f"  Total synthesis: {total:.1f}s\n")

    return combined


# ---------------------------------------------------------------------------
# 6. Main
# ---------------------------------------------------------------------------

def main() -> None:
    # --- Get prompt --------------------------------------------------------
    if not TEST_STORY_FILE:
        if len(sys.argv) > 1:
            prompt = " ".join(sys.argv[1:])
        else:
            prompt = input("Enter your story prompt: ").strip()
            if not prompt:
                print("No prompt provided. Exiting.")
                sys.exit(1)

    # --- Generate story ----------------------------------------------------
    if TEST_STORY_FILE:
        print(f"[Test] Reading story from '{TEST_STORY_FILE}' (skipping Grok) …")
        with open(TEST_STORY_FILE, "r") as f:
            story = f.read().strip()
    else:
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
    t_start = time.time()
    wav = generate_audio(model, chunks)
    t_total = time.time() - t_start

    # --- Adjust speed ------------------------------------------------------
    if SPEECH_RATE != 1.0:
        wav = ta.functional.resample(wav, int(model.sr * SPEECH_RATE), model.sr)
        print(f"[Speed] Applied rate {SPEECH_RATE}x.")

    # --- Save output -------------------------------------------------------
    audio_duration = wav.shape[-1] / model.sr
    ta.save(OUTPUT_FILE, wav, model.sr)
    print(f"[Done] Audio saved to '{OUTPUT_FILE}'  "
          f"({audio_duration:.1f}s of audio @ {model.sr} Hz)")
    print(f"[Done] Total generation time: {t_total:.1f}s")


if __name__ == "__main__":
    main()
