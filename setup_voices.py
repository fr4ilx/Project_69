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
from chatterbox.tts_turbo import ChatterboxTurboTTS
import numpy as np
import torch
from chatterbox.models.s3tokenizer.s3tokenizer import S3Tokenizer, padding
from chatterbox.models.voice_encoder.voice_encoder import VoiceEncoder


VOICES_DIR = Path(story_tts.VOICES_DIR)


def _patch_s3tokenizer_float32() -> None:
    """Force float32 in tokenizer forward to avoid MPS/CPU float64 crashes."""
    if getattr(S3Tokenizer, "_project69_float32_patch", False):
        return

    @torch.no_grad()
    def _forward_float32(self, wavs, accelerator=None, max_len=None):
        processed_wavs = self._prepare_audio(wavs)
        mels, mel_lens = [], []
        for wav in processed_wavs:
            wav = wav.to(self.device, dtype=torch.float32)
            mel = self.log_mel_spectrogram(wav)
            if max_len is not None:
                mel = mel[..., : max_len * 4]
            mels.append(mel.squeeze(0))

        mels, mel_lens = padding(mels)
        tokenizer = self if accelerator is None else accelerator.unwrap_model(self)
        speech_tokens, speech_token_lens = tokenizer.quantize(mels, mel_lens.to(self.device))
        return (
            speech_tokens.long().detach(),
            speech_token_lens.long().detach(),
        )

    S3Tokenizer.forward = _forward_float32
    S3Tokenizer._project69_float32_patch = True


def _patch_voice_encoder_float32() -> None:
    """Force float32 mel tensors before voice encoder inference."""
    if getattr(VoiceEncoder, "_project69_float32_patch", False):
        return

    original = VoiceEncoder.embeds_from_mels

    def _embeds_from_mels_float32(self, mels, mel_lens=None, as_spk=False, batch_size=32, **kwargs):
        if isinstance(mels, list):
            mels = [np.asarray(mel, dtype=np.float32) for mel in mels]
        elif torch.is_tensor(mels):
            mels = mels.float()
        return original(self, mels, mel_lens=mel_lens, as_spk=as_spk, batch_size=batch_size, **kwargs)

    VoiceEncoder.embeds_from_mels = _embeds_from_mels_float32
    VoiceEncoder._project69_float32_patch = True


def main():
    if not VOICES_DIR.exists():
        print(f"[Setup] Creating '{VOICES_DIR}/' …")
        VOICES_DIR.mkdir()

    wavs = sorted(VOICES_DIR.glob("*.wav"))
    if not wavs:
        print(f"[Setup] No .wav files found in '{VOICES_DIR}/'. Add a .wav and re-run.")
        return

    print("[Setup] Loading TTS model on CPU for stable voice baking…")
    _patch_s3tokenizer_float32()
    _patch_voice_encoder_float32()
    model = ChatterboxTurboTTS.from_pretrained(device="cpu")

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
