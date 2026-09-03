# Korg MS-20 Filter — Implementation Specification

**Project:** HyperMix (`src/hypermix/transitions/dsp.py`)
**Authoring agent:** GitHub Copilot (FW Kimi K3)
**Date:** 2026-08-11
**Status:** production — offline, deterministic

---

## 1. What it is

A digital emulation of the **Korg MS-20 low-pass filter** — the aggressive,
screaming resonant filter from the 1978 semi-modular synth (and its desktop
reissue). The MS-20's signature is a **resonance peak that "bites" and a drive
stage that growls/distorts** when pushed — the sound that "tears concrete".

The implementation is **offline and deterministic** (no realtime master-tempo
engine). All curves are computed once at render time on integer sample counts.

---

## 2. DSP topology

The core is a **2-pole (12 dB/oct) state-variable filter (SVF)** with a
nonlinear feedback loop — standing in for the MS-20's Sallen-Key / OTA design.

### 2.1 State-variable loop

Per sample `i`, per channel:

```
f   = 2*pi * cutoff[i]                # angular cutoff (time-varying)
g   = tan(pi * cutoff[i] * dt)        # bilinear-transform-ish integrator coeff
g   = min(g, 1.2)                     # stability clamp

inp = sig[i] * drive                  # pre-filter input gain
inp = tanh(inp)                       # OTA soft-clipper (growl / distortion)

hp  = (inp - k*s1 - s2) / (1 + k*g + g*g)   # high-pass node
bp  = g*hp + s1                                # band-pass node
lp  = g*bp + s2                                # low-pass node (output)

s1  = tanh(bp)                        # nonlinear resonance damping
s2  = tanh(lp)                        # keeps it aggressive but bounded

out[i] = lp
```

- **`k = 2.0 * res`** — resonance feedback coefficient.
- **`s1`, `s2`** — per-channel integrator state (the two poles).
- **`tanh` on the input** = the OTA drive/growl stage.
- **`tanh` on the integrator states** = nonlinear resonance damping — lets the
  resonance scream near self-oscillation without blowing up.

### 2.2 Resonance

- `res` ∈ `0 .. 1.15`, clamped. The MS-20 self-oscillates; we keep `k` **just
  under unstable** so the peak screams but stays bounded.
- `k = 2.0 * res` (linear mapping).

### 2.3 Drive (OTA growl)

- `drive` ≥ `0.5`. Multiplies the input **before** the `tanh` clipper.
- This is what makes the late **OTA** MS-20 growl and distort.

### 2.4 Variants

The MS-20 shipped with two filter revisions; both are emulated:

| variant   | `k` scaling | `drive` scaling | input clip              | character                    |
|-----------|-------------|-----------------|-------------------------|------------------------------|
| `korg35`  | `* 0.9`     | `* 0.9`         | `tanh(inp*0.9) * 1.05`  | early, smoother, more musical |
| `ota`     | `* 1.0`     | `* 1.0`         | `tanh(inp)`             | late, aggressive, edgy       |

### 2.5 Time-varying cutoff (sweeps)

- `cutoff_hz` may be a **scalar** (static filter) or a **per-sample array**
  (for sweeps). The loop recomputes `f` and `g` every sample.
- Cutoff clamped to `[20 Hz, sr * 0.45]` for stability.
- `g` additionally clamped to `≤ 1.2` to keep the trapezoidal-ish integrator
  stable at high cutoffs.

---

## 3. Public API

### 3.1 `ms20_lowpass(x, sr, cutoff_hz, res=0.9, drive=1.5, variant="ota")`

The core filter. Mono `(n,)` or multi-channel `(n, ch)` float arrays.
Returns the filtered signal, same shape. **Per-sample cutoff supported.**

### 3.2 `ms20_open(x, sr, bpm, beats=8.0, from_hz=90, to_hz=16000, res=0.95, drive=1.7, variant="ota", curve="exp")`

**"Filter open" intro.** Sweeps the resonant LP from `from_hz` up to `to_hz`
over `beats` beats, then **hard off** (full-band, unfiltered) — the classic
"filter snap open into the first drop". The tail is returned untouched (unity).

- `curve="exp"` → perceptually-even **log sweep** (slow in the lows, snapping
  into the highs — how a hand on an MS-20 cutoff knob actually feels).
- Boundary declicked with `declick_join(..., fade_ms=3.0)` so the snap to
  full-band doesn't click.

### 3.3 `filter_automation(x, sr, bpm, *, bars=1, lp_from=0.05, lp_to=1.0, res=0.6, drive=1.1)`

**Clean filter-automation effect** (the "Vengeance envelope" sound). A resonant
MS-20 LP sweep from `lp_from`→`lp_to` (normalized 0..1 mapped to **200 Hz →
16 kHz, log**) over `bars` bars. **No buffer mangle / gate / pitch / pan** —
just the clean "filter opens over N bars" automation. Returns same shape.

Used in the intro **dual-speed FX**: 1× slow 1-bar sweep + 4× fast ¼-bar
(16th-note) sweeps back-to-back.

### 3.4 Glitch engine post-filter

`glitch_bitch(...)` and the FX programs run their buffer-mangled output through
`ms20_lowpass(..., variant="ota")` with a **static cutoff (≈ 14 kHz) and
aggressive res** — the "CyberLuke edition grit" on top of the mangle.

---

## 4. Determinism & numerics

- **Deterministic:** fixed coefficients from `(sr, res, drive, variant)`; the
  filter state only evolves forward. Same input → identical output every render.
- **dtype:** all computation in `float32` (`np.float32` buffers, float64
  intermediates for `tan`/`pi` constants).
- **Canonical audio:** 48000 Hz / 2 ch / float32 (see `audio_io.read_wav`).
- **Stability:** cutoff clamp, `g` clamp, and `tanh` state damping keep the
  filter bounded even at high resonance / drive.

---

## 4.5 Reference: Parker/Esqueda/Bergner DAFx-19 STN

This implementation is a **hand-tuned virtual-analog (white-box-inspired)
emulation**, not a learned black-box model. The canonical research reference
for a *learned* MS-20 filter is:

> J. D. Parker, F. Esqueda, A. Bergner (Native Instruments),
> *"Modelling of Nonlinear State-Space Systems using a Deep Neural Network,"*
> Proc. DAFx-19, Birmingham, UK, 2019. (`DAFx2019_paper_42.pdf`)

Their **State Trajectory Network (STN)** learns the MS-20 REV2 (Sallen-Key +
LM13700 OTA + 1N4148 resonance-feedback diodes) as a **discrete-time
state-space system with an embedded MLP**:

```
[x_{n+1}]        [u_n]
[  y_n ]  =  fd  [x_n]     <- fd is a learned static (memoryless) MLP
```

- **States:** x1 = output diff of OTA1 (IC1) vs feedback amp; x2 = output of
  OTA2 (IC2) = the output node y.
- **Network:** small MLP (e.g. `3x4 tanh` ≈ 524 ops/sample ≈ 0.10 GFLOPS),
  trained on measured state-trajectories (swept-sine + music).
- **Captures self-oscillation** — the closed-orbit in state space — which
  black-box I/O-only models (Volterra, Wiener-Hammerstein) cannot.

### How our model differs

| Aspect | This repo (`ms20_lowpass`) | Parker STN (DAFx-19) |
|--------|---------------------------|----------------------|
| Approach | White-box-inspired SVF, hand-tuned | Pseudo-black-box learned STN |
| Core | 2-pole SVF + `tanh` drive + `tanh` state damping | MLP approximating state-derivative |
| Nonlinearity | `tanh` (input clip + state damping) | learned (captures diode + OTA saturation) |
| Self-oscillation | bounded, just under unstable | modelled as a learned closed orbit |
| Params | `res`, `drive`, `variant`, per-sample `cutoff` | fixed Ictl (cutoff) + fixed resonance pot |
| Runtime | pure NumPy, offline, deterministic | MLP, real-time capable (0.10 GFLOPS) |

### Possible upgrade path

If we want **true self-oscillation** (the MS-20 "sine" when res is maxed with
no input) or a closer match to the hardware's *phase-accurate* saturation, the
STN approach is the way: replace the `tanh` SVF core with a small learned MLP
(`3x4 tanh`) trained on state-trajectory data from a real MS-20 (or a SPICE /
white-box sim). For our offline render use-case the current SVF is sufficient
and far simpler; the STN would matter if we ever need a *self-oscillating
resonance tail* or a *measured-hardware* timbre.

---

## 5. Libraries used

| Library | Version (venv `.venv-hypermix`) | Role |
|---------|----------------------------------|------|
| **NumPy** | 2.4.6 | All DSP math — arrays, `tanh`, `tan`, `pi`, `linspace`/`exp` cutoff sweeps, per-sample loop over float32 buffers. The MS-20 core is **pure NumPy** — no compiled filter extension. |
| **SciPy** | (transitions/dsp.py imports `scipy.signal.butter`, `sosfilt`) | Used only by the **one-pole** helpers (`one_pole_lowpass`, `one_pole_highpass`) for simple Butterworth crossfade/utility filtering — **not** by the MS-20 SVF itself. |
| **librosa** | 0.11.0 | **Not used by the filter.** Used elsewhere in the pipeline for spectral features / key detection (`goldenrun._spectral_features`, `phrase_key.detect_key`). |

**The MS-20 filter core depends only on NumPy** (`np.tan`, `np.tanh`, `np.pi`,
`np.clip`, array ops). The per-sample Python loop is intentional — it gives a
true state-variable feedback loop with nonlinear damping, which vectorized
`scipy.signal` forms (SOS/lfilter) cannot express (they are LTI; the MS-20 is
deliberately nonlinear via `tanh` drive + state damping).

---

## 6. Python environment

- **venv:** `.venv-hypermix` → `.\.venv-hypermix\Scripts\python.exe`
- **Python:** 3.14.7
- Rendered via the canonical command:

```
.\.venv-hypermix\Scripts\python.exe -W ignore -m src.hypermix.cli pack render \
  packs\my-library --out renders\mix-arc --mode deep --segment-bars 64 \
  --length 16 --seed 7 --cut --harmonic-arc
```

---

## 7. Tuning reference (current intro chain)

| Stage | Call | res | drive | variant | cutoff |
|-------|------|-----|-------|---------|--------|
| Intro sweep | `ms20_open(res=0.6, drive=1.15)` + head ×0.7 | 0.6 | 1.15 | ota | 90 Hz → 16 kHz exp, 8 beats |
| Post-tag slow FX | `filter_automation(bars=1, res=0.6, drive=1.1)` | 0.6 | 1.1 | ota | 200 Hz → 16 kHz log, 1 bar |
| Post-tag fast FX | `filter_automation(bars=0.25, res=0.7, drive=1.2)` ×4 | 0.7 | 1.2 | ota | 200 Hz → 16 kHz log, ¼ bar |
| Glitch grit | `ms20_lowpass(res, drive, variant="ota")` | spec | spec | ota | static ≈ 14 kHz |

*(Intro sweep gain was turned DOWN from res 0.95 / drive 1.7 — the resonance
was overcooking the intro.)*
