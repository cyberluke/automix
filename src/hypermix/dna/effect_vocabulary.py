"""Formalized producer-effect vocabulary for HyperMix.

This module is where our practical DNA know-how lives as data, not hidden in a
render script.  Each effect entry declares the phrase features it likes, the
features it must avoid, the operator modules it uses, and the parameter policy
that turns a scored phrase into concrete DSP parameters.

The goal is not to make the effect random.  It is to make each decision
explainable: a phrase gets an effect because its measured energy, structure,
vocals, novelty and spectral shape passed the declared guards.
"""

from __future__ import annotations

from typing import Any, Dict, List

EFFECT_VOCABULARY: List[Dict[str, Any]] = [
    {
        "id": "leave_clean",
        "operator": "none",
        "modules": [],
        "base_scores": {
            "musical_gain": 0.35,
            "energy_gain": 0.0,
            "contrast": 0.05,
            "spectral_fit": 0.5,
            "structural_fit": 0.45,
            "hook_support": 0.5,
            "transition_value": 0.1,
            "novelty": 0.0,
        },
        "guards": {
            "collision_risk_scale": 0.05,
            "gimmick": 0.0,
        },
        "expected_effect": "preserve the phrase when processing would add no clear gain",
        "principle": "do not decorate a phrase that already works",
    },
    {
        "id": "ms20_build",
        "operator": "filter_sweep",
        "modules": ["MS20MFilter", "filter_automation", "voice_tag"],
        "base_scores": {
            "musical_gain": 0.45,
            "spectral_fit": "1.0 - spectral.high_ratio",
            "structural_fit": 0.75,
            "hook_support": "hook_repetition_strength * 0.5",
            "novelty": 0.45,
        },
        "dynamic_scores": {
            "energy_gain": "max(0.0, slopes.rms) * 0.9",
            "contrast": "boundary_strength * 0.6",
            "transition_value": "boundary_strength",
        },
        "guards": {
            "collision": "content.vocal_probability * 0.55 + 0.1",
            "gimmick": 0.0,
            "minimum_attack_hz": 900.0,
            "maximum_warmup_s": 0.08,
            "fast_start": True,
            "dry_safety": 1.0,
        },
        "parameter_policy": {
            "bars": 1,
            "lp_from_hz": 900.0,
            "lp_to_hz": 15000.0,
            "revision": "rev1",
            "res": 0.52,
            "drive": 1.0,
            "bypass_hpf": True,
            "warmup_s": 0.08,
            "fast_reps": 2,
        },
        "follow_up": {
            "operator": "voice_tag",
            "offset_bars": 1.0,
            "params": {
                "path": "samples/stabs/horns.mp3",
                "gain": 0.72,
                "hipass_hz": 140.0,
                "echo_times": 2,
                "echo_decay": 0.35,
                "echo_pingpong": False,
            },
        },
        "expected_effect": "compress the phrase with MS-20 REV1, reopen quickly, and answer with a short horn re-entry",
        "principle": "filter questions need an audible sample answer",
    },
    {
        "id": "bass_spotlight",
        "operator": "bass_solo",
        "modules": ["Demucs bass/vocals stems"],
        "base_scores": {
            "musical_gain": 0.55,
            "spectral_fit": "1.0 - spectral.high_ratio",
            "structural_fit": 0.85,
            "hook_support": "bass_dominance * 0.5",
            "transition_value": "boundary_strength",
            "novelty": "0.8 if bass_dominance > 0.35 else 0.2",
        },
        "dynamic_scores": {
            "energy_gain": "bass_dominance * 0.9",
            "contrast": "bass_dominance * 0.7",
        },
        "guards": {
            "collision": "content.vocal_probability * 0.8 + 0.15",
            "requires_stems": ["bass", "vocals"],
        },
        "parameter_policy": {
            "profile": "bass_solo_malugi",
            "stem_window_bars": 8,
        },
        "expected_effect": "isolate a bass-forward phrase while retaining enough vocal continuity",
        "principle": "bass solos are structural contrast, not decoration",
    },
    {
        "id": "boundary_juggle",
        "operator": "juggle",
        "modules": ["juggle.disco_show"],
        "base_scores": {
            "musical_gain": 0.5,
            "spectral_fit": 0.65,
            "structural_fit": "boundary_strength * 1.2",
            "hook_support": "hook_repetition_strength * 0.6",
            "transition_value": "boundary_strength * 1.2",
            "novelty": "0.9 * (1.0 - novelty_vs_previous)",
        },
        "dynamic_scores": {
            "energy_gain": "boundary_strength * 0.8",
            "contrast": "boundary_strength",
        },
        "guards": {
            "collision": "content.vocal_probability * 0.65 + 0.12",
            "gimmick": "0.0 if boundary_strength >= 0.25 else 0.1",
            "maximum_replacement_beats": 1.0,
            "preserve_master_outside_effect": True,
        },
        "parameter_policy": {
            "preset": "disco_show",
            "seed": "phrase_index",
        },
        "expected_effect": "reframe a strong transient boundary with a one-beat beat-locked loop gesture",
        "principle": "boundary gestures must return to the original groove fast",
    },
    {
        "id": "spectral_stutter",
        "operator": "micro_edit",
        "modules": ["run_fx_program", "GlitchBitch buffer mangle"],
        "base_scores": {
            "musical_gain": 0.35,
            "energy_gain": "rhythm.transient_density / 10.0",
            "contrast": "(1.0 - spectral.high_ratio) * 0.7",
            "spectral_fit": 0.55,
            "structural_fit": "boundary_strength",
            "hook_support": "content.vocal_probability * 0.4",
            "transition_value": "boundary_strength * 0.9",
            "novelty": "0.85 * (1.0 - novelty_vs_previous)",
        },
        "guards": {
            "collision": "content.vocal_probability * 0.9 + 0.2",
            "gimmick": 0.15,
            "minimum_dry_mix": 0.5,
            "maximum_filter_hz": 2400.0,
            "ms20_post_filter": False,
        },
        "parameter_policy": {
            "length_bars": 1.0,
            "seed": "phrase_index + 101",
            "program": {
                "engine": "glitch",
                "sync": "1/8",
                "steps": 8,
                "buffer": {
                    "ramp": ["1/4", "1/4", "1/8", "1/8",
                             "1/16", "1/16", "1/32", "1/32"],
                    "reversePattern": [0, 0, 0, 1, 0, 0, 1, 1],
                },
                "pitch": {"values": [0, 0, 0, 3, 0, 3, 7, 12]},
                "gate": {"values": [1.0, 0.8, 0.6, 0.5]},
                "rate": {"values": [1.0, 1.0, 1.0, 0.5]},
                "pan": {"wiggle": 0.4},
                "filter": {"type": "bandpass", "fromHz": 120.0,
                           "toHz": 2400.0, "upperHz": 6500.0},
                "mix": {"from": 0.25, "to": 0.5},
                "ms20": {"on": False},
            },
        },
        "expected_effect": "turn low novelty and transient density into a midrange rhythmic mutation without removing groove energy",
        "principle": "glitch should mutate the groove, not delete its energy",
    },
    {
        "id": "chaos_burst",
        "operator": "micro_edit+juggle",
        "modules": ["run_fx_program", "GlitchBitch buffer mangle", "juggle.disco_show"],
        "base_scores": {
            "musical_gain": 0.5,
            "energy_gain": "boundary_strength * 1.1",
            "contrast": "boundary_strength * 1.25",
            "spectral_fit": 0.8,
            "structural_fit": "boundary_strength * 1.4",
            "hook_support": "hook_repetition_strength * 0.35",
            "transition_value": "boundary_strength * 1.4",
            "novelty": "(1.0 - novelty_vs_previous) * 1.1",
        },
        "guards": {
            "collision": "content.vocal_probability * 0.85 + 0.18",
            "gimmick": "0.05 if boundary_strength > 0.45 and rhythm.transient_density > 1.0 else 0.5",
            "minimum_dry_mix": 0.5,
            "ms20_post_filter": False,
        },
        "parameter_policy": {
            "micro_edit": {
                "length_bars": 1.0,
                "seed": "phrase_index + 211",
                "program": {
                    "engine": "glitch",
                    "sync": "1/16",
                    "steps": 16,
                    "buffer": {"size": "1/16",
                               "reversePattern": [0, 1, 0, 0, 1, 0, 1, 1]},
                    "pitch": {"values": [0, 0, 5, 0, 7, 12, 7, 0]},
                    "gate": {"values": [1.0, 0.75, 0.5, 0.25]},
                    "rate": {"values": [1.0, 1.0, 0.5, 0.5]},
                    "pan": {"values": [-0.7, 0.7, -0.35, 0.35]},
                    "filter": {"type": "bandpass", "fromHz": 500.0,
                               "toHz": 2200.0, "upperHz": 3600.0},
                    "mix": {"from": 0.35, "to": 0.5},
                    "ms20": {"on": False},
                },
            },
            "juggle": {"preset": "disco_show", "seed": "phrase_index + 311"},
        },
        "expected_effect": "collapse a repetitive boundary into a pitched buffer burst and return with a one-beat juggle",
        "principle": "controlled chaos must resolve immediately back to the beat",
    },
]

EFFECT_BY_ID = {effect["id"]: effect for effect in EFFECT_VOCABULARY}
