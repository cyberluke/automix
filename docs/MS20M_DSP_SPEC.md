# MS-20M Dual-Revision DSP — Architecture Spec

This document describes the **physical Korg MS-20M virtual-analog model**
implemented under `src/hypermix/dsp/`. It supersedes the generic state-variable
filter (SVF) previously used for the `ms20_*` transition effects.

The golden reference is the physical **Korg MS-20M** desktop module, which has a
hardware **REV.1 / REV.2 FILTER TYPE** switch, independent resonant **HPF + LPF**
(each 50 Hz – 15 kHz, both self-oscillating), an external VCF input (up to
~3 Vp-p), and independent HPF/LPF cutoff CV.

---

## 1. Separation of concerns

| Layer | Module | Responsibility |
|-------|--------|----------------|
| Physical device model | `dsp/ms20m.py` (`MS20MFilter`) | The MS-20M itself: HPF→LPF, two revisions, self-oscillation, input gain, noise floor |
| Revision cores | `dsp/ms20m_rev1.py`, `dsp/ms20m_rev2.py` | Thin device classes delegating to compiled backends |
| Nonlinear backends | `dsp/nonlinear_backend.py` | Numba-compiled per-sample inner loops (Korg-35 + OTA) |
| Island infra | `dsp/oversampling.py` | Linear-phase oversampled island around the nonlinear core |
| Quality tiers | `dsp/quality.py` | `MS20M_QUALITY` preview / production / reference |
| Linear-phase EQ | `dsp/linear_phase.py` | HyperMix *production* EQ (separate from the MS-20 model) |
| Production FX | `transitions/dsp.py` | `ms20_open`, `filter_automation`, glitch, declick — composition only |
| Calibration | `calibration/` | Probes, capture matrix, measurements, grey-box fitting |

The production layer intentionally contains **no analog math** — it composes the
device model. The device model intentionally contains **no transition
composition**.

---

## 2. Signal path

```
INPUT
  → input gain (input_gain_db, linear)
  → resonant HPF (revision core)
  → resonant LPF (revision core)
  → OUTPUT
```

Always HPF then LPF, matching the hardware. Both filters share the revision
character. Cutoffs/resonances may be static scalars or per-sample arrays at the
48 kHz authoring rate; they are interpolated (log-space for Hz) into the
oversampled domain inside the island.

---

## 3. Revisions

### REV.1 — Korg-35 (`_korg35_core`)
Earlier, aggressive, distorted, noisier.

- Input `tanh(inp · drive)` — hard-ish drive.
- Resonance `fb = 2.2 · peak²` (squared law → smooth scream onset).
- Nonlinear resonant return `ret = tanh(s1)`.
- Integrator saturation `s1 = tanh((s1 + g·hp) · 1.02)` — the `1.02` keeps the
  loop alive into true self-oscillation.
- Measured (48 kHz, fc=1.2 kHz, peak=0): passband ≈ 0.26 for a 0.40 sine
  (compressed); self-oscillates (rms ≈ 0.20) at peak=1.

### REV.2 — OTA + 1N4148 diode (`_ota_core`)
Later, lower-noise, smoother.

- Input `tanh(inp · drive)` — gentler.
- Resonance `k = 2.3 · peak²`; feedback saturates through `tanh(s1·1.5)`
  (the 1N4148 pair lives in the **feedback path**, not on the states).
- Stable ZDF 2-pole; states stay near-linear in the passband; mild integrator
  overdrive `tanh(·)·1.06` sustains self-oscillation.
- Measured: passband ≈ 0.48 (cleaner than REV.1); self-osc rms ≈ 0.41
  (stronger, smoother scream).

Both revisions self-oscillate under a silence probe at peak=1 and pass a
sub-cutoff sine near their characteristic gain at peak=0.

---

## 4. Oversampled nonlinear island

The recursive nonlinear core runs inside a linear-phase oversampled island so
that the nonlinearities do not alias into the audible band.

```
48 kHz
  → cascaded 2x half-band linear-phase FIR upsampler
  → [ nonlinear core @ factor·48 kHz ]
  → cascaded 2x half-band anti-alias downsampler
  → 48 kHz
```

- Half-band kernel: `firwin(n, 0.25, blackmanharris)`, DC-normalised.
- Each 2x upsample stage is multiplied by 2 to compensate polyphase gain
  (`upfirdn(up=2)` has a DC gain of 0.5). Without this the island attenuates by
  0.5^stages (0.0625 at 16x) — this was a real bug, fixed and verified.
- Group delay of every stage is compensated so the canonical 48 kHz sample
  clock is preserved and phrase boundaries do not move.
- Only the **island boundary** filters are linear-phase; the filter's own phase
  response (part of the physical emulation) is preserved.

### Quality tiers (`MS20M_QUALITY`)

| profile | oversample | FIR stopband | taps |
|---------|-----------|--------------|------|
| preview | 8x | 100 dB | 65 |
| production (default) | 16x | 120 dB | 129 |
| reference | 32x | 140 dB | 257 |

All internal processing is float64; I/O is float32 at 48 kHz / 2ch.

---

## 5. Numba acceleration

The per-sample cores are compiled with `@njit(cache=True, fastmath=False)`.

- `fastmath=False` keeps results deterministic (no reassociation).
- Numba cannot use `np.random.default_rng` or untyped module-level helpers
  inside `njit`. Deterministic analogue noise therefore uses an inline LCG hash
  `nz = (nz·1103515245 + 12345) mod 2147483647`, and control broadcasting is done
  in the (non-JIT) wrappers before the core call.
- 16x oversampling of 1 s of audio = 768 k samples processed in ≈ 0.14 s
  (cached). First call pays JIT compile; `cache=True` persists it.

---

## 6. Calibration harness (`src/hypermix/calibration/`)

Built to fit the model against the **physical** MS-20M (sections below are the
harness; no hardware captures exist yet).

- `probes.py` — ESS log sweep, stepped sines, multisine, pink/white noise,
  impulse, saw, square, kick transient, silence (for self-osc capture).
- `ms20m_capture.py` — capture matrix over revisions × peaks × input levels ×
  cutoffs; writes probe WAVs + `capture_matrix.json` with the full knob state.
- `ms20m_measure.py` — magnitude/phase (csd/welch), THD (H2–H5), harmonic
  levels, resonant peak, self-osc amplitude, noise floor, DC offset, residual
  (latency-aligned, gain-fitted `hw − model`).
- `ms20m_fit.py` — grey-box fitting: `fit_peak_mapping` (`a·pk + b·pk²`
  correction) and `fit_cutoff_mapping` (log-log linear). Deliberately does **not**
  train an opaque NN first.

---

## 7. Public API

```python
from src.hypermix.dsp.ms20m import MS20MFilter, ms20m_filter

y = ms20m_filter(x, sr,
                 revision="rev2",
                 hpf_cutoff_hz=20.0, hpf_peak=0.0,
                 lpf_cutoff_hz=1200.0, lpf_peak=0.85,
                 input_gain_db=0.0, quality="production",
                 noise_mode="deterministic", seed=7)
```

Production wrappers in `dsp/ms20m_fx.py`: `ms20m_open`, `ms20m_close`,
`ms20m_band_sweep`, `ms20m_scream`.

The legacy `transitions/dsp.py::legacy_ms20_style_svf` is kept (with the alias
`ms20_lowpass`) only as a fallback when the new package is unavailable; it is
explicitly documented as *not* a physical MS-20 model.

---

## 8. Status / acceptance

- [x] Dual-revision model (REV.1 Korg-35, REV.2 OTA) with self-oscillation
- [x] Linear-phase oversampled island, unity gain, group-delay compensated
- [x] Quality tiers preview / production / reference
- [x] Numba-compiled deterministic cores
- [x] Production layer routes through the model (import guard + legacy fallback)
- [x] Calibration harness (probes / capture / measure / fit)
- [ ] Hardware captures + per-revision mapping fits (needs the physical unit)
- [ ] Chunked render state carry (long-form streaming)
- [ ] JP-8080 model (future work)

See also: `docs/MS20_FILTER_SPEC.md` §4.5 (DAFx-19 STN reference) and the CTO
implementation instructions that drove this work.
