"""ProducerRecipe — the deterministic, bar/beat-indexed 'cookbook' recipe.

A recipe is a named, ordered list of steps. Each step says:
  WHEN  (bar/beat position or bar range, in PHRASE bars — 0-indexed), and
  WHAT  (an OperatorCall = operator name + params).

Because steps are indexed to BARS (not seconds), a recipe recorded on one phrase
applies to ANY other phrase — the engine resolves bar→seconds via the phrase BPM.
This is the 'state machine' the user wants his producer DNA recorded into.

Storage: JSON (one file per recipe) so recipes are portable / diffable / editable.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

RECIPE_DIR = os.path.join("data", "dna_recipes")


@dataclass
class OperatorCall:
    """One operator invocation with its parameters."""
    op: str                       # e.g. 'bass_solo', 'cyber_bass', 'juggle', ...
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RecipeStep:
    """A single bar/beat-indexed step in the recipe.

    bar / beat: 0-indexed position within the phrase (beat is fractional OK).
    span_bars: how many bars the step covers (None = instantaneous at bar.beat).
    when_role: optional phrase-role gate (only fire on DROP_HOOK / BREAKDOWN ...).
    """
    id: str = ""
    bar: float = 0.0
    beat: float = 0.0
    span_bars: Optional[float] = None
    when_role: Optional[str] = None
    call: OperatorCall = field(default_factory=lambda: OperatorCall(op="noop"))
    note: str = ""


@dataclass
class ProducerRecipe:
    """A named, ordered producer recipe (the 'state machine')."""
    name: str
    phrase_bars: float            # the phrase length the recipe was recorded on
    bpm_ref: float                # reference BPM (for documentation; engine re-resolves)
    steps: List[RecipeStep] = field(default_factory=list)
    note: str = ""
    description: str | List[str] = ""
    principles: Dict[str, Any] = field(default_factory=dict)

    def add(self, step: RecipeStep) -> "ProducerRecipe":
        self.steps.append(step)
        self.steps.sort(key=lambda s: (s.bar, s.beat))
        return self

    # ---- serialization -----------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "phrase_bars": self.phrase_bars,
            "bpm_ref": self.bpm_ref, "note": self.note,
            "description": self.description,
            "principles": self.principles,
                "steps": [{"id": s.id, "bar": s.bar, "beat": s.beat,
                           "span_bars": s.span_bars, "when_role": s.when_role,
                           "note": s.note,
                           "call": {"op": s.call.op, "params": s.call.params}}
                          for s in self.steps]}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ProducerRecipe":
        r = ProducerRecipe(name=d["name"], phrase_bars=d["phrase_bars"],
                           bpm_ref=d.get("bpm_ref", 174.0), note=d.get("note", ""),
                           description=d.get("description", ""),
                           principles=d.get("principles", {}))
        for s in d.get("steps", []):
            c = s.get("call", {})
            r.steps.append(RecipeStep(
                id=s.get("id", ""), bar=s["bar"], beat=s.get("beat", 0.0),
                span_bars=s.get("span_bars"), when_role=s.get("when_role"),
                note=s.get("note", ""),
                call=OperatorCall(op=c.get("op", "noop"),
                                  params=c.get("params", {}))))
        return r


# ---------------------------------------------------------------------------
# persistence (JSON, one file per recipe)
# ---------------------------------------------------------------------------

def _path(name: str, recipe_dir: str = RECIPE_DIR) -> str:
    return os.path.join(recipe_dir, f"{name}.json")


def save_recipe(r: ProducerRecipe, recipe_dir: str = RECIPE_DIR) -> str:
    os.makedirs(recipe_dir, exist_ok=True)
    p = _path(r.name, recipe_dir)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(r.to_dict(), f, indent=2, ensure_ascii=False)
    return p


def load_recipe(name: str, recipe_dir: str = RECIPE_DIR) -> ProducerRecipe:
    with open(_path(name, recipe_dir), encoding="utf-8") as f:
        return ProducerRecipe.from_dict(json.load(f))


def list_recipes(recipe_dir: str = RECIPE_DIR) -> List[str]:
    if not os.path.isdir(recipe_dir):
        return []
    return sorted(os.path.splitext(f)[0] for f in os.listdir(recipe_dir)
                  if f.endswith(".json"))


def get_recipe(name: str, recipe_dir: str = RECIPE_DIR) -> ProducerRecipe:
    return load_recipe(name, recipe_dir)
