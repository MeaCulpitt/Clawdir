"""Simple in-memory rate limiting middleware."""
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from collections import defaultdict
from datetime import datetime, timedelta
import asyncio


class RateLimiter:
    """Simple sliding window rate limiter."""
    
    def __init__(self):
        self.requests = defaultdict(list)
        self.lock = asyncio.Lock()
    
    async def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        """Check if request is allowed under rate limit."""
        async with self.lock:
            now = datetime.utcnow()
            window_start = now - timedelta(seconds=window_seconds)
            
            # Clean old requests
            self.requests[key] = [
                ts for ts in self.requests[key]
                if ts > window_start
            ]
            
            if len(self.requests[key]) >= limit:
                return False
            
            self.requests[key].append(now)
            return True
    
    def get_remaining(self, key: str, limit: int, window_seconds: int) -> int:
        """Get remaining requests in window."""
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=window_seconds)
        
        recent = [ts for ts in self.requests[key] if ts > window_start]
        return max(0, limit - len(recent))


# Global rate limiter
rate_limiter = RateLimiter()


# Rate limit configs by endpoint pattern
RATE_LIMITS = {
    # Public endpoints
    "discover": (60, 60),      # 60 requests per minute
    "agents_get": (100, 60),   # 100 requests per minute
    "activity": (30, 60),      # 30 requests per minute
    
    # Authenticated endpoints
    "agents_create": (10, 60), # 10 registrations per minute
    "ratings": (30, 60),       # 30 ratings per minute
    "verify": (10, 60),        # 10 verifications per minute
    
    # Default
    "default": (100, 60),      # 100 requests per minute
}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware."""
    
    async def dispatch(self, request: Request, call_next):
        # Get client identifier (IP or API key)
        client_ip = request.client.host if request.client else "unknown"
        auth_header = request.headers.get("authorization", "")
        
        if auth_header.startswith("Bearer "):
            # Use API key hash prefix as identifier (more granular)
            client_key = f"api:{auth_header[7:15]}"
        else:
            client_key = f"ip:{client_ip}"
        
        # Determine rate limit based on path
        path = request.url.path
        
        if "/discover" in path:
            limit_key = "discover"
        elif "/activity" in path:
            limit_key = "activity"
        elif "/agents" in path and request.method == "POST":
            limit_key = "agents_create"
        elif "/agents" in path:
            limit_key = "agents_get"
        elif "/ratings" in path:
            limit_key = "ratings"
        elif "/verify" in path:
            limit_key = "verify"
        else:
            limit_key = "default"
        
        limit, window = RATE_LIMITS[limit_key]
        
        # Check rate limit
        rate_key = f"{client_key}:{limit_key}"
        allowed = await rate_limiter.is_allowed(rate_key, limit, window)
        
        if not allowed:
            return HTTPException(
                status_code=429,
                detail={
                    "error": "rate_limit_exceeded",
                    "limit": limit,
                    "window_seconds": window,
                    "retry_after": window
                }
            )
        
        # Add rate limit headers
        response = await call_next(request)
        remaining = rate_limiter.get_remaining(rate_key, limit, window)
        
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Window"] = str(window)
        
        return response
