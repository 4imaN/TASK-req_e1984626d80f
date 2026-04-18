import json
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.trailgoods.middleware.request_id import request_id_ctx

logger = logging.getLogger("trailgoods.api")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.monotonic()
        rid = request_id_ctx.get("")
        method = request.method
        path = request.url.path
        client_ip = request.client.host if request.client else None

        try:
            response = await call_next(request)
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.info(json.dumps({
                "event": "request",
                "request_id": rid,
                "method": method,
                "path": path,
                "status": response.status_code,
                "duration_ms": round(elapsed_ms, 1),
                "client_ip": client_ip,
            }))
            return response
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            logger.error(json.dumps({
                "event": "request_error",
                "request_id": rid,
                "method": method,
                "path": path,
                "error": type(exc).__name__,
                "duration_ms": round(elapsed_ms, 1),
                "client_ip": client_ip,
            }))
            raise
