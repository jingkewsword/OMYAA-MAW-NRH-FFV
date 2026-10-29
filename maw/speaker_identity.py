"""Helpers for source speaker identities; project migration is handled separately."""

from __future__ import annotations

import copy
import re
import unicodedata
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


def migrate_speaker_segments(
    segments: Iterable[Mapping[str, Any]], source_to_project: Mapping[str, str],
    *, reserved_segment_ids: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split legacy word identities, returning segments and per-input ID mapping.

    Callers must use the mapping to update bindings and groups when a cue splits.
    The first run keeps its original ID; generated IDs avoid all input and
    caller-reserved IDs. Blank item identities follow the previous known one;
    leading blanks join the first known run. For an unsplit cue an existing
    segment identity wins over an item identity.

    Split only when text and boundary timestamps are available without guessing.
    Segment frame boundaries require corresponding item frames at internal edges.
    """
    source = copy.deepcopy(list(segments))
    ids = [s.get("id") for s in source if is_valid_speaker_id(s.get("id"))]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate segment id")
    used = set(ids) | set(reserved_segment_ids)
    result: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []

    def identity(value: object) -> str | None:
        if value is None or (isinstance(value, str) and not is_valid_speaker_id(value)):
            return None
        if not isinstance(value, str):
            raise ValueError("invalid source speaker")
        return value

    def new_id(base: str) -> str:
        number = 1
        while f"{base}-speaker-{number}" in used:
            number += 1
        candidate = f"{base}-speaker-{number}"
        used.add(candidate)
        return candidate

    for index, segment in enumerate(source):
        items = segment.get("items")
        if items is None:
            items = []
        if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
            raise ValueError("items must be an array of objects")
        segment_speaker = identity(segment.get("speaker"))
        item_speakers = [identity(item.get("speaker")) for item in items]
        runs: list[tuple[list[dict[str, Any]], str | None]] = []
        current: list[dict[str, Any]] = []
        current_speaker = None
        for item, speaker in zip(items, item_speakers):
            if current and speaker is not None and current_speaker is not None and speaker != current_speaker:
                runs.append((current, current_speaker))
                current, current_speaker = [], None
            current.append(item)
            if speaker is not None:
                current_speaker = speaker
        if current:
            runs.append((current, current_speaker))
        if not runs:
            runs = [([], None)]
        split = len(runs) > 1
        if split:
            if (not isinstance(segment.get("text"), str)
                    or any(not isinstance(item.get("text"), str) for item in items)):
                raise ValueError("cannot split segment without matching item text")
            # Providers may omit spaces and punctuation from word tokens. Keep
            # the original segment text and partition it at matched word edges.
            def significant(char: str) -> bool:
                return not (char.isspace() or char == "\ufeff" or unicodedata.category(char).startswith("P"))

            text = segment["text"]
            if ([c for c in text if significant(c)]
                    != [c for item in items for c in item["text"] if significant(c)]):
                raise ValueError("cannot split segment without matching item text")
            cuts = []
            cursor = count = 0
            for run, _ in runs[:-1]:
                count += sum(significant(c) for item in run for c in item["text"])
                while cursor < len(text) and count:
                    if significant(text[cursor]):
                        count -= 1
                    cursor += 1
                while cursor < len(text) and not significant(text[cursor]):
                    cursor += 1
                cuts.append(cursor)
            text_pieces = [text[start:end] for start, end in zip([0, *cuts], [*cuts, len(text)])]
            edges = [(run[0], "start") for run, _ in runs[1:]] + [
                (run[-1], "end") for run, _ in runs[:-1]
            ]
            if any(type(item.get(key)) is not int for item, key in edges):
                raise ValueError("cannot split segment without integer item timestamps")
            if ("start_frame" in segment) != ("end_frame" in segment):
                raise ValueError("segment frame boundaries must be paired")
            if "start_frame" in segment and any(
                type(item.get(f"{key}_frame")) is not int for item, key in edges
            ):
                raise ValueError("cannot split framed segment without item frame boundaries")
        old_id = segment.get("id")
        output_ids: list[str | None] = []
        for run_index, (run, run_speaker) in enumerate(runs):
            out = copy.deepcopy(segment)
            if split:
                if run_index or not is_valid_speaker_id(old_id):
                    out["id"] = new_id(old_id if is_valid_speaker_id(old_id) else f"segment-{index + 1}")
                out["items"] = run
                out["text"] = text_pieces[run_index]
                out["start"] = segment["start"] if run_index == 0 else run[0]["start"]
                out["end"] = segment["end"] if run_index == len(runs) - 1 else run[-1]["end"]
                if "start_frame" in segment:
                    out["start_frame"] = segment["start_frame"] if run_index == 0 else run[0]["start_frame"]
                    out["end_frame"] = segment["end_frame"] if run_index == len(runs) - 1 else run[-1]["end_frame"]
            speaker = run_speaker if split else (segment_speaker or run_speaker)
            if speaker is not None:
                project_id = source_to_project.get(speaker)
                if not is_valid_speaker_id(project_id):
                    raise ValueError("unmapped source speaker")
                out["speaker"] = project_id
            else:
                out.pop("speaker", None)
            for item in out.get("items") or []:
                item.pop("speaker", None)
            result.append(out)
            output_ids.append(out.get("id"))
        mappings.append({"input_index": index, "old_id": old_id, "new_ids": output_ids})
    return result, mappings


def prepare_asr_speaker_segments(
    segments: Iterable[Mapping[str, Any]], source_to_project: Mapping[str, str],
) -> list[dict[str, Any]]:
    """Prepare an unbound ASR result; use migrate_speaker_segments for bindings."""
    return migrate_speaker_segments(segments, source_to_project)[0]


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
