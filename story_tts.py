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
    from chatterbox.tts_turbo import ChatterboxTurboTTS, Conditionals
except ImportError:
    print("Installing chatterbox-tts …")
    pip_install("chatterbox-tts")
    from chatterbox.tts_turbo import ChatterboxTurboTTS, Conditionals


# ---------------------------------------------------------------------------
# 2. Configuration
# ---------------------------------------------------------------------------

# TTS generation settings — defaults (overridden by params.md if present)
# Note: exaggeration, cfg_weight, and min_p are ignored by ChatterboxTurboTTS
TTS_EXAGGERATION   = 0.0
TTS_CFG_WEIGHT     = 0.0
TTS_TEMPERATURE    = 0.8
TTS_REP_PENALTY    = 1.2
TTS_MIN_P          = 0.0
TTS_TOP_P          = 0.95
TTS_TOP_K          = 1000
SPEECH_RATE        = 1.0
CHUNK_MAX_CHARS    = 280

# Voice clone: path to a clean 15–30 sec .wav file, or None for default voice
AUDIO_PROMPT_PATH = "voice-1.wav"

# Voices directory: contains <name>.wav and <name>_conds.pt files
VOICES_DIR = "voices"

# In-memory cache of pre-baked voice conditionals, populated by load_voices()
VOICES: dict[str, Conditionals] = {}
VOICE_NAME_ALIASES: dict[str, str] = {
    "audiomass-output": "jean",
}

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
        "top_k":             ("TTS_TOP_K",          int),
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

def generate_story(prompt: str, target_words: int = 900) -> str:
    """Call the Grok API and return the generated story as a string.

    target_words controls the length instruction sent to the LLM.
    For very long stories (>2500 words) this is called in multiple segments
    by generate_story_long(); call that instead for 30min/1hr experiences.
    """
    api_key = os.environ.get("GROK_API_KEY", "")
    base_url = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
    model = os.environ.get("GROK_MODEL", "grok-3-mini")

    if not api_key:
        raise ValueError(
            "GROK_API_KEY environment variable is not set. "
            "Export it before running:\n  export GROK_API_KEY='your-key-here'"
        )

    client = OpenAI(api_key=api_key, base_url=base_url)

    # Allow ~20% slack so the model doesn't cut off right at the limit
    word_floor = int(target_words * 0.85)
    word_ceil  = int(target_words * 1.15)
    # max_tokens: ~1.3 tokens per word + headroom
    max_tokens = int(target_words * 1.4) + 200

    system_msg = (
        "You are a master storyteller specialising in erotic, sensual short fiction. "
        "Write explicit, immersive prose — do not sanitise or soften the content. "
        "Honour exactly what is asked for, with full intensity and heat. "
        f"Write between {word_floor} and {word_ceil} words — hitting this range is critical. "
        "Do not include a title or any meta-commentary — only the story itself.\n\n"
        "PACING IS CRITICAL — follow this structure strictly:\n"
        "- First ~1/3 of the word count: sensual buildup. Set the scene, build tension and desire.\n"
        "- Next ~1/2 of the word count: the climax. Hard, intense, explicit action — this is the core of the story. Do NOT hold back.\n"
        "- Final ~1/6 of the word count: the finish. Wind down, post-climax resolution.\n"
        "Do NOT spend most of the story on atmosphere and setup. "
        "Get into the action by the midpoint at the latest. The explicit scenes must be the longest part.\n\n"
        "The story will be read aloud by a text-to-speech narrator. "
        "Sprinkle in paralinguistic expression tags where they feel natural and heighten the moment. "
        "Use them sparingly (roughly one tag per 200 words). "
        "Supported tags (use exactly as written, including brackets): "
        "[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]\n"
        "Example: 'She pulled him closer. [gasp] He didn\\'t resist.'"
    )

    print(f"\n[Grok] Generating story (~{target_words} words) for prompt: '{prompt[:80]}' …")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.9,
        max_tokens=max_tokens,
    )

    story = response.choices[0].message.content.strip()
    print(f"[Grok] Story received ({len(story)} chars, ~{len(story.split())} words).\n")
    return story


def generate_story_long(prompt: str, target_words: int) -> str:
    """Generate a long story by stitching together multiple Grok segments.

    Used when target_words > 2500 (i.e. 30-min and 1-hour selections).
    Each segment is ~2000 words; subsequent segments continue the story.
    """
    api_key = os.environ.get("GROK_API_KEY", "")
    base_url = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
    model    = os.environ.get("GROK_MODEL", "grok-3-mini")
    client   = OpenAI(api_key=api_key, base_url=base_url)

    SEGMENT_WORDS = 2000
    num_segments  = max(2, round(target_words / SEGMENT_WORDS))
    seg_max_tokens = int(SEGMENT_WORDS * 1.4) + 200

    tag_note = (
        "Sprinkle in paralinguistic expression tags where they feel natural. "
        "Use roughly one tag per 200 words. "
        "Supported tags (exact brackets): "
        "[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]"
    )

    base_system = (
        "You are a master storyteller specialising in erotic, sensual short fiction. "
        "Write explicit, immersive prose — do not sanitise or soften the content. "
        "Honour exactly what is asked for, with full intensity and heat. "
        "Do not include a title or any meta-commentary — only the story itself.\n\n"
        "PACING IS CRITICAL — the overall story must follow this structure:\n"
        "- First ~1/3: sensual buildup. Set the scene, build tension and desire.\n"
        "- Next ~1/2: the climax. Hard, intense, explicit action — this is the core. Do NOT hold back.\n"
        "- Final ~1/6: the finish. Wind down, post-climax resolution.\n"
        "Do NOT spend most of the story on atmosphere and setup. "
        "The explicit scenes must be the longest part.\n\n"
        "The story will be read aloud by a TTS narrator. " + tag_note
    )

    segments: list[str] = []
    story_so_far = ""

    for seg in range(1, num_segments + 1):
        is_last = seg == num_segments
        word_floor = int(SEGMENT_WORDS * 0.85)
        word_ceil  = int(SEGMENT_WORDS * 1.15)

        if seg == 1:
            user_msg = (
                f"{prompt}\n\n"
                f"Write the OPENING of this story ({word_floor}–{word_ceil} words). "
                f"This is part 1 of {num_segments}; do NOT conclude — leave the tension building."
            )
        elif is_last:
            user_msg = (
                f"Here is the story so far:\n\n{story_so_far}\n\n"
                f"Continue and CONCLUDE the story ({word_floor}–{word_ceil} words). "
                "Bring it to a satisfying, climactic end. Output only the new segment."
            )
        else:
            user_msg = (
                f"Here is the story so far:\n\n{story_so_far}\n\n"
                f"Continue the story ({word_floor}–{word_ceil} words). "
                f"This is part {seg} of {num_segments}; keep the tension rising, do NOT conclude yet. "
                "Output only the new segment."
            )

        print(f"\n[Grok] Generating segment {seg}/{num_segments} (~{SEGMENT_WORDS} words) …")
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": base_system},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.9,
            max_tokens=seg_max_tokens,
        )
        segment_text = response.choices[0].message.content.strip()
        print(f"[Grok] Segment {seg} received ({len(segment_text)} chars, ~{len(segment_text.split())} words).")
        segments.append(segment_text)
        # Give subsequent segments context from last ~500 words only (keep prompt short)
        story_so_far = " ".join(" ".join(segments).split()[-500:])

    full_story = "\n\n".join(segments)
    print(f"\n[Grok] Full story: {len(full_story)} chars, ~{len(full_story.split())} words.\n")
    return full_story


# ---------------------------------------------------------------------------
# 3b. Chunk-by-chunk generation via Grok
# ---------------------------------------------------------------------------

_ARC_DIRECTIVES: dict[str, str] = {
    "setup": (
        "Establish the scene, characters, and initial tension. "
        "Be sensual and evocative but do not escalate sexually yet."
    ),
    "build": (
        "Deepen the intimacy and physical tension. Escalate desire and sensation. "
        "Do not bring things to climax yet — keep the tension rising."
    ),
    "peak": (
        "Bring the scene to full sexual climax. Full intensity, raw and explicit. "
        "This is the peak moment — hold nothing back."
    ),
    "finish": (
        "Wind down from the climax. Post-orgasm afterglow, tender or breathless. "
        "Bring the story to a satisfying close."
    ),
}


def compute_arc_phase(para_index: int, n_paragraphs: int) -> str:
    """Return the arc phase for a given paragraph index.

    Split: ~1/3 setup, ~1/2 peak (climax), ~1/6 finish.
    'build' is a single transitional paragraph between setup and peak.
    """
    setup_end = max(1, round(n_paragraphs * (1 / 3)))       # first ~1/3
    finish_start = max(setup_end + 1, n_paragraphs - max(1, round(n_paragraphs * (1 / 6))))  # last ~1/6

    if para_index < setup_end:
        return "setup"
    elif para_index == setup_end:
        return "build"
    elif para_index < finish_start:
        return "peak"
    else:
        return "finish"


def generate_next_chunk(
    prompt: str,
    story_so_far: str,
    arc_phase: str = "setup",
    is_first: bool = False,
    is_last: bool = False,
    words: int = 100,
    event_hint: str | None = None,
) -> str:
    """Generate the next story paragraph using Grok, guided by arc phase.

    Args:
        prompt:       The original user story concept.
        story_so_far: All previously generated text (from DB).
        arc_phase:    Current narrative phase — 'setup', 'build', or 'peak'.
        is_first:     True for the opening paragraph (no story_so_far yet).
        is_last:      True for the final paragraph (conclude the scene).
        words:        Target word count for this paragraph.
        event_hint:   Optional user instruction to weave into this paragraph.
    """
    api_key = os.environ.get("GROK_API_KEY", "")
    base_url = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
    model = os.environ.get("GROK_MODEL", "grok-3-mini")
    client = OpenAI(api_key=api_key, base_url=base_url)

    directive = _ARC_DIRECTIVES.get(arc_phase, _ARC_DIRECTIVES["setup"])

    system_msg = (
        "You are a master storyteller specialising in erotic, sensual short fiction. "
        "Write explicit, immersive prose — do not sanitise or soften the content. "
        "The story will be read aloud by a TTS narrator. "
        "Sprinkle in paralinguistic tags sparingly (0–1 per paragraph): "
        "[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]"
    )

    hint_line = ""
    if event_hint:
        hint_line = (
            f"\nIMPORTANT — the listener has requested this happen in this paragraph: "
            f"\"{event_hint}\". Weave it in naturally.\n"
        )

    if is_first:
        user_msg = (
            f"Story concept: {prompt}\n\n"
            f"Write the OPENING paragraph of this story ({words} words). "
            f"{directive} "
            f"{hint_line}"
            "Do not include a title. Output only the paragraph."
        )
    elif is_last:
        user_msg = (
            f"Story concept: {prompt}\n\n"
            f"Story so far:\n{story_so_far}\n\n"
            f"Write the FINAL paragraph ({words} words). "
            f"{directive} "
            f"{hint_line}"
            "Output only the paragraph."
        )
    else:
        user_msg = (
            f"Story concept: {prompt}\n\n"
            f"Story so far:\n{story_so_far}\n\n"
            f"Write the next paragraph ({words} words). "
            f"{directive} "
            f"{hint_line}"
            "Continue naturally. Do not repeat what was already written. "
            "Output only the paragraph."
        )

    print(f"[Grok] Generating next chunk (phase={arc_phase}, first={is_first}, last={is_last}) …")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.9,
        max_tokens=int(words * 1.5) + 50,
    )
    paragraph = response.choices[0].message.content.strip()
    print(f"[Grok] Paragraph received ({len(paragraph)} chars, ~{len(paragraph.split())} words).")
    return paragraph


# ---------------------------------------------------------------------------
# 3c. Segment rewrite via Grok
# ---------------------------------------------------------------------------

def rewrite_story_segment(
    story_before: str,
    old_segment_text: str,
    user_instruction: str,
    num_paragraphs: int = 3,
) -> str:
    """Rewrite a segment of the current story according to a user instruction."""
    api_key = os.environ.get("GROK_API_KEY", "")
    base_url = os.environ.get("GROK_BASE_URL", "https://api.x.ai/v1")
    model = os.environ.get("GROK_MODEL", "grok-3-mini")

    if not api_key:
        raise ValueError("GROK_API_KEY environment variable is not set.")

    client = OpenAI(api_key=api_key, base_url=base_url)

    system_msg = (
        "You are a master storyteller specialising in erotic, sensual short fiction. "
        "Write explicit, immersive prose — do not sanitise or soften the content. "
        "The story will be read aloud by a text-to-speech narrator. "
        "Sprinkle in paralinguistic expression tags where they feel natural and heighten the moment. "
        "Use them sparingly (1–3 times). "
        "Supported tags (use exactly as written, including brackets): "
        "[laugh] [chuckle] [sigh] [gasp] [cough] [sniff] [groan] [shush] [clear throat]"
    )

    user_msg = (
        f"Here is the story so far:\n{story_before}\n\n"
        f"The following segment is to be REPLACED:\n{old_segment_text}\n\n"
        f"The user wants: {user_instruction}\n\n"
        f"Write ONLY the replacement for that segment ({num_paragraphs} paragraphs), "
        "in the same style and tone as the story so far, with paralinguistic tags where natural. "
        "Do not repeat the story so far. Do not include a title or commentary. "
        "Output only the new segment."
    )

    print(f"[Grok] Rewriting segment with instruction: '{user_instruction}' …")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user",   "content": user_msg},
        ],
        temperature=0.9,
    )

    new_segment = response.choices[0].message.content.strip()
    print(f"[Grok] New segment received ({len(new_segment)} chars).")
    return new_segment


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

def load_voices(model: ChatterboxTurboTTS) -> None:
    """Load all *_conds.pt files from VOICES_DIR into the VOICES cache."""
    import glob as _glob
    pts = sorted(_glob.glob(f"{VOICES_DIR}/*_conds.pt"))
    if not pts:
        return
    device = model.device
    for pt in pts:
        raw_name = os.path.basename(pt).replace("_conds.pt", "")
        name = VOICE_NAME_ALIASES.get(raw_name, raw_name)
        conds = Conditionals.load(pt, map_location=device).to(device)
        VOICES[name] = conds
        if raw_name != name:
            print(f"[TTS] Loaded voice '{raw_name}' as alias '{name}' from '{pt}'.")
        else:
            print(f"[TTS] Loaded voice '{name}' from '{pt}'.")


def load_tts_model() -> ChatterboxTurboTTS:
    """Load ChatterboxTurboTTS, preferring CUDA > MPS > CPU, then load pre-baked voices."""
    if torch.cuda.is_available():
        device = "cuda"
    elif torch.backends.mps.is_available():
        device = "mps"
    else:
        device = "cpu"
    print(f"[TTS] Loading ChatterboxTurboTTS on device='{device}' …")
    model = ChatterboxTurboTTS.from_pretrained(device=device)
    print("[TTS] Model loaded.")
    load_voices(model)
    print()
    return model


def generate_audio(
    model: ChatterboxTurboTTS,
    chunks: list[str],
    voice_name: str = "alyssa",
) -> torch.Tensor:
    """
    Generate audio for every text chunk and concatenate them into one tensor.
    Returns a 2-D tensor shaped (channels, samples).

    If voice_name is in VOICES, sets model.conds to the pre-baked embedding
    (no audio_prompt_path needed). Falls back to live cloning via AUDIO_PROMPT_PATH.
    """
    if voice_name in VOICES:
        model.conds = VOICES[voice_name]
        prompt_path = None
        print(f"[TTS] Using pre-baked voice '{voice_name}'.")
    else:
        prompt_path = AUDIO_PROMPT_PATH
        print(f"[TTS] Voice '{voice_name}' not found in cache; falling back to live cloning.")

    audio_parts: list[torch.Tensor] = []
    chunk_times: list[float] = []

    for i, chunk in enumerate(chunks, 1):
        print(f"[TTS] Synthesising chunk {i}/{len(chunks)}: '{chunk[:60]}…'")
        t0 = time.time()
        wav = model.generate(
            chunk,
            audio_prompt_path=prompt_path,
            temperature=TTS_TEMPERATURE,
            repetition_penalty=TTS_REP_PENALTY,
            top_p=TTS_TOP_P,
            top_k=TTS_TOP_K,
        )
        elapsed = time.time() - t0
        chunk_times.append(elapsed)
        suffix = " (+ live clone)" if i == 1 and prompt_path else ""
        print(f"         └─ {elapsed:.1f}s{suffix}")
        # model.generate may return (1, T) or (T,); normalise to (1, T)
        if wav.dim() == 1:
            wav = wav.unsqueeze(0)
        audio_parts.append(wav)

    # Concatenate along the time axis
    combined = torch.cat(audio_parts, dim=-1)

    # --- Timing summary ----------------------------------------------------
    print("\n[Timing]")
    for i, t in enumerate(chunk_times, 1):
        print(f"  Chunk {i}: {t:.1f}s")
    print(f"  Total synthesis: {sum(chunk_times):.1f}s\n")

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
