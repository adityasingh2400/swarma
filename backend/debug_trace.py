"""Copy-paste friendly tracing for support/debugging.

Every line starts with ``SWARMA |`` so you can grep or share logs easily.
Enable via normal Python logging (see run.py basicConfig); logger name: ``swarma.trace``.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

_trace = logging.getLogger("swarma.trace")


def _safe_value(v: Any, max_len: int = 400) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        if len(v) > max_len:
            return repr(v[:max_len] + "…")
        return repr(v)
    if isinstance(v, bytes):
        return f"<bytes len={len(v)}>"
    try:
        s = json.dumps(v, default=str)
        if len(s) > max_len:
            return s[:max_len] + "…"
        return s
    except Exception:
        s = str(v)
        return (s[:max_len] + "…") if len(s) > max_len else s


def swarma_line(component: str, event: str, **fields: Any) -> None:
    """One line: SWARMA | UTC ISO | component | event | k=v pairs."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [f"SWARMA | {ts} | {component} | {event}"]
    if fields:
        kv = " | ".join(f"{k}={_safe_value(v)}" for k, v in sorted(fields.items()))
        parts.append(kv)
    _trace.info(" ".join(parts))


def swarma_ws_out(job_id: str, event: dict, *, client_count: int | None = None) -> None:
    """Log outbound WebSocket JSON without huge payloads."""
    t = event.get("type")
    data = event.get("data")
    summary: dict[str, Any] = {"job_id": job_id, "type": t}
    if client_count is not None:
        summary["ws_clients"] = client_count
    if isinstance(data, dict):
        summary["data_keys"] = sorted(data.keys())
        if "agent" in data:
            summary["agent"] = data.get("agent")
        if "item_id" in data:
            summary["item_id"] = data.get("item_id")
        if "message" in data and isinstance(data["message"], str):
            m = data["message"]
            summary["message"] = m[:120] + ("…" if len(m) > 120 else "")
        if "progress" in data:
            summary["progress"] = data.get("progress")
        if "frame_paths" in data:
            fp = data.get("frame_paths")
            summary["frame_paths_n"] = len(fp) if isinstance(fp, list) else "?"
        if "transcript_text" in data:
            tt = data.get("transcript_text")
            summary["transcript_len"] = len(tt) if isinstance(tt, str) else 0
    else:
        summary["data_type"] = type(data).__name__
    swarma_line("ws.broadcast", "emit", **summary)
