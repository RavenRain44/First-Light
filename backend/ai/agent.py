"""Interpretation entry point (Strands agent wired in Phase 6; deterministic fallback for now)."""
from __future__ import annotations

from ai import fallback
from ai.prompts import Interpretation


async def interpret(snap: dict, use_model: bool = True) -> tuple[dict, str]:
    interp: Interpretation = fallback.build(snap, snap.get("analogs"))
    return interp.model_dump(mode="json"), "deterministic-fallback"
