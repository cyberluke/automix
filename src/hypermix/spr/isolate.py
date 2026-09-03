"""SPR isolation: crop user phrase + Demucs "other" stem + vocal-bleed gate.

Runs INSIDE .venv-stems (needs torch + demucs). Invoked as a subprocess from
the HyperMix side; exchange via WAV files + a JSON summary on stdout.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def crop_phrase(source_wav: str, start_s: float, bars: int, bpm: float,
                sr: int = 44100) -> tuple[np.ndarray, int]:
    """Crop `bars` bars starting at `start_s` from a WAV. Returns (float32 [n,2] or [n], sr)."""
    import soundfile as sf

    audio, file_sr = sf.read(source_wav, dtype="float32", always_2d=True)
    if file_sr != sr:
        import librosa
        audio = librosa.resample(audio.T, orig_sr=file_sr, target_sr=sr).T

    bar_s = 4.0 * 60.0 / bpm
    dur_s = bars * bar_s
    i0 = int(start_s * sr)
    i1 = min(len(audio), i0 + int(dur_s * sr))
    if i1 <= i0:
        raise ValueError(f"Empty crop: start={start_s}s bars={bars} bpm={bpm}")
    return audio[i0:i1], sr


def demucs_isolate_other(audio: np.ndarray, sr: int = 44100,
                         model_name: str = "htdemucs",
                         device: str | None = None) -> np.ndarray:
    """Return the 'other' stem (synths/pads live here) as float32 [n,2]."""
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])
    audio = np.ascontiguousarray(audio, dtype=np.float32)

    model = get_model(model_name)
    model.to(device)
    model.eval()

    wav = torch.from_numpy(audio.T).float().unsqueeze(0).to(device)
    with torch.no_grad():
        sources = apply_model(model, wav, shifts=1, split=True,
                              overlap=0.25, progress=False)
    # [batch, source, channels, samples]; order drums/bass/other/vocals
    other = sources[0, 2].cpu().numpy().T  # → [n, 2]
    return other.astype(np.float32)


def demucs_all_stems(audio: np.ndarray, sr: int = 44100,
                     model_name: str = "htdemucs",
                     device: str | None = None) -> dict[str, np.ndarray]:
    """Return ALL Demucs stems {drums,bass,other,vocals} float32 [n,2].
    Demucs masks are ~conservative (sum of stems ≈ mix), so we can NULL OUT one
    stem and re-sum the rest with NO phase-shift/artefacts — the clean way to
    replace only the synth element and keep everything else original."""
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if audio.ndim == 1:
        audio = np.column_stack([audio, audio])
    audio = np.ascontiguousarray(audio, dtype=np.float32)
    model = get_model(model_name)
    model.to(device)
    model.eval()
    wav = torch.from_numpy(audio.T).float().unsqueeze(0).to(device)
    with torch.no_grad():
        sources = apply_model(model, wav, shifts=1, split=True,
                              overlap=0.25, progress=False)
    names = ["drums", "bass", "other", "vocals"]
    return {names[i]: sources[0, i].cpu().numpy().T.astype(np.float32)
            for i in range(len(names))}


def vocal_bleed_probability(other: np.ndarray, sr: int) -> float:
    """Vocal-bleed gate: how much of the 'other' stem sits in the vocal band
    with speech-like modulation. Reuses the phrase-native vocal-band heuristic
    (300–3400 Hz band share × modulation) so it agrees with the sequencer.

    Returns 0..1. High → Demucs leaked vocals into 'other' → don't transcribe.
    """
    from scipy.signal import butter, sosfilt

    mono = other.mean(axis=1) if other.ndim > 1 else other
    if len(mono) < sr // 4 or float(np.max(np.abs(mono))) < 1e-6:
        return 0.0

    # Vocal band energy share
    sos = butter(4, [300.0, 3400.0], btype="band", fs=sr, output="sos")
    band = sosfilt(sos, mono)
    band_rms = float(np.sqrt(np.mean(band ** 2)) + 1e-12)
    full_rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-12)
    band_share = band_rms / full_rms

    # Amplitude-modulation in the speech syllable range (2–8 Hz)
    env = np.abs(band)
    env_sr = 200
    hop = max(1, sr // env_sr)
    env_ds = env[::hop]
    if len(env_ds) < 16:
        return float(np.clip(band_share * 0.5, 0.0, 1.0))
    spec = np.abs(np.fft.rfft(env_ds - env_ds.mean()))
    freqs = np.fft.rfftfreq(len(env_ds), d=hop / sr)
    speech_mask = (freqs >= 2.0) & (freqs <= 8.0)
    if not speech_mask.any():
        return float(np.clip(band_share * 0.5, 0.0, 1.0))
    modulation = float(spec[speech_mask].sum() / (spec.sum() + 1e-12))

    prob = float(np.clip(band_share * (0.4 + 0.6 * modulation), 0.0, 1.0))
    return prob


def main() -> int:
    p = argparse.ArgumentParser(description="SPR isolate: crop + Demucs-other + vocal-bleed gate")
    p.add_argument("--source", required=True)
    p.add_argument("--start-s", type=float, required=True)
    p.add_argument("--bars", type=int, default=4)
    p.add_argument("--bpm", type=float, default=174.0)
    p.add_argument("--out", required=True, help="output WAV for 'other' stem")
    p.add_argument("--crop-out", default=None, help="optional output WAV for raw crop")
    p.add_argument("--backing-out", default=None,
                   help="optional output WAV for backing (drums+bass+vocals, no synth)")
    p.add_argument("--model", default="htdemucs")
    p.add_argument("--device", default=None)
    p.add_argument("--sr", type=int, default=44100)
    args = p.parse_args()

    import soundfile as sf

    crop, sr = crop_phrase(args.source, args.start_s, args.bars, args.bpm, sr=args.sr)
    if args.crop_out:
        sf.write(args.crop_out, crop, sr)

    other = demucs_isolate_other(crop, sr=sr, model_name=args.model, device=args.device)
    sf.write(args.out, other, sr)

    # Clean-sum backing: all stems EXCEPT 'other' → mix without the synth, no
    # phase artefacts. This is the bed we lay the replacement synth over.
    if args.backing_out:
        stems = demucs_all_stems(crop, sr=sr, model_name=args.model, device=args.device)
        backing = (stems["drums"] + stems["bass"] + stems["vocals"]).astype(np.float32)
        sf.write(args.backing_out, backing, sr)

    bleed = vocal_bleed_probability(other, sr)

    summary = {
        "ok": True,
        "other_wav": str(Path(args.out).resolve()),
        "crop_wav": str(Path(args.crop_out).resolve()) if args.crop_out else None,
        "sr": sr,
        "n_samples": int(len(other)),
        "duration_s": float(len(other) / sr),
        "vocal_bleed": round(bleed, 4),
        "device": args.device or "auto",
        "model": args.model,
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
