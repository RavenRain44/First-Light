from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from backend.app.models import ThresholdDefinition

DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "engine" / "thresholds.yaml"


class ThresholdRegistry:
    def __init__(self, thresholds: list[ThresholdDefinition], raw: bytes = b"") -> None:
        self.thresholds = thresholds
        serialized = raw or "\n".join(t.model_dump_json() for t in thresholds).encode()
        self.version = f"sha256:{hashlib.sha256(serialized).hexdigest()[:12]}"

    @classmethod
    def load(cls, path: Path = DEFAULT_REGISTRY) -> ThresholdRegistry:
        raw = path.read_bytes()
        data = yaml.safe_load(raw) or {}
        return cls([ThresholdDefinition.model_validate(item) for item in data["thresholds"]], raw)

    def for_metric(self, metric: str) -> list[ThresholdDefinition]:
        return sorted(
            [
                item
                for item in self.thresholds
                if item.metric == metric and isinstance(item.value, (int, float))
            ],
            key=lambda item: float(item.value),
        )

    def by_id(self, threshold_id: str) -> ThresholdDefinition:
        return next(item for item in self.thresholds if item.id == threshold_id)
