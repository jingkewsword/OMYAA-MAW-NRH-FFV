"""Helpers for source speaker identities; project migration is handled separately."""

from __future__ import annotations

import copy
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


def prepare_asr_speaker_segments(
    segments: Iterable[Mapping[str, Any]], source_to_project: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Convert already segmented ASR cues to project identities without changing their timing.

    A cue containing multiple source identities must first be split at reliable
    word boundaries; this helper refuses to choose one or silently drop labels.
    """
    result = copy.deepcopy(list(segments))
    for segment in result:
        items = segment.get("items", [])
        if items is None:
            items = []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("items must be an array of objects")
        values = [segment.get("speaker"), *(item.get("speaker") for item in items)]
        source_ids: set[str] = set()
        for value in values:
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            if not isinstance(value, str):
                raise ValueError("invalid source speaker")
            source_ids.add(value)
        if len(source_ids) > 1:
            raise ValueError("segment contains multiple source speakers")
        if source_ids:
            source_id = next(iter(source_ids))
            project_id = source_to_project.get(source_id)
            if not isinstance(project_id, str) or not project_id.strip():
                raise ValueError("unmapped source speaker")
            segment["speaker"] = project_id
        else:
            segment.pop("speaker", None)
        for item in items:
            item.pop("speaker", None)
    return result
