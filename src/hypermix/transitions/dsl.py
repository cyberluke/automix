"""Executable Transition DSL (§13). Turns the DJ knowledge base into data-driven
definitions. Strongly-typed internal representation; JSON authoring (avoids a
YAML dependency). The planner consults these declarations for routing/fallback
rather than hard-coding technique behaviour in one giant if/elif."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class FxStep:
    type: str
    params: Dict = field(default_factory=dict)


@dataclass
class TransitionDef:
    id: str
    capabilities: Dict = field(default_factory=dict)
    outgoing_kinds: List[str] = field(default_factory=list)
    timing_anchor: str = "nextPhrase"
    fx: List[FxStep] = field(default_factory=list)
    switch_at: str = "t2"
    incoming_require_downbeat: bool = True
    incoming_preferred_kinds: List[str] = field(default_factory=list)
    fallback: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def load_dsl(path: Path) -> Dict[str, TransitionDef]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for entry in data.get("transitions", []):
        fx = [FxStep(type=s["type"], params={k: v for k, v in s.items() if k != "type"})
              for s in entry.get("fx", [])]
        out[entry["id"]] = TransitionDef(
            id=entry["id"],
            capabilities=entry.get("capabilities", {}),
            outgoing_kinds=entry.get("outgoing", {}).get("allowedKinds", []),
            timing_anchor=entry.get("timing", {}).get("anchor", "nextPhrase"),
            fx=fx,
            switch_at=entry.get("switch", {}).get("at", "t2"),
            incoming_require_downbeat=entry.get("incoming", {}).get("requireDownbeat", True),
            incoming_preferred_kinds=entry.get("incoming", {}).get("preferredKinds", []),
            fallback=entry.get("fallback", []),
        )
    return out
