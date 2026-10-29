"""Helpers for source speaker identities; project migration is handled separately."""

from __future__ import annotations

import copy
import re
from collections.abc import Iterable, Mapping
from typing import Any


def is_valid_speaker_id(value: object) -> bool:
    """Use the shared Python/JavaScript definition of a nonblank opaque ID."""
    return isinstance(value, str) and bool(value) and any(not (char.isspace() or char == '\ufeff') for char in value)


def distinct_speaker_ids(segments: Iterable[Mapping[str, Any]]) -> list[str]:
    """Return distinct, nonblank source identifiers in first-seen order.

    Provider identifiers are opaque strings: their numeric value, display name,
    and color have no bearing on how many speakers were reported.
    """
    result: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        speaker = segment.get("speaker")
        if not is_valid_speaker_id(speaker) or speaker in seen:
            continue
        result.append(speaker)
        seen.add(speaker)
    return result


def asr_palette_size(segments: Iterable[Mapping[str, Any]], *, current_size: int) -> int:
    """Expand the saved palette on a new ASR result without shrinking it."""
    if current_size not in (5, 9):
        raise ValueError("current_size must be 5 or 9")
    return 9 if current_size == 9 or len(distinct_speaker_ids(segments)) > 5 else 5


def allocate_source_speaker_ids(
    segments: Iterable[Mapping[str, Any]], *, reserved_ids: Iterable[str],
) -> dict[str, str]:
    """Allocate distinct project identities for an already-segmented ASR result.

    Existing project IDs are reserved only; matching an opaque source ID does
    not establish that speakers from separate sources are the same person.
    Include item identities so a cue with no segment-level identity can still
    be converted when its items identify one speaker unambiguously.
    """
    used = set(reserved_ids)
    mapping: dict[str, str] = {}
    number = 1
    source_entries: list[Mapping[str, Any]] = []
    for segment in segments:
        source_entries.append(segment)
        items = segment.get("items")
        if isinstance(items, list):
            source_entries.extend(item for item in items if isinstance(item, Mapping))
    for source_id in distinct_speaker_ids(source_entries):
        candidate = f"spk-{number:03d}"
        while candidate in used:
            number += 1
            candidate = f"spk-{number:03d}"
        mapping[source_id] = candidate
        used.add(candidate)
        number += 1
    return mapping


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
            if value is None or (isinstance(value, str) and not is_valid_speaker_id(value)):
                continue
            if not isinstance(value, str):
                raise ValueError("invalid source speaker")
            source_ids.add(value)
        if len(source_ids) > 1:
            raise ValueError("segment contains multiple source speakers")
        if source_ids:
            source_id = next(iter(source_ids))
            project_id = source_to_project.get(source_id)
            if not is_valid_speaker_id(project_id):
                raise ValueError("unmapped source speaker")
            segment["speaker"] = project_id
        else:
            segment.pop("speaker", None)
        for item in items:
            item.pop("speaker", None)
    return result


def validate_project_speakers(project: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate the proposed segment-level speaker references in a tracks project."""
    errors: list[dict[str, str]] = []

    def error(path: str, message: str) -> None:
        errors.append({"path": path, "message": message})

    if not isinstance(project, Mapping):
        error("$", "must be an object")
        return errors
    speakers = project.get("speakers")
    if not isinstance(speakers, list):
        error("$.speakers", "must be an array")
        speakers = []
    ids: set[str] = set()
    for index, speaker in enumerate(speakers):
        path = f"$.speakers[{index}]"
        if not isinstance(speaker, Mapping):
            error(path, "must be an object")
            continue
        identifier = speaker.get("id")
        if not is_valid_speaker_id(identifier) or identifier in ids:
            error(f"{path}.id", "must be a unique nonempty string")
        else:
            ids.add(identifier)
        name = speaker.get("name")
        if (not isinstance(name, str) or len(name) > 64
                or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in name)):
            error(f"{path}.name", "must be a name of at most 64 characters without control characters")
        color = speaker.get("color")
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            error(f"{path}.color", "must be a six-digit hex color")

    tracks = project.get("tracks")
    if not isinstance(tracks, list):
        error("$.tracks", "must be an array")
        return errors
    for track_index, track in enumerate(tracks):
        path = f"$.tracks[{track_index}].segments"
        if not isinstance(track, Mapping) or not isinstance(track.get("segments"), list):
            error(path, "must be an array")
            continue
        for segment_index, segment in enumerate(track["segments"]):
            segment_path = f"{path}[{segment_index}]"
            if not isinstance(segment, Mapping):
                error(segment_path, "must be an object")
                continue
            speaker = segment.get("speaker")
            if speaker is not None and (not isinstance(speaker, str) or speaker not in ids):
                error(f"{segment_path}.speaker", "must reference a project speaker")
            items = segment.get("items", [])
            if items is None:
                continue
            if not isinstance(items, list):
                error(f"{segment_path}.items", "must be an array")
                continue
            for item_index, item in enumerate(items):
                if isinstance(item, Mapping) and "speaker" in item:
                    error(f"{segment_path}.items[{item_index}].speaker", "speaker belongs to the segment")
    return errors
