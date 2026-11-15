"""Structured JSON logging on stdout.

Cloud Run forwards stdout to Google Cloud Logging, which parses one JSON object per line
and maps `severity`, `message` and `logging.googleapis.com/trace` to first-class fields, so
log lines are grouped with the request trace without needing a client library.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
gcp_project_var: contextvars.ContextVar[str] = contextvars.ContextVar("gcp_project", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
        }
        trace = trace_id_var.get()
        if trace:
            project = gcp_project_var.get()
            entry["logging.googleapis.com/trace"] = (
                f"projects/{project}/traces/{trace}" if project else trace
            )
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            entry.update(extra)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # uvicorn's access log duplicates our request log line
    logging.getLogger("uvicorn.access").disabled = True


def log_event(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"fields": fields})
