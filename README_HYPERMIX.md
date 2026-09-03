# HyperMix — Vocal-First Golden Mix Engine

This is the documentation for the **new mix engine** that builds a megamix from
a phrase pack. It targets a different philosophy than the existing (club) mixer:
a **studio-cut vocal hook relay** — a mix made primarily of **vocal-first phrases**
that chain into each other, rendered by a deterministic, programmatic DSP layer.

> **Note for PR reviewers / maintainers:** the DSP here is *deterministic and
> programmatic*, not "autonomous" in the sense of a learned or online-deciding
> model. Every effect and every transition is a fixed, code-driven operation that
> is reproducible byte-for-byte given the same inputs.

---

## 0. It is not "just a vocal-first engine"

The vocal-first behaviour is **one weighted term** in a larger, steerable
scoring model — *not* the whole engine. The `DeepMixDirector` computes a
weighted score for every candidate phrase and picks the best (in
`deterministic` mode) or samples probabilistically (in `weighted-random` mode).
The mix style is a knob, not a fixed bias.

The complete scoring model combines these axes (each with its own weight):

| # | Axis | Weight | What it does |
|---|---|---:|---|
| 1 | **Hook / recognition density** | `rating` | short, high-rating phrase = faster payoff |
| 2 | **Section length** | — | keep the hook for the full target phrase (`target_bars`) |
| 3 | **Reset transitions** | `reset_bias` | prefer cut techniques over blends |
| 4 | **Fresh-crate + novelty** | — | each track plays once before the crate revisits |
| 5 | **Continuous flow** | `continuity_weight`, `spectral_weight` | match level & spectral signature (climax→climax, breakdown→breakdown) |
| 6 | **Energy trajectory** | `trajectory_weight` | drop→drop; avoid energy cliffs |
| 7 | **Harmonic arc (Camelot)** | `arc_weight`, `energy_gradient_weight` | ascending tonal/energy curve (tiebreak) |
| 8 | **Vocal-family** | `vocal_family_weight` | vocal↔vocal / instrumental↔instrumental (+ clash penalty) |
| 9 | **Vocal-first** | `vocal_bias_weight` | global pull toward vocal phrases |

So you can steer the mix toward any combination of styles:

- **Pure vocal-first** → high `vocal_bias_weight` (the shipped default).
- **Big, continuous energy arc** → raise `harmonic_arc`/`arc_weight`/
  `energy_gradient_weight`, lower `vocal_bias_weight`.
- **Classic deep-dance cuts** → raise `reset_bias`, keep `spectral_weight`
  high, drop `vocal_*` to 0.
- **Weighted randomness / variation** → set `mode="weighted-random"` to trade
  determinism for variety.

The shipped preset driver runs the vocal axis high to hit the vocal-relay goal,
but the underlying engine is a general weighted phrase sequencer.

---

## 1. What the engine does

The engine generates a megamix in three layered stages:

1. **Phrase selection (director)** — `DeepMixDirector` picks the order of segments
   from the phrase graph. It favours:
   - **vocal-first** phrases (the mix should read as a vocal hook relay),
   - **vocal chaining** (when the current phrase is vocal, it continues with a
     vocal phrase),
   - short, high-hook sections (target 64 bars = a full hook section),
   - **reset transitions** (`rewind` / `slam` / `backspin` / `echo_cut` /
     `stutter` / `drum_roll` / `power_up` / `power_down`) instead of smooth blends,
   - **fresh-crate**: a track is not revisited until the whole crate has played.
   - Deterministic: the same `(pack, seed)` yields the same ordering.

2. **DNA (producer recipe)** — selected segments can be processed with a
   hand-written "cookbook" of operators (voice tag, filter sweep, juggle, bass
   solo, GlitchBitch, …), indexed in bars so it can be transferred across phrases.

3. **Render / DSP (renderer)** — `GoldenRenderer` renders the plan to
   `golden.wav`. It applies graph-edge transitions and fills the mix with
   programmatic DSP effects (declick, MS-20 filter automation, voice tag,
   deep_dance_chop, …). All of it is deterministic.

---

## 2. Quick start

> First create your environment — see **2.1** below.

```powershell
# 0) activate the venv (see 2.1 for how to create it)
.\.venv-hypermix\Scripts\Activate.ps1

# 1) drop your track files into the music/ folder (any format; audio is extracted)

# 2) fire and forget — this one command builds the pack if needed, then renders
.\.venv-hypermix\Scripts\python.exe scripts/analysis/render_director_golden.py
```

The driver is **fully automatic**:

- On the **first run** it scans `music/`, auto-detects hero cues per track, and
  compiles the phrase pack (segments, edges, graph, WAV assets) for you — no
  manual crate/pack authoring.
- On later runs it only **rebuilds when your `music/` folder changed**. If nothing
  changed, it skips analysis + pack build and renders straight from the existing
  pack (no wasted work).
- So the workflow is simply: put tracks in `music/`, run the one command, get
  `golden.wav`. See **3.1** and **6**.

The script writes the following files to your output directory (`OUT_DIR`):

| File | Description |
|---|---|
| `golden.wav` | final mix |
| `set.plan.json` | director plan (segments, edges, techniques) |
| `golden.timeline.json` | actual rendered timings after DSP |
| `golden.events.json` | rendered DSP / voice-tag events |
| `golden.trace.json` | audit trace (seed, recipe, camelot, rebuild flag, report) |
| `golden.report.json` | report (samples, sha256, path) |

### 2.1 Environment setup (create your own venv)

The `.venv-hypermix` / `.venv-stems` folders are **gitignored and not in the
repo** — you must create them yourself. Do **not** commit a venv to git.

Use **Python 3.10–3.12** (the pinned deps — `numpy 1.26.4`, `librosa 0.10.1` —
predate Python 3.13/3.14 and may fail to build there).

```powershell
# 1) create + activate the base environment
py -3.12 -m venv .venv-hypermix
.\.venv-hypermix\Scripts\Activate.ps1

# 2) install the base runtime (stem-free club mixer + streaming server)
python -m pip install --upgrade pip
pip install -r requirements.txt

# 3) OPTIONAL — stem separation (demucs, heavy, PyTorch CPU build ~200 MB).
#    Only needed if you want the "HQ transitions" toggle.
pip install -r requirements-stems.txt `
    --extra-index-url https://download.pytorch.org/whl/cpu

# 4) generate the mix
python scripts/analysis/render_director_golden.py
```

The script writes the following files to your output directory (`OUT_DIR`):

| File | Description |
|---|---|
| `golden.wav` | final mix |
| `set.plan.json` | director plan (segments, edges, techniques) |
| `golden.timeline.json` | actual rendered timings after DSP |
| `golden.events.json` | rendered DSP / voice-tag events |
| `golden.trace.json` | audit trace (seed, recipe, camelot, report) |
| `golden.report.json` | report (samples, sha256, path) |

---

## 3. Parameters — how to generate your own mix

### 3.1 Entry script

The script is a **reference implementation** — the key parameters are constants at
the top:

```python
PACK          = Path('packs/my-library')   # source phrase pack (yours will differ)
OUT_DIR       = Path('renders/my-mix')     # output directory
SEED          = 7                          # selection determinism
SR            = 48000                      # sample rate
TARGET_BARS   = 64                         # phrase-section length (bars)
OPENING_END_S = 53.0                       # trim the opening track to 53 s
```

> `PACK` points at a phrase pack directory containing `graph/segments.json`,
> `graph/edges.json` and `graph/graph.json` (see **6. Key files**). Any pack you
> compile with the same graph schema works — the engine is dataset-independent.
>
> **The pack is generated automatically from `music/` — you never author it.**
> The driver scans `music/`, auto-detects hero cues per track, and drives the
> analyzer + segment/edge compilers to produce `segments`, `edges`, `graph` and
> the WAV assets. It rebuilds only when the `music/` folder has changed (tracked
> via a small `.source-manifest.json` sidecar next to the pack), so unchanged
> runs render straight from the existing pack.

### 3.2 Director (`DeepMixDirector`)

Selection parameters live in `src/hypermix/director/deep_selector.py`:

| Parameter | Default | Meaning |
|---|---|---|
| `seed` | 0 | deterministic ordering |
| `mode` | `weighted-random` | `deterministic` = always pick highest score; `weighted-random` = probabilistic |
| `target_bars` | 4 | how many bars the selected hook section uses |
| `reset_bias` | 0.8 | prefer reset transitions (cut) over continuity (blend) |
| `harmonic_arc` | False | enable Camelot / ascending-energy curve |
| `arc_weight` | 1.0 | strength of the harmonic arc (tiebreak) |
| `energy_gradient_weight` | 1.5 | prefer phrases with climbing energy |
| `continuity_weight` | 6.0 | level continuity coupling |
| `spectral_weight` | 5.0 | spectral similarity coupling |
| `vocal_family_weight` | 4.0 | vocal-to-vocal / instrumental-to-instrumental (+ clash penalty) |
| **`vocal_bias_weight`** | **8.0** | **unconditional pull toward vocal phrases — the main vocal-first lever** |
| `trajectory_weight` | 4.5 | energy trajectory (drop→drop) |

> **The most important knob for a vocal-first mix is `vocal_bias_weight`.**
> Higher values make vocal phrases dominate; lower values allow more contrast /
> continuity.

### 3.3 Renderer (`GoldenRenderer`)

Interface in `src/hypermix/compiler/deterministic_render.py`:

```python
report = GoldenRenderer().render(
    plan, segments, edges, seg_audio, out_dir,
    force_cut=bool(...),   # True=drop→drop cuts, False=full phrase length
)
```

Returns a `report` with keys such as `totalSamples`, `goldenSha256`, `goldenPath`.
The transition/edge DSP and chop run inside the renderer.

### 3.4 DNA recipe (producer recipe)

A DNA recipe is a JSON file in `data/dna_recipes/`. Example structure:

```jsonc
{
  "name": "my_dna_v1",
  "phrase_bars": 64,
  "bpm_ref": 128.0,
  "principles": { "...": "..." },          // profile semantics (optional)
  "steps": [
    {
      "id": "filter_question",
      "bar": 16.0, "beat": 0.0, "span_bars": 2.0,
      "when_role": null,                    // role gate (DROP_HOOK / ...)
      "call": { "op": "filter_sweep", "params": { "...": "..." } }
    }
  ]
}
```

Recipe names are dataset-independent — you record a recipe on one phrase and the
engine re-resolves it onto any other phrase via BPM/bar indexing.

**Operators** (`src/hypermix/dna/engine.py`, registered via `@operator`):

| Operator | What it does |
|---|---|
| `filter_sweep` | MS-20/resonant filter automation (LP/HP sweep, slow/fast) |
| `voice_tag` | voice-stab overlay (e.g. `Cyberluke2`) |
| `juggle` | beat-juggle preset (buffer replace) |
| `micro_edit` | GlitchBitch/glitch edit on the source |
| `bass_solo` / `cyber_bass` | bass passages (requires stems) |
| `noop` | no-op placeholder |

Special behaviour:

- steps with `params.post_mix: true` are rendered **after** master processing,
  so no further DSP touches them (protects voice tags / signatures).

### 3.5 How to build your own mix

1. Change `SEED` (different ordering), `TARGET_BARS` (section length), or tune
   `vocal_bias_weight`.
2. Want **director-only** (no DNA)? Remove the `apply_recipe` section in `main()`.
3. Want **a different pack**? Change `PACK` and rebuild the graph.
4. Listen to `golden.wav` and tune against `golden.timeline.json`.

---

## 4. Options / future directions

- **Force the opening track**: the reference script forces a chosen opening
  segment and trims it via `OPENING_END_S`. Change that constant / the selected
  segment for a different opening.
- **Determinism**: the same `(pack, seed, director params)` yields byte-identical
  `golden.wav` (SHA256 is in the report).
- **Vocal ratio**: raise / lower `vocal_bias_weight` (`0` = off, `8+` = aggressively
  vocal).
- **Mix length**: the number of steps is a loop bound in the driver; adjust it for
  a different number of phrases.
- **Render / DSP behaviour**: `force_cut` toggles drop→drop cuts vs. full phrase
  length.

---

## 5. What we implemented vs. the `main` branch

> Below is the **functional delta** against the original / club engine (branch
> `main`). Note: one commit in `git log` (`d6d3e46` — `.gitignore` cleanup) is on
> the `hypermix` branch; all the engine functionality below is work-in-progress
> (uncommitted) change set.

### 5.1 Vocal-first phrase selection (new)

**`src/hypermix/director/deep_selector.py`**
- New `_is_vocal(roles, feats)`: in addition to the role list, it also considers
  phrase-native `content` features, so even in bass-heavy EDM — where
  `BASS_DOMINANT` out-scores `VOCAL_DOMINANT` — a phrase with
  `vocal_probability ≥ 0.5` is recognised as vocal.
- New `_vocal_bias_bonus(seg)` + parameter **`vocal_bias_weight` (default 8.0)**:
  an unconditional pull toward vocal phrases in `_score` → the mix is primarily
  vocal-first.
- **Vocal chaining** in `choose_next`: when the current phrase is vocal it narrows
  the pool to vocal candidates → vocal phrases connect to each other.
- Result: on the original dataset, only a minority of phrases were vocal and often
  clumped in long runs. After the change the mix is dominated by vocal phrases and
  vocal phrases chain directly.

### 5.2 Deterministic "golden" render (studio-cut, not blend)

**`src/hypermix/compiler/deterministic_render.py`** — `GoldenRenderer`
- Renders a `SetPlan` to `golden.wav` + timeline / events / report.
- Programmatic DSP on graph-edge transitions (declick, MS-20 filter automation,
  voice tag, chop at the end of the first track).
- Byte-deterministic: same pack + seed + commands ⇒ identical `golden.wav`.

### 5.3 Director-based golden orchestration without a static playlist

- New driver script **`scripts/analysis/render_director_golden.py`**:
  - drives the **real director** from the phrase graph (no alphabetical ordering,
    no recipe applied indiscriminately to every track),
  - optionally forces a DNA-treated opening segment,
  - the continuation is chosen by `DeepMixDirector`,
  - keeps the deterministic `GoldenRenderer` DSP and graph-edge techniques.

### 5.4 Deferred post-processing and protected overlays

**`src/hypermix/dna/engine.py`**
- `apply_recipe` now resolves **deferred steps** (`post_mix: true`) after master
  processing, so voice tags / signatures are not damaged by further DSP.
- Operator registry: `voice_tag`, `filter_sweep`, `juggle`, `micro_edit`
  (GlitchBitch), `bass_solo`, `cyber_bass`.

### 5.5 Worked DNA profile (example: `data/dna_recipes/`)

As a worked example, the repo ships one polished producer recipe (stored under
`data/dna_recipes/`). It demonstrates the recipe format:

- Voice tag: clean `post_mix` overlay, gain 3.0, **phaser then flanger**.
- Filter Q&A question (low-open sweep) + answer.
- 16-step 1/8 glitch bandpass across a horn.
- Rewind carried 1/2 beat past a bar boundary (no cut).
- Ending: preserve the snare build, exclude the following melody-only phrase.

Recipes are dataset-independent — the same file applies to any phrase via
BPM/bar indexing.

### 5.6 Trace / evidence

- `golden.trace.json` records: seed, director, `harmonicArc`, the DNA recipe used,
  `opening_end_seconds`, the selected steps, the camelot chain and the report → full
  auditability.

---

## 6. Key files

| Path | Role |
|---|---|
| `scripts/analysis/render_director_golden.py` | reference driver (entry point) |
| `src/hypermix/director/deep_selector.py` | `DeepMixDirector` (phrase selection) |
| `src/hypermix/director/graph.py` | `MixGraph` (adjacency, edges) |
| `src/hypermix/compiler/deterministic_render.py` | `GoldenRenderer` (render/DSP) |
| `src/hypermix/compiler/set_compiler.py` | `SetCompiler` / `SetPlan` / `SetStep` |
| `src/hypermix/dna/engine.py` | DNA operator engine (`apply_recipe`) |
| `src/hypermix/dna/recipe.py` | `ProducerRecipe` / `RecipeStep` / `OperatorCall` |
| `data/dna_recipes/*.json` | DNA recipe files (dataset-independent) |
| `<pack>/graph/{segments,edges,graph}.json` | phrase pack graph of your dataset |
| `<out>/golden.{wav,plan,timeline,events,trace,report}` | output render + trace |