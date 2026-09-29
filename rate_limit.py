from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address
import asyncio

from config import get_rate_limit, get_max_concurrent_generations

def client_key(request: Request) -> str:
  return get_remote_address(request)

# Keep swallow_errors=False while testing
limiter = Limiter(key_func=client_key, headers_enabled=True, swallow_errors=True)

GENERATE_LIMIT = get_rate_limit("RATE_LIMIT_GENERATE", "10/minute")
SCHEMA_LIMIT = get_rate_limit("RATE_LIMIT_SCHEMA", "60/minute")

generation_semaphore = asyncio.Semaphore(get_max_concurrent_generations())