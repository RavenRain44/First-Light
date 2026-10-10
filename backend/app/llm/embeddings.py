from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass


def local_embedding(text: str, dimensions: int = 128) -> list[float]:
    vector = [0.0] * dimensions
    for token in re.findall(r"[a-z0-9]+", text.lower()):
        digest = hashlib.sha256(token.encode()).digest()
        slot = int.from_bytes(digest[:4], "big") % dimensions
        vector[slot] += -1.0 if digest[4] & 1 else 1.0
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


@dataclass
class Precedent:
    id: str
    text: str
    citation: str
    embedding: list[float]


class PrecedentIndex:
    def __init__(self) -> None:
        self.items: list[Precedent] = []

    def add(self, identifier: str, text: str, citation: str) -> None:
        self.items.append(Precedent(identifier, text, citation, local_embedding(text)))

    def search(self, query: str, limit: int = 3) -> list[tuple[Precedent, float]]:
        query_vector = local_embedding(query)
        return sorted(
            ((item, cosine(query_vector, item.embedding)) for item in self.items),
            key=lambda pair: pair[1],
            reverse=True,
        )[:limit]
