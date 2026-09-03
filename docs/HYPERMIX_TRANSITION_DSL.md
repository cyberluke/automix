# HyperMix transition DSL

Data-driven transition definitions live in
`contracts/hypermix-transitions-dsl.json`. The DSL lets you tweak technique
behavior without touching Python DSP code.

## Shape

```json
{
  "id": "rewind_drop",
  "capabilities": ["universal"],
  "outgoing": { "bars": 2, "fx": [ { "op": "reverse_tail", "tailBeats": 2 } ] },
  "timing": { "switchOffsetBeats": 0 },
  "fx": [ { "op": "echo_tail", "feedback": 0.45 } ],
  "switch": { "snap": "downbeat" },
  "incoming": { "bars": 4, "gainRamp": [0, 1] },
  "fallback": "slam"
}
```

## Fields

| Field | Meaning |
|---|---|
| `id` | Unique technique id used by the planner / edges |
| `capabilities` | `universal`, or gated tags requiring stems |
| `outgoing.fx` | Ordered `FxStep` ops applied to outgoing tail |
| `timing.switchOffsetBeats` | Where the switch lands relative to the grid |
| `switch.snap` | Snap mode for the switch point (see snapping) |
| `incoming` | Ramp-in behavior for the next segment |
| `fallback` | Technique used if a `CapabilityMiss` is raised |

## Fx ops

`reverse_tail`, `echo_tail`, `filter_sweep` (lowpass/highpass), `gain_ramp`,
`variable_rate_resample`, `stutter_slices`, `declick_join`, `normalize_peak`.

## Loading

```python
from src.hypermix.transitions.dsl import load_dsl
defs = load_dsl("contracts/hypermix-transitions-dsl.json")
```

Definitions map to registered techniques in `TransitionRegistry`; unknown ids
are rejected at load time. DSL tweaks parameters, never structure — the DSP
execution path stays the registered technique's `render()`.
