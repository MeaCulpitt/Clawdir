from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
import time

# Global rate limit: max requests per IP per window
MAX_REQUESTS = 10
WINDOW_SECONDS = 60

_request_counts = defaultdict(list)


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only rate-limit the registration endpoint
        if request.url.path == "/api/agents/register" and request.method == "POST":
            client_ip = request.client.host if request.client else "unknown"
            now = time.time()

            # Clean old entries
            _request_counts[client_ip] = [
                t for t in _request_counts[client_ip] if now - t < WINDOW_SECONDS
            ]

            if len(_request_counts[client_ip]) >= MAX_REQUESTS:
                raise HTTPException(
                    status_code=429,
                    detail=f"Rate limit exceeded. Max {MAX_REQUESTS} requests per {WINDOW_SECONDS}s."
                )

            _request_counts[client_ip].append(now)

        return await call_next(request)
