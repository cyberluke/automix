"""CyberLuke CTO Synth — CyberSynth.

JP-8000/8080-style supersaw: N detuned saw oscillators → resonant lowpass →
stereo chorus. Pure numpy/scipy, offline render. Runs in .venv-hypermix.

Design goals (neurofunk D&B context):
- brighter & tighter than the original production layer it reinforces
- phase-aligned note starts (no sloppy attack) so it locks to the beat grid
- gentle chorus for width without smearing transients
"""

from __future__ import annotations

import numpy as np

from .types import NoteEvent, SPRConfig


def _midi_to_hz(midi: float) -> float:
    return 440.0 * (2.0 ** ((midi - 69.0) / 12.0))


def _saw(phase: np.ndarray) -> np.ndarray:
    """Band-limited-ish naive saw from phase 0..1 → -1..1 (PolyBLEP-lite skipped:
    for reinforcement layering at -20 dB the aliasing is masked by the original)."""
    return 2.0 * (phase % 1.0) - 1.0


def _env(n: int, sr: int, attack_s: float, release_s: float) -> np.ndarray:
    """AR envelope. Attack linear, release exponential-ish."""
    env = np.ones(n, dtype=np.float32)
    a = max(1, int(attack_s * sr))
    r = max(1, int(release_s * sr))
    a = min(a, n)
    r = min(r, n)
    env[:a] = np.linspace(0.0, 1.0, a, dtype=np.float32)
    if r > 0:
        env[-r:] *= np.linspace(1.0, 0.0, r, dtype=np.float32) ** 2
    return env


def _render_supersaw_voice(freq_hz: float, n: int, sr: int, detune_cents: float,
                           cfg: SPRConfig) -> np.ndarray:
    f = freq_hz * (2.0 ** (detune_cents / 1200.0))
    phase = np.cumsum(np.full(n, f / sr, dtype=np.float64))
    sig = _saw(phase).astype(np.float32)
    return sig


def _lowpass(x: np.ndarray, cutoff_hz: float, resonance: float, sr: int) -> np.ndarray:
    """One-pole resonant-ish lowpass. For V1 a clean Butterworth LP is enough;
    resonance emulated by a slight pre-emphasis peak near cutoff."""
    from scipy.signal import butter, sosfilt
    nyq = sr / 2.0
    c = float(np.clip(cutoff_hz / nyq, 0.01, 0.95))
    sos = butter(4, c, btype="low", output="sos")
    y = sosfilt(sos, x)
    if resonance > 0.0:
        # crude resonance: band-pass bump at cutoff, mixed in
        lo = max(0.01, c * 0.8)
        hi = min(0.99, c * 1.2)
        if hi > lo:
            sos_bp = butter(2, [lo, hi], btype="band", output="sos")
            bump = sosfilt(sos_bp, x)
            y = y + resonance * 0.5 * bump.astype(np.float32)
    return y.astype(np.float32)


def _chorus(x: np.ndarray, sr: int, rate_hz: float, depth_ms: float, mix: float) -> np.ndarray:
    """Stereo chorus: two LFO-modulated delays (L/R quadrature)."""
    n = len(x)
    t = np.arange(n) / sr
    base_ms = 12.0
    lfo_l = np.sin(2 * np.pi * rate_hz * t)
    lfo_r = np.sin(2 * np.pi * rate_hz * t + np.pi / 2)
    delay_l = ((base_ms + depth_ms * lfo_l) * 1e-3 * sr).astype(np.int64)
    delay_r = ((base_ms + depth_ms * lfo_r) * 1e-3 * sr).astype(np.int64)

    def _fetch(delay: np.ndarray) -> np.ndarray:
        idx = np.arange(n) - delay
        idx = np.clip(idx, 0, n - 1)
        return x[idx]

    wet_l = _fetch(delay_l)
    wet_r = _fetch(delay_r)
    dry = (1.0 - mix) * x
    left = dry + mix * wet_l
    right = dry + mix * wet_r
    return np.stack([left, right], axis=1).astype(np.float32)


def render_notes(notes: list[NoteEvent], cfg: SPRConfig,
                 transpose_semitones: int = 0,
                 tail_s: float = 0.25,
                 bpm: float = 174.0,
                 min_total: int = 0) -> np.ndarray:
    """Render notes through the CyberSynth → stereo float32 [n, 2] at cfg.sr.
    `min_total` pads the output to at least that many samples (the full crop
    length) so notes in the first half are never truncated by a short tail."""
    sr = cfg.sr
    if not notes:
        return np.zeros((max(min_total, sr // 10), 2), dtype=np.float32)

    end_s = max(n.start_s + n.dur_s for n in notes) + tail_s
    total = max(int(np.ceil(end_s * sr)) + 1, min_total)

    # Sum supersaw voices
    voice_offsets = np.linspace(-cfg.supersaw_detune_cents / 2,
                                cfg.supersaw_detune_cents / 2,
                                cfg.supersaw_voices)
    mix = np.zeros(total, dtype=np.float32)

    for note in notes:
        freq = _midi_to_hz(note.midi + transpose_semitones)
        i0 = int(note.start_s * sr)
        n_samp = int(note.dur_s * sr) + 1
        if n_samp <= 0 or i0 >= total:
            continue
        n_samp = min(n_samp, total - i0)
        env = _env(n_samp, sr, cfg.attack_s, cfg.release_s) * note.velocity

        voice = np.zeros(n_samp, dtype=np.float32)
        for off in voice_offsets:
            voice += _render_supersaw_voice(freq, n_samp, sr, off, cfg)
        voice /= float(len(voice_offsets))
        mix[i0:i0 + n_samp] += voice * env

    # Filter (clean LP) → MS-20-style drive with ±10% 1-beat sinus LFO → chorus
    mix = _lowpass(mix, cfg.filter_cutoff_hz, cfg.filter_resonance, sr)
    mix = _drive_lfo(mix, cfg, sr, bpm)

    # Normalize headroom (leave -6 dBFS)
    peak = float(np.max(np.abs(mix)))
    if peak > 1e-6:
        mix *= (0.5 / peak)

    # Chorus → stereo
    stereo = _chorus(mix, sr, cfg.chorus_rate_hz, cfg.chorus_depth_ms, cfg.chorus_mix)
    return stereo


def repeat_note_throw(stereo: np.ndarray, sr: int,
                      notes: list[NoteEvent], count: int = 2,
                      interval_s: float = 0.16, decay: float = 0.55) -> np.ndarray:
    """MANUAL echo: duplicate the PENULTIMATE note's audio `count` times in quick
    succession, each repeat quieter (×decay). Covers a missing last note like a
    real echo-repeat a DJ would ride — no wonky ping-pong, perfectly in time."""
    if len(notes) < 2:
        return stereo
    n = len(stereo)
    penult = notes[-2]
    src_i = int(penult.start_s * sr)
    src_n = int(penult.dur_s * sr)
    if src_n <= 0 or src_i >= n:
        return stereo
    src_n = min(src_n, n - src_i)
    seg = stereo[src_i:src_i + src_n].copy()
    out = stereo.copy()
    # place repeats right after the note ends, quick succession, decaying volume
    place = src_i + src_n
    gain = 1.0
    for r in range(count):
        gain *= decay
        if place >= n:
            break
        seg_len = min(src_n, n - place)
        out[place:place + seg_len] += seg[:seg_len] * gain
        place += int(interval_s * sr)
    # soft-clip safety
    np.clip(out, -1.0, 1.0, out=out)
    return out.astype(np.float32)


def gap_fill_repeats(stereo: np.ndarray, sr: int,
                     notes: list[NoteEvent], min_gap_s: float = 0.08,
                     interval_s: float = 0.16, decay: float = 0.60) -> np.ndarray:
    """MEGAMIX groove-filler: for EVERY silent gap between consecutive notes,
    echo-repeat the PREVIOUS note into the hole (quick succession, decaying
    volume) so the loop never loses rhythm. Universal + deterministic — same
    behaviour for every song, driven purely by the note grid."""
    if len(notes) < 2:
        return stereo
    n = len(stereo)
    out = stereo.copy()
    for i in range(len(notes) - 1):
        cur = notes[i]
        nxt = notes[i + 1]
        gap_s = nxt.start_s - (cur.start_s + cur.dur_s)
        if gap_s < min_gap_s:
            continue
        # source = the current note's audio tail
        src_i = int(cur.start_s * sr)
        src_n = int(cur.dur_s * sr)
        if src_n <= 0 or src_i >= n:
            continue
        src_n = min(src_n, n - src_i)
        seg = stereo[src_i:src_i + src_n].copy()
        # fill the gap with decaying repeats spaced `interval_s` apart
        gap_i = int((cur.start_s + cur.dur_s) * sr)
        gap_end = int(nxt.start_s * sr)
        place = gap_i
        gain = 1.0
        while place < gap_end and place < n:
            gain *= decay
            seg_len = min(src_n, gap_end - place, n - place)
            if seg_len <= 0:
                break
            out[place:place + seg_len] += seg[:seg_len] * gain
            place += int(interval_s * sr)
    np.clip(out, -1.0, 1.0, out=out)
    return out.astype(np.float32)


def _drive_lfo(mix: np.ndarray, cfg: SPRConfig, sr: int, bpm: float) -> np.ndarray:
    """MS-20-style soft-clip drive, tamed ~50% vs before, with a sinus LFO
    modulating the drive ±10% at 1 cycle per beat → organic movement."""
    base = float(getattr(cfg, 'filter_drive', 0.5))  # already halved default
    depth = float(getattr(cfg, 'filter_drive_lfo_depth', 0.10))
    n = len(mix)
    if getattr(cfg, 'filter_drive_lfo_per_beat', True) and bpm > 0:
        beat_s = 60.0 / bpm
        lfo_rate = 1.0 / beat_s
    else:
        lfo_rate = 0.5  # fallback slow wobble
    t = np.arange(n) / sr
    lfo = 1.0 + depth * np.sin(2 * np.pi * lfo_rate * t)  # 1±depth
    drive = base * lfo * 4.0  # scale into a usable tanh range
    return np.tanh(drive * mix).astype(np.float32) / np.tanh(drive)


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)) + 1e-12)


def brighten(layer: np.ndarray, sr: int, drive: float = 0.6, mix: float = 0.35,
             shelf_hz: float = 3200.0, shelf_db: float = 5.0) -> np.ndarray:
    """Make the supersaw cut through: (1) parallel high-shelf presence boost on
    the dry signal, (2) a harmonic-exciter (soft-clip) band blended in. Adds
    upper-harmonic 'air' so notes poke out of a dense mix instead of hiding
    under the bass/lead bed. Returns stereo float32, same shape."""
    from scipy.signal import butter, sosfilt
    x = layer.astype(np.float32)
    if x.ndim == 1:
        x = np.column_stack([x, x])
    nyq = sr / 2.0
    c = float(np.clip(shelf_hz / nyq, 0.01, 0.99))
    sos_hp = butter(2, c, btype="high", output="sos")
    highs = sosfilt(sos_hp, x, axis=0)
    gain = float(10.0 ** (shelf_db / 20.0))
    shelved = x + (gain - 1.0) * highs            # (1) presence shelf
    driven = np.tanh(drive * 3.0 * highs)         # (2) exciter harmonics
    out = shelved + mix * driven
    peak = float(np.max(np.abs(out)))
    if peak > 1e-6:
        out *= (0.95 / peak)
    return out.astype(np.float32)


def highpass(layer: np.ndarray, sr: int, cutoff_hz: float = 160.0) -> np.ndarray:
    """Clean 2-pole Butterworth high-pass. De-mud: removes the low-end build-up
    that makes the synth fight the bass/drums and sound dull."""
    from scipy.signal import butter, sosfilt
    x = layer.astype(np.float32)
    if x.ndim == 1:
        x = np.column_stack([x, x])
    nyq = sr / 2.0
    c = float(np.clip(cutoff_hz / nyq, 0.005, 0.5))
    sos = butter(2, c, btype="high", output="sos")
    return sosfilt(sos, x, axis=0).astype(np.float32)


def brickwall(layer: np.ndarray, threshold: float = 0.7) -> np.ndarray:
    """Brickwall peak limiter: clamp every channel to ±threshold so the
    gap-fill / drive / 4x-filter sums can never produce a volume spike."""
    x = layer.astype(np.float32)
    return (np.clip(x, -threshold, threshold) / max(threshold, 1e-6)).astype(np.float32) * 0.9


def mix_layers(original: np.ndarray, layer: np.ndarray,
               original_gain_db: float, layer_gain_db: float,
               layer_duck_db: float = 0.0) -> np.ndarray:
    """Mix original/backing + reinforcement layer with gain staging.
    `layer_duck_db` attenuates the ORIGINAL (backing bed) relative to the layer
    so the replacement synth/melody pokes through a dense mix."""
    """Mix original phrase + reinforcement layer with gain staging.

    The layer is first RMS-normalized to the original phrase's level so the
    gain staging behaves identically regardless of which branch produced the
    layer (supersaw / resample / vocoder all have different intrinsic RMS).
    """
    n = max(len(original), len(layer))
    def _fit(x: np.ndarray) -> np.ndarray:
        if x.ndim == 1:
            x = np.column_stack([x, x])
        out = np.zeros((n, 2), dtype=np.float32)
        m = min(n, len(x))
        out[:m] = x[:m]
        return out
    o_raw = _fit(original)
    l_raw = _fit(layer)
    # Normalize layer RMS to match the phrase RMS, then apply gain offsets.
    o_rms = _rms(o_raw)
    l_rms = _rms(l_raw)
    if l_rms > 1e-9 and o_rms > 1e-9:
        l_raw = l_raw * (o_rms / l_rms)
    o = o_raw * (10.0 ** ((original_gain_db + layer_duck_db) / 20.0))
    l = l_raw * (10.0 ** (layer_gain_db / 20.0))
    y = o + l
    # Gentle soft-knee glue (not a hard clamp) to catch accidental overs, then a
    # safety headroom trim. Leaves dynamics intact so there are no 'spikes'.
    y = np.tanh(y * 1.1) * 0.9
    peak = float(np.max(np.abs(y)))
    if peak > 0.9:
        y *= (0.9 / peak)
    return y.astype(np.float32)
