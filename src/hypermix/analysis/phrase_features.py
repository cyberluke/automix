"""Phrase-native feature extraction (§-phrase-native upgrade).

THE PHRASE IS THE UNIT OF MUSICAL REASONING. A track is only a container.

Every feature here is computed PER PHRASE from short STFT windows, so we get a
*distribution* (median / percentiles / slope / variance), not a single FFT
snapshot. Two phrases can share a mean spectral centroid yet be musically
opposite (constant-bright vs dark-with-a-riser); only the distribution and the
*slope* tell them apart. Slopes are what make build-up ("we're ramping into the
drop") mathematically detectable.

Deterministic, float32-in / plain-dicts-out. No track-level scalars leak into
mix decisions — track context is derived separately for normalization only.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

# Frequency band edges (Hz) for occupancy / low-end analysis.
SUB_HI = 60.0
BASS_HI = 200.0
LOMID_HI = 500.0
MID_HI = 2000.0
HIMID_HI = 6000.0
# Vocal formant band (rough telephonic-ish presence region).
VOCAL_LO = 300.0
VOCAL_HI = 3400.0


def _mono(samples: np.ndarray) -> np.ndarray:
    return samples.mean(axis=1) if samples.ndim > 1 else samples


def _slope(series: np.ndarray) -> float:
    """Normalised linear slope of a per-frame series (-1..+1-ish)."""
    s = np.asarray(series, dtype=np.float64)
    if s.size < 3:
        return 0.0
    t = np.arange(s.size, dtype=np.float64)
    t = (t - t.mean()) / (np.ptp(t) + 1e-9)
    m = float(np.polyfit(t, s, 1)[0])
    scale = float(np.abs(s).mean()) + 1e-9
    return float(np.clip(m / scale, -1.0, 1.0))


def _pct(series: np.ndarray, q: float) -> float:
    return float(np.percentile(series, q)) if np.asarray(series).size else 0.0


def extract_phrase_features(samples: np.ndarray, sr: int, bpm: float) -> Dict[str, Any]:
    """Compute the full per-phrase feature vector.

    Returns a nested dict matching the §9 schema:
        {spectral, rhythm, content, loudness, low_end, slopes, derived}
    All values are floats; raw features are kept so the scoring model can be
    re-weighted later without re-running DSP.
    """
    mono = _mono(samples).astype(np.float32)
    n = mono.shape[0]
    empty = _empty_features()
    if n < 2048 or bpm <= 0:
        return empty

    import librosa  # local import: heavy, deterministic
    hop = 512
    n_fft = 2048
    S = np.abs(librosa.stft(mono, n_fft=n_fft, hop_length=hop))
    power = S ** 2
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    n_frames = S.shape[1]

    # ---- spectral distribution ----
    cent = librosa.feature.spectral_centroid(S=S, sr=sr)[0]
    bw = librosa.feature.spectral_bandwidth(S=S, sr=sr)[0]
    rolloff = librosa.feature.spectral_rolloff(S=S, sr=sr)[0]
    flat = librosa.feature.spectral_flatness(S=S)[0]
    contrast = librosa.feature.spectral_contrast(S=S, sr=sr).mean(axis=0)
    flux = np.sqrt(((power[:, 1:] - power[:, :-1]) ** 2).mean(axis=0)) if n_frames > 1 else np.zeros(1)

    nyq = sr / 2.0
    tot = power.sum(axis=0) + 1e-9
    def band_ratio(lo: float, hi: float) -> np.ndarray:
        m = (freqs >= lo) & (freqs < hi)
        return power[m].sum(axis=0) / tot

    sub_r = band_ratio(0.0, SUB_HI)
    bass_r = band_ratio(SUB_HI, BASS_HI)
    lomid_r = band_ratio(BASS_HI, LOMID_HI)
    mid_r = band_ratio(LOMID_HI, MID_HI)
    himid_r = band_ratio(MID_HI, HIMID_HI)
    high_r = band_ratio(HIMID_HI, nyq)
    vocal_band_r = band_ratio(VOCAL_LO, VOCAL_HI)

    # ---- loudness / dynamics ----
    rms_frames = librosa.feature.rms(S=S)[0]
    peak = float(np.max(np.abs(mono)))
    rms = float(np.sqrt((mono ** 2).mean()))
    crest = peak / (rms + 1e-9)
    dyn_range = float(_pct(rms_frames, 95) - _pct(rms_frames, 10))

    # ---- rhythm / transients ----
    try:
        onset_env = librosa.onset.onset_strength(y=mono, sr=sr, hop_length=hop)
    except Exception:
        onset_env = np.zeros(n_frames, dtype=np.float32)
    dur_sec = max(1e-6, n / sr)
    onset_density = float((onset_env > (onset_env.mean() + onset_env.std())).sum() / dur_sec)
    onset_strength = float(onset_env.mean())
    transient_density = float(_pct(onset_env, 90))
    # kick activity: low-band flux emphasising the kick region.
    kick_activity = float(_pct(np.sqrt(((power[freqs < BASS_HI][:, 1:] - power[freqs < BASS_HI][:, :-1]) ** 2).mean(axis=0)), 90)) if n_frames > 1 else 0.0

    # ---- harmonic / tonal (fast: median-filter HPSS on the magnitude we
    # already computed, and a chroma projection of the harmonic part) ----
    try:
        from scipy.ndimage import median_filter
        H = median_filter(S, size=(1, 31))
        P = median_filter(S, size=(31, 1))
        harmonic_ratio = float(np.sqrt((H ** 2).mean()) / (np.sqrt((S ** 2).mean()) + 1e-9))
        percussive_ratio = float(np.sqrt((P ** 2).mean()) / (np.sqrt((S ** 2).mean()) + 1e-9))
        chroma = librosa.feature.chroma_stft(S=H ** 2, sr=sr, n_fft=n_fft)
        chroma_strength = float(np.max(chroma.sum(axis=0)) / (chroma.sum() + 1e-9) * chroma.shape[1])
    except Exception:
        harmonic_ratio = percussive_ratio = chroma_strength = 0.0

    # ---- vocal content (heuristic: vocal-band energy + stability) ----
    vocal_energy_ratio = float(vocal_band_r.mean())
    # Vocals fluctuate in the formant band AND occupy a meaningful share of
    # total energy. A steady synth pad fluctuates a little; drums/bass leave
    # the vocal band quiet. Combine band share with band self-modulation so a
    # track that is all kick+bass does not read as vocal.
    vb = vocal_band_r
    band_share = float(np.clip(vb.mean() / 0.28, 0.0, 1.0))      # vs typical vocal share
    modulation = float(np.clip(vb.std() / (vb.mean() + 1e-9), 0.0, 1.0))
    vocal_probability = float(np.clip(band_share * (0.4 + 0.6 * modulation), 0.0, 1.0))
    vocal_onset_density = float((vb[1:] - vb[:-1] > vb.std()).sum() / dur_sec) if n_frames > 1 else 0.0

    # ---- slopes (build-up signature) ----
    slopes = {
        "centroid": _slope(cent),
        "flux": _slope(flux),
        "rms": _slope(rms_frames),
        "bass_ratio": _slope(bass_r),
        "high_ratio": _slope(high_r),
        "low_energy": _slope(sub_r + bass_r),
        "onset_strength": _slope(onset_env),
    }

    feats: Dict[str, Any] = {
        "loudness": {
            "rms": rms, "peak": peak, "crest": crest,
            "dynamic_range": dyn_range,
        },
        "spectral": {
            "centroid_mean": float(cent.mean() / nyq),
            "centroid_median": _pct(cent, 50) / nyq,
            "centroid_p10": _pct(cent, 10) / nyq,
            "centroid_p90": _pct(cent, 90) / nyq,
            "centroid_slope": slopes["centroid"],
            "bandwidth_mean": float(bw.mean() / nyq),
            "rolloff_mean": float(rolloff.mean() / nyq),
            "flatness_mean": float(flat.mean()),
            "contrast_mean": float(contrast.mean()),
            "flux_mean": float(flux.mean()),
            "flux_p90": _pct(flux, 90),
            "sub_ratio": float(sub_r.mean()),
            "bass_ratio": float(bass_r.mean()),
            "lomid_ratio": float(lomid_r.mean()),
            "mid_ratio": float(mid_r.mean()),
            "himid_ratio": float(himid_r.mean()),
            "high_ratio": float(high_r.mean()),
        },
        "rhythm": {
            "onset_density": onset_density,
            "onset_strength": onset_strength,
            "transient_density": transient_density,
            "kick_activity": kick_activity,
            "percussive_ratio": percussive_ratio,
        },
        "content": {
            "vocal_probability": vocal_probability,
            "vocal_energy_ratio": vocal_energy_ratio,
            "vocal_onset_density": vocal_onset_density,
            "harmonic_ratio": harmonic_ratio,
            "percussive_ratio": percussive_ratio,
            "chroma_strength": chroma_strength,
        },
        "slopes": slopes,
    }
    feats["perceived_energy"] = _perceived_energy(feats)
    feats["roles"] = classify_phrase(feats)
    return feats


def _perceived_energy(f: Dict[str, Any]) -> float:
    """Loudness is NOT energy. A compressed quiet breakdown can read loud in RMS
    yet feel low-energy; a drop reads similar loudness but far higher energy
    because of kick density, bass activity, transients, spectral width, HF
    content and rhythmic activity. Weighted heuristic over the raw features."""
    sp = f["spectral"]; rh = f["rhythm"]; lo = f["loudness"]; sl = f["slopes"]
    loud = float(np.clip(lo["rms"] * 6.0, 0.0, 1.0))           # ~normalised
    rhythmic = float(np.clip(rh["onset_density"] / 8.0, 0.0, 1.0))
    transient = float(np.clip(rh["transient_density"] / (rh["transient_density"] + 4.0), 0.0, 1.0))
    bass_act = float(np.clip(rh["kick_activity"] / (rh["kick_activity"] + 0.05), 0.0, 1.0))
    bright = float(np.clip(sp["centroid_median"], 0.0, 1.0))
    width = float(np.clip(sp["bandwidth_mean"], 0.0, 1.0))
    hf = float(np.clip(sp["high_ratio"] * 3.0, 0.0, 1.0))
    build = float(np.clip(0.5 + 0.5 * sl["rms"], 0.0, 1.0))    # rising = energy
    e = (0.22 * loud + 0.20 * rhythmic + 0.16 * transient +
         0.18 * bass_act + 0.10 * bright + 0.08 * width +
         0.04 * hf + 0.02 * build)
    return float(np.clip(e, 0.0, 1.0))


def classify_phrase(f: Dict[str, Any]) -> List[Dict[str, float]]:
    """Multi-label semantic role classification with confidence.

    Roles: VOCAL_DOMINANT, VOCAL_LIGHT, INSTRUMENTAL, PERCUSSIVE,
    BASS_DOMINANT, MELODIC, BREAKDOWN, BUILD, DROP_HOOK, OUTRO.
    """
    sp = f["spectral"]; rh = f["rhythm"]; co = f["content"]; sl = f["slopes"]
    pe = f["perceived_energy"]
    roles: List[Dict[str, float]] = []

    def add(role: str, conf: float) -> None:
        conf = float(np.clip(conf, 0.0, 1.0))
        if conf >= 0.35:
            roles.append({"role": role, "confidence": round(conf, 3)})

    add("VOCAL_DOMINANT", co["vocal_probability"] * 1.2 if co["vocal_energy_ratio"] > 0.30 else 0.0)
    add("VOCAL_LIGHT", co["vocal_probability"] * 0.8 if 0.15 < co["vocal_energy_ratio"] <= 0.30 else 0.0)
    add("INSTRUMENTAL", 1.0 - co["vocal_probability"])
    add("PERCUSSIVE", rh["percussive_ratio"])
    add("BASS_DOMINANT", float(np.clip((sp["sub_ratio"] + sp["bass_ratio"]) * 1.8, 0.0, 1.0)))
    add("MELODIC", co["harmonic_ratio"] * float(np.clip(co["chroma_strength"] * 2.0, 0.0, 1.0)))

    # Structural roles from energy + slopes.
    rising = (sl["rms"] > 0.25 and sl["centroid"] > 0.15) or (sl["high_ratio"] > 0.25 and sl["flux"] > 0.2)
    add("BUILD", (0.5 + 0.5 * sl["rms"]) * (0.5 + 0.5 * sl["centroid"]) if rising else 0.0)
    add("DROP_HOOK", pe * (0.6 + 0.4 * float(np.clip(rh["kick_activity"] / (rh["kick_activity"] + 0.05), 0.0, 1.0))))
    add("BREAKDOWN", (1.0 - pe) * (0.5 + 0.5 * float(np.clip(sp["bass_ratio"] * 2.0, 0.0, 1.0))))
    # OUTRO: low energy + decaying.
    add("OUTRO", (1.0 - pe) * (0.5 - 0.5 * sl["rms"]) if sl["rms"] < -0.1 else 0.0)

    roles.sort(key=lambda r: -r["confidence"])
    return roles


def _empty_features() -> Dict[str, Any]:
    return {
        "loudness": {"rms": 0.0, "peak": 0.0, "crest": 0.0, "dynamic_range": 0.0},
        "spectral": {k: 0.0 for k in (
            "centroid_mean", "centroid_median", "centroid_p10", "centroid_p90",
            "centroid_slope", "bandwidth_mean", "rolloff_mean", "flatness_mean",
            "contrast_mean", "flux_mean", "flux_p90", "sub_ratio", "bass_ratio",
            "lomid_ratio", "mid_ratio", "himid_ratio", "high_ratio")},
        "rhythm": {k: 0.0 for k in (
            "onset_density", "onset_strength", "transient_density",
            "kick_activity", "percussive_ratio")},
        "content": {k: 0.0 for k in (
            "vocal_probability", "vocal_energy_ratio", "vocal_onset_density",
            "harmonic_ratio", "percussive_ratio", "chroma_strength")},
        "slopes": {k: 0.0 for k in (
            "centroid", "flux", "rms", "bass_ratio", "high_ratio",
            "low_energy", "onset_strength")},
        "perceived_energy": 0.0,
        "roles": [],
    }
