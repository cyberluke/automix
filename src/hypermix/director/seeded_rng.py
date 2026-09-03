"""Deterministic seeded PRNG for the director (§16). Same pack + seed + commands
must produce the same choices."""
from __future__ import annotations

import random
from typing import List, Sequence, TypeVar

T = TypeVar("T")


class SeededRNG:
    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def choice(self, seq: Sequence[T]) -> T:
        return self._rng.choice(list(seq))

    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        total = sum(weights)
        if total <= 0:
            return self.choice(items)
        r = self._rng.random() * total
        acc = 0.0
        for item, w in zip(items, weights):
            acc += w
            if r <= acc:
                return item
        return items[-1]

    def random(self) -> float:
        return self._rng.random()
