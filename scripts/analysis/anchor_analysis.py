"""Anchor-resolution + feature extraction for CyberLuke's annotated tracks.

Runs in the STEMS venv (Python 3.11, `.venv-stems`) which has torch+demucs AND
numpy/scipy. Beat grid comes from the same library the main analyzer trusts
(librosa), so the resolved samples match what HyperMix sees downstream.

For each user anchor (an APPROXIMATE time, not ground truth) we:
  1. search a +-2 bar window around the anchor,
  2. snap to the nearest plausible beat/downbeat,
  3. refine to the strongest low-end / spectral onset (the physical impact),
  4. measure a band-energy + onset + chroma + vocal feature set and the
     BEFORE/AFTER deltas that separate BREAKDOWN / BUILD / DROP / MICRO_EDIT.

Output: JSON report (per track, per anchor) for cross-track signature mining.

    .\\.venv-stems\\Scripts\\python.exe scripts/analysis/anchor_analysis.py \
        --annotations data/annotations/cyberluke_anchors.json \
        --music-dir music --out renders/anchor_analysis.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

SR = 48000  # canonical sample rate used across HyperMix


# --------------------------------------------------------------------------
# Audio loading (ffmpeg -> 48k mono float32), independent of the 3.14 venv.
# --------------------------------------------------------------------------
def load_mono(path: Path, sr: int = SR) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn",
           "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def load_stereo(path: Path, sr: int = SR) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-i", str(path), "-vn",
           "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    a = np.frombuffer(raw, dtype=np.float32)
    return a.reshape(-1, 2)


# --------------------------------------------------------------------------
# Beat grid via librosa (same donor lib the main analyzer uses).
# --------------------------------------------------------------------------
def beat_grid(mono: np.ndarray, sr: int = SR):
    import librosa
    tempo, beat_frames = librosa.beat.beat_track(y=mono, sr=sr, units="samples")
    tempo = float(np.atleast_1d(tempo)[0])
    beats = np.asarray(beat_frames, dtype=np.int64)
    return tempo, beats


# --------------------------------------------------------------------------
# Feature extractors.
# --------------------------------------------------------------------------
def _band_rms(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
    from scipy.signal import butter, sosfiltfilt
    if len(x) < 16:
        return 0.0
    sos = butter(2, [lo, hi], "bandpass", fs=sr, output="sos")
    y = sosfiltfilt(sos, x)
    return float(np.sqrt(np.mean(y ** 2) + 1e-12))


def _lowpass(x: np.ndarray, sr: int, cutoff: float) -> np.ndarray:
    from scipy.signal import butter, sosfiltfilt
    sos = butter(2, cutoff, "lowpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x)


def frame_series(x: np.ndarray, sr: int, hop: int = 512) -> dict:
    """Per-frame band energies + onset strengths over the whole track."""
    sub = _lowpass(x, sr, 70.0)
    bass = _lowpass(x, sr, 160.0)
    import librosa
    onset_full = librosa.onset.onset_strength(y=x, sr=sr, hop_length=hop)
    onset_low = librosa.onset.onset_strength(y=bass, sr=sr, hop_length=hop)
    n = min(len(onset_full), len(onset_low), len(x) // hop)

    def framewise(sig):
        m = len(sig) // hop
        return np.sqrt(np.convolve(sig ** 2, np.ones(hop) / hop, mode="same")[:m * hop]
                       .reshape(m, hop).mean(axis=1) + 1e-12)

    return {
        "hop": hop,
        "n_frames": n,
        "sub_rms": framewise(sub),          # 20-70 Hz (kick fundamental)
        "bass_rms": framewise(bass),        # <160 Hz (kick+bass)
        "onset_full": onset_full[:n],
        "onset_low": onset_low[:n],
        "rms": framewise(x),
    }


def window_stats(series: dict, center_s: float, before_s: float, after_s: float,
                 sr: int = SR) -> dict:
    """Mean of each series in [center-before, center] vs [center, center+after]."""
    hop = series["hop"]
    c = int(center_s * sr / hop)

    def seg(arr, a_s, b_s):
        a, b = int(a_s * sr / hop), int(b_s * sr / hop)
        a, b = max(0, a), min(len(arr), b)
        return float(np.mean(arr[a:b])) if b > a else 0.0

    out = {}
    for k in ("sub_rms", "bass_rms", "onset_full", "onset_low", "rms"):
        arr = series[k]
        b = seg(arr, center_s - before_s, center_s)
        a = seg(arr, center_s, center_s + after_s)
        out[f"{k}_before"] = round(b, 5)
        out[f"{k}_after"] = round(a, 5)
        out[f"{k}_delta"] = round(a - b, 5)  # +ve => enters, -ve => drops out
    return out


def kick_onsets_near(mono: np.ndarray, sr: int, lo_s: float, hi_s: float,
                     threshold_rel: float = 0.5) -> list[float]:
    """Low-band onset times inside [lo_s, hi_s] — kick events for micro-edit
    detection (double-kick = two kicks closer than the beat grid)."""
    bass = _lowpass(mono, sr, 160.0)
    import librosa
    env = librosa.onset.onset_strength(y=bass, sr=sr)
    times = librosa.frames_to_time(np.arange(len(env)), sr=sr)
    mask = (times >= lo_s) & (times <= hi_s)
    peaks = librosa.util.peak_pick(env, pre_max=3, post_max=3, pre_avg=3,
                                   post_avg=3, delta=threshold_rel *
                                   (float(np.max(env[mask])) if mask.any() else 1.0),
                                   wait=1)
    return [round(float(times[p]), 3) for p in peaks if lo_s <= times[p] <= hi_s]


# --------------------------------------------------------------------------
# Anchor resolution.
# --------------------------------------------------------------------------
_LABEL_SCORE = {
    # label -> which physical change to maximise when snapping the anchor
    "DROP": "bass_entry",        # kick+bass slam in: quiet -> loud
    "BREAKDOWN": "bass_exit",    # kick+bass drop out: loud -> quiet
    "PRE_DROP_BUILD": "nearest", # build-up: no full kick yet -> stay near anchor
    "MINI_HOOK": "nearest",
    "MICRO_BREAK": "bass_exit",
    "GATED_SYNTH": "bass_exit",
    "OUTRO": "nearest",
    "LAST_GROOVE_LOOP": "nearest",
    "CLAP_ENTRY": "onset",       # mid transient enters
    "VOCAL_ENTRY": "nearest",
    "CLAP_HAT_FILL": "onset",
    "DOUBLE_KICK": "bass_entry",
}


def _bass_delta_at(bass_env, t_s, sr, beat_s, hop=512):
    """bass RMS in the beat AFTER t minus the beat BEFORE t (entry > 0)."""
    f = int(t_s * sr / hop)
    w = max(1, int(beat_s * sr / hop))
    before = float(bass_env[max(0, f - w):f].mean()) if f > 0 else 0.0
    after = float(bass_env[f:f + w].mean()) if f + w <= len(bass_env) else 0.0
    return after - before


def resolve_anchor(mono, beats, tempo, anchor_s, sr, label="", window_bars=2):
    """Snap an approximate anchor onto the beat grid inside +-window_bars,
    maximising the physical change that defines the label (bass entry for a
    DROP, bass exit for a BREAKDOWN, transient onset for CLAP, ...)."""
    import librosa
    beat_s = 60.0 / tempo
    bar_s = beat_s * 4.0
    lo, hi = anchor_s - window_bars * bar_s, anchor_s + window_bars * bar_s
    mode = _LABEL_SCORE.get(label, "onset")

    beat_times = beats / sr
    cand = [b for b in beat_times if lo <= b <= hi]
    if not cand:
        return anchor_s, None, 0.0

    bass = _lowpass(mono, sr, 160.0)
    bass_rms = np.sqrt(np.convolve(bass ** 2, np.ones(512) / 512, mode="same"))
    bass_env = bass_rms[::512]
    onset_env = librosa.onset.onset_strength(y=bass, sr=sr)

    def score(b):
        f = int(b * sr / 512)
        prox = 1.0 - abs(b - anchor_s) / (window_bars * bar_s)
        d = _bass_delta_at(bass_env, b, sr, beat_s)
        if mode == "bass_entry":
            return d + 0.02 * prox
        if mode == "bass_exit":
            return -d + 0.02 * prox
        if mode == "onset":
            v = float(onset_env[max(0, f - 1):f + 2].max()) if f < len(onset_env) else 0.0
            return v + 0.05 * prox
        return prox  # nearest

    best = max(cand, key=score)
    bar_idx = int(round(best / bar_s))
    conf = float(min(1.0, abs(score(best)) / (float(np.abs(bass_env).max()) or 1e-9)))
    return best, bar_idx, round(conf, 3)


# --------------------------------------------------------------------------
# Optional Demucs stem measurement (drums/bass/vocals deltas).
# --------------------------------------------------------------------------
def stem_deltas(stem_path: Path, anchor_s: float, before_s: float, after_s: float,
                sr: int = SR) -> dict:
    import soundfile as sf
    out = {}
    for stem in ("drums", "bass", "vocals"):
        p = stem_path / f"{stem}.wav"
        if not p.exists():
            continue
        data, ssr = sf.read(str(p), dtype="float32", always_2d=True)
        x = data.mean(axis=1)
        def rms(a_s, b_s):
            a, b = int(a_s * ssr), int(b_s * ssr)
            a, b = max(0, a), min(len(x), b)
            return float(np.sqrt(np.mean(x[a:b] ** 2) + 1e-12)) if b > a else 0.0
        b = rms(anchor_s - before_s, anchor_s)
        a = rms(anchor_s, anchor_s + after_s)
        out[f"{stem}_before"] = round(b, 5)
        out[f"{stem}_after"] = round(a, 5)
        out[f"{stem}_delta"] = round(a - b, 5)
    return out


def separate_stems(audio_path: Path, out_root: Path) -> Path:
    """Run htdemucs -> <out_root>/<stem>/{drums,bass,other,vocals}.wav."""
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    import soundfile as sf
    import torch

    model = get_model("htdemucs")
    model.eval()
    wav = load_stereo(audio_path, model.samplerate)
    ref = wav.mean(axis=1)
    x = torch.from_numpy(wav.T).float()[None]  # [1, 2, n]
    with torch.no_grad():
        est = apply_model(model, x, device="cpu", progress=False)[0]
    stem_dir = out_root / audio_path.stem
    stem_dir.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(model.sources):
        sf.write(str(stem_dir / f"{name}.wav"),
                 est[i].cpu().numpy().T, model.samplerate)
    return stem_dir


# --------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(prog="anchor_analysis")
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--music-dir", default="music")
    ap.add_argument("--out", default="renders/anchor_analysis.json")
    ap.add_argument("--stems", action="store_true",
                    help="also run htdemucs and measure stem deltas (slow)")
    ap.add_argument("--stems-root", default="renders/stems")
    args = ap.parse_args()

    ann = json.loads(Path(args.annotations).read_text(encoding="utf-8"))
    music = Path(args.music_dir)
    report = {"sr": SR, "tracks": {}}

    for fname, tdata in ann["tracks"].items():
        fpath = music / fname
        if not fpath.exists():
            report["tracks"][fname] = {"error": "file not found"}
            continue
        print(f"[analyze] {fname}", flush=True)
        mono = load_mono(fpath, SR)
        tempo, beats = beat_grid(mono, SR)
        beat_s = 60.0 / tempo
        series = frame_series(mono, SR)
        stem_dir = None
        if args.stems:
            print(f"  [demucs] separating {fname} ...", flush=True)
            stem_dir = separate_stems(fpath, Path(args.stems_root))

        entries = []
        for a in tdata.get("anchors", []):
            anchor_s = float(a["sec"])
            res_s, bar_idx, conf = resolve_anchor(mono, beats, tempo, anchor_s, SR,
                                                  label=a["label"])
            feats = window_stats(series, res_s, before_s=4 * beat_s,
                                 after_s=4 * beat_s, sr=SR)
            entry = {
                "label": a["label"],
                "anchorSec": anchor_s,
                "resolvedSec": round(res_s, 3),
                "bar": bar_idx,
                "confidence": conf,
                "note": a.get("note", ""),
                **feats,
            }
            # micro-edit: count kicks in the +-1 bar neighbourhood
            kicks = kick_onsets_near(mono, SR, res_s - 4 * beat_s,
                                     res_s + 4 * beat_s)
            entry["kickTimesNear"] = kicks
            entry["kickCountNear"] = len(kicks)
            if stem_dir is not None:
                entry["stems"] = stem_deltas(stem_dir, res_s, 4 * beat_s,
                                             4 * beat_s, model_sr := SR)
            entries.append(entry)
            print(f"    {a['label']:<16} anchor={anchor_s:7.2f} -> {res_s:7.2f}s "
                  f"bar={bar_idx} conf={conf:.2f} subD={feats['sub_rms_delta']:+.4f} "
                  f"bassD={feats['bass_rms_delta']:+.4f}", flush=True)

        report["tracks"][fname] = {
            "bpm": round(tempo, 2),
            "beatSec": round(beat_s, 4),
            "userPreference": tdata.get("userPreference"),
            "anchors": entries,
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\n[wrote] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
