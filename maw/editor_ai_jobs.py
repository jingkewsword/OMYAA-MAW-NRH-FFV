"""In-memory, cancellable candidates for editor selection AI actions."""

from __future__ import annotations

import copy
import json
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from maw.project_tracks import get_main_track
from maw.editor_ai import resegment_selection, translate_selection, validate_selection

JOB_TIMEOUT_SECONDS = 900
RESULT_TTL_SECONDS = 3600


class EditorAiJobs:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job: dict[str, Any] | None = None
        self._cancel = threading.Event()
        self._closed = False
        self._running = False

    def start(self, payload: dict[str, Any], binding: tuple[int, str], media: Path | None) -> dict[str, Any]:
        operation = payload.get("operation")
        if operation not in {"translate", "align", "resegment"}:
            raise ValueError("未知的 AI 操作。")
        cues = validate_selection(payload.get("cues"))
        if operation == "align" and (media is None or not media.is_file()):
            raise ValueError("生成时间码需要当前工程关联的媒体。")
        with self._lock:
            if self._closed:
                raise ValueError("编辑器服务已关闭。")
            if self._running:
                raise ValueError("已有 AI 任务运行或正在取消，请稍候。")
            self._cancel = threading.Event()
            self._running = True
            self._job = {"id": secrets.token_urlsafe(18), "binding": binding,
                         "state": "running", "created": time.monotonic(), "result": None}
            job = self._job
            timer = threading.Timer(JOB_TIMEOUT_SECONDS, self._expire, args=(job, self._cancel))
            timer.daemon = True
            job["timer"] = timer
            timer.start()
            threading.Thread(target=self._run, args=(job, copy.deepcopy(payload), cues, media, self._cancel), daemon=True).start()
            return {"id": job["id"], "state": job["state"]}

    def status(self, job_id: object, binding: tuple[int, str], *, cancel: bool = False) -> dict[str, Any]:
        with self._lock:
            job = self._job
            if job and job["state"] != "running" and time.monotonic() - job.get("finished", job["created"]) > RESULT_TTL_SECONDS:
                self._job = job = None
            if not job or job["id"] != job_id or job["binding"] != binding:
                raise ValueError("任务不存在或工程已切换。")
            if cancel and job["state"] == "running":
                self._cancel.set()
                job["state"] = "cancelled"
                job["result"] = None
                job["finished"] = time.monotonic()
            return {key: copy.deepcopy(job[key]) for key in ("id", "state", "result")}

    def invalidate(self) -> None:
        with self._lock:
            self._cancel.set()
            if self._job:
                self._job["timer"].cancel()
            self._job = None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._cancel.set()
            if self._job:
                self._job["timer"].cancel()
            self._job = None

    def _expire(self, job: dict[str, Any], cancelled: threading.Event) -> None:
        with self._lock:
            if self._job is job and job["state"] == "running":
                cancelled.set()
                job["state"] = "error"
                job["result"] = {"error": "AI 任务超时，请重试。"}
                job["finished"] = time.monotonic()

    def _run(self, job: dict[str, Any], payload: dict[str, Any], cues: list[dict[str, Any]],
             media: Path | None, cancelled: threading.Event) -> None:
        try:
            result = self._compute(payload, cues, media, cancelled)
            state = "done"
        except ValueError as error:
            result, state = {"error": str(error)}, "error"
        except Exception:
            # Provider exceptions can contain text, paths or credentials. The
            # response deliberately does not copy arbitrary backend errors.
            result, state = {"error": "处理失败，请检查启动器中的模型配置或运行环境。"}, "error"
        with self._lock:
            self._running = False
            job["timer"].cancel()
            if self._job is job and job["state"] == "running" and not cancelled.is_set():
                job["result"], job["state"] = result, state
                job["finished"] = time.monotonic()

    @staticmethod
    def _compute(payload: dict[str, Any], cues: list[dict[str, Any]], media: Path | None,
                 cancelled: threading.Event) -> dict[str, Any]:
        operation = payload["operation"]
        if operation in {"translate", "resegment"}:
            from maw.app_paths import default_env_path
            from maw.postprocess_llm import LlmSettings, PRESETS, complete_subtitle_groups
            from maw.postprocess_pipeline import _llm_values
            from maw.postprocess_resegment import complete_boundaries

            provider = payload.get("provider")
            if provider not in {preset.id for preset in PRESETS}:
                raise ValueError("请选择启动器中配置的 AI 服务商。")
            values = _llm_values(default_env_path(), provider)
            settings = LlmSettings(provider, values["apiKey"], values["baseUrl"], values["model"])
            def complete(prompt: str, rows: list[dict[str, Any]]) -> Any:
                method = complete_boundaries if operation == "resegment" else complete_subtitle_groups
                return method(settings, prompt, rows, is_cancelled=cancelled.is_set)
            if operation == "translate":
                return {"translations": translate_selection(cues, payload.get("target"), complete)}
            return {"groups": resegment_selection(cues, complete, max_chars=payload.get("maxChars", 0))}

        from maw.alignment_models import alignment_model_by_id
        from maw.app_paths import default_env_path
        from maw.gui_config import effective_config
        from maw.local_runtime import run_timestamp_alignment_in_runtime
        from maw.postprocess_io import read_project
        from maw.language import timestamp_items_cover_text

        model = payload.get("model")
        if not isinstance(model, str):
            raise ValueError("请选择对齐模型。")
        alignment_model_by_id(model)
        mode = payload.get("mode")
        if mode not in {"fill", "generate"}:
            raise ValueError("请选择补缺或重新生成时间码。")
        # Fill means completely untimed cues only. The shared toolbox aligner
        # otherwise replaces partially timed cues and zero-width punctuation.
        protected = sum(bool(cue.get("items")) for cue in cues) if mode == "fill" else 0
        if mode == "fill":
            cues = [cue for cue in cues if not cue.get("items")]
        if not cues:
            return {"aligned": [], "report": {"alignedSegments": 0, "skippedSegments": protected, "failedSegments": 0}}
        assert media is not None
        with tempfile.TemporaryDirectory(prefix="maw-editor-ai-") as temp:
            root = Path(temp)
            project = root / "selection.mosp"
            project.write_text(json.dumps({"segments": cues, "language": payload.get("language", "")}, ensure_ascii=False), encoding="utf-8")
            # Compare with the same normalization the worker uses. Comparing
            # against the raw browser input can misclassify normalization as a
            # successful generation when a cue actually failed or was skipped.
            baseline_segments = get_main_track(read_project(project))["segments"]
            response = run_timestamp_alignment_in_runtime(
                project_path=project, media_path=media, model_id=model,
                output_mode="json", alignment_mode=mode, output_directory=root,
                model_cache_root=effective_config(default_env_path()).model_cache_root,
                cancel_event=cancelled,
            )
            output = response.get("artifact", {}).get("projectPath")
            if not isinstance(output, str) or not output:
                raise ValueError("对齐模型未返回工程结果。")
            generated = get_main_track(read_project(Path(output))).get("segments")
            if not isinstance(generated, list) or len(generated) != len(cues):
                raise ValueError("对齐结果数量不匹配。")
            result = []
            for cue, baseline, segment in zip(cues, baseline_segments, generated, strict=True):
                if not isinstance(segment, dict) or segment.get("id") != cue["id"]:
                    raise ValueError("对齐结果的字幕身份不匹配。")
                items = segment.get("items")
                # A failed or skipped cue retains its old items in the worker
                # output. Never present unchanged data as a new candidate.
                if items == baseline.get("items"):
                    continue
                if isinstance(items, list) and items and timestamp_items_cover_text(cue["text"], items):
                    previous = cue["start"]
                    for item in items:
                        if (not isinstance(item, dict) or type(item.get("start")) is not int
                            or type(item.get("end")) is not int or not previous <= item["start"] <= item["end"] <= cue["end"]):
                            raise ValueError("对齐结果包含无效时间码。")
                        previous = item["end"]
                    result.append({"id": cue["id"], "items": items})
            report = dict(response.get("report") or {})
            report["skippedSegments"] = int(report.get("skippedSegments") or 0) + protected
            return {"aligned": result, "report": report}
