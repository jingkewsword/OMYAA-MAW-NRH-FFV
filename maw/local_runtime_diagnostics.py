"""Compatibility entry point for Launcher local-runtime diagnostics.

The implementation lives in :mod:`maw.runtime_diagnostics` so it can stay
runtime-agnostic while this name remains discoverable beside
``maw.local_runtime`` and ``maw.moss_runtime``.
"""

from maw.runtime_diagnostics import (
    GPU_PROBE_TIMEOUT_SECONDS,
    PYTHON_PROBE_TIMEOUT_SECONDS,
    SCHEMA_VERSION,
    build_runtime_diagnostics_report,
    collect_runtime_diagnostics,
    diagnose_runtime,
    redact_path,
)

__all__ = [
    "GPU_PROBE_TIMEOUT_SECONDS",
    "PYTHON_PROBE_TIMEOUT_SECONDS",
    "SCHEMA_VERSION",
    "build_runtime_diagnostics_report",
    "collect_runtime_diagnostics",
    "diagnose_runtime",
    "redact_path",
]
