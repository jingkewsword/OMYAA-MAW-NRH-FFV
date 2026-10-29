"""Helpers for source speaker identities; project migration is handled separately."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def distinct_speaker_ids(segments: Iterable[Mapping[str, Any]]) -> list[str]:
    """Return distinct, nonblank source identifiers in first-seen order.

    Provider identifiers are opaque strings: their numeric value, display name,
    and color have no bearing on how many speakers were reported.
    """
    result: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        speaker = segment.get("speaker")
        if not isinstance(speaker, str) or not speaker.strip() or speaker in seen:
            continue
        result.append(speaker)
        seen.add(speaker)
    return result


def asr_palette_size(segments: Iterable[Mapping[str, Any]], *, current_size: int) -> int:
    """Expand the saved palette on a new ASR result without shrinking it."""
    if current_size not in (5, 9):
        raise ValueError("current_size must be 5 or 9")
    return 9 if current_size == 9 or len(distinct_speaker_ids(segments)) > 5 else 5
