"""JuggleMiner DSP: the master-buffer backstep + musicality scorers.

All numpy/scipy, runs in .venv-hypermix. No stems venv needed.

Core move (Pioneer ROLL / Technics backstep, same thing on the MASTER buffer):
    slice  = master[boundary - offset : boundary - offset + duration]
    output = master with `slice` re-triggered IN TIME at the boundary
             (repeat `repeat` times, decaying, with a tiny de-click edge fade).

Because the slice is the FULL master, one half-beat step can stack vocal
syllable + kick retrigger + synth stab + reverb tail into a brand-new hook.
"""

from __future__ import annotations

from dataclasses import replace

import math

import numpy as np


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def _declick(x: np.ndarray, sr: int, ms: float) -> np.ndarray:
    """Tiny raised-cosine fade in/out at the slice edges (no pops)."""
    n = len(x)
    k = int(sr * ms / 1000.0)
    if k <= 0 or n < 2 * k:
        return x
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, k))
    out = x.copy()
    out[:k] *= ramp[:, None] if x.ndim > 1 else ramp
    out[-k:] *= ramp[::-1][:, None] if x.ndim > 1 else ramp
    return out


def _resample_arbitrary(x: np.ndarray, sr: int, rate_curve: np.ndarray) -> np.ndarray:
    """Variable-rate resample: rate_curve (len n_out) = instantaneous speed
    (1.0 = normal, >1 = faster/higher, <1 = slower/lower). Returns n_out samples.
    This is the turntable-motor / tape-wow nonlinearity: the platter slows and
    re-spins, dragging pitch and time with it."""
    n_out = len(rate_curve)
    if n_out == 0:
        return x[:0]
    # cumulative source position under the variable rate
    pos = np.cumsum(rate_curve)
    pos = np.clip(pos, 0, max(0, len(x) - 1))
    if x.ndim > 1:
        out = np.zeros((n_out, x.shape[1]), dtype=np.float32)
        for c in range(x.shape[1]):
            out[:, c] = np.interp(pos, np.arange(len(x)), x[:, c])
        return out
    return np.interp(pos, np.arange(len(x)), x).astype(np.float32)


def _motor_wow_curve(n: int, sr: int, depth: float, slow_s: float,
                     rng: np.random.Generator) -> np.ndarray:
    """Speed curve for one backstep hit: the platter DIPS (motor bogs down) then
    re-spins to nominal. depth=how deep the bog (0..0.5), slow_s=time to recover.
    Adds a touch of random wow flutter on top so it isn't sterile."""
    curve = np.ones(n, dtype=np.float32)
    dip_n = max(1, int(slow_s * sr))
    dip_n = min(dip_n, n)
    # smooth V-shaped bog: 1.0 → (1-depth) → 1.0
    half = dip_n // 2
    if half > 0:
        down = 1.0 - depth * np.sin(np.linspace(0, np.pi / 2, half))
        up = (1.0 - depth) + depth * np.sin(np.linspace(0, np.pi / 2, dip_n - half))
        curve[:dip_n] = np.concatenate([down, up])[:dip_n]
    # wow/flutter: a slow random drift + tiny fast flutter
    t = np.arange(n) / sr
    wow = (1.0
           + 0.004 * np.sin(2 * np.pi * rng.uniform(0.4, 0.9) * t + rng.uniform(0, 6.28))
           + 0.002 * np.sin(2 * np.pi * rng.uniform(4.0, 7.0) * t + rng.uniform(0, 6.28)))
    return (curve * wow).astype(np.float32)


def render_juggle(master: np.ndarray, sr: int, bpm: float, boundary_s: float,
                  offset_beats: float, duration_beats: float, repeat: int = 1,
                  phase: str = "onbeat", mode: str = "retrigger",
                  loop_count: int = 2,
                  slice_gain: float = 1.0, declick_ms: float = 6.0,
                  context_beats: float = 4.0,
                  peak_ceiling: float = 0.95,
                  vinyl: bool = False, vinyl_depth: float = 0.5,
                  reverse_flourish: bool = False,
                  grid: str = "straight", slap_beats: float = 0.75,
                  seed: int = 0,
                  humanize: bool = False, humanize_timing_ms: float = 9.0,
                  humanize_gain: float = 0.10, humanize_pitch: float = 0.008,
                  swing: float = 0.0, accelerate: float = 0.0,
                  buffer_hack: bool = False, hack_div: int = 4,
                  hack_shrink: float = 0.6, hack_rate: float = 0.9,
                  hack_cut_ms: float = 10.0,
                  chirp: bool = False, chirp_ms: float = 38.0,
                  chirp_swing: float = 1.8, skip_bars: float = 0.0,
                  power_down: bool = False, power_down_s: float = 0.7,
                  forward_last: bool = False, forward_shift: float = 0.5,
                  fader_cut_ms: float = 0.0,
                  power_down_overlap_beats: float = 0.0) -> np.ndarray:
    """Render the full juggle preview.

    phase:
      - 'onbeat'  → anchor the buffer ON the kick (the boundary transient)
      - 'offbeat' → shift the anchor half a beat late so the buffer lands ON
                    the snare/backbeat (the 'off' hit)
    mode:
      - 'retrigger' → play the slice `repeat` times back-to-back AT the anchor
      - 'loop'      → DJ double/triple loop: let the phrase play to its end,
                      then loop the LAST `duration_beats` `loop_count` times.
    master: (n,) or (n,2) float. Returns same-channel float32.

    vinyl / reverse_flourish (turntable nonlinearity — 'frajer' mode):
      - reverse_flourish → prepend a short REVERSED kick tail (back-cue scratch)
        so the first hit winds up backwards into the buffer.
      - vinyl → turntable MOTOR wow: the platter bogs down then re-spins during
        the hit (variable-rate pitch/time dip) + a little wow/flutter, so it
        sounds like a real record being juggled, not a sterile digital repeat.
      - vinyl_depth (0..0.6) = how deep the motor bogs.

    grid — WHERE the repeats land (this is the jungle/DnB 'slap' feel):
      - 'straight' → repeats at 0, 1, 2 ... × duration (on the beat)
      - 'slap'     → repeats at 0, slap, 2·slap ... (default slap=0.75) so the
                     middle hit lands BETWEEN beats — 'snare snare snare' with
                     the 2nd snare closer to the 1st and farther from the 3rd.
      - 'swing'    → repeats at 0, 0.67, 1.33 ... (lilting triplet shuffle)
      The buffer OVERLAPS/interleaves like a DJ dropping samples between beats,
      not laid end-to-end — that's why a 0.75 read sounds like 3/4, not 1b.
    """
    spb = 60.0 / float(bpm)
    beat_s = spb
    anchor_i = int(round(boundary_s * sr))
    if phase == "offbeat":
        anchor_i += int(round(0.5 * beat_s * sr))  # land on the snare/backbeat

    # BACKSTEP: the buffer is the LAST `duration_beats` immediately BEFORE the
    # anchor. `offset_beats` only decides HOW FAR BACK the slice starts (extra
    # context), but the material that repeats is what just played. This is the
    # Technics back-cue / Pioneer beat-repeat move: grab what you just heard,
    # re-fire it in time.
    dur_n = max(1, int(round(duration_beats * beat_s * sr)))
    slice_i = max(0, anchor_i - dur_n)
    if slice_i >= len(master):
        return master.copy().astype(np.float32)
    slice_audio = master[slice_i:anchor_i].copy()
    if slice_audio.shape[0] == 0:
        return master.copy().astype(np.float32)
    # DJ rides the fader a touch under the master so the double doesn't push red
    slice_audio = _declick(slice_audio, sr, declick_ms) * float(slice_gain)

    rng = np.random.default_rng(int(seed))

    # VINYL NONLINEARITY 1 — reverse kick flourish (back-cue scratch): prepend a
    # short REVERSED tail of the slice head so the first hit 'winds up' backwards
    # into the buffer, like cueing the record back before letting it go.
    rev_n = 0
    if reverse_flourish:
        rev_n = min(int(0.5 * beat_s * sr), dur_n)  # up to a half-beat of reverse
        rev_seg = slice_audio[:rev_n][::-1].copy()
        # scratch texture: tiny band-limited squelch via a fast gain wobble
        wob = 1.0 + 0.25 * np.sin(2 * np.pi * rng.uniform(18, 30) *
                                  np.arange(rev_n) / sr)
        rev_seg = (rev_seg * (wob[:, None] if rev_seg.ndim > 1 else wob))
        rev_seg = _declick(rev_seg, sr, max(2.0, declick_ms))
        slice_audio = np.concatenate([rev_seg, slice_audio], axis=0)
        dur_n = slice_audio.shape[0]

    # VINYL NONLINEARITY 2 — turntable motor wow: the platter bogs down then
    # re-spins during the hit (pitch+time dip), plus a little wow/flutter.
    if vinyl:
        depth = float(np.clip(vinyl_depth, 0.0, 0.6)) * rng.uniform(0.7, 1.0)
        slow_s = min(0.35, 0.5 * beat_s) * rng.uniform(0.7, 1.3)
        curve = _motor_wow_curve(len(slice_audio), sr, depth, slow_s, rng)
        slice_audio = _resample_arbitrary(slice_audio, sr, curve)
        dur_n = slice_audio.shape[0]
        slice_audio = _declick(slice_audio, sr, declick_ms)

    # CHIRP = VINYL SLIDE — the needle is ON the record, the MOTOR is spinning,
    # and the HAND drags/pushes the sample like a slide: a SMOOTH variable-rate
    # pitch+time sweep (down then back up, like a hand pulling the record back
    # then letting the motor carry it forward). NOT a digital stutter — the
    # pitch glides continuously because the platter is always turning.
    # CHIRP plays ONCE (the wind-up slide into the FIRST hit) — it is NOT
    # baked into the slice, or it would repeat on every retrigger. We build it
    # separately and lay it just before the first hit. The buffer effect then
    # follows IMMEDIATELY after this single chirp.
    chirp_seg = None
    if chirp:
        chirp_n = max(32, int(round(chirp_ms / 1000.0 * sr)))
        grain = slice_audio[:chirp_n].copy()
        # one smooth slide: speed dips (hand drags back / pitch falls) then
        # rises past nominal (hand pushes forward / pitch jumps) and settles.
        t = np.linspace(0, 1, chirp_n)
        dip = 0.55 - 0.45 * np.cos(np.pi * t)          # hand drag (pitch falls)
        push = 1.0 + (chirp_swing - 1.0) * np.sin(np.pi * t)  # push overshoot
        rate = np.clip(dip * push, 0.15, 2.5).astype(np.float32)
        chirp_seg = _resample_arbitrary(grain, sr, rate)
        chirp_seg = _declick(chirp_seg, sr, max(2.0, declick_ms))

    # output window: a bit of context before and after the anchor
    pre_n = int(round(context_beats * beat_s * sr))
    post_n = int(round(context_beats * beat_s * sr))
    start = max(0, anchor_i - pre_n)
    end = min(len(master), anchor_i + post_n)
    out = master[start:end].copy()
    out_anchor = anchor_i - start  # anchor index within `out`

    # TEMPORAL BUFFER REPLACE: the effect AGGRESSIVELY CUTS the current
    # playback and REPLACES it with the buffer — like a Pioneer beat-repeat.
    # No summing, no ducking under the master. A short raised-cosine crossfade
    # at the region edges keeps the hard cut from clicking.
    xf_n = min(int(sr * declick_ms / 1000.0), max(1, dur_n // 8))
    n_hits = int(loop_count) if mode == "loop" else int(repeat)
    # placement grid: how far apart (in beats) successive hits land
    if grid == "slap":
        step_beats = float(slap_beats)          # 3/4 — middle hit between beats
    elif grid == "swing":
        step_beats = duration_beats * 0.67      # lilting triplet shuffle
    else:                                       # 'straight'
        step_beats = duration_beats             # on the beat
    # region spans to the END of the last hit (overlaps extend past last step)
    region_beats = step_beats * max(0, n_hits - 1) + duration_beats
    region_n = int(round(region_beats * beat_s * sr))
    # HUMANIZE/ACCELERATE can push the tail out — extend the region so the
    # last (possibly shifted) hit + a buffer-hack stutter never clips off early.
    accel = float(np.clip(accelerate, 0.0, 1.0))
    tail_extra_n = 0
    if humanize:
        tail_extra_n += int(round((humanize_timing_ms / 1000.0 + abs(swing) * step_beats * beat_s) * sr))
    if buffer_hack:
        tail_extra_n += int(round(1.5 * duration_beats * beat_s * sr))  # room for stutter decay
    # SKIP BARS — a real hand can't shuttle every hit; leave N bars of the
    # ORIGINAL playback between juggle bursts so the groove breathes.
    if skip_bars > 0:
        tail_extra_n += int(round(skip_bars * 4.0 * beat_s * sr))
    # POWER-DOWN — room for the motor-stop tail after the effect.
    if power_down:
        tail_extra_n += int(round(power_down_s * sr))
    # CHIRP — reserve room for the single wind-up slide at the head.
    chirp_len = len(chirp_seg) if chirp_seg is not None else 0
    region_end = min(len(out), out_anchor + region_n + tail_extra_n + chirp_len)
    region_n = region_end - out_anchor
    if region_n > 0:
        # build the repeated buffer by PLACING the slice at the grid offsets and
        # SUMMING the overlaps (a DJ drops samples between beats — they overlap).
        buf = np.zeros((region_n,) + slice_audio.shape[1:], dtype=np.float32)
        # lay the ONE chirp (wind-up slide) at the very head; the hits follow it
        head = 0
        if chirp_seg is not None:
            cl = min(chirp_len, region_n)
            buf[:cl] = chirp_seg[:cl]
            head = cl  # the first hit starts right after the chirp
        step_n = max(1, int(round(step_beats * beat_s * sr)))
        gain = 1.0
        for r in range(n_hits):
            # --- placement with ACCELERATE (compress later hits) + SWING (drag)
            # accelerate: compress the MIDDLE hits for tension, but EASE OFF on
            # the last two hits so they don't bunch up robotically back-to-back.
            if n_hits > 1:
                frac = r / (n_hits - 1)
                # sine arc: strongest compression mid-run, ~0 on the last hits
                accel_frac = accel * math.sin(math.pi * min(1.0, frac)) if accel > 0 else 0.0
            else:
                accel_frac = 0.0
            place_f = float(head) + float(r) * (1.0 - accel_frac * 0.5) * step_n
            # swing: NEGATIVE = drag/pull later hits a touch late (human feel)
            place_f += swing * step_n * r
            if humanize:
                place_f += rng.uniform(-1, 1) * (humanize_timing_ms / 1000.0) * sr
            place = int(round(place_f))
            if place < 0:
                place = 0
            if place >= region_n:
                break
            seg = min(len(slice_audio), region_n - place)
            if seg <= 0:
                break
            # --- per-hit source: optional micro pitch/tape wobble (humanize)
            src = slice_audio
            if humanize and humanize_pitch > 0:
                rate = 1.0 + rng.uniform(-1, 1) * humanize_pitch
                if abs(rate - 1.0) > 1e-5:
                    n_out = max(1, int(round(len(slice_audio) / rate)))
                    curve = np.full(n_out, rate, dtype=np.float32)
                    src = _resample_arbitrary(slice_audio, sr, curve)
                    seg = min(len(src), region_n - place)
                    if seg <= 0:
                        continue
            # FORWARD LAST — the final hit is NOT a backstep repeat; it SHIFTS
            # the buffer into the FUTURE by forward_shift of the slice (plays
            # what was ABOUT to come, half a slice ahead), so the run resolves
            # forward instead of looping the past.
            if forward_last and r == n_hits - 1:
                sh = int(round(len(slice_audio) * float(forward_shift)))
                src = master[anchor_i + sh: anchor_i + sh + dur_n]
                if src.shape[0] == 0:
                    src = slice_audio
                else:
                    src = _declick(src.copy(), sr, declick_ms)
                # re-fit seg to THIS source (the forward slice may be shorter)
                seg = min(len(src), region_n - place)
                if seg <= 0:
                    continue
            # FADER CUT — a hip-hop DJ 'cut': after each hit, drop the fader
            # HARD with a SHARP curve for a few ms so the next kick doesn't
            # clash. Not a smooth fade — an aggressive, near-vertical cut.
            if fader_cut_ms > 0 and r < n_hits - 1:
                cut_n = int(round(fader_cut_ms / 1000.0 * sr))
                c0 = place + seg  # gap starts right at the hit end
                c1 = min(region_n, c0 + cut_n)
                if c1 > c0:
                    # sharp (steep) curve in AND out of the cut — square-ish
                    halfc = (c1 - c0) // 2
                    env = np.zeros(c1 - c0, dtype=np.float32)
                    # steep attack into the hole, steep release out of it
                    if halfc > 0:
                        env[:halfc] = (np.linspace(0, 1, halfc) ** 3)      # sharp down
                        env[halfc:] = (np.linspace(1, 0, (c1 - c0) - halfc) ** 3)  # sharp up
                    # carve the gap: pull existing buf toward silence with the sharp env
                    buf[c0:c1] *= (env[:, None] if buf.ndim > 1 else env)
            g = gain
            if humanize and humanize_gain > 0:
                g = gain * (1.0 + rng.uniform(-1, 1) * humanize_gain)
            buf[place:place + seg] += src[:seg] * g
            gain *= 0.92  # slight fader ride on each repeat
            # SKIP BARS — the hand rests a bar, but the GROOVE MUST NOT DIE:
            # fill the gap with the ORIGINAL master playback (the track keeps
            # rolling under the rest) instead of silence. No click, no hole.
            if skip_bars > 0 and r < n_hits - 1:
                gap_n = int(round(skip_bars * 4.0 * beat_s * sr))
                g0 = place + seg
                g1 = min(region_n, g0 + gap_n)
                if g1 > g0:
                    # original audio under the rest (from `out`, i.e. the master)
                    orig = out[out_anchor + g0:out_anchor + g1]
                    dk = min(int(sr * 0.008), (g1 - g0) // 2)
                    if dk > 0:
                        ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, dk))
                        ramp = ramp[:, None] if buf.ndim > 1 else ramp
                        # crossfade hit-tail → original → (next hit)
                        orig = orig.copy()
                        orig[:dk] *= ramp
                        orig[-dk:] *= ramp[::-1]
                        buf[g0:g1] = orig
                    else:
                        buf[g0:g1] = orig
                # push the NEXT hit past the gap
                step_n += gap_n

        # BUFFER HACK — dramatic ending: chop the tail of the buffer into a
        # stutter that shrinks + slows (pitches down) so it 'pokopane' collapses.
        if buffer_hack and hack_div > 1:
            # take a short tail grain = last slice head, repeated shrinking
            grain_n = max(64, dur_n // hack_div)
            grain = slice_audio[:grain_n].copy()
            cursor = out_anchor + max(0, region_n - tail_extra_n) if tail_extra_n > 0 else out_anchor + region_n - grain_n
            gn = grain_n
            rate = 1.0
            ggain = 0.9
            # BUTCHER the kick: each chop gets a SHORT DECAY envelope (fast
            # attack, quick exponential decay) so the kick is hacked off clean
            # and the next kick lands IMMEDIATELY after — no gaps, no silence,
            # the rhythm never dies. 'nasekat jako reznik'.
            for _ in range(hack_div * 2):
                if cursor >= region_n or gn < 32:
                    break
                src = grain[:gn]
                if hack_rate != 1.0:
                    rate *= float(hack_rate)  # slow + pitch down each repeat
                    n_out = max(32, int(round(gn / rate)))
                    curve = np.full(n_out, rate, dtype=np.float32)
                    src = _resample_arbitrary(grain[:gn], sr, curve)
                seg = min(len(src), region_n - cursor)
                if seg <= 0:
                    break
                chop = src[:seg] * ggain
                # SHORT DECAY: fast attack then a quick exponential falloff so
                # the kick is chopped tight (not a fade-out tail, a hard decay).
                atk = min(int(sr * 0.003), seg // 4)
                env = np.exp(-np.linspace(0, 6.0, seg)).astype(np.float32)  # fast decay
                if atk > 0:
                    env[:atk] *= 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, atk))
                chop = chop * (env[:, None] if chop.ndim > 1 else env)
                buf[cursor:cursor + seg] = chop
                cursor += seg  # next kick lands RIGHT after — no gap
                gn = int(round(gn * hack_shrink))
                ggain *= 0.9
        # FILL ANY UNUSED TAIL — if the effect (hack/spinup/short last hit)
        # didn't reach the end of the reserved region, the leftover would be
        # SILENT zeros and kill the rhythm. Backfill the near-silent remainder
        # with the ORIGINAL master so the groove never drops out.
        if region_n > 0:
            mono = buf.mean(axis=1) if buf.ndim > 1 else buf
            # find the last index with real signal
            win = max(1, int(0.02 * sr))
            nwin = region_n // win
            if nwin > 0:
                env = np.sqrt((mono[:nwin * win].reshape(nwin, win) ** 2).mean(axis=1))
                live = np.nonzero(env > 0.02)[0]
                last_live = (live[-1] + 1) * win if live.size else 0
            else:
                last_live = region_n
            if last_live < region_n:
                # crossfade the live tail into the original master resume
                orig = out[out_anchor + last_live:region_end]
                dk = min(int(sr * 0.01), region_n - last_live, len(orig))
                if dk > 0:
                    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, dk))
                    ramp = ramp[:, None] if buf.ndim > 1 else ramp
                    orig = orig.copy()
                    orig[:dk] = orig[:dk] * ramp + buf[last_live:last_live + dk] * (1 - ramp)
                    buf[last_live:region_n] = orig
                else:
                    buf[last_live:region_n] = orig
        # tame overlap build-up so interleaved hits don't slam over the red
        bpeak = float(np.abs(buf).max()) if buf.size else 0.0
        if bpeak > 0.95:
            buf = np.tanh(buf / 0.95) * 0.95
        # crossfade in/out so the cut is aggressive but click-free
        if xf_n > 0 and buf.shape[0] >= 2 * xf_n:
            ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, xf_n))
            ramp = ramp[:, None] if buf.ndim > 1 else ramp
            buf[:xf_n] = buf[:xf_n] * ramp + out[out_anchor:out_anchor + xf_n] * (1 - ramp)
            buf[-xf_n:] = buf[-xf_n:] * ramp[::-1] + out[region_end - xf_n:region_end] * (1 - ramp[::-1])
        out[out_anchor:region_end] = buf  # REPLACE the playback buffer

    # VINYL MOTOR — hand-STOPS the platter INSTANTLY (a hard chop to silence),
    # then RELEASES it and the motor SLOWLY SPINS BACK UP to tempo (pitch+tempo
    # ramp from ~0 back to 1.0). This is the OPPOSITE of a slow power-down: a
    # dead stop, a beat of near-silence, then the motor's lazy acceleration.
    if power_down:
        # The motor STOP starts BEFORE the region ends by `power_down_overlap_beats`
        # so the spin-up OVERWRITES the boring last repeat (the spin-up replaces
        # that repeat on the timeline, not after it).
        stop_n = int(round(0.05 * sr))
        pd_start = min(len(out), region_end) - int(round(power_down_overlap_beats * beat_s * sr))
        pd_start = max(out_anchor, pd_start)
        # 1) INSTANT STOP: hard cut to a brief near-silence (platter halted).
        s0 = max(0, pd_start - stop_n)
        if pd_start > s0:
            ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, pd_start - s0)))
            out[s0:pd_start] = out[s0:pd_start] * (ramp[::-1][:, None] if out.ndim > 1 else ramp[::-1])
        # 2) SLOW ACCELERATION back to tempo, with NO GAP: the spin-up begins
        #    in the SAME instant as the stop (the very first sample is already
        #    spinning up from ~0). No dead air before the motor re-accelerates.
        acc_n = int(round(power_down_s * sr))
        a_end = min(len(out), pd_start + acc_n)
        n = a_end - pd_start
        if n > 8:
            seg = out[pd_start:a_end].copy()
            # spin-up curve: start from HALF speed (not near-zero — a from-0
            # grind takes too long). The motor is already turning, it just
            # re-accelerates 0.5 → 1.0 with a fast initial rise.
            spd = (0.5 + 0.5 * (np.linspace(0, 1, n) ** 0.7)).astype(np.float32)
            seg = _resample_arbitrary(seg, sr, spd)
            seg = _declick(seg, sr, max(2.0, declick_ms))
            out[pd_start:pd_start + len(seg)] = seg
            # fill any leftover with the resuming track (not silence)
            tail0 = pd_start + len(seg)
            if tail0 < a_end:
                out[tail0:a_end] = out[tail0:a_end]  # already the master resume

    # keep under ceiling without hard clipping
    peak = float(np.abs(out).max()) if out.size else 0.0
    if peak > peak_ceiling:
        out = np.tanh(out / peak_ceiling) * peak_ceiling
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------

def _onset_strength(x: np.ndarray, sr: int) -> float:
    mono = x.mean(axis=1) if x.ndim > 1 else x
    if len(mono) < 2048:
        return 0.0
    try:
        import librosa
        o = librosa.onset.onset_strength(y=mono.astype(np.float32), sr=sr)
        return float(np.clip(o.mean() / (o.max() + 1e-9), 0.0, 1.0))
    except Exception:
        # fallback: spectral flux via RMS of frame-to-frame diff
        hop = 512
        frames = [mono[i:i + hop] for i in range(0, len(mono) - hop, hop)]
        if len(frames) < 2:
            return 0.0
        e = np.array([np.sqrt(np.mean(f ** 2)) for f in frames])
        d = np.abs(np.diff(e))
        return float(np.clip(d.mean() / (e.max() + 1e-9), 0.0, 1.0))


def _transient_density(x: np.ndarray, sr: int) -> float:
    mono = x.mean(axis=1) if x.ndim > 1 else x
    if len(mono) < 2048:
        return 0.0
    try:
        import librosa
        o = librosa.onset.onset_strength(y=mono.astype(np.float32), sr=sr)
        peaks = (o > (o.mean() + o.std())).sum()
        dur = len(mono) / sr
        return float(np.clip(peaks / max(dur, 1e-9) / 8.0, 0.0, 1.0))  # ~8 onsets/s = dense
    except Exception:
        return 0.0


def _spectral_novelty(slice_audio: np.ndarray, context: np.ndarray, sr: int) -> float:
    """How different is the slice's spectrum vs its surrounding context — the
    'happy accident' axis. High novelty + punch = a hook you didn't plan."""
    try:
        import librosa
        s = slice_audio.mean(axis=1) if slice_audio.ndim > 1 else slice_audio
        c = context.mean(axis=1) if context.ndim > 1 else context
        if len(s) < 2048 or len(c) < 2048:
            return 0.0
        S = np.abs(librosa.stft(s.astype(np.float32))).mean(axis=1)
        C = np.abs(librosa.stft(c.astype(np.float32))).mean(axis=1)
        S /= (S.sum() + 1e-9)
        C /= (C.sum() + 1e-9)
        # cosine DISTANCE = novelty
        cos = float(np.dot(S, C) / (np.linalg.norm(S) * np.linalg.norm(C) + 1e-9))
        return float(np.clip(1.0 - cos, 0.0, 1.0))
    except Exception:
        return 0.0


def _vocal_hook(x: np.ndarray, sr: int, lo_hz: float, hi_hz: float) -> float:
    """Energy in the vocal/formant band at the slice head (syllable retrigger)."""
    try:
        import librosa
        mono = x.mean(axis=1) if x.ndim > 1 else x
        head = mono[:int(sr * 0.25)]  # first 250 ms = where the syllable lands
        if len(head) < 2048:
            return 0.0
        S = np.abs(librosa.stft(head.astype(np.float32)))
        freqs = librosa.fft_frequencies(sr=sr)
        band = (freqs >= lo_hz) & (freqs <= hi_hz)
        if not band.any():
            return 0.0
        band_e = float(S[band].sum())
        tot_e = float(S.sum()) + 1e-9
        return float(np.clip(band_e / tot_e * 3.0, 0.0, 1.0))
    except Exception:
        return 0.0


def _groove(onset_times_s: np.ndarray, bpm: float) -> float:
    """Do the retrigger onsets land on the beat grid? (tight = groovy)."""
    if len(onset_times_s) == 0:
        return 0.0
    beat_s = 60.0 / float(bpm)
    grid = beat_s / 4.0  # 1/16 grid
    resid = np.abs(onset_times_s / grid - np.round(onset_times_s / grid)) * grid
    within = (resid < grid * 0.25).mean()  # within a 1/64 → on-grid
    return float(np.clip(within, 0.0, 1.0))


def score_candidate(master: np.ndarray, slice_audio: np.ndarray,
                    context: np.ndarray, sr: int, bpm: float,
                    cfg, boost: str) -> "tuple[float, dict]":
    """Compute the 5 metrics and a weighted total, with a per-role boost."""
    from .types import JuggleScores

    punch = _onset_strength(slice_audio, sr)
    transient = _transient_density(slice_audio, sr)
    novelty = _spectral_novelty(slice_audio, context, sr)
    vocal = _vocal_hook(slice_audio, sr, cfg.vocal_lo_hz, cfg.vocal_hi_hz)

    # groove from slice onsets
    try:
        import librosa
        mono = slice_audio.mean(axis=1) if slice_audio.ndim > 1 else slice_audio
        ot = librosa.onset.onset_detect(y=mono.astype(np.float32), sr=sr,
                                        units="time")
        groove = _groove(np.asarray(ot), bpm)
    except Exception:
        groove = 0.0

    w = dict(punch=cfg.w_punch, transient=cfg.w_transient,
             novelty=cfg.w_novelty, vocal=cfg.w_vocal, groove=cfg.w_groove)
    # role boost: bump the favoured axis
    keymap = {"punch": "punch", "vocal_hook": "vocal",
              "spectral_novelty": "novelty", "groove": "groove"}
    bk = keymap.get(boost, "punch")
    w[bk] = w.get(bk, 0.0) + 0.15
    wsum = sum(w.values()) + 1e-9
    total = (w["punch"] * punch + w["transient"] * transient +
             w["novelty"] * novelty + w["vocal"] * vocal +
             w["groove"] * groove) / wsum
    sc = JuggleScores(punch=round(punch, 4), transient_density=round(transient, 4),
                      spectral_novelty=round(novelty, 4), vocal_hook=round(vocal, 4),
                      groove=round(groove, 4), total=round(float(total), 4))
    return float(total), sc
