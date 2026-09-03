# Deep Mix Mode (Deep Dance / Megamix)

A third sequencing policy alongside `ClubMix` and `HyperMix`, modelled on the
German **Deep Dance** series (Andreas Peine, a.k.a. DJ Deep). Deep Dance was not
a realtime two-deck DJ set — it was a **studio-cut megamix** (Revox 2/8-track,
later Logic Audio). The engine's offline compile + deterministic render is a
natural fit.

## The core insight

> Deep Dance optimizes **time-to-next-recognition**, not graceful mixing.

It is a **hook relay**, not `track A → 32-bar blend → track B`:

```
hook A → vocal B → synth hook C → kick/chorus D → stab → hook E → rewind → drop F
```

Reference density: `Deep 50 Part I` is 18:18 with 27+ tracks → **≤ ~40 s/track**,
and since layers/jingles overlap, many hooks are far shorter.

## The three modes

| | CLUB MIX | HYPER MIX | DEEP MIX (this) |
|---|---|---|---|
| segment length | 16–32 bar blends | 4–16 bar hero phrases | **1–8 bar hooks** |
| goal | tempo continuity | max energy / hot-swap | **recognition density** |
| transitions | EQ / bass swap | rewind / slam / echo | **aggressive RESET** |
| track identity | preserved | preserved | **raw material** |
| BPM continuity | required | preferred | **not required** |

## DeepMixDirector policy

Implemented in `src/hypermix/director/deep_selector.py`. Same engine, different
policy. Deterministic given (pack, seed).

- **Short segments.** `segment_bars` (default 4). Each compiled segment is
  truncated to its head — `bar_samples = length / bars`, play `segment_bars`
  worth, quantized to the segment's own bar grid. 32-bar stays are effectively
  forbidden unless something major happens.
- **Recognition/hook density scoring.** `rating` is the hook proxy; short
  segments score higher (faster payoff); long ones penalized.
- **RESET vs CONTINUITY grammar.**
  - *Reset* (perceptual tempo/identity reset — jingle/siren/rewind family):
    `rewind, slam, drop_on_the_one, backspin, echo_cut, stutter, drum_roll,
    power_down, power_up, transformer_cuts, back_and_forth`
  - *Continuity* (keep the beat/phrase alive):
    `phrase_match, double_drop, triple_drop, loop_transition, melodic_mix,
    modulation, thematic_handoff, acapella_overlay`
  - If any reachable candidate is arrived at via a RESET edge, the candidate
    pool is restricted to those. Continuity only when no reset exit exists.
- **Fresh-first crate digging.** Never replay a track until the crate is spent.
- **Novelty pressure ("max boring time").** Consecutive steps on one track are
  increasingly penalized, pushing a cut to something new.

## Usage

```
.\.venv-hypermix\Scripts\python.exe -m src.hypermix.cli pack render \
    packs/my-library --out renders/my-library-deep \
    --mode deep --segment-bars 4 --length 20 --seed 42
```

- `--mode deep` selects `DeepMixDirector`.
- `--segment-bars N` bars per hook (default 4). Try `2` for hyper-frantic.
- `--length` is the number of hooks (steps); raise it since each is short.

Verified profile (8-track library, seed 42): 20 hooks / 2:55, ~8.8 s/hook,
all 8 tracks, 18/19 reset transitions.

## Roadmap (not yet implemented)

These need extra backends and are intentionally deferred:

1. **Time-stretch** (candidate: `timestretch-rs`) → lets `phrase_match`/beat
   continuity work across differing BPMs, so the rare Deep *blends* land on-grid.
2. **Stem layering** (Demucs) → true megamix stacking: track A drums + B synth
   hook + C vocal stab over 2–4 bars.
3. **Keysampling / persona stabs** → slice a persona voice ("BUILD", "YEAH"),
   pitch-map it (+3st/+7st), and fire it as a transition asset before the drop —
   the 2026 Deep Dance DNA. Needs a sampler voice + a `keysample` technique.

## Blueprint-from-a-real-mix (next analysis step)

Take one concrete Deep Dance release (Take 40 / 47 / 50) and measure: segment
length distribution, cuts/minute, reset-vs-continuity ratio, where a shared beat
is kept, where vocal overlays land. Convert those numbers 1:1 into
`DeepMixDirector` constants (target_bars, reset_bias, novelty window).
