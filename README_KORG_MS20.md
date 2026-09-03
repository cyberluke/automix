# KORG MS-20 / Korg-35 Filter — Engineering Notes

Internal working notes for future tuning of our nonlinear MS-20 (Korg-35 and
OTA "later") filter model in `src/hypermix/dsp/`.

Scope: what was found, what was fixed (2026-09), and what to watch for when
re-tuning the model.

---

## 1. Context

HyperMix models the MS-20 filter as a physical virtual-analog device
(`MS20MFilter`) with two revisions:

| Revision | File | Topology | Character |
|---|---|---|---|
| **rev1** | `src/hypermix/dsp/ms20m_rev1.py` | `_korg35_core` (nonlinear_backend) | Korg-35, more aggressive, rougher |
| **rev2** | `src/hypermix/dsp/ms20m_rev2.py` | `_ota_core` (nonlinear_backend) | OTA "later", smoother, lower noise |

Both delegate to the backend in `src/hypermix/dsp/nonlinear_backend.py`.

---

## 2. Issue Found (2026-09)

### Symptom

On the first phrase of the golden mix the Korg filter sounded overdriven /
too hot specifically under **automation** (cutoff/resonance sweep), not in a
steady-state condition.

### Diagnosis

We measured THD on an **automated cutoff** sweep (300→16000 Hz, res 0.6,
drive 1.0) and found an asymmetry:

| Revision | THD before fix | THD after fix |
|---|---|---|
| **rev2 (OTA)** | **~35.6 %** | **~3.4 %** |
| rev1 (Korg-35) | ~14.0 % | ~14.0 % (untouched) |

Target was "roughly half"; rev2 now sits well under that (3.4 %).

### Root Cause (thoroughly verified)

`_ota_core` (rev2) carried nonlinearities that the **real MS-20 filter does not
have**, and those surfaced specifically under automation:

```python
# BEFORE (problematic):
k  = 2.3 * pk[i] * pk[i]   # resonance squaring law
fb = np.tanh(s1 * 1.5)     # 1.5 feedback boost
s1 = np.tanh(bp) * 1.06    # per-sample overdrive ×1.06
s2 = np.tanh(lp) * 1.06
```

```python
# AFTER (fixed):
k  = 2.0 * pk[i]           # linear Q-map, no squaring
fb = np.tanh(s1)           # cleaner diode, no 1.5 boost
s1 = np.tanh(bp)           # no ×1.06 overdrive
s2 = np.tanh(lp)
```

### Reference Comparison

Authoritative reference: **Eric Tarr / STK `korg35LPF`** in
`faustlibraries/vaeffects.lib` (MS-10/MS-20 filter). Reference structure:

- resonance: `K = 2·(Q − 1/√2)/(10 − 1/√2)` → **linear Q-mapping, no `pk²`**
- ZDF coeffs: `B2 = −1/(1+g)`, `B3 = (K − K·G)/(1+g)`,
  `alpha0 = 1/(1 − K·G + K·G²)`
- **no** `tanh(s·1.5)`, **no** `·1.06` per-sample overdrive

Conclusion: rev2 contained **deterministic nonlinear "cosmetic" boosts** that the
real device does not have → removed. rev1 left unchanged.

---

## 3. Where the Code Lives

- `src/hypermix/dsp/nonlinear_backend.py`
  - `_korg35_core` (rev1)
  - `_ota_core` (rev2) — **this was fixed**
- `src/hypermix/dsp/ms20m.py` — `MS20MFilter` (revision selection, oversampling, gain)
- `src/hypermix/dsp/ms20m_rev1.py`, `ms20m_rev2.py` — thin wrappers
- `src/hypermix/dsp/oversampling.py` — oversampled nonlinear island (ZOH cutoff)
- `src/hypermix/dsp/nonlinear_backend.py` — the filter cores

---

## 4. How to Measure / Tune

### THD on Automated Cutoff (the scenario that caught the bug)

```python
import numpy as np
from src.hypermix.dsp.ms20m import MS20MFilter

sr = 48000; n = int(sr*2.0); t = np.arange(n)/sr; f0 = 1000.0
x = np.stack([np.sin(2*np.pi*f0*t)*0.15]*2, axis=1)

def thd(y, sr, f0):
    m = y[:,0]; w = np.hanning(len(m)); Y = np.abs(np.fft.rfft(m*w))
    f = np.fft.rfftfreq(len(m), 1/sr)
    def idx(k):
        mm = (f > k*f0-60) & (f < k*f0+60); return Y[mm].max() if np.any(mm) else 0.0
    return np.sqrt(sum(idx(k)**2 for k in range(2,8))) / max(1e-12, idx(1))

c = np.geomspace(300, 16000, n)   # automated cutoff (sweep)
for rev in ["rev1", "rev2"]:
    filt = MS20MFilter(sr, revision=rev, hpf_cutoff_hz=20, hpf_peak=0,
                       lpf_cutoff_hz=c, lpf_peak=0.6, bypass_hpf=True,
                       input_gain_db=0.0, quality="production")
    y = filt.process(x)
    print(f"{rev}: THD={thd(y,sr,f0)*100:.1f}%  peak={float(np.abs(y).max()):.3f}")
```

### Tuning Guidelines

- **Always tune THD against an automated sweep, not a static cutoff.** A static
  measurement will not catch this class of bug (before the fix everything looked
  nominally fine under static conditions).
- **One nonlinearity per site.** No MS-20 model uses per-sample multipliers
  (`·1.06`) or two layered tanh. Put the nonlinearity either in the integration
  loop *or* in the resonance feedback path — never both.
- **Resonance ≈ linear mapping to peak** (see reference). The quadratic `pk²`
  feels nice but is not physically MS-20. To make it more aggressive, raise the
  coefficient `k` linearly (e.g. 2.0 → 2.4), not via `pk²`.

### Safe Way to Add Aggression to rev2 (if needed)

1. `k = 2.0·pk` → `k = 2.4·pk`, then re-measure THD (should rise, but keep below target).
2. `fb = tanh(s1)` → `fb = tanh(s1 * 1.15)`, then re-measure.
3. Optionally use `lpf_peak` at input (already present) instead of internal overdrive.

Always **re-run the THD script above** and compare against the baseline numbers
(rev1 14 %, rev2 3.4 %).

---

## 5. Reference Sources

| Source | What it is | Link |
|---|---|---|
| Faust `vaeffects.lib` — `korg35LPF` / `korg35HPF` | Eric Tarr / STK, authoritative Korg-35 model | `https://raw.githubusercontent.com/grame-cncm/faustlibraries/master/vaeffects.lib` |
| René Schmitz MS-20 (later filter) | schematic + 2-section HPF→LPF description | `https://www.schmitzbits.de/ms20.html` |
| `SpotlightKid/faustfilters` | collection of virtual-analog filters (multi-format) | `https://github.com/SpotlightKid/faustfilters` |
| Kassutronics KS-20 | MS-20 clone | `https://kassu2000.blogspot.com/2019/07/ks-20-filter.html` |

> Local search (for future research): local SearXNG runs at
> `http://localhost:8080/`, JSON API `http://localhost:8080/search?q=...&format=json`.
> The MCP server `mcp-searxng` uses `SEARXNG_URL` (see VS Code profile mcp.json) —
> it previously pointed at a dead ngrok endpoint, now set to `http://localhost:8080/`.

---

## 6. Open / Remaining Items

- **rev1 (Korg-35) THD 14 %** under automation — intentionally **untouched**
  (different character, more aggressive sound). If rev1 also overdrives in the
  golden mix, apply the same logic (remove `tanh(s·1.02)` and `2.2·pk²`, see
  `_korg35_core`).
- **ZOH cutoff in oversampling** (`oversampling.py`, `np.repeat` for ctrl) —
  under automation the cutoff is held via zero-order hold, not interpolated. It
  was not the primary THD cause, but for surgically smooth sweeps consider
  interpolation.
- **No official Faust reference for rev2/OTA** (unlike Korg-35). When tuning
  rev2 further, base it on the MK model + schematic (Schmitz) + target THD.