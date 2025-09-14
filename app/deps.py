import asyncio
import time
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings


security = HTTPBearer(auto_error=False)
_rate_lock = asyncio.Lock()
_rate_data = {}


async def verify_api_key(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> None:
    """Verify bearer token if PROXY_API_KEY is set."""
    if settings.proxy_api_key:
        if not credentials or credentials.credentials != settings.proxy_api_key:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


async def rate_limiter(request: Request) -> None:
    """Simple in-memory rate limiter per IP address."""
    if settings.rate_limit_per_minute <= 0:
        return

    ip = request.client.host if request.client else "anonymous"
    now = time.time()
    window = 60
    async with _rate_lock:
        count, reset = _rate_data.get(ip, (0, now + window))
        if reset < now:
            count, reset = 0, now + window
        if count >= settings.rate_limit_per_minute:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        _rate_data[ip] = (count + 1, reset)
