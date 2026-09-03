"""Deterministic golden render (§18). Renders a SetPlan into golden.wav +
timeline/events/report. Same pack + seed + commands => byte-identical assets."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from ..audio_io import CanonicalAudio, atomic_write_wav
from ..transitions.dsp import (declick_join, ms20_open, load_voice_tag,
                                 glitch_bitch, filter_automation, duck_under,
                               chop_on_gaps, render_chop_sequence)
from ..config import DEFAULT_CONFIG
from ..hashing import sha256_file
from ..model import PackEvent, Segment, TransitionEdge
from .set_compiler import SetPlan


def _last_kick_sample(samples: np.ndarray, sr: int, bpm: float) -> int:
    """Sample index of the END of the last beat whose low-band (kick+bass) is
    still playing. Used in cut mode so a hard cut lands on the final beat that
    still has the kick, not inside a trailing breakdown (kick drops out a few
    beats before phrase end -> a cut there kills mix energy).

    Beat energy is measured per exact beat-length sample window, so the returned
    index is always an exact integer multiple of one beat in samples -> the cut
    lands exactly ON the beat grid (no off-beat gap before the next drop).

    Returns len(samples) when no drop-out is detected (segment stays hot to the
    end). Deterministic: pure function of (samples, sr, bpm).
    """
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    n = mono.shape[0]
    if n < sr or not bpm:
        return n
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, 160.0 / (sr / 2.0), btype="low", output="sos")
    bass = sosfiltfilt(sos, mono)
    spb = int(round(sr * 60.0 / float(bpm)))  # exact samples per beat
    if spb < 1:
        return n
    n_beats = n // spb
    if n_beats < 8:
        return n
    trimmed = bass[: n_beats * spb]
    beat_e = np.sqrt((trimmed.reshape(n_beats, spb) ** 2).mean(axis=1))
    hot_mask = beat_e > 1e-4
    if not np.any(hot_mask):
        return n
    hot = float(np.median(beat_e[hot_mask]))
    thresh = 0.25 * hot  # beat "has kick" if its bass >= 25% of the hot median
    last = n_beats - 1
    while last > 0 and beat_e[last] < thresh:
        last -= 1
    # Trim only when the tail actually dies; otherwise keep the full segment.
    if last >= n_beats - 2:
        # Tail looks hot, but a dead patch can sit EARLIER in the segment (the
        # kick drops out for a mid-phrase break, then a final hit or two come
        # back at the very end). Cut at the start of the dead patch instead.
        dead = [k for k in range(n_beats - 2) if beat_e[k] < thresh]
        if len(dead) >= 3:
            last = dead[0] - 1
        else:
            return n
    # Snap the cut to the END of the BAR containing the last hot beat, so a
    # vocal/musical phrase finishes on the barline instead of being chopped
    # mid-word by a mid-beat release. Use the exact (un-rounded) samples-per-
    # beat so the bar boundary doesn't drift over a long segment. If that bar
    # end would exceed the clip, fall back to the START of that bar (cut just
    # before the phrase).
    exact_spb = sr * 60.0 / float(bpm)
    bar_end = int(round((int(last // 4) + 1) * 4 * exact_spb))
    if bar_end <= n:
        return bar_end
    bar_start = int(round(int(last // 4) * 4 * exact_spb))
    return max(0, min(n, bar_start))


def _drop_start_sample(samples: np.ndarray, sr: int, bpm: float) -> int:
    """Sample index of the FIRST beat whose kick+bass is already playing.

    In cut mode we want drop->drop: skip any quiet/beatless lead-in at the top
    of the next segment so the cut lands exactly on the incoming drop's first
    downbeat, on the exact beat grid (no perceived gap into a build-up).
    Returns 0 when the segment is hot from the very first beat (or no clear
    lead-in is found).
    """
    mono = samples.mean(axis=1) if samples.ndim > 1 else samples
    n = mono.shape[0]
    if n < sr or not bpm:
        return 0
    from scipy.signal import butter, sosfiltfilt
    sos = butter(4, 160.0 / (sr / 2.0), btype="low", output="sos")
    bass = sosfiltfilt(sos, mono)
    spb = int(round(sr * 60.0 / float(bpm)))
    if spb < 1:
        return 0
    n_beats = n // spb
    if n_beats < 4:
        return 0
    trimmed = bass[: n_beats * spb]
    beat_e = np.sqrt((trimmed.reshape(n_beats, spb) ** 2).mean(axis=1))
    hot_mask = beat_e > 1e-4
    if not np.any(hot_mask):
        return 0
    hot = float(np.median(beat_e[hot_mask]))
    thresh = 0.25 * hot
    # Only treat it as a lead-in when the first beat is clearly quiet and a hot
    # beat shows up soon after (<= 8 beats) -> that's the drop to snap to.
    if beat_e[0] >= thresh:
        return 0
    for k in range(1, min(9, n_beats)):
        if beat_e[k] >= thresh:
            return k * spb
    return 0


# IDENTITY FX voice-tag cache: keyed by (sr, bpm) so a given render run glitches
# the tag once and reuses it (deterministic). Resolved lazily so a missing tag
# never breaks a render — it just logs & skips the overlay.
_VOICE_TAG_CACHE: Dict[tuple, Optional[np.ndarray]] = {}
_VOICE_TAG_PATH = Path("samples/voice_tags/Cyberluke2.wav")


def _clean_voice_tag(sr: int) -> Optional[np.ndarray]:
    """Load Cyberluke2.wav CLEAN (no FX) at canonical sr, normalized to a
    healthy peak so it's audible over the drop. Cached per sr (deterministic).
    The Glitch Bitch effect is applied to the MUSIC after the tag ends, not to
    the tag itself."""
    key = int(sr)
    if key in _VOICE_TAG_CACHE:
        return _VOICE_TAG_CACHE[key]
    out: Optional[np.ndarray] = None
    if _VOICE_TAG_PATH.exists():
        try:
            raw = load_voice_tag(_VOICE_TAG_PATH, sr)
            peak = float(np.abs(raw).max())
            if peak > 1e-6:
                raw = (raw * np.float32(0.6 / peak)).astype(np.float32)
            out = raw
        except Exception:
            out = None
    _VOICE_TAG_CACHE[key] = out
    return out


# deep_dance chop sequence (2nd-track IDENTITY FX). Cached per (sr, bpm).
_DEEP_DANCE_PATH = Path("samples/voice_tags/deep_dance2.wav")
_DEEP_DANCE_CACHE: Dict[tuple, Optional[np.ndarray]] = {}
# "deep" and "dance" land TWO beats apart (beat 1 and beat 3) so each word
# breathes, then the fast 1/8-note chop rhythm (deep deep dance dance x2)
# picks up the pace afterwards.
_DEEP_DANCE_SLOTS = [(0, 2.0), (1, 2.0),
                     (0, 0.5), (0, 0.5), (1, 0.5), (1, 0.5),
                     (0, 0.5), (0, 0.5), (1, 0.5), (1, 0.5)]


def _deep_dance_sequence(sr: int, bpm: float) -> Optional[np.ndarray]:
    """Chop deep_dance2.wav into ["deep","dance"] and lay them on the beat:
    deep on beat 1, dance on beat 2, then a fast 1/8-note chop rhythm.
    Cached per (sr, bpm); deterministic. None when the sample is missing."""
    key = (int(sr), round(float(bpm), 3))
    if key in _DEEP_DANCE_CACHE:
        return _DEEP_DANCE_CACHE[key]
    out: Optional[np.ndarray] = None
    if _DEEP_DANCE_PATH.exists():
        try:
            raw = load_voice_tag(_DEEP_DANCE_PATH, sr)
            chops = chop_on_gaps(raw, sr)
            if len(chops) >= 2:
                spb = sr * 60.0 / float(bpm)
                tail = max(c.shape[0] for c in chops)
                last = spb * sum(d for _, d in _DEEP_DANCE_SLOTS[:-1])
                total = int(round(last + tail))
                buf = np.zeros((total, 2), dtype=np.float32)
                pos = 0.0
                for ci, div in _DEEP_DANCE_SLOTS:
                    s = int(round(pos))
                    c = chops[ci]
                    e = min(total, s + c.shape[0])
                    buf[s:e] += c[: e - s]
                    pos += spb * div
                # Headroom so the overlay summed with the drop doesn't clip.
                peak = float(np.abs(buf).max())
                if peak > 0.5:
                    buf *= np.float32(0.5 / peak)
                out = buf
        except Exception:
            out = None
    _DEEP_DANCE_CACHE[key] = out
    return out


def _loudness_match(x: np.ndarray, ref_rms: float, max_gain: float = 4.0,
                    ceiling: float = 0.95) -> np.ndarray:
    """Scale `x` (float32 stereo) so its RMS matches `ref_rms`, with a soft
    limiter for tracks that are already recorded hot (low RMS but near-full
    peak -> little headroom). A naive gain would clip or be faded back down and
    lose the loudness lift; instead we push up and then soft-saturate the
    peaks with tanh so the RMS rise survives without hard distortion. The fold
    is mild so dynamics are preserved. Deterministic: pure function."""
    seg_rms = float(np.sqrt(np.mean(x ** 2))) or 1e-9
    g = float(np.clip(ref_rms / seg_rms, 0.25, max_gain))
    out = x * np.float32(g)
    pk = float(np.abs(out).max())
    if pk > ceiling:
        # Soft-knee limit: normalise then gently fold the overs so the RMS
        # lift is kept instead of a hard linear fade that undoes the gain.
        norm = np.float32(ceiling / pk)
        out = out * norm
        drive = np.float32(1.15)
        out = np.tanh(out * drive) / np.tanh(drive)
        npk = float(np.abs(out).max())
        if npk > 0.96:
            out = out * np.float32(0.96 / npk)
    return out.astype(np.float32)


class GoldenRenderer:
    def __init__(self, sample_rate: int = DEFAULT_CONFIG.sample_rate) -> None:
        self.sample_rate = sample_rate

    def render(self, plan: SetPlan, segments: Dict[str, Segment],
               edges: Dict[str, TransitionEdge],
               seg_audio: Dict[str, CanonicalAudio],
               out_dir: Path,
               force_cut: bool = False) -> dict:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        body = None
        timeline = []
        events: List[PackEvent] = []
        pos = 0
        # Auto-gain reference loudness, captured from the FIRST (opening) phrase
        # so quieter tracks don't dip in the mix. RMS-based running mean.
        _ref_rms = 0.0
        _ref_n = 0
        for i, step in enumerate(plan.steps):
            seg = segments[step.segment_id]
            audio = seg_audio[step.segment_id]
            # Honor per-step length (Deep/megamix truncates each segment to a
            # short hook); clamp to the available audio.
            n = int(step.length_samples) if step.length_samples else audio.n_samples
            n = max(1, min(n, audio.n_samples))
            # Copy so per-track auto-gain / FX never mutate shared source audio.
            clip = np.array(audio.samples[:n], dtype=np.float32)
            # --- AUTO-GAIN: loudness-match every segment to the first phrase.
            # Measure perceptual-ish RMS over the whole clip; for the opening
            # segment record it as the reference, for everything else scale the
            # clip to that reference (gain clamped + peak-limited to stay clean).
            seg_rms = float(np.sqrt(np.mean(clip ** 2))) or 1e-9
            if i == 0:
                _ref_rms = seg_rms if _ref_n == 0 else _ref_rms
                _ref_n += 1
            elif _ref_n:
                clip = _loudness_match(clip, _ref_rms)
            if force_cut:
                # Radio-hit cut: end on the last beat that still has the kick,
                # so a trailing breakdown tail doesn't bleed into the cut.
                kn = _last_kick_sample(clip, self.sample_rate, seg.bpm)
                if kn < n:
                    clip = clip[:kn]
                    n = kn
                # Drop->drop: skip any quiet lead-in at the top of this segment
                # so the cut lands exactly on the incoming drop's first beat.
                if i > 0:
                    ds = _drop_start_sample(clip, self.sample_rate, seg.bpm)
                    if 0 < ds < n:
                        clip = clip[ds:]
                        n -= ds
            start = pos
            step.start_sample = start
            if body is None:
                # Mix intro: MS-20 resonant low-pass sweeps 90 Hz -> 16 kHz over
                # the first 8 beats, then snaps hard open into the first drop.
                # Gain turned DOWN: res/drive reduced + the swept head is pulled
                # back so the resonance doesn't overcook the intro.
                clip = ms20_open(clip, self.sample_rate, seg.bpm, beats=8.0,
                                 from_hz=90.0, to_hz=16000.0,
                                 res=0.6, drive=1.15, variant="ota")
                sweep_n = int(round(8.0 * self.sample_rate * 60.0 / seg.bpm))
                sweep_n = max(1, min(sweep_n, clip.shape[0]))
                clip[:sweep_n] *= np.float32(0.7)
                n = clip.shape[0]
                # IDENTITY FX: CyberLuke voice tag (samples/voice_tags/
                # Cyberluke2.wav) plays CLEAN (no effect) over the first drop
                # right as the MS-20 sweep snaps open. When the tag ENDS, the
                # Glitch Bitch buffer-mangle fires on the MUSIC underneath
                # (not on the tag), quantized to the next beat.
                vt = _clean_voice_tag(self.sample_rate)
                if vt is not None:
                    on = int(round(8.0 * self.sample_rate * 60.0 / seg.bpm))
                    on = min(on, n - 1)
                    avail = n - on
                    vt = vt[:avail]
                    # DUCK the music under the tag, then push the tag HOT.
                    # Ducking (not just louder tag) is what makes a voice tag
                    # read clearly over a drop without clipping the sum.
                    # Milder sidechain (depth 0.6 ≈ -4.4 dB, not -10 dB) with a
                    # gentle release so the music glides back when the tag
                    # ends instead of pumping up abruptly into the filter sweep.
                    duck_under(clip, on, vt.shape[0], self.sample_rate,
                               depth=0.6, attack_ms=6.0, release_ms=220.0)
                    # RMS-match the tag to the (now-ducked) drop, then boost.
                    drop_rms = float(np.sqrt((clip[on:on + vt.shape[0]] ** 2).mean()))
                    tag_rms = float(np.sqrt((vt ** 2).mean()))
                    if tag_rms > 1e-6 and drop_rms > 1e-6:
                        vt = vt * np.float32((1.6 * drop_rms) / tag_rms)
                        peak = float(np.abs(vt).max())
                        if peak > 0.95:
                            vt = vt * np.float32(0.95 / peak)
                    clip[on:on + vt.shape[0]] += vt
                    events.append(PackEvent(
                        sample=start + on, type="identityfx.voice_tag",
                        payload={"file": str(_VOICE_TAG_PATH),
                                 "effect": "none (clean) + duck",
                                 "bpm": float(seg.bpm)}))
                    # CLEAN FILTER AUTOMATION on the music after the tag ends:
                    # the Vengeance 'envelope' sound — a resonant MS-20 LP sweep
                    # (no buffer mangle). TWO passes:
                    #   SLOW: one 1-bar sweep at this speed (the cool open-up);
                    #   FAST: four 1/4-bar (16th-note) sweeps back-to-back — the
                    #         rapid wobble/stutter-filter effect.
                    spb = self.sample_rate * 60.0 / float(seg.bpm)
                    tag_end = on + vt.shape[0]
                    g_start = int(np.ceil(tag_end / spb) * spb)
                    reps_slow = 0
                    reps_fast = 0
                    # Reset the humanized cutoff tracker so this FX sequence
                    # starts fresh (the 4x loop then carries it continuously).
                    filter_automation._knob = None
                    # SLOW pass: 1 bar.
                    bar_n = int(round(4.0 * spb))
                    if g_start + bar_n <= n:
                        seg_slice = clip[g_start:g_start + bar_n].copy()
                        clip[g_start:g_start + bar_n] = filter_automation(
                            seg_slice, self.sample_rate, seg.bpm,
                            bars=1, lp_from_hz=700.0, lp_to_hz=15000.0,
                            res=0.6, drive=1.1)
                        reps_slow = 1
                    # FAST pass: 4 x 1/4-bar sweeps right after the slow one.
                    fast_start = g_start + bar_n
                    qbar_n = int(round(spb))  # 1 beat = 1/4 bar at 4/4
                    for r in range(4):
                        s0 = fast_start + r * qbar_n
                        if s0 + qbar_n > n:
                            break
                        seg_slice = clip[s0:s0 + qbar_n].copy()
                        clip[s0:s0 + qbar_n] = filter_automation(
                            seg_slice, self.sample_rate, seg.bpm,
                            bars=0.25, lp_from_hz=1000.0, lp_to_hz=15000.0,
                            res=0.7, drive=1.2)
                        reps_fast += 1
                    if reps_slow or reps_fast:
                        events.append(PackEvent(
                            sample=start + g_start, type="identityfx.filter_sweep",
                            payload={"on": "music", "after": "voice_tag",
                                     "slow_bars": reps_slow,
                                     "fast_reps": reps_fast,
                                     "bpm": float(seg.bpm)}))
                body = clip.copy()
                pos = n
            else:
                # IDENTITY FX: deep_dance chop sequence rides OUT the tail of the
                # 1st track (right before the cut into track 2), not the top of
                # track 2. It's stamped onto `body` (the outgoing 1st segment),
                # ducked so the chops cut through, then the hard cut follows.
                if i == 1:
                    prev_seg = segments[plan.steps[i - 1].segment_id]
                    dd = _deep_dance_sequence(self.sample_rate, prev_seg.bpm)
                    if dd is not None:
                        end_n = body.shape[0]
                        dd_n = min(dd.shape[0], end_n)
                        on = end_n - dd_n
                        # DUCK the tail under the chops, then sum them in. Milder duck
                        # (0.55, -5 dB) so the tail doesn't dip hard and the
                        # chops don't leave a level hole when they stop.
                        duck_under(body, on, dd_n, self.sample_rate,
                                   depth=0.55, attack_ms=6.0, release_ms=200.0)
                        seg_rms = float(np.sqrt((body[on:on + dd_n] ** 2).mean()))
                        dd_rms = float(np.sqrt((dd[:dd_n] ** 2).mean()))
                        if dd_rms > 1e-6 and seg_rms > 1e-6:
                            dd[:dd_n] *= np.float32((1.5 * seg_rms) / dd_rms)
                            pk = float(np.abs(dd[:dd_n]).max())
                            if pk > 0.95:
                                dd[:dd_n] *= np.float32(0.95 / pk)
                        body[on:on + dd_n] += dd[:dd_n]
                        events.append(PackEvent(
                            sample=on, type="identityfx.deep_dance_chop",
                            payload={"file": str(_DEEP_DANCE_PATH),
                                     "at": "end_of_track_1",
                                     "bpm": float(prev_seg.bpm),
                                     "slots": len(_DEEP_DANCE_SLOTS)}))
                # force_cut = "radio hit" megamix mode: hard drop->drop cut at the
                # bar boundary, NO precompiled transition audio. Keeps mix energy
                # up (no amateur overlap dips); just a declicked sample-accurate cut.
                edge = None if force_cut else (
                    edges.get(step.edge_id) if step.edge_id else None)
                if force_cut:
                    # Hard radio cut: tiny 2 ms declick, no 20 ms crossfade flat.
                    body = declick_join(body, clip, self.sample_rate, fade_ms=2.0)
                    pos = body.shape[0]
                elif edge is not None:
                    e_audio = seg_audio.get(edge.id)
                    if e_audio is not None:
                        # GA-PLESS transition. The precompiled edge asset already
                        # embeds the incoming phrase after its t2 (switch) point,
                        # so appending the whole buffer and THEN the clip would
                        # duplicate the incoming head and create a dead-air band.
                        # Instead we blend the pre-switch transition effect over
                        # the tail of the outgoing phrase and let the incoming
                        # clip continue immediately (gapless), so the transition
                        # is heard right at the boundary with no silence gap.
                        ev = e_audio.samples.astype(np.float32)
                        sw = int(getattr(edge.timeline, "t2_sample", 0) or 0)
                        sw = max(0, min(sw, ev.shape[0]))
                        # Blend window. Cap at ~4s so full bars of build/roll
                        # (power_up 2 bars, drum_roll ~3.4s) are heard whole;
                        # only extreme assets get trimmed. Short resets
                        # (slam/backspin, now ~1 bar) sit well under this.
                        X = min(sw, body.shape[0], int(4.0 * self.sample_rate))
                        if X > 0:
                            # DUCK the outgoing phrase in the transition window
                            # so the effect CUTS THROUGH instead of being masked
                            # under the still-full-level tail. Making the
                            # transition audible is what the golden mix needs —
                            # without this, short resets read as a plain gapless
                            # cut (transition 'not heard').
                            duck_under(body, body.shape[0] - X, X,
                                       self.sample_rate,
                                       depth=0.5, attack_ms=4.0, release_ms=90.0)
                            seg_rms = float(np.sqrt((body[-X:] ** 2).mean())) or 1.0
                            ev_rms = float(np.sqrt((ev[:X] ** 2).mean())) or 1.0
                            if ev_rms > 1e-6 and seg_rms > 1e-6:
                                ev[:X] = ev[:X] * np.float32((1.05 * seg_rms) / ev_rms)
                            pk = float(np.abs(ev[:X]).max())
                            if pk > 0.95:
                                ev[:X] = ev[:X] * np.float32(0.95 / pk)
                            body[-X:] = (body[-X:] + ev[:X]).astype(np.float32)
                        # Incoming phrase continues immediately (gapless). The
                        # post-switch region of the asset duplicates clip, so we
                        # go straight to the original clip (cleaner continuity).
                        body = declick_join(body, clip, self.sample_rate, fade_ms=2.0)
                        pos = body.shape[0]
                    else:
                        body = declick_join(body, clip, self.sample_rate)
                        pos = body.shape[0]
                else:
                    body = declick_join(body, clip, self.sample_rate)
                    pos = body.shape[0]
            timeline.append({"segmentId": step.segment_id,
                             "technique": (None if force_cut else step.technique),
                             "cut": bool(force_cut and i > 0),
                             "startSample": start,
                             "lengthSamples": n})
            events.append(PackEvent(sample=start, type="segment.enter",
                                    payload={"segmentId": step.segment_id}))

        # Peak safety: identity-FX overlays (voice tag, deep/dance chops) are
        # summed on top of the drops; if the mix would clip, scale the whole
        # body down to -0.3 dBFS instead of distorting.
        peak = float(np.abs(body).max())
        if peak > 0.966:
            body = (body * np.float32(0.966 / peak)).astype(np.float32)

        golden = out_dir / "golden.wav"
        atomic_write_wav(golden, body, self.sample_rate)
        digest = sha256_file(golden)

        (out_dir / "golden.timeline.json").write_text(json.dumps(timeline, indent=2))
        (out_dir / "golden.events.json").write_text(json.dumps(
            [e.to_dict() for e in events], indent=2))
        report = {
            "seed": plan.seed,
            "steps": len(plan.steps),
            "totalSamples": int(body.shape[0]),
            "goldenSha256": digest,
            "goldenPath": str(golden),
        }
        (out_dir / "golden.report.json").write_text(json.dumps(report, indent=2))
        return report
