from __future__ import annotations

import json
import re
from typing import Any

NUMBER = re.compile(r"(?<![\w-])-?\d+(?:\.\d+)?(?:%|\s?(?:mph|in|ft|hours?|minutes?))?", re.I)
TIME = re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?[AP]M)?\b", re.I)


def _normalized_tokens(value: Any) -> set[str]:
    text = json.dumps(value, sort_keys=True, default=str)
    return {match.group(0).lower().replace(" ", "") for match in NUMBER.finditer(text)} | {
        match.group(0).lower().replace(" ", "") for match in TIME.finditer(text)
    }


def verify_grounding(draft: str, sources: Any) -> tuple[bool, list[str]]:
    allowed = _normalized_tokens(sources)
    claimed = _normalized_tokens(draft)
    invented = sorted(token for token in claimed if token not in allowed and token not in {"1"})
    return not invented, [f"Unsupported numeric or time claim: {token}" for token in invented]
