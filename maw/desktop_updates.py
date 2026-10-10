"""Serialized desktop update jobs over the private Electron backend channel."""

from __future__ import annotations

from copy import deepcopy
from threading import Event, Lock, Thread

from maw.updater import UpdateCancelled, UpdateClient, UpdateError


class DesktopUpdates:
    def __init__(self, client: UpdateClient) -> None:
        self.client = client
        self.lock = Lock()
        self.cancel_event = Event()
        self.phase = "idle"
        self.progress = {"received": 0, "total": 0}
        self.error = ""
        self.result = client.initial_status()

    def _snapshot(self) -> dict:
        result = deepcopy(self.result)
        result.pop("downloadPath", None)
        result.pop("errorDetail", None)
        return {"ok": True, "phase": self.phase, "progress": dict(self.progress),
                "errorCode": self.error, "update": result}

    def status(self) -> dict:
        with self.lock:
            return self._snapshot()

    def operation(self, action: str, payload: dict) -> dict:
        with self.lock:
            if action == "status":
                return self._snapshot()
            if action == "cancel":
                self.cancel_event.set()
                return self._snapshot()
            if self.phase in {"checking", "downloading"}:
                raise UpdateError("update_busy")
            if action == "preferences":
                if type(payload.get("autoCheck")) is not bool:
                    raise UpdateError("update_target_invalid")
                self.client.set_preferences(auto_check=payload["autoCheck"])
                self.result = self.client.initial_status()
                return self._snapshot()
            if action in {"ready", "prepare"}:
                tag = str(payload.get("tag") or "")
                try:
                    path = self.client.cached_download(tag)
                except UpdateError:
                    self.result["downloaded"] = False
                    self.phase = "error"
                    self.error = "update_not_downloaded"
                    raise
                result = self.client._cached_result_for_tag(tag)
                can_apply = result.get("capability") == "installer" and self.client.installation.can_apply
                if action == "prepare":
                    if not can_apply:
                        raise UpdateError("update_manual_only")
                    self.client.mark_pending(tag, str(result["latestVersion"]))
                return {"ok": True, "path": str(path), "canApply": can_apply,
                        "tag": tag, "version": result["latestVersion"],
                        "size": result["asset"]["size"], "sha256": result["asset"]["sha256"]}
            if action not in {"check", "download"}:
                raise UpdateError("update_target_invalid")
            self.phase = "checking" if action == "check" else "downloading"
            self.error = ""
            self.progress = {"received": 0, "total": 0}
            self.cancel_event = Event()
            Thread(target=self._run, args=(action, dict(payload), self.cancel_event), daemon=True).start()
            return self._snapshot()

    def _run(self, action: str, payload: dict, cancel: Event) -> None:
        try:
            if action == "check":
                result = self.client.check(force=payload.get("force") is True)
                phase = "idle"
            else:
                self.client.download(str(payload.get("tag") or ""), cancel_event=cancel,
                                     on_progress=self._progress)
                if cancel.is_set():
                    raise UpdateCancelled()
                result = self.client.initial_status()
                phase = "ready"
            with self.lock:
                self.result = result
                self.phase = phase
        except Exception as error:
            with self.lock:
                self.phase = "cancelled" if isinstance(error, UpdateCancelled) else "error"
                self.error = error.code if isinstance(error, UpdateError) else "update_failed"
                if action == "download":
                    self.result["downloaded"] = False

    def _progress(self, received: int, total: int) -> None:
        with self.lock:
            self.progress = {"received": received, "total": total}
