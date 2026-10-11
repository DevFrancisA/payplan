"""Structured logging and CloudWatch metrics.

On ECS the container's stdout is shipped to CloudWatch Logs by the awslogs driver. Lines in
CloudWatch Embedded Metric Format (EMF) are turned into metrics automatically, so the API
publishes request latency and error counts without calling the CloudWatch API.
"""

import json
import logging
import sys
import time
import uuid
from datetime import UTC, datetime

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("payplan")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(getattr(record, "fields", {}))
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class Metrics:
    """Writes CloudWatch EMF records to stdout when enabled; no-op otherwise."""

    def __init__(self) -> None:
        self.enabled = False
        self.namespace = "PayPlan"
        self.service = "payplan-api"
        self._stream = sys.stdout

    def configure(self, enabled: bool, namespace: str, service: str, stream=None) -> None:
        self.enabled = enabled
        self.namespace = namespace
        self.service = service
        self._stream = stream or sys.stdout

    def emit(self, values: dict[str, tuple[float, str]], **properties: object) -> None:
        if not self.enabled:
            return
        record = {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": self.namespace,
                        "Dimensions": [["Service"]],
                        "Metrics": [
                            {"Name": name, "Unit": unit} for name, (_, unit) in values.items()
                        ],
                    }
                ],
            },
            "Service": self.service,
            **{name: value for name, (value, _) in values.items()},
            **properties,
        }
        self._stream.write(json.dumps(record, default=str) + "\n")
        self._stream.flush()

    def count(self, name: str, value: int = 1, **properties: object) -> None:
        self.emit({name: (value, "Count")}, **properties)


metrics = Metrics()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns a request id, logs one structured line per request, and records latency."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            route = request.scope.get("route")
            path = getattr(route, "path", request.url.path)
            logger.info(
                "request",
                extra={
                    "fields": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": path,
                        "status": status,
                        "latency_ms": latency_ms,
                    }
                },
            )
            if path not in ("/healthz", "/readyz"):
                metrics.emit(
                    {
                        "Latency": (latency_ms, "Milliseconds"),
                        "Requests": (1, "Count"),
                        "ServerErrors": (1 if status >= 500 else 0, "Count"),
                        "ClientErrors": (1 if 400 <= status < 500 else 0, "Count"),
                    },
                    route=f"{request.method} {path}",
                    status=status,
                    request_id=request_id,
                )
