"""Validation and model protocols for temporary editor selection operations.

These functions only produce candidates. The editor owns conflict detection,
confirmation and the eventual mutation of its live project.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from maw.postprocess_resegment import boundary_prompt, limit_groups, parse_boundaries, refine_groups, source_units


MAX_SELECTED_CUES = 100
MAX_SELECTED_TEXT = 20_000


def validate_selection(raw: object) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_SELECTED_CUES:
        raise ValueError(f"请选择 1 到 {MAX_SELECTED_CUES} 条主字幕。")
    cues: list[dict[str, Any]] = []
    ids: set[str] = set()
    text_length = 0
    last_end = -1
    for cue in raw:
        if not isinstance(cue, dict):
            raise ValueError("字幕数据无效。")
        cue_id, text, start, end = (cue.get(key) for key in ("id", "text", "start", "end"))
        if not isinstance(cue_id, str) or not cue_id or len(cue_id) > 160 or cue_id in ids:
            raise ValueError("字幕 ID 缺失或重复。")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("所选字幕包含空文本。")
        if type(start) is not int or type(end) is not int or start < last_end or end <= start:
            raise ValueError("所选字幕的时间范围无效或重叠。")
        text_length += len(text)
        if text_length > MAX_SELECTED_TEXT:
            raise ValueError("所选字幕文本过长，请分批处理。")
        ids.add(cue_id)
        last_end = end
        # The model sees temporary IDs, never the project's stable IDs.
        items = cue.get("items")
        if items is not None and not isinstance(items, list):
            raise ValueError("字幕的字词时间码格式无效。")
        cues.append({"id": cue_id, "text": text, "start": start, "end": end,
                     **({"items": items} if items is not None else {}),
                     **({"speaker": cue["speaker"]} if isinstance(cue.get("speaker"), str) else {})})
    return cues


def translate_selection(
    cues: Sequence[Mapping[str, Any]], target: str,
    complete: Callable[[str, list[dict[str, Any]]], Mapping[str, Any]],
) -> list[dict[str, str]]:
    if target not in ("zh", "en"):
        raise ValueError("请选择中文或英文作为目标语言。")
    rows = [{"id": f"c{i + 1:04d}", "text": cue["text"]} for i, cue in enumerate(cues)]
    prompt = (
        f"将每条字幕翻译成{'中文' if target == 'zh' else '英文'}。"
        "必须一条输入对应一条输出，按原顺序返回全部 ID，不合并、拆分或改写 ID。"
        '只返回 JSON：{"groups":[{"id":"c0001","text":"译文"}]}。'
    )
    response = complete(prompt, rows)
    groups = response.get("groups") if isinstance(response, Mapping) else None
    if not isinstance(groups, list) or len(groups) != len(rows):
        raise ValueError("翻译结果数量不匹配，未应用结果。")
    result = []
    for cue, row, group in zip(cues, rows, groups, strict=True):
        if not isinstance(group, dict):
            raise ValueError("翻译结果格式无效。")
        identity = group.get("id")
        if identity is None and group.get("source_ids") == [row["id"]]:
            identity = row["id"]
        text = group.get("text")
        source_ids = group.get("source_ids")
        if (identity != row["id"] or (source_ids is not None and source_ids != [row["id"]])
                or not isinstance(text, str) or not text.strip() or len(text) > MAX_SELECTED_TEXT):
            raise ValueError("翻译结果 ID、顺序或文本无效，未应用结果。")
        result.append({"id": str(cue["id"]), "text": text.strip()})
    return result


def resegment_selection(
    cues: Sequence[Mapping[str, Any]],
    complete: Callable[[str, list[dict[str, Any]]], Mapping[str, Any]],
    *, max_chars: int = 0,
) -> list[list[str]]:
    rows = []
    units = []
    for index, cue in enumerate(cues):
        source = dict(cue)
        source_items = source.get("items")
        cue_units = source_units(source, index)
        # source_units deliberately downgrades zero-width punctuation and other
        # unsupported inputs. Do not use those fallback units for a mutation.
        if not isinstance(source_items, list) or not source_items or any(unit.item is None for unit in cue_units):
            raise ValueError("选中字幕缺少可安全断句的完整字词时间码。")
        units.extend(cue_units)
        rows.append({"id": f"c{index + 1:04d}", "text": cue["text"],
                     "items": [{"id": unit.id, "text": unit.text} for unit in cue_units]})
    if type(max_chars) is not int or not 0 <= max_chars <= 200:
        raise ValueError("最大字数必须在 0 到 200 之间。")
    groups = parse_boundaries(complete(boundary_prompt(max_chars), rows), units)
    limited = []
    for group in refine_groups(groups, max_chars):
        parts, over = limit_groups(group, max_chars)
        if over:
            raise ValueError("完整词项或数字单位无法满足最大字数，请调整上限。")
        limited.extend(parts)
    return [[unit.id for unit in group] for group in limited]
