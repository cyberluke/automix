"""Autonomous phrase-effect designer for HyperMix.

The designer owns the production decisions that were previously embedded in
analysis scripts:

1. extract phrase features,
2. score the declared effect vocabulary,
3. select deterministically with diversity and hash tie-breaks,
4. instantiate concrete ProducerRecipe steps,
5. return an auditable trace.

This is the formalized producer DNA layer: DSP operators execute; this module
decides *why* an operator belongs to a phrase.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

import numpy as np

from src.hypermix.analysis.phrase_features import extract_phrase_features
from .recipe import OperatorCall, ProducerRecipe, RecipeStep
from .effect_vocabulary import EFFECT_BY_ID, EFFECT_VOCABULARY

PHRASE_BARS = 8


def _role_confidence(features: dict, role: str) -> float:
    return max((float(x["confidence"]) for x in features.get("roles", [])
                if x.get("role") == role), default=0.0)


def _lufs(samples: np.ndarray) -> float:
    power = np.asarray(samples, dtype=np.float64)
    if power.ndim == 2:
        power = np.mean(power ** 2, axis=1)
    else:
        power = power ** 2
    return float(-0.691 + 10.0 * np.log10(np.mean(power) + 1e-10))


def extended_features(segment: np.ndarray, sr: int, bpm: float,
                      previous: dict | None, global_energy: float) -> dict:
    """Phrase-native feature vector plus producer-facing derived features."""
    f = extract_phrase_features(segment, sr, bpm)
    corr = float(np.corrcoef(segment[:, 0], segment[:, 1])[0, 1]) if segment.shape[1] > 1 else 1.0
    width = float(np.clip(1.0 - corr, 0.0, 2.0) / 2.0)
    rms = float(f["loudness"]["rms"])
    novelty = 0.0
    if previous:
        a = f["spectral"]
        b = previous["spectral"]
        novelty = float(np.clip(
            abs(a["centroid_mean"] - b["centroid_mean"]) +
            abs(a["flux_mean"] - b["flux_mean"]) /
            (abs(a["flux_mean"]) + abs(b["flux_mean"]) + 1e-6) +
            abs(rms - previous["loudness"]["rms"]) * 4.0, 0.0, 1.0))
    f.update({
        "lufs": _lufs(segment),
        "stereo_width": width,
        "stereo_correlation": corr,
        "vocal_phrase_boundaries": float(f["content"]["vocal_onset_density"]),
        "hook_repetition_strength": _role_confidence(f, "DROP_HOOK"),
        "harmonic_confidence": float(np.clip(
            f["content"]["harmonic_ratio"] * f["content"]["chroma_strength"],
            0.0, 1.0)),
        "reese_likelihood": float(np.clip(
            f["spectral"]["lomid_ratio"] *
            (1.0 - f["content"]["harmonic_ratio"]) * 2.0, 0.0, 1.0)),
        "rhythmic_density": float(f["rhythm"]["onset_density"]),
        "arrangement_density": float(np.clip(
            f["spectral"]["mid_ratio"] + f["spectral"]["high_ratio"] +
            f["content"]["vocal_probability"], 0.0, 1.0)),
        "novelty_vs_previous": novelty,
        "energy_global": global_energy,
        "energy_local_trajectory": float(f["slopes"]["rms"]),
    })
    return f


def analyze_canvas(audio: np.ndarray, sr: int, bpm: float,
                   phrase_bars: int = PHRASE_BARS) -> List[dict]:
    """Split the canvas into phrases and extract one producer feature vector each."""
    spb = sr * 60.0 / bpm
    phrase_samples = int(round(phrase_bars * 4.0 * spb))
    n_phrases = int(np.ceil(len(audio) / phrase_samples))
    raw = []
    for i in range(n_phrases):
        i0 = i * phrase_samples
        i1 = min(len(audio), i0 + phrase_samples)
        raw.append(extract_phrase_features(audio[i0:i1], sr, bpm))
    energies = [float(x.get("perceived_energy", 0.0)) for x in raw]
    ref = float(np.percentile(energies, 95)) if energies else 1.0
    ref = ref or 1.0
    rows = []
    previous = None
    for i, base in enumerate(raw):
        i0 = i * phrase_samples
        i1 = min(len(audio), i0 + phrase_samples)
        f = extended_features(
            audio[i0:i1], sr, bpm, previous,
            float(np.clip(energies[i] / ref, 0.0, 1.0)),
        )
        rows.append({
            "phrase_index": i,
            "bar_start": i * phrase_bars,
            "bar_end": (i + 1) * phrase_bars,
            "complete_phrase": i1 - i0 >= int(0.95 * phrase_samples),
            "features": f,
        })
        previous = f
    return rows


class _AttrDict(dict):
    """Read-only attribute access for feature dicts in vocabulary rules."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _wrap_rule_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _AttrDict({k: _wrap_rule_value(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_wrap_rule_value(v) for v in value]
    return value


def _eval_rule(expr: Any, features: dict, phrase_index: int,
               boundary: float, bass: float) -> float:
    """Evaluate the small deterministic rule language used in the vocabulary."""
    if isinstance(expr, (int, float)):
        return float(expr)
    if isinstance(expr, str):
        if expr == "phrase_index":
            return float(phrase_index)
        namespace = {
            "spectral": _wrap_rule_value(features["spectral"]),
            "rhythm": _wrap_rule_value(features["rhythm"]),
            "content": _wrap_rule_value(features["content"]),
            "slopes": _wrap_rule_value(features["slopes"]),
            "boundary_strength": boundary,
            "bass_dominance": bass,
            "novelty_vs_previous": features["novelty_vs_previous"],
            "hook_repetition_strength": features["hook_repetition_strength"],
            "phrase_index": phrase_index,
            "max": max,
            "min": min,
            "abs": abs,
        }
        return float(eval(expr, {"__builtins__": {}}, namespace))
    raise TypeError(f"unsupported rule expression {expr!r}")


def score_effect(effect: dict, features: dict, phrase_index: int,
                 recent: list[str], repetition_penalty: float) -> dict:
    """Score one vocabulary effect against one measured phrase."""
    boundary = float(np.clip(abs(features["slopes"]["rms"]) +
                             features["slopes"]["flux"] * 0.5, 0.0, 1.0))
    bass = float(np.clip(
        features["spectral"]["sub_ratio"] + features["spectral"]["bass_ratio"] +
        features["reese_likelihood"], 0.0, 1.0))
    scores: Dict[str, float] = {}
    for key, expr in effect.get("base_scores", {}).items():
        scores[key] = round(float(_eval_rule(expr, features, phrase_index,
                                             boundary, bass)), 4)
    for key, expr in effect.get("dynamic_scores", {}).items():
        scores[key] = round(float(_eval_rule(expr, features, phrase_index,
                                             boundary, bass)), 4)
    collision_expr = effect.get("guards", {}).get("collision", 0.0)
    collision = float(_eval_rule(collision_expr, features, phrase_index,
                                 boundary, bass)) if collision_expr else 0.0
    gimmick_expr = effect.get("guards", {}).get("gimmick", 0.0)
    gimmick = float(_eval_rule(gimmick_expr, features, phrase_index,
                               boundary, bass)) if gimmick_expr else 0.0
    recent_penalty = 0.35 if effect["id"] in recent else 0.0
    total = sum(float(v) for k, v in scores.items())
    total -= collision + gimmick + recent_penalty + repetition_penalty
    scores.update({
        "collision_risk": round(collision, 4),
        "gimmick_penalty": round(gimmick, 4),
        "recent_technique_penalty": round(recent_penalty, 4),
        "total": round(total, 4),
    })
    return {"id": effect["id"], "scores": scores}


def choose_edits(rows: List[dict], track_hash: str, dna_version: str) -> List[dict]:
    """Select effects deterministically, with diversity and complete audit fields."""
    recent: list[str] = []
    for row in rows:
        f = row["features"]
        repetition_penalty = round((1.0 - f["novelty_vs_previous"]) * 0.35, 4)
        candidates = [score_effect(effect, f, row["phrase_index"], recent,
                                   repetition_penalty)
                      for effect in EFFECT_VOCABULARY]
        if not row["complete_phrase"]:
            for candidate in candidates:
                candidate["scores"]["partial_phrase_penalty"] = 10.0
                candidate["scores"]["total"] = round(candidate["scores"]["total"] - 10.0, 4)
        available = [candidate for candidate in candidates if candidate["id"] not in recent]
        if not available:
            available = candidates
        available.sort(key=lambda c: (
            -c["scores"]["total"],
            hashlib.sha256(
                f"{track_hash}|{row['phrase_index']}|{dna_version}|{c['id']}"
                .encode("utf-8")).hexdigest(),
            c["id"],
        ))
        selected = available[0] if row["complete_phrase"] else next(
            (c for c in available if c["id"] == "leave_clean"), available[0])
        for candidate in candidates:
            candidate["scores"]["eligible_after_diversity_filter"] = candidate in available
        recent.append(selected["id"])
        recent = recent[-2:]
        row["observations"] = {
            "roles": f.get("roles", []),
            "energy_global": f["energy_global"],
            "novelty_vs_previous": f["novelty_vs_previous"],
            "vocal_probability": f["content"]["vocal_probability"],
            "bass_reese_likelihood": f["reese_likelihood"],
            "boundary_strength": float(np.clip(
                abs(f["slopes"]["rms"]) + f["slopes"]["flux"], 0.0, 1.0)),
        }
        row["derived_rule"] = {
            "rule": "declared effect vocabulary scored against phrase features",
            "diversity_constraint": "penalize techniques used in the previous two phrases",
            "tie_break": "sha256(track_hash|phrase_index|dna_version|effect_id)",
            "seed_context": f"{track_hash}|{row['phrase_index']}|{dna_version}",
        }
        row["candidate_edits"] = candidates
        row["scores"] = {candidate["id"]: candidate["scores"] for candidate in candidates}
        row["selected_edit"] = selected["id"]
        row["modules_used"] = list(EFFECT_BY_ID[selected["id"]]["modules"])
        row["parameters"] = {}
        row["expected_effect"] = EFFECT_BY_ID[selected["id"]]["expected_effect"]
        row["measured_post_edit_change"] = {}
    return rows


def _resolve_params(value: Any, phrase_index: int, bpm: float) -> Any:
    """Resolve small parameter expressions such as phrase_index + 101."""
    if isinstance(value, str):
        if not any(token in value for token in ("phrase_index", "bpm", "beat_seconds")):
            return value
        namespace = {"phrase_index": phrase_index, "bpm": bpm,
                     "beat_seconds": 60.0 / bpm}
        return float(eval(value, {"__builtins__": {}}, namespace))
    if isinstance(value, dict):
        return {k: _resolve_params(v, phrase_index, bpm) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_params(v, phrase_index, bpm) for v in value]
    if isinstance(value, float):
        return float(value)
    return value


def build_recipe(rows: List[dict], bpm: float, recipe_name: str,
                 phrase_bars: int = PHRASE_BARS) -> ProducerRecipe:
    """Instantiate selected vocabulary effects as bar-indexed ProducerRecipe steps."""
    recipe = ProducerRecipe(
        name=recipe_name,
        phrase_bars=80,
        bpm_ref=bpm,
        note="autonomous phrase-native MixShow DNA",
        description=[
            "Autonomous HyperMix DNA generated from phrase-native measurements.",
            "The effect vocabulary declares musical intent, guardrails and parameter policy.",
            "The designer scores candidates, applies diversity, and instantiates operators.",
        ],
        principles={
            "selection": "declared vocabulary plus deterministic feature-conditioned scoring",
            "diversity": "no same chain on adjacent phrases; recent techniques penalized",
            "reference_frame": "8-bar musical phrases relative to the canvas start",
            "guardrails": "preserve groove energy, protect vocals, avoid high-frequency artifacts",
        },
    )
    for row in rows:
        effect = EFFECT_BY_ID[row["selected_edit"]]
        phrase_index = row["phrase_index"]
        b = float(row["bar_start"])
        if row["selected_edit"] == "leave_clean":
            continue
        params = _resolve_params(effect["parameter_policy"], phrase_index, bpm)
        row["parameters"] = params
        if row["selected_edit"] == "ms20_build":
            recipe.add(RecipeStep(
                id=f"auto_ms20_{phrase_index}",
                bar=b + 7.0,
                span_bars=1.0,
                call=OperatorCall("filter_sweep", params),
                note=effect["expected_effect"],
            ))
            follow = effect.get("follow_up") or {}
            if follow:
                follow_params = dict(follow["params"])
                follow_params["echo_s"] = 60.0 / bpm
                follow_params["sample_tail_cut_s"] = 60.0 / bpm
                recipe.add(RecipeStep(
                    id=f"auto_ms20_sample_{phrase_index}",
                    bar=b + 7.0 + float(follow.get("offset_bars", 1.0)),
                    call=OperatorCall(follow["operator"], follow_params),
                    note="sample answer after the MS-20 question",
                ))
        elif row["selected_edit"] == "boundary_juggle":
            recipe.add(RecipeStep(
                id=f"auto_juggle_{phrase_index}",
                bar=b + 8.0,
                call=OperatorCall("juggle", params),
                note=effect["expected_effect"],
            ))
        elif row["selected_edit"] == "bass_spotlight":
            recipe.add(RecipeStep(
                id=f"auto_bass_{phrase_index}",
                bar=b + 4.0,
                call=OperatorCall("bass_solo", params),
                note=effect["expected_effect"],
            ))
        elif row["selected_edit"] == "spectral_stutter":
            recipe.add(RecipeStep(
                id=f"auto_stutter_{phrase_index}",
                bar=b + 6.0,
                call=OperatorCall("micro_edit", params),
                note=effect["expected_effect"],
            ))
        elif row["selected_edit"] == "chaos_burst":
            recipe.add(RecipeStep(
                id=f"auto_chaos_micro_{phrase_index}",
                bar=b + 7.0,
                call=OperatorCall("micro_edit", params["micro_edit"]),
                note=effect["expected_effect"],
            ))
            recipe.add(RecipeStep(
                id=f"auto_chaos_juggle_{phrase_index}",
                bar=b + 8.0,
                call=OperatorCall("juggle", params["juggle"]),
                note="chaos burst boundary re-entry",
            ))
    return recipe


def design_phrase_dna(audio: np.ndarray, sr: int, bpm: float,
                      track_hash: str, recipe_name: str,
                      phrase_bars: int = PHRASE_BARS) -> Tuple[ProducerRecipe, List[dict]]:
    """One-call autonomous design API: canvas audio -> recipe + auditable rows."""
    rows = analyze_canvas(audio, sr, bpm, phrase_bars=phrase_bars)
    rows = choose_edits(rows, track_hash, dna_version=recipe_name)
    recipe = build_recipe(rows, bpm, recipe_name, phrase_bars=phrase_bars)
    return recipe, rows
